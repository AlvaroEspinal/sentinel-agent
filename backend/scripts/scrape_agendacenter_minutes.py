#!/usr/bin/env python3
"""
Scrape meeting minutes from AgendaCenter towns and ingest to Supabase.

Uses the AgendaCenterClient to scrape meeting minutes for towns that use
CivicPlus AgendaCenter (wellesley, weston, sherborn, etc.).

Downloads minutes PDFs, extracts text, and stores in data_cache + Supabase.

Usage:
    python scripts/scrape_agendacenter_minutes.py                # all 3 missing towns
    python scripts/scrape_agendacenter_minutes.py --town wellesley
    python scripts/scrape_agendacenter_minutes.py --no-pdf       # skip PDF download
    python scripts/scrape_agendacenter_minutes.py --ingest-only  # just ingest cached files
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

from scrapers.connectors.agendacenter_client import AgendaCenterClient
from scrapers.connectors.town_config import TARGET_TOWNS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

MINUTES_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "meeting_minutes"
MINUTES_DIR.mkdir(parents=True, exist_ok=True)

# Towns to scrape — all use AgendaCenter
AGENDACENTER_TOWNS = ["wellesley", "weston", "sherborn"]

# Years to scrape
SCRAPE_YEARS = [2023, 2024, 2025, 2026]

# Max PDFs to download per board (to avoid hitting rate limits)
MAX_PDFS_PER_BOARD = 10


async def scrape_town(
    client: AgendaCenterClient,
    town_id: str,
    download_pdfs: bool = True,
) -> dict:
    """Scrape all board meeting minutes for a single AgendaCenter town."""
    cfg = TARGET_TOWNS.get(town_id)
    if not cfg:
        logger.error(f"Town {town_id} not found in TARGET_TOWNS")
        return {"error": f"Town {town_id} not configured"}

    base_url_match = re.match(r'(https?://[^/]+)', cfg.meeting_minutes_url or "")
    if not base_url_match:
        logger.error(f"No meeting_minutes_url for {town_id}")
        return {"error": "No meeting_minutes_url configured"}
    base_url = base_url_match.group(1)

    all_documents = []
    boards_found = []

    for board in cfg.boards:
        if not board.minutes_url:
            continue

        cat_id = AgendaCenterClient.extract_cat_id(board.minutes_url)
        if not cat_id:
            logger.warning(f"  Could not extract cat_id from {board.minutes_url}")
            continue

        logger.info(f"  Scraping {board.name} (cat_id={cat_id})...")
        meetings = await client.list_meetings(base_url, cat_id, years=SCRAPE_YEARS)

        if not meetings:
            logger.info(f"    No meetings found for {board.name}")
            continue

        boards_found.append(board.name)
        logger.info(f"    Found {len(meetings)} meetings with minutes")

        # Download PDFs for recent meetings
        pdf_count = 0
        for meeting in meetings:
            content_text = ""
            if download_pdfs and meeting.get("minutes_url") and pdf_count < MAX_PDFS_PER_BOARD:
                try:
                    pdf_bytes = await client.download_pdf(meeting["minutes_url"])
                    if pdf_bytes:
                        content_text = AgendaCenterClient.extract_pdf_text(pdf_bytes)
                        if content_text:
                            pdf_count += 1
                            # Truncate to avoid massive JSON files
                            content_text = content_text[:3000]
                except Exception as e:
                    logger.warning(f"    PDF download error: {e}")

                # Small delay to be polite
                await asyncio.sleep(0.5)

            meeting_date = meeting.get("meeting_date")
            date_str = meeting_date.isoformat() if meeting_date else ""

            doc = {
                "board": board.name,
                "title": meeting.get("title", "Meeting Minutes"),
                "meeting_date": date_str,
                "file_url": meeting.get("minutes_url", ""),
                "agenda_url": meeting.get("agenda_url", ""),
                "content_text": content_text,
                "source_url": board.minutes_url,
            }
            all_documents.append(doc)

        logger.info(f"    Downloaded {pdf_count} PDFs for {board.name}")

    # Build output
    result = {
        "town": cfg.name,
        "town_id": town_id,
        "total_documents": len(all_documents),
        "boards": boards_found,
        "documents": all_documents,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source_url": cfg.meeting_minutes_url,
        "year_range": f"{SCRAPE_YEARS[0]}-{SCRAPE_YEARS[-1]}",
    }

    # Save to cache
    outpath = MINUTES_DIR / f"{town_id}_minutes.json"
    outpath.write_text(json.dumps(result, indent=2, default=str))
    logger.info(f"  Saved {len(all_documents)} docs to {outpath.name}")

    return result


async def ingest_to_supabase(town_ids: list[str] | None = None):
    """Ingest cached meeting minutes JSONs to Supabase."""
    from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
    from database.supabase_client import SupabaseRestClient
    from scripts.ingest_meeting_minutes import ingest_minutes

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Supabase credentials missing")
        return

    db = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    if not await db.connect():
        logger.error("Could not connect to Supabase")
        return

    await ingest_minutes(db)
    await db.disconnect()


async def main():
    parser = argparse.ArgumentParser(description="Scrape AgendaCenter meeting minutes")
    parser.add_argument("--town", help="Only scrape a specific town")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF downloads")
    parser.add_argument("--ingest-only", action="store_true", help="Only ingest cached files")
    args = parser.parse_args()

    if args.ingest_only:
        logger.info("=== Ingest-only mode ===")
        await ingest_to_supabase()
        return

    towns = [args.town] if args.town else AGENDACENTER_TOWNS

    # Skip towns that already have cached data
    towns_to_scrape = []
    for t in towns:
        cache_file = MINUTES_DIR / f"{t}_minutes.json"
        if cache_file.exists() and cache_file.stat().st_size > 1000:
            logger.info(f"Skipping {t} — cache exists ({cache_file.stat().st_size:,} bytes)")
        else:
            towns_to_scrape.append(t)

    if not towns_to_scrape:
        logger.info("All towns already cached. Use --ingest-only to push to Supabase.")
        await ingest_to_supabase()
        return

    logger.info(f"=== Scraping {len(towns_to_scrape)} towns: {towns_to_scrape} ===")

    client = AgendaCenterClient(timeout=30.0)

    for town_id in towns_to_scrape:
        logger.info(f"\n--- {town_id.upper()} ---")
        result = await scrape_town(client, town_id, download_pdfs=not args.no_pdf)
        if result.get("error"):
            logger.error(f"  FAILED: {result['error']}")
        else:
            logger.info(f"  SUCCESS: {result['total_documents']} documents, {len(result['boards'])} boards")

    await client.close()

    # Ingest all cached files to Supabase
    logger.info("\n=== Ingesting to Supabase ===")
    await ingest_to_supabase()


if __name__ == "__main__":
    asyncio.run(main())
