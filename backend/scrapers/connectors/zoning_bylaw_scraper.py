import os
import json
import logging
import asyncio
import re
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = os.getenv("OPENROUTER_DEFAULT_MODEL", "google/gemini-2.0-flash-001")


async def _call_openrouter(prompt: str, max_tokens: int = 8192) -> str:
    """Send a prompt to OpenRouter and return the response text."""
    import httpx

    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set in environment")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/AlvaroEspinal/sentinel-agent",
        "X-Title": "Sentinel Agent Zoning Scraper",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


def _is_anchor_only(url: str) -> bool:
    """Return True if a URL is only a fragment anchor (e.g. page.html#section)."""
    parsed = urlparse(url)
    # An anchor-only or same-page anchor URL has a fragment and a path that
    # matches the page path (or no meaningful path component beyond the anchor)
    return bool(parsed.fragment) and not parsed.path.strip("/").replace(parsed.fragment, "")


def _is_document_viewer_url(url: str) -> bool:
    """Return True if the URL is a CivicPlus/Granicus document viewer URL that serves a PDF."""
    lower = url.lower()
    return (
        "/documentcenter/view/" in lower
        or "/documentcenter/home/view/" in lower
        or "filestore" in lower
    )


class ZoningBylawScraper:
    def __init__(self):
        logger.info(
            "[ZoningBylawScraper] Initialized with OpenRouter model: %s", OPENROUTER_MODEL
        )

    async def _fetch_page_with_httpx(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch a page using direct httpx + BeautifulSoup. Returns the full result dict or None."""
        import httpx

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = await client.get(url)

            if resp.status_code != 200:
                logger.warning(
                    "[ZoningBylawScraper] HTTP %d fetching %s", resp.status_code, url
                )
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract all href links
            links: List[str] = []
            for tag in soup.find_all("a", href=True):
                href = tag["href"].strip()
                if href:
                    abs_href = href if href.startswith("http") else urljoin(url, href)
                    links.append(abs_href)

            # Extract page text as markdown-like string
            # Remove script/style noise
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            page_text = soup.get_text(separator="\n", strip=True)

            logger.info(
                "[ZoningBylawScraper] Fetched %s: %d chars, %d links",
                url, len(page_text), len(links),
            )
            return {"markdown": page_text, "links": links}

        except Exception as exc:
            logger.warning("[ZoningBylawScraper] httpx fetch failed for %s: %s", url, exc)
            return None

    def _score_pdf_link(self, url: str) -> int:
        """Score a PDF/document link by relevance to zoning bylaws. Higher = more relevant."""
        lower = url.lower()
        score = 0
        # High-priority keywords in filename
        for kw in ["zoning", "bylaw", "by-law", "ordinance", "regulation"]:
            if kw in lower:
                score += 10
        # Medium-priority
        for kw in ["chapter", "title", "code", "bylaw"]:
            if kw in lower:
                score += 5
        # It's a real .pdf extension
        if lower.endswith(".pdf"):
            score += 3
        # It's a document viewer URL (often serves PDFs)
        if _is_document_viewer_url(url):
            score += 2
        # Penalize obviously non-zoning docs
        for kw in ["map", "guideline", "design", "sign", "beacon", "boylston",
                   "preservation", "parking", "lhd", "boa-rules", "subdivision",
                   "town-by-laws", "general-by"]:
            if kw in lower:
                score -= 8
        return score

    def _find_pdf_links(self, result: Dict[str, Any], base_url: str) -> List[str]:
        """Extract PDF/document links from a Firecrawl result, ranked by relevance.

        Handles:
        - Direct .pdf URLs
        - CivicPlus DocumentCenter/View/ viewer URLs (serve PDFs)
        - Markdown link syntax
        """
        candidate_links: List[str] = []

        links = list(result.get("links", []))

        # Also scan markdown for bare PDF URLs
        markdown = result.get("markdown", "")
        md_urls = re.findall(r'https?://[^\s\)\"\']+\.pdf(?:\?[^\s\)\"\']*)?', markdown, re.IGNORECASE)
        for u in md_urls:
            if u not in links:
                links.append(u)

        for link in links:
            if not link:
                continue
            # Skip anchor-only links
            if link.startswith("#"):
                continue
            parsed = urlparse(link)
            if parsed.fragment and not parsed.path:
                continue  # pure anchor

            # Make absolute
            abs_link = link if link.startswith("http") else urljoin(base_url, link)
            lower = abs_link.lower()

            is_pdf = lower.endswith(".pdf") or ".pdf?" in lower
            is_viewer = _is_document_viewer_url(abs_link)

            if is_pdf or is_viewer:
                score = self._score_pdf_link(abs_link)
                if score > 0:  # Only include if positively scored
                    candidate_links.append((score, abs_link))

        # Sort by score descending, de-duplicate
        candidate_links.sort(key=lambda x: x[0], reverse=True)
        seen: set = set()
        result_links: List[str] = []
        for score, lnk in candidate_links:
            if lnk not in seen:
                seen.add(lnk)
                result_links.append(lnk)
                logger.debug("[ZoningBylawScraper] PDF candidate (score=%d): %s", score, lnk)

        return result_links

    def _find_zoning_subpage_url(
        self, result: Dict[str, Any], base_url: str, current_url: str
    ) -> Optional[str]:
        """Find a zoning chapter/subpage link on an index page.

        Skips anchor-only fragments and same-page anchors.
        Prefers URLs that differ meaningfully from the current page.
        """
        links = result.get("links", [])
        current_path = urlparse(current_url).path.lower()

        candidates: List[tuple] = []

        for link in links:
            if not link or link.startswith("#"):
                continue
            parsed = urlparse(link)
            if parsed.fragment and not parsed.path:
                continue  # pure anchor
            if not link.startswith("http"):
                abs_link = urljoin(base_url, link)
            else:
                abs_link = link

            link_path = urlparse(abs_link).path.lower()
            if link_path == current_path:
                continue  # Same page (with or without anchor)

            lower = abs_link.lower()
            if "zoning" in lower and "amendment" not in lower and "map" not in lower:
                # Prefer links that look like the actual bylaw page
                score = 0
                if "bylaw" in lower or "by-law" in lower or "ordinance" in lower:
                    score += 10
                if "planning" in lower:
                    score += 2
                if "ecode360" in lower:
                    score -= 5  # Avoid ecode360 — it needs auth
                candidates.append((score, abs_link))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        best_url = candidates[0][1]
        logger.info("[ZoningBylawScraper] Best zoning subpage: %s (score=%d)", best_url, candidates[0][0])
        return best_url

    async def _extract_text_from_pdf_url(self, pdf_url: str) -> str:
        """Download a PDF (or document viewer URL) and extract text from the first 30 pages."""
        import httpx
        import pdfplumber
        import io

        # For CivicPlus DocumentCenter viewer, try appending /download or just fetch directly
        # The viewer URL itself often redirects to the PDF
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/pdf,*/*",
        }

        extracted = ""
        try:
            async with httpx.AsyncClient(
                timeout=60.0,
                follow_redirects=True,
                headers=headers,
            ) as client:
                logger.info("[ZoningBylawScraper] Downloading: %s", pdf_url)
                resp = await client.get(pdf_url)

                if resp.status_code != 200:
                    logger.warning(
                        "[ZoningBylawScraper] Download failed HTTP %d: %s",
                        resp.status_code, pdf_url,
                    )
                    return ""

                content_type = resp.headers.get("content-type", "").lower()
                content = resp.content

                # Check if it's actually a PDF
                if not (content[:4] == b"%PDF" or "pdf" in content_type):
                    logger.warning(
                        "[ZoningBylawScraper] Response is not a PDF (content-type: %s): %s",
                        content_type, pdf_url,
                    )
                    return ""

                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    pages_to_read = min(30, len(pdf.pages))
                    logger.info(
                        "[ZoningBylawScraper] Reading %d/%d pages from PDF",
                        pages_to_read, len(pdf.pages),
                    )
                    for page in pdf.pages[:pages_to_read]:
                        page_text = page.extract_text()
                        if page_text:
                            extracted += page_text + "\n\n"
                        table = page.extract_table()
                        if table:
                            for row in table:
                                clean_row = [str(c) if c else "" for c in row]
                                extracted += " | ".join(clean_row) + "\n"

        except Exception as exc:
            logger.error("[ZoningBylawScraper] Error processing %s: %s", pdf_url, exc)

        return extracted

    async def extract_table_of_uses(
        self, town_name: str, zoning_url: str
    ) -> Optional[Dict[str, Any]]:
        """Main entry point: scrape a town's zoning page and extract structured data.

        Workflow:
        1. Use direct httpx to fetch the zoning page → page text + links
        2. Find PDF/document links on the page (ranked by zoning relevance)
        3. If no good PDFs found, check if the page links to a zoning bylaws subpage
        4. Download PDFs and extract text (first 30 pages)
        5. Use OpenRouter LLM to extract structured zoning data
        """
        logger.info(
            "[ZoningBylawScraper] Starting extraction for %s from %s", town_name, zoning_url
        )

        extracted_text = ""
        attachment_urls: List[str] = []

        # Handle direct PDF URL or CivicPlus DocumentCenter URL (which serves PDFs directly)
        if (zoning_url.lower().endswith(".pdf")
                or "/attachment/" in zoning_url.lower()
                or _is_document_viewer_url(zoning_url)
                or "showpublisheddocument" in zoning_url.lower()):
            logger.info("[ZoningBylawScraper] URL is a direct PDF/document — skipping page scrape")
            attachment_urls.append(zoning_url)
        else:
            # Step 1: Scrape the zoning page
            result = await self._fetch_page_with_httpx(zoning_url)

            if result:
                # Collect page text (markdown)
                markdown = result.get("markdown", "")
                extracted_text += markdown

                # Step 2: Find PDF/document links
                pdf_links = self._find_pdf_links(result, zoning_url)
                attachment_urls.extend(pdf_links)

                if pdf_links:
                    logger.info(
                        "[ZoningBylawScraper] Found %d PDF/document links on main page",
                        len(pdf_links),
                    )
                else:
                    # Step 3: Look for a zoning bylaws subpage
                    logger.info(
                        "[ZoningBylawScraper] No PDF links found — looking for zoning subpage"
                    )
                    subpage_url = self._find_zoning_subpage_url(result, zoning_url, zoning_url)
                    if subpage_url:
                        logger.info("[ZoningBylawScraper] Fetching subpage: %s", subpage_url)
                        result2 = await self._fetch_page_with_httpx(subpage_url)
                        if result2:
                            markdown2 = result2.get("markdown", "")
                            extracted_text += "\n\n" + markdown2
                            pdf_links2 = self._find_pdf_links(result2, subpage_url)
                            attachment_urls.extend(pdf_links2)
                            if pdf_links2:
                                logger.info(
                                    "[ZoningBylawScraper] Found %d PDF links on subpage",
                                    len(pdf_links2),
                                )
            else:
                logger.error(
                    "[ZoningBylawScraper] Failed to fetch %s via httpx", zoning_url
                )

        # Step 4: Download and extract text from PDFs (up to 3 best-ranked)
        if attachment_urls:
            logger.info(
                "[ZoningBylawScraper] Processing up to 3 of %d document link(s) for %s",
                len(attachment_urls), town_name,
            )
            pdf_text_parts: List[str] = []
            for doc_url in attachment_urls[:3]:
                pdf_text = await self._extract_text_from_pdf_url(doc_url)
                if pdf_text:
                    pdf_text_parts.append(pdf_text)
                    logger.info(
                        "[ZoningBylawScraper] Extracted %d chars from %s",
                        len(pdf_text), doc_url,
                    )
            if pdf_text_parts:
                # Prepend PDF text — it's more structured than HTML page text
                extracted_text = "\n\n".join(pdf_text_parts) + "\n\n" + extracted_text
        else:
            logger.info(
                "[ZoningBylawScraper] No PDF links found for %s — using page text only",
                town_name,
            )

        if not extracted_text.strip():
            logger.error(
                "[ZoningBylawScraper] No text extracted for %s — giving up", town_name
            )
            return None

        logger.info(
            "[ZoningBylawScraper] Sending %d chars to LLM for %s",
            len(extracted_text), town_name,
        )

        # Step 5: LLM extraction
        prompt = f"""You are an expert real estate attorney and municipal data engineer.
I am providing you with text extracted from the Zoning Bylaws (or Zoning Ordinance) for {town_name}, Massachusetts.
The text may come from HTML pages, PDFs, or both.

Your objective: extract the zoning districts and their key rules into structured JSON.

Specifically, look for:
1. "Table of Use Regulations" or "Use Schedule" — which uses are permitted by right vs. by special permit per district
2. "Dimensional Requirements" or "Dimensional Schedule" — minimum lot size, frontage, setbacks, height limits per district
3. District names/codes (e.g. SR-1, RO, CB, MU, etc.)

Output valid JSON ONLY with the following schema:
{{
  "town": "{town_name}",
  "source_type": "page_text or pdf",
  "districts": [
    {{
      "code": "e.g. SR-1, RO, CB",
      "name": "e.g. Single Residence, Central Business",
      "allowed_uses": ["List of uses permitted by right"],
      "special_permit_uses": ["List of uses requiring a special permit"],
      "dimensional_requirements": {{
        "min_lot_size_sqft": 15000,
        "min_frontage_ft": 100,
        "max_height_ft": 35,
        "min_front_setback_ft": 20,
        "min_side_setback_ft": 10,
        "min_rear_setback_ft": 20
      }}
    }}
  ],
  "sections": [
    {{
      "title": "Section heading",
      "summary": "1-2 sentence summary of this section"
    }}
  ]
}}

Rules:
- Include dimensional_requirements only when numeric data is present in the text.
- List the most important 5-10 uses per category (by right / special permit). Don't list every minor variant.
- If districts are not clearly named, infer from context.
- The "sections" array should capture major headings found in the document (up to 20 sections).
- Return ONLY valid JSON — no markdown code fences, no explanations.

Extracted text:
---
{extracted_text[:120000]}
---
"""
        try:
            result_text = await _call_openrouter(prompt, max_tokens=8192)

            # Strip markdown code fences if present
            if result_text.startswith("```"):
                parts = result_text.split("```")
                if len(parts) >= 3:
                    result_text = parts[1]
                    if result_text.startswith("json"):
                        result_text = result_text[4:]
                result_text = result_text.strip()

            try:
                parsed = json.loads(result_text)
                parsed["source_url"] = zoning_url
                return parsed
            except json.JSONDecodeError as exc:
                logger.error(
                    "[ZoningBylawScraper] Failed to parse LLM JSON output: %s", exc
                )
                with open("/tmp/failed_zoning_json.txt", "w") as f:
                    f.write(result_text)
                logger.info("Raw LLM output dumped to /tmp/failed_zoning_json.txt")
                return None

        except Exception as exc:
            logger.error(
                "[ZoningBylawScraper] LLM extraction error for %s: %s", town_name, exc
            )
            return None

    async def scrape(
        self, town_id: str, town_name: str, url: str
    ) -> Dict[str, Any]:
        """Public alias for extract_table_of_uses. Returns a result dict always.

        On failure, returns {"status": "failed", "town_id": town_id, ...}
        On success, returns the parsed zoning JSON with "status": "success".
        """
        result = await self.extract_table_of_uses(town_name, url)
        if result is None:
            return {
                "status": "failed",
                "town_id": town_id,
                "town": town_name,
                "source_url": url,
                "districts": [],
                "sections": [],
            }
        result["status"] = "success"
        result["town_id"] = town_id
        return result
