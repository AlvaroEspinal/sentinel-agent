#!/usr/bin/env python3
"""
Newton Meeting Minutes Scraper — Granicus/CivicPlus via Firecrawl.

Newton PDFs at https://www.newtonma.gov/home/showpublisheddocument/...
return HTTP 403 when fetched directly (session/Referer requirement).

Fix: Use FirecrawlClient.scrape() with browser rendering for both:
  1. Listing pages (discover PDF links)
  2. PDF downloads (browser session bypasses 403)

Boards:
  - Planning Board
  - City Council
  - ZBA (Zoning Board of Appeals)
  - Conservation Commission

Output: backend/data_cache/meeting_minutes/newton_minutes.json
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sys
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scrape_newton_minutes")

from backend.config import FIRECRAWL_API_KEY
from backend.scrapers.connectors.firecrawl_client import FirecrawlClient

# ── Config ─────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "meeting_minutes"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NEWTON_BASE = "https://www.newtonma.gov"

# Limit per board and year range
MAX_PER_BOARD = 20
MIN_YEAR = 2024
MAX_YEAR = 2026

# Board listing pages — the primary discovery URLs
NEWTON_BOARDS: Dict[str, Dict[str, Any]] = {
    "planning_board": {
        "name": "Planning Board",
        "listing_urls": [
            f"{NEWTON_BASE}/government/planning-development/planning-board/planning-board-agendas-minutes",
            f"{NEWTON_BASE}/government/planning/boards-commissions/planning-and-development-board/archived-meeting-documents",
            f"{NEWTON_BASE}/government/planning/boards-commissions/planning-and-development-board/current-year-agendas-minutes",
        ],
    },
    "city_council": {
        "name": "City Council",
        "listing_urls": [
            f"{NEWTON_BASE}/government/city-clerk/city-council-agendas-minutes",
            f"{NEWTON_BASE}/government/city-clerk/city-council",
        ],
    },
    "zba": {
        "name": "Zoning Board of Appeals",
        "listing_urls": [
            f"{NEWTON_BASE}/government/inspectional-services/zoning-board-of-appeals/zba-agendas-minutes",
            f"{NEWTON_BASE}/government/planning/zoning-board-of-appeals/meeting-documents",
        ],
    },
    "conservation_commission": {
        "name": "Conservation Commission",
        "listing_urls": [
            f"{NEWTON_BASE}/government/conservation-commission/conservation-commission-minutes",
            f"{NEWTON_BASE}/government/planning/conservation-office/meeting-info-documents",
        ],
    },
}


# ── Date utilities ─────────────────────────────────────────────────────────────

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


def extract_date(text: str) -> Optional[str]:
    """Return first plausible meeting date as 'YYYY-MM-DD' or None."""
    if not text:
        return None

    # YYYY-MM-DD
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if MIN_YEAR <= d.year <= MAX_YEAR + 1:
                return d.isoformat()
        except ValueError:
            pass

    # MM/DD/YYYY or MM-DD-YYYY
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](20\d{2})", text)
    if m:
        try:
            d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            if MIN_YEAR <= d.year <= MAX_YEAR + 1:
                return d.isoformat()
        except ValueError:
            pass

    # Month DD, YYYY  or  Month DD YYYY
    m = re.search(
        r"(january|february|march|april|may|june|july|august|"
        r"september|october|november|december|jan|feb|mar|apr|"
        r"jun|jul|aug|sep|sept|oct|nov|dec)"
        r"[.\s]+(\d{1,2})[,\s]+(20\d{2})",
        text.lower(),
    )
    if m:
        try:
            d = date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
            if MIN_YEAR <= d.year <= MAX_YEAR + 1:
                return d.isoformat()
        except (ValueError, KeyError):
            pass

    return None


def is_in_year_range(meeting_date: Optional[str]) -> bool:
    """Return True if the date is within our target range (or if date is unknown)."""
    if not meeting_date:
        return True  # Include unknowns — we'll filter by context
    try:
        y = int(meeting_date[:4])
        return MIN_YEAR <= y <= MAX_YEAR
    except (ValueError, TypeError):
        return True


# ── Document builder ───────────────────────────────────────────────────────────

def make_doc(
    board_slug: str,
    board_name: str,
    title: str,
    meeting_date: Optional[str],
    content: str,
    url: str,
) -> Dict[str, Any]:
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    return {
        "board": board_slug,
        "title": title,
        "date": meeting_date,
        "url": url,
        "content": content[:50000],
        "content_hash": content_hash,
        "_board_name": board_name,
    }


# ── PDF link extraction ────────────────────────────────────────────────────────

def extract_pub_doc_links(
    result: Dict[str, Any],
    base_url: str = "",
) -> List[Tuple[str, str]]:
    """
    Extract showpublisheddocument links from a Firecrawl result.
    Returns list of (url, title_hint) tuples.
    """
    pairs: Dict[str, str] = {}  # url -> title_hint

    links = result.get("links", []) or []
    md = result.get("markdown", "") or ""

    # From the links list
    for lnk in links:
        if not lnk:
            continue
        lnk = lnk.strip()
        if "showpublisheddocument" in lnk.lower():
            # Make absolute
            if lnk.startswith("/"):
                lnk = f"{NEWTON_BASE}{lnk}"
            if lnk not in pairs:
                pairs[lnk] = ""

    # From markdown — captures [title](url) patterns
    for title_hint, lnk in re.findall(
        r"\[([^\]]{1,200})\]\((https?://[^)]+showpublisheddocument[^)]+)\)",
        md, re.I,
    ):
        lnk = lnk.strip()
        if lnk not in pairs or not pairs[lnk]:
            pairs[lnk] = title_hint.strip()

    # Also look for bare URLs in markdown text
    for lnk in re.findall(
        r"https?://[^\s\)\"']+showpublisheddocument[^\s\)\"']+",
        md, re.I,
    ):
        lnk = lnk.strip().rstrip(".,;)")
        if lnk not in pairs:
            pairs[lnk] = ""

    return list(pairs.items())


def filter_minutes_links(
    pairs: List[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    """
    Keep links that look like minutes (or are ambiguous).
    Drop links that are clearly agendas or non-document items.
    """
    skip_words = [
        "agenda",
        "presentation", "present",
        "attachment", "exhibit",
        "recording", "video",
        "staff report", "staffreport",
        "report",
    ]
    minutes_words = ["minute", "approved", "draft"]

    result = []
    for url, title in pairs:
        title_lower = title.lower()
        url_lower = url.lower()

        # Skip obvious non-minutes
        if any(w in title_lower for w in skip_words):
            continue

        # Prefer confirmed minutes
        if any(w in title_lower or w in url_lower for w in minutes_words):
            result.append((url, title))
            continue

        # Include ambiguous (no clear indicator either way)
        result.append((url, title))

    return result


# ── Board scraper ──────────────────────────────────────────────────────────────

async def discover_pdf_links(
    fc: FirecrawlClient,
    listing_url: str,
    board_name: str,
) -> List[Tuple[str, str]]:
    """
    Scrape a board's listing page via Firecrawl and extract PDF document links.
    Returns (url, title_hint) pairs.
    """
    logger.info("[Newton/%s] Fetching listing: %s", board_name, listing_url)

    result = await fc.scrape(
        listing_url,
        formats=["markdown", "links"],
        only_main_content=False,
        wait_for=5000,
    )

    if not result:
        logger.warning("[Newton/%s] No result from Firecrawl for %s", board_name, listing_url)
        return []

    pairs = extract_pub_doc_links(result, listing_url)
    logger.info("[Newton/%s] Found %d document links on listing page", board_name, len(pairs))

    # Also check if there are sub-pages (year folders, etc.) with more links
    md = result.get("markdown", "") or ""
    links = result.get("links", []) or []

    # Look for year-folder sub-pages
    year_folder_links = []
    for lnk in links:
        if not lnk:
            continue
        # Pattern: /-folder-NNN or /archived-meeting-documents or year sub-paths
        if re.search(r"(-folder-\d+|archived-meeting|/20(24|25|26))", lnk, re.I):
            if lnk.startswith("/"):
                lnk = f"{NEWTON_BASE}{lnk}"
            if NEWTON_BASE in lnk and lnk != listing_url:
                year_folder_links.append(lnk)

    # Deduplicate year folder links
    year_folder_links = list(dict.fromkeys(year_folder_links))[:5]

    for sub_url in year_folder_links:
        logger.info("[Newton/%s] Checking sub-page: %s", board_name, sub_url)
        sub_result = await fc.scrape(
            sub_url,
            formats=["markdown", "links"],
            only_main_content=False,
            wait_for=4000,
        )
        if sub_result:
            sub_pairs = extract_pub_doc_links(sub_result, sub_url)
            logger.info("[Newton/%s] Sub-page %s: %d links", board_name, sub_url, len(sub_pairs))
            for url, title in sub_pairs:
                if url not in [p[0] for p in pairs]:
                    pairs.append((url, title))
        await asyncio.sleep(1.0)

    return pairs


async def fetch_pdf_via_firecrawl(
    fc: FirecrawlClient,
    pdf_url: str,
    board_name: str,
) -> str:
    """
    Use Firecrawl browser rendering to fetch a PDF URL that returns 403 on direct access.
    Firecrawl extracts text from PDFs automatically.
    Returns extracted text/markdown content, or empty string on failure.
    """
    logger.info("[Newton/%s] Fetching PDF via Firecrawl: %s", board_name, pdf_url)

    result = await fc.scrape(
        pdf_url,
        formats=["markdown"],
        only_main_content=False,
        wait_for=6000,
    )

    if not result:
        logger.warning("[Newton/%s] No Firecrawl result for PDF %s", board_name, pdf_url)
        return ""

    content = result.get("markdown", "") or ""

    # Also try html if markdown is empty
    if not content or len(content) < 50:
        content = result.get("html", "") or ""
        if content:
            # Strip HTML tags
            content = re.sub(r"<[^>]+>", " ", content)
            content = re.sub(r"\s+", " ", content).strip()

    if content:
        logger.info(
            "[Newton/%s] PDF content extracted: %d chars", board_name, len(content)
        )
    else:
        logger.warning("[Newton/%s] Empty content from PDF %s", board_name, pdf_url)

    return content


async def scrape_newton_board(
    fc: FirecrawlClient,
    board_slug: str,
    board_cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Scrape one Newton board — discover PDF links then fetch each via Firecrawl."""
    board_name = board_cfg["name"]
    listing_urls = board_cfg["listing_urls"]

    logger.info("=" * 50)
    logger.info("[Newton] Board: %s", board_name)
    logger.info("=" * 50)

    # Step 1: Discover all PDF links across all listing URLs
    all_pairs: Dict[str, str] = {}  # url -> title_hint

    for listing_url in listing_urls:
        try:
            pairs = await discover_pdf_links(fc, listing_url, board_name)
            for url, title in pairs:
                if url not in all_pairs or not all_pairs[url]:
                    all_pairs[url] = title
        except Exception as exc:
            logger.error(
                "[Newton/%s] Error discovering links from %s: %s",
                board_name, listing_url, exc,
            )
        await asyncio.sleep(1.5)

    # Step 2: Filter to minutes-only links
    raw_pairs = list(all_pairs.items())
    filtered_pairs = filter_minutes_links(raw_pairs)

    logger.info(
        "[Newton/%s] %d total links -> %d after minutes filter",
        board_name, len(raw_pairs), len(filtered_pairs),
    )

    if not filtered_pairs:
        logger.warning("[Newton/%s] No document links found", board_name)
        return []

    # Step 3: Limit to MAX_PER_BOARD (take the most recent-looking ones first)
    # Try to sort by date hint in URL or title (descending)
    def sort_key(pair: Tuple[str, str]) -> str:
        url, title = pair
        # Extract year from URL or title for rough sort
        year_m = re.search(r"(20\d{2})", title + url)
        return year_m.group(1) if year_m else "0000"

    filtered_pairs.sort(key=sort_key, reverse=True)
    filtered_pairs = filtered_pairs[:MAX_PER_BOARD]

    logger.info(
        "[Newton/%s] Fetching %d documents (max %d)",
        board_name, len(filtered_pairs), MAX_PER_BOARD,
    )

    # Step 4: Fetch each PDF via Firecrawl
    docs: List[Dict[str, Any]] = []
    seen_hashes: set = set()

    for idx, (pdf_url, title_hint) in enumerate(filtered_pairs):
        try:
            content = await fetch_pdf_via_firecrawl(fc, pdf_url, board_name)

            if not content or len(content) < 80:
                logger.warning(
                    "[Newton/%s] Skipping %s — insufficient content (%d chars)",
                    board_name, pdf_url, len(content) if content else 0,
                )
                # Small delay even on failure
                await asyncio.sleep(0.5)
                continue

            # Extract date from title, URL, then content
            meeting_date = (
                extract_date(title_hint)
                or extract_date(pdf_url)
                or extract_date(content[:2000])
            )

            # Filter to 2024-2026 range
            if meeting_date and not is_in_year_range(meeting_date):
                logger.debug(
                    "[Newton/%s] Skipping %s — date %s outside range",
                    board_name, pdf_url, meeting_date,
                )
                await asyncio.sleep(0.5)
                continue

            # Build title
            if title_hint and len(title_hint) > 5:
                title = title_hint
            else:
                doc_id_m = re.search(r"/showpublisheddocument/(\d+)", pdf_url)
                doc_id = doc_id_m.group(1) if doc_id_m else "?"
                title = f"{board_name} Minutes — doc{doc_id}"

            if meeting_date and meeting_date not in title:
                title = f"{board_name} Minutes — {meeting_date}"

            doc = make_doc(
                board_slug=board_slug,
                board_name=board_name,
                title=title,
                meeting_date=meeting_date,
                content=content,
                url=pdf_url,
            )

            # Deduplicate by content hash
            ch = doc["content_hash"]
            if ch in seen_hashes:
                logger.debug("[Newton/%s] Skipping duplicate content", board_name)
                await asyncio.sleep(0.5)
                continue
            seen_hashes.add(ch)

            docs.append(doc)
            logger.info(
                "[Newton/%s] [%d/%d] %s  date=%s  (%d chars)",
                board_name, idx + 1, len(filtered_pairs),
                title, meeting_date or "?", len(content),
            )

            # Polite delay between PDF fetches
            if idx < len(filtered_pairs) - 1:
                await asyncio.sleep(1.5)

        except Exception as exc:
            logger.error(
                "[Newton/%s] Error processing %s: %s", board_name, pdf_url, exc
            )
            await asyncio.sleep(1.0)

    logger.info("[Newton/%s] Total docs scraped: %d", board_name, len(docs))
    return docs


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    if not FIRECRAWL_API_KEY:
        logger.error("FIRECRAWL_API_KEY not set — cannot proceed")
        sys.exit(1)

    fc = FirecrawlClient(api_key=FIRECRAWL_API_KEY)
    logger.info("Firecrawl client ready")
    logger.info("Target: Newton MA, boards=%s, years=%d-%d, max=%d/board",
                list(NEWTON_BOARDS.keys()), MIN_YEAR, MAX_YEAR, MAX_PER_BOARD)

    all_docs: List[Dict[str, Any]] = []
    boards_data: Dict[str, List[Dict[str, Any]]] = {}
    board_counts: Dict[str, int] = {}

    try:
        for board_slug, board_cfg in NEWTON_BOARDS.items():
            try:
                board_docs = await scrape_newton_board(fc, board_slug, board_cfg)
                boards_data[board_slug] = board_docs
                board_counts[board_slug] = len(board_docs)
                all_docs.extend(board_docs)
                logger.info(
                    "[Newton] Board %s complete: %d docs", board_slug, len(board_docs)
                )
            except Exception as exc:
                logger.error("[Newton] Board %s failed: %s", board_slug, exc)
                import traceback; traceback.print_exc()
                boards_data[board_slug] = []
                board_counts[board_slug] = 0

    finally:
        await fc.close()

    # Build output structure
    output = {
        "town": "newton",
        "name": "Newton",
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "total_documents": len(all_docs),
        "year_range": f"{MIN_YEAR}-{MAX_YEAR}",
        "boards": {
            slug: [
                {
                    "title": d["title"],
                    "date": d["date"],
                    "url": d["url"],
                }
                for d in docs
            ]
            for slug, docs in boards_data.items()
        },
        "documents": [
            {
                "board": d["board"],
                "title": d["title"],
                "date": d["date"],
                "url": d["url"],
                "content": d["content"],
            }
            for d in all_docs
        ],
    }

    out_path = OUTPUT_DIR / "newton_minutes.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    logger.info("Saved %d docs to %s", len(all_docs), out_path)

    # Print summary
    print()
    print("=" * 60)
    print("  NEWTON MINUTES SCRAPE COMPLETE")
    print("=" * 60)
    for board_slug, count in board_counts.items():
        board_name = NEWTON_BOARDS[board_slug]["name"]
        status = "OK" if count > 0 else "EMPTY"
        print(f"  {board_name:35s}  {count:3d} docs  [{status}]")
    print(f"  {'TOTAL':35s}  {len(all_docs):3d} docs")
    print("=" * 60)
    print(f"  Output: {out_path}")
    print("=" * 60)
    print()

    return len(all_docs)


if __name__ == "__main__":
    asyncio.run(main())
