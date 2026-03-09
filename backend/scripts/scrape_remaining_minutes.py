#!/usr/bin/env python3
"""
Phase 4a: Re-scrape Meeting Minutes for Lexington, Wayland, and Newton.

Strategy per town:
  - Lexington: Laserfiche WebLink (records.lexingtonma.gov/WebLink)
               4 boards: Select Board (2920639), Planning Board (2920625),
               ZBA (2920512), Conservation Commission (2920521)

  - Wayland:   Drupal CMS with year sub-pages (wayland.ma.us/node/{id}/minutes/{year})
               Each meeting is a separate HTML page — scrape via Firecrawl.
               4 boards: Select Board (node/350), Planning Board (node/36),
               ZBA (node/230), Conservation Commission (node/240)

  - Newton:    Granicus/CivicPlus CMS (newtonma.gov) — JS-rendered, uses Firecrawl.
               - City Council: /government/city-clerk/city-council
               - Planning Board (P&D): /government/planning/boards-commissions/
                   planning-and-development-board/archived-meeting-documents/-folder-{year_folder}
               - ZBA: /government/planning/zoning-board-of-appeals/meeting-documents/-folder-{year_folder}
               - Conservation: /government/planning/conservation-office/meeting-info-documents
               Documents accessed via /home/showpublisheddocument/{id}/... URLs.

Output: backend/data_cache/meeting_minutes/{town_id}_minutes.json
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sys
import warnings
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")

# Ensure backend package is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scrape_remaining_minutes")

try:
    import httpx
except ImportError:
    httpx = None

try:
    import pdfplumber
    import io as _io
except ImportError:
    pdfplumber = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from urllib.parse import urljoin

from backend.config import FIRECRAWL_API_KEY, OPENROUTER_API_KEY

try:
    from backend.scrapers.connectors.firecrawl_client import FirecrawlClient
except ImportError:
    FirecrawlClient = None

from backend.scrapers.connectors.laserfiche_client import LaserficheClient
from backend.scrapers.connectors.llm_extractor import LLMExtractor

# ── Output directory ───────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "meeting_minutes"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Shared HTTP client ─────────────────────────────────────────────────────────

_http_client: Optional[Any] = None


async def get_http() -> Any:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=15.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MunicipalIntel/1.0)"},
            limits=httpx.Limits(max_connections=5),
            verify=False,
        )
    return _http_client


async def close_http():
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None


# ── PDF utilities ──────────────────────────────────────────────────────────────

def extract_pdf_text(pdf_bytes: bytes) -> str:
    if pdfplumber is None:
        logger.warning("pdfplumber not installed — cannot extract PDF text")
        return ""
    try:
        with pdfplumber.open(_io.BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            return "\n\n".join(pages)
    except Exception as exc:
        logger.warning("PDF extraction error: %s", exc)
        return ""


def extract_date(text: str) -> Optional[str]:
    """Extract first ISO-ish date from text/filename. Returns 'YYYY-MM-DD' string."""
    if not text:
        return None
    # YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except ValueError:
            pass
    # MM-DD-YY or MM/DD/YYYY
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", text)
    if m:
        y = int(m.group(3))
        if y < 100:
            y += 2000
        try:
            d = date(y, int(m.group(1)), int(m.group(2)))
            if 2000 <= d.year <= 2030:
                return d.isoformat()
        except ValueError:
            pass
    # Month DD, YYYY
    MONTHS = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    m = re.search(
        r"(january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})",
        text.lower(),
    )
    if m:
        try:
            d = date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
            return d.isoformat()
        except (ValueError, KeyError):
            pass
    return None


def make_doc(
    town_id: str, board_slug: str, board_name: str,
    title: str, meeting_date: Optional[str],
    content_text: str, source_url: str, file_url: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
) -> Dict[str, Any]:
    content_hash = hashlib.sha256(content_text.encode()).hexdigest()
    return {
        "town_id": town_id,
        "doc_type": "meeting_minutes",
        "board": board_slug,
        "title": title,
        "meeting_date": meeting_date,
        "source_url": source_url,
        "file_url": file_url,
        "content_text": content_text[:50000],
        "file_size_bytes": file_size_bytes,
        "content_hash": content_hash,
        "content_summary": None,
        "keywords": [],
        "mentions": [],
    }


# ── LLM extraction helper ──────────────────────────────────────────────────────

async def llm_enrich(
    llm: Optional[LLMExtractor],
    doc: Dict[str, Any],
    town_name: str,
    board_name: str,
) -> Dict[str, Any]:
    if not llm or not doc.get("content_text"):
        return doc
    try:
        extraction = await llm.extract_from_minutes(
            doc["content_text"][:20000], town_name, board_name,
        )
        doc["content_summary"] = extraction.get("summary")
        doc["keywords"] = extraction.get("keywords", [])
        doc["mentions"] = extraction.get("mentions", [])
    except Exception as exc:
        logger.warning("[LLM] Extraction failed for %s: %s", doc.get("title", "?"), exc)
    return doc


# ════════════════════════════════════════════════════════════════════════════════
# LEXINGTON — Laserfiche WebLink
# ════════════════════════════════════════════════════════════════════════════════

LEXINGTON_BOARDS = {
    "select_board": ("Select Board", 2920639),
    "planning_board": ("Planning Board", 2920625),
    "zba": ("Zoning Board of Appeals", 2920512),
    "conservation_commission": ("Conservation Commission", 2920521),
}

LEXINGTON_YEARS = [2024, 2025, 2026]


async def scrape_lexington(
    llm: Optional[LLMExtractor] = None,
) -> List[Dict[str, Any]]:
    logger.info("=" * 60)
    logger.info("LEXINGTON — Laserfiche WebLink")
    logger.info("=" * 60)

    all_docs: List[Dict[str, Any]] = []

    lc = LaserficheClient(
        base_url="https://records.lexingtonma.gov/WebLink",
        repo_name="TownOfLexington",
    )

    try:
        for board_slug, (board_name, root_folder_id) in LEXINGTON_BOARDS.items():
            logger.info("[Lexington] Scraping %s (folder=%d)...", board_name, root_folder_id)
            try:
                doc_metas = await lc.get_recent_documents(root_folder_id, LEXINGTON_YEARS)
                logger.info("[Lexington] %s: %d documents found", board_name, len(doc_metas))

                board_docs = 0
                for meta in doc_metas:
                    entry_id = meta.get("entryId")
                    file_name = meta.get("name", "")
                    if not entry_id:
                        continue

                    download_url = lc.get_download_url(entry_id)

                    # Download PDF
                    pdf_bytes = await lc.download_pdf(download_url)
                    if not pdf_bytes or len(pdf_bytes) < 200:
                        logger.debug("[Lexington] Skip empty PDF: %s", file_name)
                        continue

                    # Extract text
                    text = LaserficheClient.extract_pdf_text(pdf_bytes)
                    if not text or len(text) < 50:
                        logger.debug("[Lexington] No text from %s", file_name)
                        continue

                    meeting_date = extract_date(file_name) or extract_date(text[:500])
                    title = f"{board_name} Minutes — {file_name}".strip(" —")

                    doc = make_doc(
                        town_id="lexington",
                        board_slug=board_slug,
                        board_name=board_name,
                        title=title,
                        meeting_date=meeting_date,
                        content_text=text,
                        source_url=f"https://records.lexingtonma.gov/WebLink/Browse.aspx?dbid=0&startid={root_folder_id}",
                        file_url=download_url,
                        file_size_bytes=len(pdf_bytes),
                    )
                    doc = await llm_enrich(llm, doc, "Lexington", board_name)
                    all_docs.append(doc)
                    board_docs += 1
                    logger.info("[Lexington] %s  %s  (%d chars)", board_name, meeting_date or "?", len(text))

                logger.info("[Lexington] %s: %d docs processed", board_name, board_docs)

            except Exception as exc:
                logger.error("[Lexington] Error scraping %s: %s", board_name, exc)
                import traceback; traceback.print_exc()

    finally:
        await lc.close()

    logger.info("[Lexington] Total: %d documents", len(all_docs))
    return all_docs


# ════════════════════════════════════════════════════════════════════════════════
# WAYLAND — Drupal CMS with Firecrawl
# ════════════════════════════════════════════════════════════════════════════════

WAYLAND_BOARDS = {
    "select_board": ("Board of Selectmen", "350"),
    "planning_board": ("Planning Board", "36"),
    "zba": ("Zoning Board of Appeals", "230"),
    "conservation_commission": ("Conservation Commission", "240"),
}

WAYLAND_YEARS = [2024, 2025, 2026]
WAYLAND_BASE = "https://www.wayland.ma.us"


async def scrape_wayland_board(
    fc: FirecrawlClient,
    board_slug: str,
    board_name: str,
    node_id: str,
    llm: Optional[LLMExtractor] = None,
) -> List[Dict[str, Any]]:
    """Scrape one Wayland board: fetch year listing pages, then individual meeting pages."""
    docs: List[Dict[str, Any]] = []

    for year in WAYLAND_YEARS:
        year_url = f"{WAYLAND_BASE}/node/{node_id}/minutes/{year}"
        logger.info("[Wayland] %s  year=%d  %s", board_name, year, year_url)

        # Fetch the year listing page
        result = await fc.scrape(year_url, formats=["markdown", "links"], only_main_content=False, wait_for=3000)
        if not result:
            logger.warning("[Wayland] No Firecrawl result for %s", year_url)
            continue

        links = result.get("links", [])
        md = result.get("markdown", "")

        # Find individual meeting links on this year page
        # Pattern: /select-board/minutes/select-board-minutes-NNN
        #          /planning-board/minutes/planning-board-minutes-NNN  etc.
        meeting_links = []
        for lnk in links:
            # Match /some-board/minutes/some-slug-NNN
            if re.search(r"/minutes/[^/]+-\d+$", lnk):
                if lnk not in meeting_links:
                    meeting_links.append(lnk)

        # Also extract from markdown text (some may be relative)
        md_links = re.findall(r"\((/[^\)]+/minutes/[^/]+-\d+)\)", md)
        for ml in md_links:
            full = f"{WAYLAND_BASE}{ml}"
            if full not in meeting_links:
                meeting_links.append(full)

        logger.info("[Wayland] %s year=%d: %d meeting pages found", board_name, year, len(meeting_links))

        for meeting_url in meeting_links:
            try:
                meeting_result = await fc.scrape(
                    meeting_url,
                    formats=["markdown", "links"],
                    only_main_content=True,
                    wait_for=2000,
                )
                if not meeting_result:
                    continue

                meeting_md = meeting_result.get("markdown", "")
                if not meeting_md or len(meeting_md) < 100:
                    continue

                # Extract date from content
                meeting_date = extract_date(meeting_md[:1000])

                # Build title from URL slug
                slug = meeting_url.rstrip("/").split("/")[-1]
                title = f"{board_name} Minutes — {slug.replace('-', ' ').title()}"
                if meeting_date:
                    title = f"{board_name} Minutes — {meeting_date}"

                doc = make_doc(
                    town_id="wayland",
                    board_slug=board_slug,
                    board_name=board_name,
                    title=title,
                    meeting_date=meeting_date,
                    content_text=meeting_md,
                    source_url=year_url,
                    file_url=meeting_url,
                )
                doc = await llm_enrich(llm, doc, "Wayland", board_name)
                docs.append(doc)
                logger.info("[Wayland] %s  %s  (%d chars)", board_name, meeting_date or "?", len(meeting_md))

                # Small delay to be polite
                await asyncio.sleep(0.5)

            except Exception as exc:
                logger.warning("[Wayland] Error scraping %s: %s", meeting_url, exc)

    return docs


async def scrape_wayland(
    fc: FirecrawlClient,
    llm: Optional[LLMExtractor] = None,
) -> List[Dict[str, Any]]:
    logger.info("=" * 60)
    logger.info("WAYLAND — Drupal CMS via Firecrawl")
    logger.info("=" * 60)

    all_docs: List[Dict[str, Any]] = []

    for board_slug, (board_name, node_id) in WAYLAND_BOARDS.items():
        try:
            board_docs = await scrape_wayland_board(fc, board_slug, board_name, node_id, llm)
            all_docs.extend(board_docs)
            logger.info("[Wayland] %s: %d docs", board_name, len(board_docs))
        except Exception as exc:
            logger.error("[Wayland] Board %s failed: %s", board_name, exc)
            import traceback; traceback.print_exc()

    logger.info("[Wayland] Total: %d documents", len(all_docs))
    return all_docs


# ── Wayland httpx+BS4 fallback (no Firecrawl) ─────────────────────────────────


async def scrape_wayland_board_httpx(
    board_slug: str,
    board_name: str,
    node_id: str,
    llm: Optional[LLMExtractor] = None,
) -> List[Dict[str, Any]]:
    """Scrape one Wayland board using httpx + BeautifulSoup (no Firecrawl)."""
    docs: List[Dict[str, Any]] = []
    http = await get_http()

    for year in WAYLAND_YEARS:
        year_url = f"{WAYLAND_BASE}/node/{node_id}/minutes/{year}"
        logger.info("[Wayland/httpx] %s  year=%d  %s", board_name, year, year_url)

        try:
            resp = await http.get(year_url, timeout=30.0)
            if resp.status_code != 200:
                logger.warning("[Wayland/httpx] HTTP %d for %s", resp.status_code, year_url)
                continue

            html = resp.text

            # Parse meeting links from the year listing page
            meeting_links: List[str] = []

            if BeautifulSoup is not None:
                soup = BeautifulSoup(html, "html.parser")
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]
                    # Match /some-board/minutes/some-slug-NNN pattern
                    if re.search(r"/minutes/[^/]+-\d+$", href):
                        full_url = urljoin(year_url, href)
                        if full_url not in meeting_links:
                            meeting_links.append(full_url)
            else:
                # Regex fallback
                for match in re.finditer(r'href="([^"]*?/minutes/[^"]*?-\d+)"', html):
                    full_url = urljoin(year_url, match.group(1))
                    if full_url not in meeting_links:
                        meeting_links.append(full_url)

            logger.info("[Wayland/httpx] %s year=%d: %d meeting pages", board_name, year, len(meeting_links))

            for meeting_url in meeting_links:
                try:
                    meeting_resp = await http.get(meeting_url, timeout=30.0)
                    if meeting_resp.status_code != 200:
                        continue

                    meeting_html = meeting_resp.text
                    # Extract main content text
                    if BeautifulSoup is not None:
                        ms = BeautifulSoup(meeting_html, "html.parser")
                        # Drupal main content area
                        main = ms.find("div", class_="field-items") or ms.find("article") or ms.find("main") or ms
                        meeting_text = main.get_text(separator="\n", strip=True)
                    else:
                        meeting_text = re.sub(r"<[^>]+>", " ", meeting_html)
                        meeting_text = re.sub(r"\s+", " ", meeting_text).strip()

                    if not meeting_text or len(meeting_text) < 100:
                        continue

                    meeting_date = extract_date(meeting_text[:1000])
                    slug = meeting_url.rstrip("/").split("/")[-1]
                    title = f"{board_name} Minutes — {meeting_date}" if meeting_date else f"{board_name} Minutes — {slug.replace('-', ' ').title()}"

                    doc = make_doc(
                        town_id="wayland",
                        board_slug=board_slug,
                        board_name=board_name,
                        title=title,
                        meeting_date=meeting_date,
                        content_text=meeting_text,
                        source_url=year_url,
                        file_url=meeting_url,
                    )
                    doc = await llm_enrich(llm, doc, "Wayland", board_name)
                    docs.append(doc)
                    logger.info("[Wayland/httpx] %s  %s  (%d chars)", board_name, meeting_date or "?", len(meeting_text))

                    await asyncio.sleep(0.5)

                except Exception as exc:
                    logger.warning("[Wayland/httpx] Error scraping %s: %s", meeting_url, exc)

        except Exception as exc:
            logger.error("[Wayland/httpx] Error fetching year page %s: %s", year_url, exc)

    return docs


async def scrape_wayland_httpx(
    llm: Optional[LLMExtractor] = None,
) -> List[Dict[str, Any]]:
    """Scrape Wayland meeting minutes using httpx (no Firecrawl)."""
    logger.info("=" * 60)
    logger.info("WAYLAND — Drupal CMS via httpx (no Firecrawl)")
    logger.info("=" * 60)

    all_docs: List[Dict[str, Any]] = []

    for board_slug, (board_name, node_id) in WAYLAND_BOARDS.items():
        try:
            board_docs = await scrape_wayland_board_httpx(board_slug, board_name, node_id, llm)
            all_docs.extend(board_docs)
            logger.info("[Wayland/httpx] %s: %d docs", board_name, len(board_docs))
        except Exception as exc:
            logger.error("[Wayland/httpx] Board %s failed: %s", board_name, exc)
            import traceback; traceback.print_exc()

    logger.info("[Wayland/httpx] Total: %d documents", len(all_docs))
    return all_docs


# ════════════════════════════════════════════════════════════════════════════════
# NEWTON — Granicus/CivicPlus via Firecrawl
# ════════════════════════════════════════════════════════════════════════════════

NEWTON_BASE = "https://www.newtonma.gov"

# Newton folder IDs for archived documents (discovered via live inspection)
NEWTON_ARCHIVE_FOLDERS: Dict[str, Dict[str, Any]] = {
    "planning_board": {
        "name": "Planning & Development Board",
        "base_url": f"{NEWTON_BASE}/government/planning/boards-commissions/planning-and-development-board/archived-meeting-documents",
        "year_folder_ids": {
            # folder IDs from the -folder-NNN URL format
            2024: 3629,
            2025: None,  # will try year sub-path
        },
        "current_url": f"{NEWTON_BASE}/government/planning/boards-commissions/planning-and-development-board/current-year-agendas-minutes",
    },
    "zba": {
        "name": "Zoning Board of Appeals",
        "base_url": f"{NEWTON_BASE}/government/planning/zoning-board-of-appeals/meeting-documents",
        "year_folder_ids": {
            2024: 3628,
            2025: None,
        },
        "current_url": f"{NEWTON_BASE}/government/planning/zoning-board-of-appeals/meeting-documents",
    },
    "conservation_commission": {
        "name": "Conservation Commission",
        "base_url": f"{NEWTON_BASE}/government/planning/conservation-office/meeting-info-documents",
        "year_folder_ids": {},
        "current_url": f"{NEWTON_BASE}/government/planning/conservation-office/meeting-info-documents",
    },
    "city_council": {
        "name": "City Council",
        "base_url": f"{NEWTON_BASE}/government/city-clerk/city-council",
        "year_folder_ids": {},
        "current_url": f"{NEWTON_BASE}/government/city-clerk/city-council",
    },
}

NEWTON_YEARS = [2024, 2025, 2026]


async def scrape_newton_board_page(
    fc: FirecrawlClient,
    url: str,
    board_slug: str,
    board_name: str,
    llm: Optional[LLMExtractor] = None,
) -> List[Dict[str, Any]]:
    """Scrape one Newton board page — extract published document links, download PDFs."""
    docs: List[Dict[str, Any]] = []

    logger.info("[Newton] Scraping %s — %s", board_name, url)
    result = await fc.scrape(url, formats=["markdown", "links"], only_main_content=False, wait_for=5000)
    if not result:
        logger.warning("[Newton] No Firecrawl result for %s", url)
        return []

    links = result.get("links", [])
    md = result.get("markdown", "")

    # Collect showpublisheddocument links
    pub_doc_links: List[Tuple[str, str]] = []  # (url, title_hint)

    # From links list
    for lnk in links:
        if "showpublisheddocument" in lnk.lower() and lnk not in [l for l, _ in pub_doc_links]:
            pub_doc_links.append((lnk, ""))

    # From markdown — capture title hints too
    # Pattern: [title](https://...showpublisheddocument/...)
    md_matches = re.findall(
        r"\[([^\]]+)\]\((https://[^)]+showpublisheddocument[^)]+)\)",
        md, re.I,
    )
    for title_hint, lnk in md_matches:
        if lnk not in [l for l, _ in pub_doc_links]:
            pub_doc_links.append((lnk, title_hint))

    # Filter: only include minutes documents (skip pure agendas when we can tell)
    # Keep all if unsure (better to have more than less)
    minutes_docs = []
    for lnk, title_hint in pub_doc_links:
        # Skip obvious non-minutes (presentations, attachments)
        skip_words = ["presentation", "attachment", "exhibit", "recording", "recording"]
        if any(w in title_hint.lower() for w in skip_words):
            continue
        minutes_docs.append((lnk, title_hint))

    if not minutes_docs:
        # Fallback: use all pub docs
        minutes_docs = pub_doc_links

    logger.info("[Newton] %s: %d document links found", board_name, len(minutes_docs))

    http = await get_http()

    for doc_url, title_hint in minutes_docs:
        try:
            # Download document
            resp = await http.get(doc_url, timeout=30.0)
            if resp.status_code != 200:
                logger.debug("[Newton] HTTP %d for %s", resp.status_code, doc_url)
                continue

            content_type = resp.headers.get("content-type", "")
            raw_bytes = resp.content

            if len(raw_bytes) < 200:
                continue

            # Extract text
            if "pdf" in content_type.lower() or doc_url.lower().endswith(".pdf"):
                text = extract_pdf_text(raw_bytes)
            else:
                # HTML or unknown — convert to text
                text = re.sub(r"<[^>]+>", " ", raw_bytes.decode("utf-8", errors="replace"))
                text = re.sub(r"\s+", " ", text).strip()

            if not text or len(text) < 100:
                continue

            # Extract meeting date
            meeting_date = extract_date(title_hint) or extract_date(text[:1000])

            # Build title
            title = title_hint.strip() if title_hint else f"{board_name} Minutes"
            if not title or title == board_name:
                doc_id = re.search(r"/showpublisheddocument/(\d+)", doc_url)
                title = f"{board_name} Minutes — doc{doc_id.group(1) if doc_id else '?'}"

            doc = make_doc(
                town_id="newton",
                board_slug=board_slug,
                board_name=board_name,
                title=f"{board_name} Minutes — {title}".rstrip(" —"),
                meeting_date=meeting_date,
                content_text=text,
                source_url=url,
                file_url=doc_url,
                file_size_bytes=len(raw_bytes),
            )
            doc = await llm_enrich(llm, doc, "Newton", board_name)
            docs.append(doc)
            logger.info("[Newton] %s  %s  (%d chars)", board_name, meeting_date or "?", len(text))

        except Exception as exc:
            logger.warning("[Newton] Error downloading %s: %s", doc_url, exc)

    return docs


async def scrape_newton(
    fc: FirecrawlClient,
    llm: Optional[LLMExtractor] = None,
) -> List[Dict[str, Any]]:
    logger.info("=" * 60)
    logger.info("NEWTON — Granicus/CivicPlus via Firecrawl")
    logger.info("=" * 60)

    all_docs: List[Dict[str, Any]] = []

    for board_slug, cfg in NEWTON_ARCHIVE_FOLDERS.items():
        board_name = cfg["name"]
        urls_to_try: List[str] = []

        # Add current year URL
        if cfg.get("current_url"):
            urls_to_try.append(cfg["current_url"])

        # Add year-folder archived URLs
        for year, folder_id in cfg.get("year_folder_ids", {}).items():
            if folder_id:
                archived_url = f"{cfg['base_url']}/-folder-{folder_id}"
                urls_to_try.append(archived_url)
            else:
                # Try year sub-path
                archived_url = f"{cfg['base_url']}/{year}"
                urls_to_try.append(archived_url)

        # Deduplicate
        seen_urls = set()
        deduped_urls = []
        for u in urls_to_try:
            if u not in seen_urls:
                deduped_urls.append(u)
                seen_urls.add(u)

        board_docs: List[Dict[str, Any]] = []
        seen_hashes: set = set()

        for url in deduped_urls:
            try:
                page_docs = await scrape_newton_board_page(fc, url, board_slug, board_name, llm)
                for doc in page_docs:
                    ch = doc.get("content_hash", "")
                    if ch not in seen_hashes:
                        seen_hashes.add(ch)
                        board_docs.append(doc)
            except Exception as exc:
                logger.error("[Newton] %s — %s: %s", board_name, url, exc)

        all_docs.extend(board_docs)
        logger.info("[Newton] %s: %d unique docs", board_name, len(board_docs))

    logger.info("[Newton] Total: %d documents", len(all_docs))
    return all_docs


# ── Newton httpx+BS4 fallback (no Firecrawl) ──────────────────────────────────


async def scrape_newton_board_page_httpx(
    url: str,
    board_slug: str,
    board_name: str,
    llm: Optional[LLMExtractor] = None,
) -> List[Dict[str, Any]]:
    """Scrape one Newton board page using httpx + BS4 (no Firecrawl).

    Newton uses showpublisheddocument links for PDFs. The listing pages
    are server-rendered HTML (not JS-only), so httpx can extract them.
    """
    docs: List[Dict[str, Any]] = []
    http = await get_http()

    logger.info("[Newton/httpx] Scraping %s — %s", board_name, url)

    try:
        resp = await http.get(url, timeout=30.0)
        if resp.status_code != 200:
            logger.warning("[Newton/httpx] HTTP %d for %s", resp.status_code, url)
            return []

        html = resp.text

        # Collect showpublisheddocument links with title hints
        pub_doc_links: List[Tuple[str, str]] = []

        if BeautifulSoup is not None:
            soup = BeautifulSoup(html, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "showpublisheddocument" in href.lower():
                    full_url = urljoin(url, href)
                    title_hint = a_tag.get_text(strip=True) or ""
                    if full_url not in [l for l, _ in pub_doc_links]:
                        pub_doc_links.append((full_url, title_hint))
        else:
            # Regex fallback
            for match in re.finditer(
                r'<a[^>]+href="([^"]*showpublisheddocument[^"]*)"[^>]*>([^<]*)</a>',
                html, re.I,
            ):
                full_url = urljoin(url, match.group(1))
                title_hint = match.group(2).strip()
                if full_url not in [l for l, _ in pub_doc_links]:
                    pub_doc_links.append((full_url, title_hint))

        # Filter out obvious non-minutes
        minutes_docs = []
        for lnk, title_hint in pub_doc_links:
            skip_words = ["presentation", "attachment", "exhibit", "recording"]
            if any(w in title_hint.lower() for w in skip_words):
                continue
            minutes_docs.append((lnk, title_hint))

        if not minutes_docs:
            minutes_docs = pub_doc_links

        logger.info("[Newton/httpx] %s: %d document links found", board_name, len(minutes_docs))

        for doc_url, title_hint in minutes_docs:
            try:
                doc_resp = await http.get(doc_url, timeout=30.0)
                if doc_resp.status_code != 200:
                    logger.debug("[Newton/httpx] HTTP %d for %s", doc_resp.status_code, doc_url)
                    continue

                content_type = doc_resp.headers.get("content-type", "")
                raw_bytes = doc_resp.content

                if len(raw_bytes) < 200:
                    continue

                if "pdf" in content_type.lower() or doc_url.lower().endswith(".pdf"):
                    text = extract_pdf_text(raw_bytes)
                else:
                    text = re.sub(r"<[^>]+>", " ", raw_bytes.decode("utf-8", errors="replace"))
                    text = re.sub(r"\s+", " ", text).strip()

                if not text or len(text) < 100:
                    continue

                meeting_date = extract_date(title_hint) or extract_date(text[:1000])
                title = title_hint.strip() if title_hint else f"{board_name} Minutes"
                if not title or title == board_name:
                    doc_id = re.search(r"/showpublisheddocument/(\d+)", doc_url)
                    title = f"{board_name} Minutes — doc{doc_id.group(1) if doc_id else '?'}"

                doc = make_doc(
                    town_id="newton",
                    board_slug=board_slug,
                    board_name=board_name,
                    title=f"{board_name} Minutes — {title}".rstrip(" —"),
                    meeting_date=meeting_date,
                    content_text=text,
                    source_url=url,
                    file_url=doc_url,
                    file_size_bytes=len(raw_bytes),
                )
                doc = await llm_enrich(llm, doc, "Newton", board_name)
                docs.append(doc)
                logger.info("[Newton/httpx] %s  %s  (%d chars)", board_name, meeting_date or "?", len(text))

            except Exception as exc:
                logger.warning("[Newton/httpx] Error downloading %s: %s", doc_url, exc)

    except Exception as exc:
        logger.error("[Newton/httpx] Error fetching %s: %s", url, exc)

    return docs


async def scrape_newton_httpx(
    llm: Optional[LLMExtractor] = None,
) -> List[Dict[str, Any]]:
    """Scrape Newton meeting minutes using httpx (no Firecrawl)."""
    logger.info("=" * 60)
    logger.info("NEWTON — Granicus/CivicPlus via httpx (no Firecrawl)")
    logger.info("=" * 60)

    all_docs: List[Dict[str, Any]] = []

    for board_slug, cfg in NEWTON_ARCHIVE_FOLDERS.items():
        board_name = cfg["name"]
        urls_to_try: List[str] = []

        if cfg.get("current_url"):
            urls_to_try.append(cfg["current_url"])

        for year, folder_id in cfg.get("year_folder_ids", {}).items():
            if folder_id:
                urls_to_try.append(f"{cfg['base_url']}/-folder-{folder_id}")
            else:
                urls_to_try.append(f"{cfg['base_url']}/{year}")

        seen_urls = set()
        deduped_urls = [u for u in urls_to_try if u not in seen_urls and not seen_urls.add(u)]

        board_docs: List[Dict[str, Any]] = []
        seen_hashes: set = set()

        for url in deduped_urls:
            try:
                page_docs = await scrape_newton_board_page_httpx(url, board_slug, board_name, llm)
                for doc in page_docs:
                    ch = doc.get("content_hash", "")
                    if ch not in seen_hashes:
                        seen_hashes.add(ch)
                        board_docs.append(doc)
            except Exception as exc:
                logger.error("[Newton/httpx] %s — %s: %s", board_name, url, exc)

        all_docs.extend(board_docs)
        logger.info("[Newton/httpx] %s: %d unique docs", board_name, len(board_docs))

    logger.info("[Newton/httpx] Total: %d documents", len(all_docs))
    return all_docs


# ════════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════════

async def main():
    # Set up LLM (OpenRouter, Gemini Flash)
    llm: Optional[LLMExtractor] = None
    if OPENROUTER_API_KEY:
        try:
            llm = LLMExtractor(provider="openrouter", model="google/gemini-2.0-flash-001")
            logger.info("LLM extractor ready (OpenRouter / gemini-2.0-flash-001)")
        except Exception as exc:
            logger.warning("LLM not available: %s", exc)
    else:
        logger.warning("OPENROUTER_API_KEY not set — skipping LLM extraction")

    # Set up Firecrawl
    fc: Optional[FirecrawlClient] = None
    if FIRECRAWL_API_KEY:
        fc = FirecrawlClient(api_key=FIRECRAWL_API_KEY)
        logger.info("Firecrawl client ready")
    else:
        logger.info("FIRECRAWL_API_KEY not set — will use httpx fallback for Newton and Wayland")

    results: Dict[str, int] = {}

    try:
        # ── Lexington ──────────────────────────────────────────────────
        lex_out_path = OUTPUT_DIR / "lexington_minutes.json"
        if lex_out_path.exists() and lex_out_path.stat().st_size > 1000:
            logger.info("Skipping Lexington — output file already exists (%d bytes)", lex_out_path.stat().st_size)
            lex_docs = json.loads(lex_out_path.read_text())
            results["lexington"] = len(lex_docs)
        else:
            logger.info("")
            lex_docs = await scrape_lexington(llm)
            results["lexington"] = len(lex_docs)
            lex_out_path.write_text(json.dumps(lex_docs, indent=2, default=str))
            logger.info("Saved %d Lexington docs to %s", len(lex_docs), lex_out_path)

            # Also update the legacy scraped/minutes path
            legacy_path = Path(__file__).resolve().parent.parent / "data" / "scraped" / "minutes" / "lexington.json"
            if legacy_path.parent.exists():
                legacy_path.write_text(json.dumps(lex_docs, indent=2, default=str))
                logger.info("Also updated legacy path: %s", legacy_path)

        # ── Wayland ───────────────────────────────────────────────────
        way_out_path = OUTPUT_DIR / "wayland_minutes.json"
        if way_out_path.exists() and way_out_path.stat().st_size > 1000:
            logger.info("Skipping Wayland — output file already exists (%d bytes)", way_out_path.stat().st_size)
            way_docs = json.loads(way_out_path.read_text())
            results["wayland"] = len(way_docs)
        elif fc:
            logger.info("")
            way_docs = await scrape_wayland(fc, llm)
            results["wayland"] = len(way_docs)
            way_out_path.write_text(json.dumps(way_docs, indent=2, default=str))
            logger.info("Saved %d Wayland docs to %s", len(way_docs), way_out_path)

            legacy_path = Path(__file__).resolve().parent.parent / "data" / "scraped" / "minutes" / "wayland.json"
            if legacy_path.parent.exists():
                legacy_path.write_text(json.dumps(way_docs, indent=2, default=str))
        else:
            # httpx fallback — no Firecrawl needed
            logger.info("")
            logger.info("Using httpx fallback for Wayland (no Firecrawl)")
            way_docs = await scrape_wayland_httpx(llm)
            results["wayland"] = len(way_docs)
            way_out_path.write_text(json.dumps(way_docs, indent=2, default=str))
            logger.info("Saved %d Wayland docs to %s", len(way_docs), way_out_path)

        # ── Newton ────────────────────────────────────────────────────
        newt_out_path = OUTPUT_DIR / "newton_minutes.json"
        if newt_out_path.exists() and newt_out_path.stat().st_size > 1000:
            logger.info("Skipping Newton — output file already exists (%d bytes)", newt_out_path.stat().st_size)
            newt_docs = json.loads(newt_out_path.read_text())
            results["newton"] = len(newt_docs)
        elif fc:
            logger.info("")
            newt_docs = await scrape_newton(fc, llm)
            results["newton"] = len(newt_docs)
            newt_out_path.write_text(json.dumps(newt_docs, indent=2, default=str))
            logger.info("Saved %d Newton docs to %s", len(newt_docs), newt_out_path)

            legacy_path = Path(__file__).resolve().parent.parent / "data" / "scraped" / "minutes" / "newton.json"
            if legacy_path.parent.exists():
                legacy_path.write_text(json.dumps(newt_docs, indent=2, default=str))
        else:
            # httpx fallback — no Firecrawl needed
            logger.info("")
            logger.info("Using httpx fallback for Newton (no Firecrawl)")
            newt_docs = await scrape_newton_httpx(llm)
            results["newton"] = len(newt_docs)
            newt_out_path.write_text(json.dumps(newt_docs, indent=2, default=str))
            logger.info("Saved %d Newton docs to %s", len(newt_docs), newt_out_path)

    finally:
        if fc:
            await fc.close()
        await close_http()

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  PHASE 4a COMPLETE — Meeting Minutes Re-Scrape Results")
    print("=" * 60)
    for town, count in results.items():
        status = "OK" if count > 0 else "EMPTY"
        print(f"  {town:12s}  {count:4d} docs  [{status}]")
    print("=" * 60)
    print(f"  Output directory: {OUTPUT_DIR}")
    print("=" * 60)
    print()


if __name__ == "__main__":
    asyncio.run(main())
