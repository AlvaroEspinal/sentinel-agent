#!/usr/bin/env python3
"""Run all pending/incomplete town scrapers in parallel.

Saves results to local JSON files (data/scraped/) when Supabase is
unavailable, so data can be committed to GitHub and migrated later.

Usage:
    python scripts/run_pending_scrapers.py                    # all pending jobs
    python scripts/run_pending_scrapers.py --type permits     # permits only
    python scripts/run_pending_scrapers.py --concurrency 6    # 6 parallel
    python scripts/run_pending_scrapers.py --check-only       # just show status
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, FIRECRAWL_API_KEY
from database.supabase_client import SupabaseRestClient
from scrapers.scheduler import ScrapeScheduler
from scrapers.connectors.firecrawl_client import FirecrawlClient
from scrapers.connectors.llm_extractor import LLMExtractor
from loguru import logger

# Local JSON output directory (relative to backend/)
LOCAL_DATA_DIR = str(Path(__file__).resolve().parent.parent / "data" / "scraped")


async def main(args: argparse.Namespace):
    # ── Init clients ──
    supabase = None
    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        supabase = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
        connected = await supabase.connect()
        if not connected:
            logger.error("Supabase connection failed")
            return
        logger.info("Supabase connected: %s", supabase.base_url)
    else:
        logger.warning("No Supabase credentials — saving to local JSON files")

    firecrawl = None
    if FIRECRAWL_API_KEY:
        firecrawl = FirecrawlClient(api_key=FIRECRAWL_API_KEY)
        logger.info("Firecrawl client ready")

    llm = None
    try:
        llm = LLMExtractor()
        logger.info("LLM extractor ready")
    except Exception as exc:
        logger.warning("LLM extractor not available: %s", exc)

    # Always enable local storage so data is saved to JSON files
    scheduler = ScrapeScheduler(
        supabase=supabase,
        firecrawl=firecrawl,
        llm_extractor=llm,
        local_storage_dir=LOCAL_DATA_DIR,
    )

    # ── Check status ──
    logger.info("Checking scrape status for all 12 towns...")
    status = await scheduler.get_scrape_status()

    summary = status["summary"]
    print(f"\n{'='*60}")
    print(f"  SCRAPE STATUS: {summary['completed']} completed, "
          f"{summary['running']} running, {summary['pending']} pending "
          f"(of {summary['total']} total)")
    print(f"{'='*60}")

    if status["completed"]:
        print(f"\n  COMPLETED ({len(status['completed'])}):")
        for j in status["completed"]:
            print(f"    done {j['town_name']:12s} / {j['source_type']:22s}  (at {j.get('completed_at', '?')})")

    if status["running"]:
        print(f"\n  RUNNING ({len(status['running'])}):")
        for j in status["running"]:
            print(f"    ...  {j['town_name']:12s} / {j['source_type']:22s}  (since {j.get('started_at', '?')})")

    if status["pending"]:
        print(f"\n  PENDING ({len(status['pending'])}):")
        for j in status["pending"]:
            print(f"    todo {j['town_name']:12s} / {j['source_type']:22s}  [{j['portal_type']:16s}]  reason: {j['reason']}")

    print()

    if args.check_only:
        if supabase:
            await supabase.disconnect()
        return

    if not status["pending"]:
        logger.info("Nothing pending — all scrapers are up to date!")
        if supabase:
            await supabase.disconnect()
        return

    # ── Run pending in parallel ──
    source_types = [args.type] if args.type else None
    concurrency = args.concurrency

    pending_count = len(status["pending"])
    if source_types:
        pending_count = sum(1 for j in status["pending"] if j["source_type"] in source_types)

    logger.info(
        "Launching %d pending scrapers in parallel (max_concurrency=%d)...",
        pending_count, concurrency,
    )

    result = await scheduler.run_pending_parallel(
        max_concurrency=concurrency,
        source_types=source_types,
    )

    # ── Flush buffered data to JSON files ──
    written = scheduler.flush_to_files()

    print(f"\n{'='*60}")
    print(f"  RESULTS: {result['summary']['succeeded']} succeeded, "
          f"{result['summary']['failed']} failed "
          f"(of {result['summary']['dispatched']} dispatched)")
    print(f"{'='*60}")

    for r in result["results"]:
        town = r.get("town_id") or r.get("town", "?")
        stype = r.get("source_type", "?")
        if "error" in r:
            print(f"    X {town:12s} / {stype:22s}  ERROR: {r['error']}")
        else:
            found = r.get("found", 0)
            new = r.get("new", 0)
            print(f"    ok {town:12s} / {stype:22s}  found={found}, new={new}")

    if written:
        print(f"\n  FILES WRITTEN:")
        total_records = 0
        for filepath, count in written.items():
            print(f"    {filepath} ({count} records)")
            total_records += count
        print(f"\n  Total: {total_records} records saved to {LOCAL_DATA_DIR}/")
    print()

    if supabase:
        await supabase.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run pending town scrapers in parallel")
    parser.add_argument("--type", choices=["permits", "meeting_minutes", "property_transfers"],
                        help="Only run a specific source type")
    parser.add_argument("--concurrency", type=int, default=4, help="Max parallel scrapers (default: 4)")
    parser.add_argument("--check-only", action="store_true", help="Just show status, don't run")
    args = parser.parse_args()
    asyncio.run(main(args))
