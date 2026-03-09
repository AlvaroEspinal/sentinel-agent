"""
Phase 4b v2: Scrape Tax Delinquency Data for 7 MA Towns — CORRECTED.

The prior run (v1) incorrectly picked up DC OTR tax sale URLs from DuckDuckGo.
This version uses the exact MA town collector page URLs and does NOT fall back
to generic web searches.

Strategy per town:
1. Scrape the specific MA collector URL via Firecrawl
2. Look for PDF links containing tax title / delinquency keywords
3. If PDF found, download + extract via pdfplumber + OpenRouter LLM
4. If no PDF but table/text with delinquency keywords found on page, extract via LLM
5. If page explicitly states data not public, record as not_published
6. Otherwise record as not_published (MA towns rarely post these lists online)

MA Legal context:
  MGL Ch. 60 §37 requires posting of tax takings — but "posting" means at Town Hall
  or in a local newspaper, NOT necessarily on a public website. Many towns don't
  publish the full list online.

Output: backend/data_cache/tax_delinquency/{town}_tax_delinquency.json
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tax_v2")

from scrapers.connectors.firecrawl_client import FirecrawlClient

# ── Config ────────────────────────────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.getenv("OPENROUTER_DEFAULT_MODEL", "google/gemini-2.0-flash-001")

OUT_DIR = BACKEND_DIR / "data_cache" / "tax_delinquency"

# ── Keywords ──────────────────────────────────────────────────────────────────
TAX_PDF_KEYWORDS = [
    "tax title", "taxtitle", "delinquent", "delinq",
    "tax-title", "tax_title", "outstanding", "unpaid",
    "lien", "overdue", "tax-taking", "taxtaking", "in-rem",
    "collector", "taxsale", "tax-sale",
]

TAX_PAGE_KEYWORDS = [
    "tax title", "delinquent", "outstanding taxes", "unpaid taxes",
    "tax taking", "lien", "overdue", "past due", "tax sale",
    "in rem", "chapter 60",
]

# ── Town definitions with CORRECT MA URLs ─────────────────────────────────────
TOWNS: List[Dict[str, Any]] = [
    {
        "id": "newton",
        "name": "Newton",
        "collector_urls": [
            "https://www.newtonma.gov/government/treasury-collector/tax-collector",
            "https://www.newtonma.gov/government/treasury-collector",
            "https://www.newtonma.gov/government/finance",
        ],
        "note_template": "Newton MA Tax Collector page scraped — no public tax title/delinquency list found online.",
    },
    {
        "id": "brookline",
        "name": "Brookline",
        "collector_urls": [
            "https://www.brooklinema.gov/collector",
            "https://www.brooklinema.gov/187/Collectors-Office",
            "https://www.brooklinema.gov/government/departments/collector",
        ],
        "note_template": "Brookline MA Collector page scraped — no public tax title list found.",
    },
    {
        "id": "needham",
        "name": "Needham",
        "collector_urls": [
            "https://www.needhamma.gov/271/Collectors-Office",
            "https://www.needhamma.gov/219/Tax-Collector",
            "https://www.needhamma.gov/collector",
        ],
        "note_template": "Needham MA Collector page scraped — no public tax title list found.",
    },
    {
        "id": "natick",
        "name": "Natick",
        "collector_urls": [
            "https://www.natickma.gov/311/Tax-Collector",
            "https://www.natickma.gov/collector",
            "https://www.natickma.gov/department/collector",
        ],
        "note_template": "Natick MA Tax Collector page scraped — no public tax title list found.",
    },
    {
        "id": "wayland",
        "name": "Wayland",
        "collector_urls": [
            "https://www.wayland.ma.us/government/tax-collector",
            "https://www.wayland.ma.us/collector",
            "https://www.wayland.ma.us/219/Tax-Collector",
        ],
        "note_template": "Wayland MA Tax Collector page scraped — no public tax title list found.",
    },
    {
        "id": "lincoln",
        "name": "Lincoln",
        "collector_urls": [
            "https://www.lincolnma.org/government/town-departments/tax-collector",
            "https://www.lincolnma.org/collector",
            "https://www.lincolnma.org/180/Tax-Collector",
        ],
        "note_template": "Lincoln MA Tax Collector page scraped — no public tax title list found.",
    },
    {
        "id": "lexington",
        "name": "Lexington",
        "collector_urls": [
            "https://www.lexingtonma.gov/collectors-office",
            "https://www.lexingtonma.gov/collector",
            "https://www.lexingtonma.gov/200/Collectors-Office",
        ],
        "note_template": "Lexington MA Collector page scraped — no public tax title list found.",
    },
]

# ── PDF helpers ───────────────────────────────────────────────────────────────

def _is_tax_pdf(url: str) -> bool:
    """True if URL ends in .pdf and contains a tax/delinquency keyword."""
    lower = url.lower()
    if ".pdf" not in lower:
        return False
    return any(kw in lower for kw in TAX_PDF_KEYWORDS)

def _is_any_pdf(url: str) -> bool:
    lower = url.lower()
    return lower.endswith(".pdf") or ".pdf?" in lower

def _is_dc_url(url: str) -> bool:
    """Reject URLs from DC government (the prior agent's mistake)."""
    return "dc.gov" in url.lower() or "otr.cfo.dc" in url.lower()

def _extract_pdf_links_from_page(page: Dict[str, Any], town_id: str) -> List[str]:
    """Extract plausible tax-delinquency PDF links from a Firecrawl page result."""
    raw_links: List[str] = page.get("links", []) or []
    markdown: str = page.get("markdown", "") or ""

    # Also scan markdown for inline href patterns
    md_links = re.findall(r'\((https?://[^\)\s]+\.pdf[^\)\s]*)\)', markdown, re.IGNORECASE)
    all_links = list(dict.fromkeys(raw_links + md_links))  # deduplicate, preserve order

    # Remove DC URLs (guard against prior bug)
    all_links = [l for l in all_links if not _is_dc_url(l)]

    # Priority 1: PDF with explicit tax keyword
    tax_pdfs = [l for l in all_links if _is_tax_pdf(l)]
    if tax_pdfs:
        logger.info("[%s] Found %d keyword-matched tax PDFs", town_id, len(tax_pdfs))
        return tax_pdfs

    # Priority 2: Any PDF on the same domain
    town_domains = {
        "newton": "newtonma.gov",
        "brookline": "brooklinema.gov",
        "needham": "needhamma.gov",
        "natick": "natickma.gov",
        "wayland": "wayland.ma.us",
        "lincoln": "lincolnma.org",
        "lexington": "lexingtonma.gov",
    }
    domain = town_domains.get(town_id, "")
    if domain:
        domain_pdfs = [l for l in all_links if _is_any_pdf(l) and domain in l.lower()]
        if domain_pdfs:
            logger.info("[%s] Found %d domain PDFs (no keyword match)", town_id, len(domain_pdfs))
            return domain_pdfs[:5]

    return []

def _page_has_tax_content(page: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if a page's markdown contains delinquency data (tables or lists).
    Returns (has_content, text_snippet).
    """
    markdown = (page.get("markdown") or "").lower()
    for kw in TAX_PAGE_KEYWORDS:
        if kw in markdown:
            # Return the full markdown (not lowercased) for LLM processing
            return True, page.get("markdown", "")
    return False, ""

# ── PDF download + text extraction ───────────────────────────────────────────

async def _download_pdf(url: str) -> Optional[bytes]:
    """Download a PDF via httpx. Returns None if not a valid PDF."""
    import httpx
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/pdf,*/*",
    }
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "text/html" in ct.lower():
                logger.warning("Got HTML instead of PDF from %s", url)
                return None
            if len(resp.content) < 500:
                logger.warning("Suspiciously small PDF (%d bytes) from %s", len(resp.content), url)
                return None
            return resp.content
    except Exception as exc:
        logger.warning("PDF download failed for %s: %s", url, exc)
        return None

def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed — run: pip install pdfplumber")
        return ""
    try:
        pages_text = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    pages_text.append(f"[PAGE {i+1}]\n{text}")
        return "\n\n".join(pages_text)
    except Exception as exc:
        logger.error("pdfplumber extraction failed: %s", exc)
        return ""

# ── OpenRouter LLM extraction ─────────────────────────────────────────────────

async def _llm_extract(text: str, town_name: str, source_type: str = "PDF") -> List[Dict[str, Any]]:
    """Send text to OpenRouter and parse structured tax delinquency entries."""
    import httpx

    prompt = f"""You are a Massachusetts municipal data engineer.

The text below was extracted from the {town_name} MA town website or a document from their Tax Collector's office.
It may contain a tax title list, tax delinquency list, or information about properties with unpaid taxes.

Your task: Extract EVERY property record you can find and return a JSON array.

Each element must have these exact fields (use null if not available):
{{
  "parcel_id": "Parcel ID, map-lot number, or account number if present",
  "owner": "Property owner name(s)",
  "address": "Full street address of the property",
  "amount_owed": "Dollar amount owed (as a string like '$1,234.56')",
  "tax_year": "Tax year or fiscal year if mentioned",
  "lien_date": "Date lien was placed or date of tax taking, if mentioned"
}}

Important:
- Extract ALL entries — don't stop early.
- If there are NO delinquency/tax-title records in this text (e.g. it's just a general collector page with hours and contact info), return an empty JSON array [].
- Do not invent data. Only include what is actually in the text.
- Return ONLY a valid JSON array. No markdown fences, no explanation.

Source type: {source_type}
Town: {town_name}, Massachusetts

Text:
---
{text[:60000]}
---

Return ONLY a JSON array:"""

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://sentinel-agent.local",
                    "X-Title": "Sentinel Tax Delinquency Scraper v2",
                },
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            parsed = [parsed]

        # Normalize keys
        normalized = []
        for item in parsed:
            normalized.append({
                "parcel_id": item.get("parcel_id"),
                "owner": item.get("owner"),
                "address": item.get("address"),
                "amount_owed": item.get("amount_owed"),
                "tax_year": item.get("tax_year") or item.get("year"),
                "lien_date": item.get("lien_date"),
            })
        return normalized

    except json.JSONDecodeError as exc:
        logger.error("LLM returned invalid JSON: %s", exc)
        return []
    except Exception as exc:
        logger.error("OpenRouter LLM call failed: %s", exc)
        return []

# ── Per-town processor ────────────────────────────────────────────────────────

async def process_town(town: Dict[str, Any], fc: FirecrawlClient) -> Dict[str, Any]:
    town_id = town["id"]
    town_name = town["name"]
    logger.info("=" * 60)
    logger.info("Processing: %s", town_name)
    logger.info("=" * 60)

    found_pdf_url: Optional[str] = None
    found_html_text: Optional[str] = None
    source_url: Optional[str] = None
    page_success = False  # did we successfully load at least one page?

    for url in town["collector_urls"]:
        logger.info("[%s] Scraping: %s", town_name, url)
        page = await fc.scrape(url, formats=["markdown", "links", "html"])

        if not page:
            logger.warning("[%s] No data returned from %s", town_name, url)
            await asyncio.sleep(3)
            continue

        page_success = True
        markdown = page.get("markdown", "") or ""
        logger.info("[%s] Got %d chars of markdown from %s", town_name, len(markdown), url)

        # Check for PDF links
        pdf_links = _extract_pdf_links_from_page(page, town_id)
        if pdf_links:
            # Use the first one (tax-keyword matched PDFs are sorted first)
            found_pdf_url = pdf_links[0]
            source_url = url
            logger.info("[%s] Found PDF link: %s", town_name, found_pdf_url)
            break

        # Check if the page itself has delinquency table/list
        has_content, content_text = _page_has_tax_content(page)
        if has_content:
            logger.info("[%s] Page has tax content (%d chars)", town_name, len(content_text))
            found_html_text = content_text
            source_url = url
            break

        await asyncio.sleep(3)

    # ── Extract records ────────────────────────────────────────────────────
    records: List[Dict[str, Any]] = []

    if found_pdf_url:
        logger.info("[%s] Downloading PDF: %s", town_name, found_pdf_url)
        pdf_bytes = await _download_pdf(found_pdf_url)
        if pdf_bytes:
            logger.info("[%s] PDF downloaded: %d bytes", town_name, len(pdf_bytes))
            pdf_text = _extract_pdf_text(pdf_bytes)
            if pdf_text and len(pdf_text.strip()) > 50:
                logger.info("[%s] PDF text extracted: %d chars", town_name, len(pdf_text))
                records = await _llm_extract(pdf_text, town_name, source_type="PDF")
                logger.info("[%s] LLM extracted %d records from PDF", town_name, len(records))
            else:
                logger.warning("[%s] PDF text extraction returned empty or too-short text", town_name)
        else:
            logger.warning("[%s] PDF download failed", town_name)

    elif found_html_text:
        logger.info("[%s] Extracting from page content (%d chars)", town_name, len(found_html_text))
        records = await _llm_extract(found_html_text, town_name, source_type="HTML page")
        logger.info("[%s] LLM extracted %d records from HTML", town_name, len(records))

    # ── Build result ───────────────────────────────────────────────────────
    ts = datetime.now().isoformat()

    if records:
        result = {
            "town": town_id,
            "name": town_name,
            "status": "extracted",
            "source_url": found_pdf_url or source_url,
            "scraped_at": ts,
            "record_count": len(records),
            "entries": records,
        }
        logger.info("[%s] SUCCESS — %d records", town_name, len(records))

    elif found_pdf_url or found_html_text:
        result = {
            "town": town_id,
            "name": town_name,
            "status": "extracted_empty",
            "source_url": found_pdf_url or source_url,
            "scraped_at": ts,
            "record_count": 0,
            "entries": [],
            "note": (
                "A potential source was found but the LLM returned 0 records. "
                "The page/PDF may contain general collector info, not a delinquency list."
            ),
        }
        logger.warning("[%s] Source found but 0 records", town_name)

    else:
        # Determine if we at least got the pages
        note = town["note_template"]
        if not page_success:
            note = (
                f"All collector URLs for {town_name} returned no data — pages may be "
                "down or blocked. MA towns typically do not publish tax title lists "
                "online; contact the Collector's office directly."
            )
        result = {
            "town": town_id,
            "name": town_name,
            "status": "not_published",
            "source_url": source_url,
            "scraped_at": ts,
            "record_count": 0,
            "entries": [],
            "note": note,
        }
        logger.info("[%s] Not published online", town_name)

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not OPENROUTER_KEY:
        logger.error("OPENROUTER_API_KEY not set — exiting")
        sys.exit(1)
    if not os.getenv("FIRECRAWL_API_KEY"):
        logger.error("FIRECRAWL_API_KEY not set — exiting")
        sys.exit(1)

    logger.info("OpenRouter model: %s", MODEL)
    logger.info("Output directory: %s", OUT_DIR)

    fc = FirecrawlClient()
    summary: List[Dict[str, Any]] = []

    for town in TOWNS:
        try:
            result = await process_town(town, fc)
        except Exception as exc:
            logger.error("Unhandled error for %s: %s", town["name"], exc, exc_info=True)
            result = {
                "town": town["id"],
                "name": town["name"],
                "status": "error",
                "error": str(exc),
                "scraped_at": datetime.now().isoformat(),
                "record_count": 0,
                "entries": [],
            }

        out_file = OUT_DIR / f"{town['id']}_tax_delinquency.json"
        out_file.write_text(json.dumps(result, indent=2))
        logger.info("Saved: %s", out_file)

        summary.append({
            "town": town["id"],
            "name": town["name"],
            "status": result["status"],
            "records": result.get("record_count", 0),
            "source": result.get("source_url") or "none",
            "note": result.get("note", ""),
        })

        logger.info("Sleeping 5s before next town...")
        await asyncio.sleep(5)

    # Save summary
    summary_file = OUT_DIR / "_run_summary_v2.json"
    summary_file.write_text(json.dumps({
        "run_at": datetime.now().isoformat(),
        "script": "scrape_remaining_tax_v2.py",
        "towns": summary,
    }, indent=2))

    # Print report
    print("\n" + "=" * 72)
    print("PHASE 4b v2 — MA TAX DELINQUENCY SCRAPE RESULTS")
    print("=" * 72)
    print(f"{'Town':<12} {'Status':<18} {'Records':>8}  Source")
    print("-" * 72)
    for s in summary:
        src = (s["source"] or "none")[:45]
        print(f"{s['name']:<12} {s['status']:<18} {s['records']:>8}  {src}")
    print("=" * 72)

    total = sum(s["records"] for s in summary)
    ok = sum(1 for s in summary if s["status"] == "extracted")
    empty = sum(1 for s in summary if s["status"] == "extracted_empty")
    not_pub = sum(1 for s in summary if s["status"] == "not_published")
    print(f"\nTotal towns: {len(summary)}")
    print(f"  extracted (with records): {ok}")
    print(f"  extracted_empty:          {empty}")
    print(f"  not_published:            {not_pub}")
    print(f"  Total records extracted:  {total}")
    print(f"\nOutput dir: {OUT_DIR}")
    print(f"Summary: {summary_file}")

    await fc.close()


if __name__ == "__main__":
    asyncio.run(main())
