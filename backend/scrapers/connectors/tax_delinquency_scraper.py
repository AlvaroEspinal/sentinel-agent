"""
Tax Delinquency & Tax Title Scraper — LLM-powered PDF extraction.

Extracts structured property data from Massachusetts municipal Treasurer
tax delinquency and tax title PDFs.  Pipeline:

1. Fetch PDF from URL (httpx) or read from local file
2. Extract raw text & tables using pdfplumber
3. Send to LLM for structured parsing into:
   {address, owner, amount_owed}

Supports two LLM backends (auto-selected from env):
- OpenRouter  (OPENROUTER_API_KEY) — default when set
- Anthropic   (ANTHROPIC_API_KEY)  — fallback
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # type: ignore

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore


# ── Data model ────────────────────────────────────────────────────────────

class TaxDelinquencyRecord:
    """Single delinquent-tax record."""

    __slots__ = ("address", "owner", "amount_owed", "parcel_id", "year", "tax_type")

    def __init__(
        self,
        address: str,
        owner: str,
        amount_owed: str,
        parcel_id: Optional[str] = None,
        year: Optional[str] = None,
        tax_type: Optional[str] = None,
    ):
        self.address = address
        self.owner = owner
        self.amount_owed = amount_owed
        self.parcel_id = parcel_id
        self.year = year
        self.tax_type = tax_type

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "address": self.address,
            "owner": self.owner,
            "amount_owed": self.amount_owed,
        }
        if self.parcel_id:
            d["parcel_id"] = self.parcel_id
        if self.year:
            d["year"] = self.year
        if self.tax_type:
            d["tax_type"] = self.tax_type
        return d


# ── Main scraper ──────────────────────────────────────────────────────────

class TaxDelinquencyScraper:
    """Extract tax delinquency / tax title records from municipal PDFs.

    Uses pdfplumber for text + table extraction, then Claude for
    structured parsing when tables are ambiguous or absent.
    """

    _CLAUDE_MODEL = "claude-sonnet-4-20250514"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        # Resolve OpenRouter config first, then fall back to Anthropic
        try:
            from config import ANTHROPIC_API_KEY
            _anthropic_key = ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
        except ImportError:
            _anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

        self._openrouter_key: str = os.getenv("OPENROUTER_API_KEY", "")
        self._openrouter_model: str = os.getenv(
            "OPENROUTER_DEFAULT_MODEL", "google/gemini-2.0-flash-001"
        )

        # Use OpenRouter when available, otherwise Anthropic
        if self._openrouter_key:
            self._provider = "openrouter"
            self.api_key = self._openrouter_key
            self.model = model or self._openrouter_model
            logger.info("[TaxDelinq] LLM provider: OpenRouter (%s)", self.model)
        else:
            self._provider = "anthropic"
            self.api_key = api_key or _anthropic_key
            self.model = model or self._CLAUDE_MODEL
            logger.info("[TaxDelinq] LLM provider: Anthropic (%s)", self.model)

        self._client: Optional[Any] = None
        self._http: Optional[Any] = None

        if not self.api_key:
            logger.warning("No LLM API key found — extraction will be unavailable")

    # ── Client helpers ────────────────────────────────────────────────────

    def _ensure_llm(self) -> Any:
        """Only used for Anthropic. OpenRouter calls go through _ensure_http."""
        if self._client is None:
            if anthropic is None:
                raise RuntimeError("anthropic package required: pip install anthropic")
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    async def _ensure_http(self) -> Any:
        if self._http is None:
            if httpx is None:
                raise RuntimeError("httpx package required: pip install httpx")
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=15.0),
                limits=httpx.Limits(max_connections=5),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
        return self._http

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None

    # ── Public API ────────────────────────────────────────────────────────

    async def extract_from_url(self, url: str) -> List[Dict[str, Any]]:
        """Download a PDF from *url* and extract tax-delinquent records.
        Attempts httpx first, falls back to Playwright if blocked.
        """
        logger.info("[TaxDelinq] Downloading PDF from %s", url)
        
        pdf_bytes = await self._download_pdf_httpx(url)
        
        if not pdf_bytes:
            logger.info("[TaxDelinq] httpx failed or returned HTML. Trying Playwright fallback...")
            pdf_bytes = await self._download_pdf_playwright(url)
            
        if not pdf_bytes:
            logger.error("[TaxDelinq] Could not download a valid PDF from %s", url)
            return []

        logger.info("[TaxDelinq] Download accomplished: %d bytes", len(pdf_bytes))
        return await self.extract_from_pdf(pdf_bytes)

    async def _download_pdf_httpx(self, url: str) -> Optional[bytes]:
        client = await self._ensure_http()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("[TaxDelinq] httpx HTTP error: %s", exc)
            return None
        except Exception as exc:
            logger.warning("[TaxDelinq] httpx failed: %s", exc)
            return None

        content_type = resp.headers.get("content-type", "")
        # If it's HTML, we're likely hitting a bot challenge
        if "text/html" in content_type.lower() or "image/" in content_type.lower():
            logger.warning("[TaxDelinq] httpx got non-PDF content-type: %s", content_type)
            return None

        return resp.content

    async def _download_pdf_playwright(self, url: str) -> Optional[bytes]:
        """Use Playwright to download the PDF, bypassing basic anti-bot pages."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[TaxDelinq] playwright not installed. Cannot use fallback.")
            return None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                accept_downloads=True
            )
            page = await context.new_page()

            try:
                # Wait for either a successful navigation to a PDF or a download event
                response = await page.goto(url, wait_until="networkidle")
                
                if response:
                    content_type = response.headers.get("content-type", "")
                    if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
                        # Sometimes body() throws if it's a huge stream, but usually works for typical municipal PDFs
                        return await response.body()
                
                # If page is HTML, maybe there's an iframe or meta refresh we missed,
                # but for now we just return None if we didn't get a PDF response directly.
                logger.warning("[TaxDelinq] Playwright reached page, but response was not a direct PDF.")
                return None
            except Exception as exc:
                logger.warning("[TaxDelinq] Playwright exception: %s", exc)
                return None
            finally:
                await browser.close()

    async def extract_from_pdf(
        self,
        source: Union[bytes, str, Path],
    ) -> List[Dict[str, Any]]:
        """Extract tax-delinquency records from a PDF.

        Args:
            source: Raw PDF bytes, or a path (str / Path) to a local file.

        Returns:
            List of dicts with keys: address, owner, amount_owed
            (and optional parcel_id, year, tax_type when present).
        """
        pdf_bytes = self._resolve_source(source)

        # Step 1 — raw text extraction
        raw_text = self._extract_text(pdf_bytes)
        if not raw_text or len(raw_text.strip()) < 50:
            logger.error("[TaxDelinq] No meaningful text extracted from PDF")
            return []

        logger.info("[TaxDelinq] Extracted %d chars of raw text", len(raw_text))

        # Step 2 — attempt pdfplumber table extraction
        tables = self._extract_tables(pdf_bytes)
        table_text = self._tables_to_text(tables) if tables else ""
        if table_text:
            logger.info(
                "[TaxDelinq] pdfplumber found %d tables (%d chars)",
                len(tables), len(table_text),
            )

        # Step 3 — send to Claude for structured parsing
        records = await self._llm_parse(raw_text, table_text)
        logger.info("[TaxDelinq] Extracted %d records via LLM", len(records))
        return records

    # ── PDF processing ────────────────────────────────────────────────────

    @staticmethod
    def _resolve_source(source: Union[bytes, str, Path]) -> bytes:
        if isinstance(source, bytes):
            return source
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {path}")
        return path.read_bytes()

    @staticmethod
    def _extract_text(pdf_bytes: bytes) -> str:
        """Extract raw text from every page via pdfplumber."""
        if pdfplumber is None:
            logger.error("[TaxDelinq] pdfplumber not installed")
            return ""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
                return "\n\n--- PAGE BREAK ---\n\n".join(pages)
        except Exception as exc:
            logger.error("[TaxDelinq] PDF text extraction error: %s", exc)
            return ""

    @staticmethod
    def _extract_tables(pdf_bytes: bytes) -> List[List[List[Optional[str]]]]:
        """Attempt to pull tabular data from every page."""
        if pdfplumber is None:
            return []
        all_tables: List[List[List[Optional[str]]]] = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    for table in page.extract_tables():
                        if table:
                            all_tables.append(table)
        except Exception as exc:
            logger.warning("[TaxDelinq] Table extraction error: %s", exc)
        return all_tables

    @staticmethod
    def _tables_to_text(tables: List[List[List[Optional[str]]]]) -> str:
        """Convert pdfplumber tables to a tab-separated text block."""
        lines: List[str] = []
        for idx, table in enumerate(tables):
            lines.append(f"[TABLE {idx + 1}]")
            for row in table:
                cleaned = [cell.strip() if cell else "" for cell in row]
                lines.append("\t".join(cleaned))
            lines.append("")
        return "\n".join(lines)

    # ── LLM structured extraction ─────────────────────────────────────────

    async def _llm_parse(
        self,
        raw_text: str,
        table_text: str,
    ) -> List[Dict[str, Any]]:
        """Build the prompt then dispatch to OpenRouter or Anthropic."""
        # Combine inputs — prefer table text when available
        combined = ""
        if table_text:
            combined += "=== TABULAR DATA (extracted by pdfplumber) ===\n"
            combined += table_text[:40000]
            combined += "\n\n"
        combined += "=== RAW TEXT (full pages) ===\n"
        combined += raw_text[:60000]

        prompt = f"""You are an expert Massachusetts municipal data engineer.

I am providing you with text extracted from a Tax Delinquency or Tax Title list
published by a Massachusetts town Treasurer's office. These PDFs list properties
whose owners owe delinquent taxes.

Your task: parse EVERY property entry you can find and return a JSON array.

Each element in the array must have these fields (use null if not found):
{{
  "address": "Full street address of the property",
  "owner": "Name(s) of the property owner(s)",
  "amount_owed": "Total dollar amount owed (as a string, e.g. '$1,234.56')",
  "parcel_id": "Parcel / map-lot ID if present (null otherwise)",
  "year": "Tax year(s) if listed (null otherwise)",
  "tax_type": "Type of tax (e.g. 'Real Estate', 'Personal Property', 'Water/Sewer', null if unclear)"
}}

Important rules:
- Extract ALL entries, not just a sample.
- Preserve dollar amounts exactly as they appear.
- If an entry spans multiple lines in the document, merge it into one record.
- If the document contains section headers (e.g. "Real Estate Taxes", "Water Liens"),
  capture that as the tax_type for all entries under that section.
- Return ONLY a valid JSON array — no markdown, no explanation.

Document text:
---
{combined}
---

Return ONLY a valid JSON array, no other text."""

        if self._provider == "openrouter":
            return await self._llm_parse_openrouter(prompt)
        return await self._llm_parse_anthropic(prompt)

    @staticmethod
    def _clean_llm_response(result_text: str) -> List[Dict[str, Any]]:
        """Strip markdown fences and parse JSON array from LLM response."""
        result_text = result_text.strip()
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()

        parsed = json.loads(result_text)
        if not isinstance(parsed, list):
            logger.warning("[TaxDelinq] LLM returned non-list JSON; wrapping")
            parsed = [parsed]

        records: List[Dict[str, Any]] = []
        for item in parsed:
            rec = TaxDelinquencyRecord(
                address=str(item.get("address") or ""),
                owner=str(item.get("owner") or ""),
                amount_owed=str(item.get("amount_owed") or ""),
                parcel_id=item.get("parcel_id"),
                year=item.get("year"),
                tax_type=item.get("tax_type"),
            )
            records.append(rec.to_dict())
        return records

    async def _llm_parse_openrouter(self, prompt: str) -> List[Dict[str, Any]]:
        """Call OpenRouter's OpenAI-compatible /chat/completions endpoint via httpx."""
        http = await self._ensure_http()
        try:
            resp = await http.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://sentinel-agent.local",
                    "X-Title": "Sentinel Agent Tax Delinquency Scraper",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            result_text = data["choices"][0]["message"]["content"]
            return self._clean_llm_response(result_text)
        except json.JSONDecodeError as exc:
            logger.error("[TaxDelinq] JSON parse error from OpenRouter: %s", exc)
            return []
        except Exception as exc:
            logger.error("[TaxDelinq] OpenRouter extraction failed: %s", exc)
            return []

    async def _llm_parse_anthropic(self, prompt: str) -> List[Dict[str, Any]]:
        """Call Anthropic Claude directly."""
        client = self._ensure_llm()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            result_text = response.content[0].text
            return self._clean_llm_response(result_text)
        except json.JSONDecodeError as exc:
            logger.error("[TaxDelinq] JSON parse error from Anthropic: %s", exc)
            return []
        except Exception as exc:
            logger.error("[TaxDelinq] Anthropic extraction failed: %s", exc)
            return []
