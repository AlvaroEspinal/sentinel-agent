#!/usr/bin/env python3
"""Scrape permits from PermitEyes towns (Lincoln, Concord) and ingest to Supabase.

Uses the PermitEyes DataTables API to paginate through all permits.

Usage:
    python scripts/scrape_permiteyes_permits.py                # all towns
    python scripts/scrape_permiteyes_permits.py --town lincoln  # single town
    python scripts/scrape_permiteyes_permits.py --ingest-only   # just ingest cached files
    python scripts/scrape_permiteyes_permits.py --dry-run       # preview without Supabase
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

import httpx
from scrapers.connectors.permiteyes_client import (
    PERMITEYES_TOWNS,
    scrape_all_permits,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PERMITS_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "permits"
PERMITS_DIR.mkdir(parents=True, exist_ok=True)

# Only scrape our MVP towns
MVP_TOWNS = ["lincoln", "concord"]


async def scrape_town(town_id: str) -> dict:
    """Scrape all permits for a PermitEyes town."""
    config = PERMITEYES_TOWNS.get(town_id)
    if not config:
        return {"town": town_id, "error": f"No PermitEyes config for {town_id}"}

    logger.info(f"  Scraping {town_id} from {config.base_url}...")
    async with httpx.AsyncClient() as client:
        permits = await scrape_all_permits(config=config, client=client)

    logger.info(f"  Got {len(permits)} permits for {town_id}")

    # Add town_id to each record
    for p in permits:
        p["town_id"] = town_id
        p["source_system"] = "permiteyes"
        # Map fields for ingest compatibility
        p["permit_type"] = p.get("app_type", "")
        p["permit_status"] = p.get("status", "")
        p["permit_number"] = p.get("permit_number") or p.get("app_number", "")
        p["applicant_name"] = p.get("applicant", "")
        p["filed_date"] = p.get("app_date", "")
        p["issued_date"] = p.get("issue_date", "")

    result = {
        "town": town_id,
        "total": len(permits),
        "source": "permiteyes",
        "permits": permits,
    }

    outpath = PERMITS_DIR / f"{town_id}_permits.json"
    outpath.write_text(json.dumps(result, indent=2, default=str))
    logger.info(f"  Saved to {outpath.name}")

    return result


async def ingest_cached():
    """Ingest cached permit JSON files to Supabase."""
    from scripts.ingest_permits_to_supabase import ingest_town as ingest_permit_town
    from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
    from database.supabase_client import SupabaseRestClient

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Supabase credentials missing")
        return

    db = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    if not await db.connect():
        logger.error("Could not connect to Supabase")
        return

    for town_id in MVP_TOWNS:
        fpath = PERMITS_DIR / f"{town_id}_permits.json"
        if not fpath.exists():
            logger.warning(f"  No cache file for {town_id}")
            continue
        result = await ingest_permit_town(db, fpath)
        logger.info(f"  {town_id}: {result}")

    await db.disconnect()


async def main():
    parser = argparse.ArgumentParser(description="Scrape PermitEyes permits")
    parser.add_argument("--town", help="Only scrape a specific town")
    parser.add_argument("--ingest-only", action="store_true", help="Only ingest cached files")
    parser.add_argument("--dry-run", action="store_true", help="Scrape but don't ingest")
    args = parser.parse_args()

    if args.ingest_only:
        logger.info("=== Ingest-only mode ===")
        await ingest_cached()
        return

    towns = [args.town] if args.town else MVP_TOWNS

    logger.info(f"=== Scraping PermitEyes permits for {towns} ===")
    start = time.time()

    for town_id in towns:
        cache_file = PERMITS_DIR / f"{town_id}_permits.json"
        if cache_file.exists() and cache_file.stat().st_size > 1000:
            logger.info(f"Skipping {town_id} — cache exists ({cache_file.stat().st_size:,} bytes)")
            continue

        result = await scrape_town(town_id)
        if result.get("error"):
            logger.error(f"  FAILED: {result['error']}")
        else:
            logger.info(f"  SUCCESS: {result['total']} permits")

    elapsed = time.time() - start
    logger.info(f"Scraping done in {elapsed:.1f}s")

    if not args.dry_run:
        logger.info("\n=== Ingesting to Supabase ===")
        await ingest_cached()


if __name__ == "__main__":
    asyncio.run(main())
