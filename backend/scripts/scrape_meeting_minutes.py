#!/usr/bin/env python3
"""Scrape meeting minutes for a single town and ingest into Supabase.

Supports four scraping modes:
  - AgendaCenter direct (most towns) — free, no API keys
  - ArchiveCenter (Needham) — free, no API keys
  - CivicClerk OData API (Brookline) — free, no API keys
  - Firecrawl (Newton, Wayland) — requires FIRECRAWL_API_KEY

Usage:
    python scripts/scrape_meeting_minutes.py --town wellesley
    python scripts/scrape_meeting_minutes.py --town newton --boards planning_board,zba
    python scripts/scrape_meeting_minutes.py --town dover --years 2024,2025,2026
    python scripts/scrape_meeting_minutes.py --town brookline --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, FIRECRAWL_API_KEY, ANTHROPIC_API_KEY
from database.supabase_client import SupabaseRestClient
from scrapers.connectors.agendacenter_client import AgendaCenterClient
from scrapers.connectors.town_config import TARGET_TOWNS, TownConfig, BoardConfig
from scrapers.connectors.llm_extractor import LLMExtractor

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "scraped" / "minutes"

# Towns that do NOT use AgendaCenter (need Firecrawl)
FIRECRAWL_TOWNS = {"newton", "wayland"}

# Towns that use CivicPlus ArchiveCenter (board_slug → AMID mapping)
ARCHIVECENTER_TOWNS = {
    "needham": {
        "base_url": "https://www.needhamma.gov",
        "boards": {
            "select_board": 31,
            "planning_board": 33,
            "conservation_commission": 39,
            "zba": 65,
        },
    },
}

# Towns that use CivicClerk OData API (tenant → category mapping)
CIVICCLERK_TOWNS = {
    "brookline": {
        "tenant": "BrooklineMA",
        "boards": {
            "select_board": "Select Board",
            "planning_board": "Planning Board",
            "zba": "Zoning Board of Appeals",
            "conservation_commission": "Conservation Commission",
        },
    },
}

# Towns that use Laserfiche WebLink (repo_name -> board minutes folder mapping)
LASERFICHE_TOWNS = {
    "lexington": {
        "base_url": "https://records.lexingtonma.gov/WebLink",
        "repo_name": "TownOfLexington",
        "boards": {
            "select_board": 2920639,
            "planning_board": 2920625,
            "zba": 2920512,
            "conservation_commission": 2920521,
        },
    },
}

# The 12 MVP towns
MVP_TOWNS = [
    "newton", "wellesley", "weston", "brookline", "needham", "dover",
    "sherborn", "natick", "wayland", "lincoln", "concord", "lexington",
]


async def scrape_board_agendacenter(
    ac_client: AgendaCenterClient,
    llm: Optional[LLMExtractor],
    town: TownConfig,
    board: BoardConfig,
    years: List[int],
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Scrape a single board via AgendaCenter direct HTTP."""
    if not board.minutes_url:
        logger.info("  [%s/%s] No minutes URL — skipping", town.id, board.slug)
        return []

    # Extract base URL and cat_id from the minutes_url
    cat_id = AgendaCenterClient.extract_cat_id(board.minutes_url)
    base_url = AgendaCenterClient.extract_base_url(board.minutes_url)

    if cat_id is None:
        logger.warning("  [%s/%s] Cannot extract cat_id from %s", town.id, board.slug, board.minutes_url)
        return []

    # List all meetings
    meetings = await ac_client.list_meetings(base_url, cat_id, years=years)
    logger.info("  [%s/%s] Found %d meetings with minutes PDFs", town.id, board.slug, len(meetings))

    if dry_run:
        for m in meetings[:5]:
            logger.info("    %s — %s", m.get("meeting_date", "?"), m.get("title", "?"))
        if len(meetings) > 5:
            logger.info("    ... and %d more", len(meetings) - 5)
        return []

    documents = []
    for meeting in meetings:
        minutes_url = meeting.get("minutes_url")
        if not minutes_url:
            continue

        # Download PDF
        pdf_bytes = await ac_client.download_pdf(minutes_url)
        if not pdf_bytes:
            continue

        # Extract text
        text = AgendaCenterClient.extract_pdf_text(pdf_bytes)
        if not text or len(text) < 100:
            continue

        content_hash = hashlib.sha256(text.encode()).hexdigest()
        meeting_date = meeting.get("meeting_date")

        doc: Dict[str, Any] = {
            "town_id": town.id,
            "doc_type": "meeting_minutes",
            "board": board.slug,
            "title": f"{board.name} Minutes — {meeting.get('title', '')}".strip(" —"),
            "meeting_date": meeting_date.isoformat() if meeting_date else None,
            "source_url": board.minutes_url,
            "file_url": minutes_url,
            "content_text": text[:50000],
            "page_count": None,
            "file_size_bytes": len(pdf_bytes),
            "content_hash": content_hash,
            "content_summary": None,
            "keywords": [],
            "mentions": [],
        }

        # LLM extraction
        if llm and text:
            try:
                extraction = await llm.extract_from_minutes(
                    text[:20000], town.name, board.name,
                )
                doc["content_summary"] = extraction.get("summary")
                doc["keywords"] = extraction.get("keywords", [])
                doc["mentions"] = extraction.get("mentions", [])
            except Exception as exc:
                logger.warning("  [%s/%s] LLM extraction failed: %s", town.id, board.slug, exc)

        documents.append(doc)

    return documents


async def scrape_board_archivecenter(
    town: TownConfig,
    board: BoardConfig,
    llm: Optional[LLMExtractor],
    amid: int,
    base_url: str,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Scrape a single board via ArchiveCenter (for Needham)."""
    from scrapers.connectors.archivecenter_client import ArchiveCenterClient

    ac = ArchiveCenterClient()
    try:
        meetings = await ac.list_meetings(base_url, amid)
        logger.info("  [%s/%s] ArchiveCenter found %d entries", town.id, board.slug, len(meetings))

        if dry_run:
            for m in meetings[:5]:
                logger.info("    %s — %s", m.get("meeting_date", "?"), m.get("title", "?"))
            return []

        documents = []
        for meeting in meetings:
            minutes_url = meeting.get("minutes_url")
            if not minutes_url:
                continue

            pdf_bytes = await ac.download_pdf(minutes_url)
            if not pdf_bytes:
                continue

            text = ArchiveCenterClient.extract_pdf_text(pdf_bytes)
            if not text or len(text) < 100:
                continue

            content_hash = hashlib.sha256(text.encode()).hexdigest()
            meeting_date = meeting.get("meeting_date")

            doc: Dict[str, Any] = {
                "town_id": town.id,
                "doc_type": "meeting_minutes",
                "board": board.slug,
                "title": f"{board.name} Minutes — {meeting.get('title', '')}".strip(" —"),
                "meeting_date": meeting_date.isoformat() if meeting_date else None,
                "source_url": f"{base_url}/Archive.aspx?AMID={amid}",
                "file_url": minutes_url,
                "content_text": text[:50000],
                "page_count": None,
                "file_size_bytes": len(pdf_bytes),
                "content_hash": content_hash,
                "content_summary": None,
                "keywords": [],
                "mentions": [],
            }

            if llm and text:
                try:
                    extraction = await llm.extract_from_minutes(
                        text[:20000], town.name, board.name,
                    )
                    doc["content_summary"] = extraction.get("summary")
                    doc["keywords"] = extraction.get("keywords", [])
                    doc["mentions"] = extraction.get("mentions", [])
                except Exception as exc:
                    logger.warning("  [%s/%s] LLM extraction failed: %s", town.id, board.slug, exc)

            documents.append(doc)

        return documents
    finally:
        await ac.close()


async def scrape_board_civicclerk(
    town: TownConfig,
    board: BoardConfig,
    llm: Optional[LLMExtractor],
    tenant: str,
    category_name: str,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Scrape a single board via CivicClerk OData API (for Brookline)."""
    from scrapers.connectors.civicclerk_client import CivicClerkClient

    cc = CivicClerkClient(tenant=tenant)
    try:
        # First get categories to find the right category ID
        categories = await cc.list_categories()
        category_id = cc.find_category_id(categories, category_name)

        if category_id is None:
            logger.warning("  [%s/%s] CivicClerk category '%s' not found in %d categories",
                          town.id, board.slug, category_name, len(categories))
            return []

        events = await cc.list_events(category_id=category_id, top=200, min_year=2024)
        meetings = cc.extract_meetings_from_events(events, board.name)
        logger.info("  [%s/%s] CivicClerk found %d meetings with minutes", town.id, board.slug, len(meetings))

        if dry_run:
            for m in meetings[:5]:
                logger.info("    %s — %s", m.get("meeting_date", "?"), m.get("title", "?"))
            return []

        documents = []
        for meeting in meetings:
            minutes_url = meeting.get("minutes_url")
            if not minutes_url:
                continue

            pdf_bytes = await cc.download_pdf(minutes_url)
            if not pdf_bytes:
                continue

            text = CivicClerkClient.extract_pdf_text(pdf_bytes)
            if not text or len(text) < 100:
                continue

            content_hash = hashlib.sha256(text.encode()).hexdigest()
            meeting_date = meeting.get("meeting_date")

            doc: Dict[str, Any] = {
                "town_id": town.id,
                "doc_type": "meeting_minutes",
                "board": board.slug,
                "title": f"{board.name} Minutes — {meeting.get('title', '')}".strip(" —"),
                "meeting_date": meeting_date.isoformat() if meeting_date else None,
                "source_url": f"https://{tenant.lower()}.portal.civicclerk.com",
                "file_url": minutes_url,
                "content_text": text[:50000],
                "page_count": None,
                "file_size_bytes": len(pdf_bytes),
                "content_hash": content_hash,
                "content_summary": None,
                "keywords": [],
                "mentions": [],
            }

            if llm and text:
                try:
                    extraction = await llm.extract_from_minutes(
                        text[:20000], town.name, board.name,
                    )
                    doc["content_summary"] = extraction.get("summary")
                    doc["keywords"] = extraction.get("keywords", [])
                    doc["mentions"] = extraction.get("mentions", [])
                except Exception as exc:
                    logger.warning("  [%s/%s] LLM extraction failed: %s", town.id, board.slug, exc)

            documents.append(doc)

        return documents
    finally:
        await cc.close()


async def scrape_board_laserfiche(
    town: TownConfig,
    board: BoardConfig,
    llm: Optional[LLMExtractor],
    base_url: str,
    repo_name: str,
    folder_id: int,
    years: List[int],
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Scrape a single board via Laserfiche WebLink (for Lexington)."""
    from scrapers.connectors.laserfiche_client import LaserficheClient
    import re

    lc = LaserficheClient(base_url=base_url, repo_name=repo_name)
    try:
        documents_metadata = await lc.get_recent_documents(folder_id, target_years=years)
        logger.info("  [%s/%s] Laserfiche found %d documents for years %s", town.id, board.slug, len(documents_metadata), years)

        if dry_run:
            for d in documents_metadata[:5]:
                logger.info("    %s", d.get("name", "?"))
            return []

        documents = []
        for doc_meta in documents_metadata:
            entry_id = doc_meta.get("entryId")
            file_name = doc_meta.get("name", "")
            if not entry_id:
                continue

            download_url = lc.get_download_url(entry_id)
            pdf_bytes = await lc.download_pdf(download_url)
            if not pdf_bytes:
                continue

            text = LaserficheClient.extract_pdf_text(pdf_bytes)
            if not text or len(text) < 100:
                continue

            content_hash = hashlib.sha256(text.encode()).hexdigest()
            
            # Try to extract date from filename (e.g., "2024-05-13 SB-min")
            meeting_date = None
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", file_name)
            if date_match:
                meeting_date = date_match.group(1)

            doc: Dict[str, Any] = {
                "town_id": town.id,
                "doc_type": "meeting_minutes",
                "board": board.slug,
                "title": f"{board.name} Minutes — {file_name}".strip(" —"),
                "meeting_date": meeting_date,
                "source_url": f"{base_url}/Browse.aspx?dbid=0&startid={folder_id}",
                "file_url": download_url,
                "content_text": text[:50000],
                "page_count": None,
                "file_size_bytes": len(pdf_bytes),
                "content_hash": content_hash,
                "content_summary": None,
                "keywords": [],
                "mentions": [],
            }

            if llm and text:
                try:
                    extraction = await llm.extract_from_minutes(
                        text[:20000], town.name, board.name,
                    )
                    doc["content_summary"] = extraction.get("summary")
                    doc["keywords"] = extraction.get("keywords", [])
                    doc["mentions"] = extraction.get("mentions", [])
                except Exception as exc:
                    logger.warning("  [%s/%s] LLM extraction failed: %s", town.id, board.slug, exc)

            documents.append(doc)

        return documents
    finally:
        await lc.close()


async def scrape_board_firecrawl(
    town: TownConfig,
    board: BoardConfig,
    llm: Optional[LLMExtractor],
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Scrape a single board via Firecrawl (for Newton/Wayland)."""
    if not board.minutes_url:
        return []

    if not FIRECRAWL_API_KEY:
        logger.warning("  [%s/%s] FIRECRAWL_API_KEY not set — skipping", town.id, board.slug)
        return []

    from scrapers.connectors.firecrawl_client import FirecrawlClient
    from scrapers.connectors.meeting_minutes import MeetingMinutesScraper

    firecrawl = FirecrawlClient(api_key=FIRECRAWL_API_KEY)
    scraper = MeetingMinutesScraper(firecrawl=firecrawl, llm_extractor=llm, max_pages_per_board=20)

    if dry_run:
        logger.info("  [%s/%s] Would scrape via Firecrawl: %s", town.id, board.slug, board.minutes_url)
        return []

    try:
        documents = await scraper._scrape_board(town, board)
        logger.info("  [%s/%s] Firecrawl found %d documents", town.id, board.slug, len(documents))
        return documents
    except Exception as exc:
        logger.error("  [%s/%s] Firecrawl error: %s", town.id, board.slug, exc)
        return []
    finally:
        await scraper.close()


async def scrape_town(
    town_id: str,
    boards_filter: Optional[List[str]] = None,
    years: Optional[List[int]] = None,
    dry_run: bool = False,
    skip_llm: bool = False,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Scrape all boards for a single town."""
    if years is None:
        years = [2024, 2025, 2026]

    town = TARGET_TOWNS.get(town_id)
    if not town:
        return {"town": town_id, "error": f"Town '{town_id}' not found in TARGET_TOWNS"}

    logger.info("=" * 60)
    logger.info("Scraping meeting minutes: %s (%d boards)", town.name, len(town.boards))
    logger.info("=" * 60)

    # Initialize LLM
    llm = None
    if not skip_llm:
        # Check if we have credentials for the chosen provider
        from config import OPENROUTER_API_KEY, LLM_PROVIDER
        provider = llm_provider or LLM_PROVIDER or "anthropic"
        has_key = (provider == "openrouter" and OPENROUTER_API_KEY) or \
                  (provider == "anthropic" and ANTHROPIC_API_KEY)

        if has_key:
            try:
                llm = LLMExtractor(provider=provider, model=llm_model)
                logger.info("LLM extractor ready (provider=%s, model=%s)", llm.provider, llm.model)
            except Exception as exc:
                logger.warning("LLM not available: %s", exc)
        else:
            logger.warning("No API key for provider '%s' — skipping LLM extraction", provider)
    else:
        logger.info("LLM extraction skipped (--skip-llm)")

    # Determine CMS type
    cms_type = "agendacenter"  # default
    if town_id in FIRECRAWL_TOWNS:
        cms_type = "firecrawl"
    elif town_id in ARCHIVECENTER_TOWNS:
        cms_type = "archivecenter"
    elif town_id in CIVICCLERK_TOWNS:
        cms_type = "civicclerk"
    elif town_id in LASERFICHE_TOWNS:
        cms_type = "laserfiche"

    logger.info("CMS type: %s", cms_type)

    ac_client = None
    if cms_type == "agendacenter":
        ac_client = AgendaCenterClient()

    all_documents: List[Dict[str, Any]] = []

    for board in town.boards:
        if boards_filter and board.slug not in boards_filter:
            continue

        if cms_type == "firecrawl":
            docs = await scrape_board_firecrawl(town, board, llm, dry_run)
        elif cms_type == "archivecenter":
            ac_config = ARCHIVECENTER_TOWNS[town_id]
            amid = ac_config["boards"].get(board.slug)
            if amid is None:
                logger.info("  [%s/%s] No ArchiveCenter AMID configured — skipping", town.id, board.slug)
                docs = []
            else:
                docs = await scrape_board_archivecenter(
                    town, board, llm, amid, ac_config["base_url"], dry_run,
                )
        elif cms_type == "civicclerk":
            cc_config = CIVICCLERK_TOWNS[town_id]
            category_name = cc_config["boards"].get(board.slug)
            if category_name is None:
                logger.info("  [%s/%s] No CivicClerk category configured — skipping", town.id, board.slug)
                docs = []
            else:
                docs = await scrape_board_civicclerk(
                    town, board, llm, cc_config["tenant"], category_name, dry_run,
                )
        elif cms_type == "laserfiche":
            lf_config = LASERFICHE_TOWNS[town_id]
            folder_id = lf_config["boards"].get(board.slug)
            if folder_id is None:
                logger.info("  [%s/%s] No Laserfiche folder configured — skipping", town.id, board.slug)
                docs = []
            else:
                docs = await scrape_board_laserfiche(
                    town, board, llm, lf_config["base_url"], lf_config["repo_name"], folder_id, years, dry_run,
                )
        else:
            docs = await scrape_board_agendacenter(ac_client, llm, town, board, years, dry_run)

        all_documents.extend(docs)
        logger.info("  [%s/%s] %d documents collected", town.id, board.slug, len(docs))

    if ac_client:
        await ac_client.close()

    if dry_run:
        logger.info("[DRY RUN] %s: would process %d documents total", town.name, len(all_documents))
        return {"town": town_id, "found": len(all_documents), "new": 0, "errors": 0}

    # ── Save to local JSON ──
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / f"{town_id}.json"
    with open(json_path, "w") as f:
        json.dump(all_documents, f, indent=2, default=str)
    logger.info("Saved %d documents to %s", len(all_documents), json_path)

    # ── Upsert to Supabase ──
    new_count = 0
    errors = 0

    if SUPABASE_URL and SUPABASE_SERVICE_KEY and all_documents:
        supabase = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
        if await supabase.connect():
            logger.info("Connected to Supabase: %s", supabase.base_url)

            for doc in all_documents:
                try:
                    # Check if document already exists by content_hash
                    existing = await supabase.fetch(
                        "municipal_documents",
                        select="id",
                        filters={"content_hash": f"eq.{doc['content_hash']}"},
                        limit=1,
                    )
                    if existing:
                        continue

                    await supabase.insert("municipal_documents", doc, minimal=True)
                    new_count += 1
                except Exception as exc:
                    errors += 1
                    if errors <= 5:
                        logger.warning("  Insert error: %s", str(exc)[:150])

            await supabase.disconnect()
            logger.info("Supabase: %d new, %d errors (of %d total)", new_count, errors, len(all_documents))
        else:
            logger.error("Supabase connection failed — data saved to JSON only")

    logger.info("")
    logger.info("RESULT: %s — %d documents found, %d new to Supabase, %d errors",
                town.name, len(all_documents), new_count, errors)
    return {"town": town_id, "found": len(all_documents), "new": new_count, "errors": errors}


async def main(args: argparse.Namespace):
    years = [int(y) for y in args.years.split(",")] if args.years else None
    boards = args.boards.split(",") if args.boards else None

    start = time.time()
    result = await scrape_town(
        town_id=args.town,
        boards_filter=boards,
        years=years,
        dry_run=args.dry_run,
        skip_llm=args.skip_llm,
        llm_provider=args.provider,
        llm_model=args.model,
    )
    elapsed = time.time() - start

    print(f"\n{'='*60}")
    print(f"  {result['town']:12s}  found={result.get('found', 0)}  "
          f"new={result.get('new', 0)}  errors={result.get('errors', 0)}  "
          f"time={elapsed:.1f}s")
    if "error" in result:
        print(f"  ERROR: {result['error']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape meeting minutes for a single town")
    parser.add_argument("--town", required=True, help="Town ID (e.g. wellesley, newton)")
    parser.add_argument("--boards", help="Comma-separated board slugs (e.g. planning_board,zba)")
    parser.add_argument("--years", help="Comma-separated years (default: 2024,2025,2026)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without downloading/storing")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM extraction (faster, no API cost)")
    parser.add_argument("--provider", choices=["anthropic", "openrouter"], default=None,
                        help="LLM provider (default: from LLM_PROVIDER env var)")
    parser.add_argument("--model", default=None,
                        help="Model name (e.g. google/gemini-2.0-flash-001, deepseek/deepseek-chat-v3-0324)")
    args = parser.parse_args()
    asyncio.run(main(args))
