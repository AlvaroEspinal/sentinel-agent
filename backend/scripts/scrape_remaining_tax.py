"""
Phase 4b: Scrape Tax Delinquency Data for 7 Remaining MA Towns.

Strategy per town:
1. Try known collector URL via Firecrawl to find PDF/HTML links
2. Try DuckDuckGo-style search via Firecrawl to find tax title PDFs
3. If PDF found, extract records via TaxDelinquencyScraper (OpenRouter LLM)
4. If only HTML found, extract tables via LLM
5. Save to backend/data_cache/tax_delinquency/{town_id}_tax_delinquency.json
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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
logger = logging.getLogger("scrape_remaining_tax")

from scrapers.connectors.tax_delinquency_scraper import TaxDelinquencyScraper
from scrapers.connectors.firecrawl_client import FirecrawlClient

# ── Town definitions ──────────────────────────────────────────────────────────

TOWNS = [
    {
        "id": "newton",
        "name": "Newton",
        "collector_urls": [
            "https://www.newtonma.gov/government/finance/collectors-office",
            "https://newtonma.gov/city-hall/finance/collector",
            "https://www.newtonma.gov/government/finance",
        ],
        "search_terms": [
            "Newton MA tax title list 2024 filetype:pdf",
            "Newton MA delinquent taxes 2024 collector PDF",
            '"tax title" site:newtonma.gov',
        ],
    },
    {
        "id": "brookline",
        "name": "Brookline",
        "collector_urls": [
            "https://www.brooklinema.gov/187/Collectors-Office",
            "https://www.brooklinema.gov/collector",
            "https://brooklinema.gov/187",
        ],
        "search_terms": [
            "Brookline MA tax title list 2024 filetype:pdf",
            "Brookline MA delinquent taxes collector PDF",
            '"tax title" site:brooklinema.gov',
        ],
    },
    {
        "id": "needham",
        "name": "Needham",
        "collector_urls": [
            "https://www.needhamma.gov/219/Tax-Collector",
            "https://www.needhamma.gov/collector",
            "https://needhamma.gov/219",
        ],
        "search_terms": [
            "Needham MA tax title list 2024 filetype:pdf",
            "Needham MA delinquent taxes collector PDF",
            '"tax title" site:needhamma.gov',
        ],
    },
    {
        "id": "natick",
        "name": "Natick",
        "collector_urls": [
            "https://www.natickma.gov/311/Tax-Collector",
            "https://www.natickma.gov/collector",
            "https://natickma.gov/311",
        ],
        "search_terms": [
            "Natick MA tax title list 2024 filetype:pdf",
            "Natick MA delinquent taxes collector PDF",
            '"tax title" site:natickma.gov',
        ],
    },
    {
        "id": "wayland",
        "name": "Wayland",
        "collector_urls": [
            "https://www.wayland.ma.us/collector",
            "https://www.wayland.ma.us/tax-collector",
            "https://www.wayland.ma.us/219/Tax-Collector",
        ],
        "search_terms": [
            "Wayland MA tax title list 2024 filetype:pdf",
            "Wayland MA delinquent taxes collector PDF",
            '"tax title" site:wayland.ma.us',
        ],
    },
    {
        "id": "lincoln",
        "name": "Lincoln",
        "collector_urls": [
            "https://www.lincolntown.org/collector",
            "https://www.lincolntown.org/tax-collector",
            "https://www.lincolntown.org/180/Tax-Collector",
        ],
        "search_terms": [
            "Lincoln MA tax title list 2024 filetype:pdf",
            "Lincoln MA delinquent taxes collector PDF",
            '"tax title" site:lincolntown.org',
        ],
    },
    {
        "id": "lexington",
        "name": "Lexington",
        "collector_urls": [
            "https://www.lexingtonma.gov/collectors-office",
            "https://www.lexingtonma.gov/collector",
            "https://lexingtonma.gov/200/Collectors-Office",
        ],
        "search_terms": [
            "Lexington MA tax title list 2024 filetype:pdf",
            "Lexington MA delinquent taxes collector PDF",
            '"tax title" site:lexingtonma.gov',
        ],
    },
]

OUT_DIR = BACKEND_DIR / "data_cache" / "tax_delinquency"

# ── PDF keyword filter ────────────────────────────────────────────────────────

PDF_KEYWORDS = [
    "tax title", "delinquent", "tax taking", "in rem", "unpaid tax",
    "collector", "lien", "overdue", "delinq", "outstanding",
]

def _looks_like_tax_pdf(url: str) -> bool:
    """Return True if the URL plausibly points to a tax delinquency PDF."""
    lower = url.lower()
    if not lower.endswith(".pdf"):
        return False
    return any(kw in lower for kw in PDF_KEYWORDS)

def _any_pdf(url: str) -> bool:
    return url.lower().endswith(".pdf")

# ── Link extraction helpers ───────────────────────────────────────────────────

def _extract_pdf_links(page_data: Dict[str, Any], town_id: str) -> List[str]:
    """Extract PDF links from a Firecrawl scrape result."""
    links: List[str] = page_data.get("links", [])
    markdown: str = page_data.get("markdown", "") or ""
    
    # Also parse markdown for hrefs
    md_links = re.findall(r'\[.*?\]\((https?://[^\)]+\.pdf[^\)]*)\)', markdown, re.IGNORECASE)
    links = list(set(links + md_links))

    # Priority 1: strong keyword match
    tax_pdfs = [l for l in links if _looks_like_tax_pdf(l)]
    if tax_pdfs:
        return tax_pdfs

    # Priority 2: any PDF from the town's domain
    town_slug = town_id.replace("_", "")
    town_pdfs = [l for l in links if _any_pdf(l) and (town_slug in l.lower() or ".gov" in l.lower() or ".us" in l.lower())]
    if town_pdfs:
        return town_pdfs[:5]  # cap to avoid garbage

    return []

def _extract_html_table_text(page_data: Dict[str, Any]) -> str:
    """Return markdown/html table text if the page contains tabular data."""
    markdown = page_data.get("markdown", "") or ""
    html = page_data.get("html", "") or ""
    
    # Check for pipe-table in markdown (common Firecrawl output for HTML tables)
    if "|" in markdown and len(markdown) > 200:
        return markdown
    if "<table" in html.lower():
        return html[:50000]
    return ""

# ── OpenRouter LLM for HTML extraction ───────────────────────────────────────

async def _llm_extract_from_html(
    html_text: str,
    town_name: str,
    openrouter_key: str,
    model: str = "google/gemini-2.0-flash-001",
) -> List[Dict[str, Any]]:
    """Send HTML/markdown table text to OpenRouter for structured extraction."""
    import httpx

    prompt = f"""You are a Massachusetts municipal data engineer.

Below is text from the {town_name} MA town website — specifically from a page related to
tax delinquency, tax titles, or overdue property taxes.

Extract EVERY property record you find and return a JSON array.

Each element must have:
{{
  "address": "Full street address",
  "owner": "Owner name(s) or null",
  "amount_owed": "Dollar amount as string, e.g. '$1,234.56' or null",
  "parcel_id": "Parcel/map-lot ID if present or null",
  "year": "Tax year if listed or null",
  "tax_type": "Type, e.g. 'Real Estate', 'Water/Sewer', or null"
}}

If there are no tax delinquency records in the text, return an empty JSON array [].

Return ONLY a valid JSON array, no markdown fences, no explanation.

Text:
---
{html_text[:50000]}
---"""

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://sentinel-agent.local",
                "X-Title": "Sentinel Tax Delinquency Scraper",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)

# ── Per-town processor ────────────────────────────────────────────────────────

async def process_town(
    town: Dict[str, Any],
    scraper: TaxDelinquencyScraper,
    fc: FirecrawlClient,
    openrouter_key: str,
) -> Dict[str, Any]:
    town_id = town["id"]
    town_name = town["name"]
    logger.info("=" * 60)
    logger.info("Processing: %s (%s)", town_name, town_id)
    logger.info("=" * 60)

    found_pdf_url: Optional[str] = None
    found_html_text: Optional[str] = None
    source_url: Optional[str] = None

    # ── Step 1: Try known collector URLs ─────────────────────────────────
    for url in town["collector_urls"]:
        logger.info("[%s] Scraping collector URL: %s", town_name, url)
        page = await fc.scrape(url, formats=["markdown", "links", "html"])
        if not page:
            logger.info("[%s] No data from %s", town_name, url)
            await asyncio.sleep(2)
            continue

        pdf_links = _extract_pdf_links(page, town_id)
        if pdf_links:
            logger.info("[%s] Found %d PDF links: %s", town_name, len(pdf_links), pdf_links[:3])
            found_pdf_url = pdf_links[0]
            source_url = url
            break

        # Check for HTML table with tax data
        table_text = _extract_html_table_text(page)
        if table_text and any(kw in table_text.lower() for kw in PDF_KEYWORDS):
            logger.info("[%s] Found HTML table text (%d chars)", town_name, len(table_text))
            found_html_text = table_text
            source_url = url
            break

        await asyncio.sleep(2)

    # ── Step 2: Search via DuckDuckGo through Firecrawl ──────────────────
    if not found_pdf_url and not found_html_text:
        logger.info("[%s] No PDF/HTML from collector pages. Trying search...", town_name)
        for query in town["search_terms"]:
            encoded = urllib.parse.quote_plus(query)
            search_url = f"https://duckduckgo.com/?q={encoded}&ia=web"
            logger.info("[%s] Searching: %s", town_name, query)
            page = await fc.scrape(search_url, formats=["markdown", "links"])
            if not page:
                await asyncio.sleep(3)
                continue

            links = page.get("links", []) or []
            # Filter for government PDFs
            gov_pdfs = [l for l in links if _looks_like_tax_pdf(l) and (".gov" in l or ".us" in l or town_id in l.lower())]
            if gov_pdfs:
                found_pdf_url = gov_pdfs[0]
                source_url = search_url
                logger.info("[%s] Search found PDF: %s", town_name, found_pdf_url)
                break

            # Also try to find any gov PDF
            any_gov_pdfs = [l for l in links if _any_pdf(l) and (".gov" in l or ".ma.us" in l)]
            if any_gov_pdfs:
                found_pdf_url = any_gov_pdfs[0]
                source_url = search_url
                logger.info("[%s] Search found gov PDF: %s", town_name, found_pdf_url)
                break

            await asyncio.sleep(3)

    # ── Step 3: Extract records ───────────────────────────────────────────
    records: List[Dict[str, Any]] = []

    if found_pdf_url:
        logger.info("[%s] Extracting from PDF: %s", town_name, found_pdf_url)
        try:
            records = await scraper.extract_from_url(found_pdf_url)
            logger.info("[%s] PDF extraction returned %d records", town_name, len(records))
        except Exception as exc:
            logger.error("[%s] PDF extraction failed: %s", town_name, exc)

    elif found_html_text:
        logger.info("[%s] Extracting from HTML table (%d chars)", town_name, len(found_html_text))
        try:
            records = await _llm_extract_from_html(found_html_text, town_name, openrouter_key)
            logger.info("[%s] HTML extraction returned %d records", town_name, len(records))
        except Exception as exc:
            logger.error("[%s] HTML extraction failed: %s", town_name, exc)

    # ── Step 4: Build result ──────────────────────────────────────────────
    timestamp = datetime.now().isoformat()

    if records and len(records) > 0:
        result = {
            "town": town_id,
            "name": town_name,
            "status": "success",
            "year": datetime.now().year,
            "source_url": found_pdf_url or source_url,
            "scraped_at": timestamp,
            "record_count": len(records),
            "entries": records,
        }
        logger.info("[%s] SUCCESS — %d records extracted", town_name, len(records))
    elif found_pdf_url or found_html_text:
        # Found a source but got 0 records (parse issue or empty document)
        result = {
            "town": town_id,
            "name": town_name,
            "status": "extracted_empty",
            "source_url": found_pdf_url or source_url,
            "scraped_at": timestamp,
            "record_count": 0,
            "entries": [],
            "note": "Source found but LLM returned 0 records — may be a garbled PDF or non-standard format",
        }
        logger.warning("[%s] Source found but 0 records extracted", town_name)
    else:
        result = {
            "town": town_id,
            "name": town_name,
            "status": "not_published",
            "scraped_at": timestamp,
            "record_count": 0,
            "entries": [],
            "note": (
                f"{town_name} MA does not appear to publish a publicly accessible "
                "tax delinquency / tax title list online. Tried collector office pages "
                "and search queries."
            ),
        }
        logger.warning("[%s] No tax delinquency data found publicly", town_name)

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Output directory: %s", OUT_DIR)

    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        logger.error("OPENROUTER_API_KEY not set. Exiting.")
        sys.exit(1)

    scraper = TaxDelinquencyScraper()
    fc = FirecrawlClient()

    summary: List[Dict[str, Any]] = []

    for town in TOWNS:
        try:
            result = await process_town(town, scraper, fc, openrouter_key)
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

        # Save individual town file
        out_file = OUT_DIR / f"{town['id']}_tax_delinquency.json"
        out_file.write_text(json.dumps(result, indent=2))
        logger.info("Saved: %s", out_file)

        summary.append({
            "town": town["id"],
            "name": town["name"],
            "status": result["status"],
            "records": result.get("record_count", 0),
            "source": result.get("source_url", "none"),
        })

        # Rate limit between towns
        logger.info("Waiting 5s before next town...")
        await asyncio.sleep(5)

    # Save summary
    summary_file = OUT_DIR / "_run_summary.json"
    summary_file.write_text(json.dumps({
        "run_at": datetime.now().isoformat(),
        "towns": summary,
    }, indent=2))

    # Print report
    print("\n" + "=" * 70)
    print("PHASE 4b — TAX DELINQUENCY SCRAPE RESULTS")
    print("=" * 70)
    print(f"{'Town':<15} {'Status':<20} {'Records':>8}  Source")
    print("-" * 70)
    for s in summary:
        src = (s["source"] or "none")[:40]
        print(f"{s['name']:<15} {s['status']:<20} {s['records']:>8}  {src}")
    print("=" * 70)

    total_records = sum(s["records"] for s in summary)
    successes = sum(1 for s in summary if s["status"] == "success")
    print(f"\nTotal towns: {len(summary)} | Successes: {successes} | Total records: {total_records}")
    print(f"Output: {OUT_DIR}")

    await scraper.close()
    await fc.close()


if __name__ == "__main__":
    asyncio.run(main())
