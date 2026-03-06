#!/usr/bin/env python3
"""Run new extractors (Zoning, MEPA) across all target towns.

This script iterates through the configured target towns and runs:
1. Zoning Bylaw Scraper (Table of Uses extraction)
2. MEPA Scraper (Environmental filings)
Results are saved to `backend/data_cache/` as JSON files.

Usage:
    python scripts/run_extractors.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Path setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TARGET_TOWN_IDS
from scrapers.connectors.town_config import get_town
from scrapers.connectors.zoning_bylaw_scraper import ZoningBylawScraper
from scrapers.connectors.mepa_scraper import MEPAScraper

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"

async def _run_zoning(town_id: str, scraper: ZoningBylawScraper) -> None:
    town = get_town(town_id)
    if not town or not town.zoning_bylaw_url:
        logger.warning(f"Zoning: Skipping {town_id} (no ecode url configured)")
        return
        
    url = town.zoning_bylaw_url
    if "ecode360.com" not in url:
        logger.info(f"Zoning: Skipping {town_id} (url {url} not ecode360 compatible)")
        return

    logger.info(f"Zoning: Extracting Table of Uses for {town.name}...")
    try:
        data = await scraper.extract_table_of_uses(town.name, url)
        if data:
            outfile = DATA_CACHE_DIR / f"{town_id}_zoning_uses.json"
            outfile.write_text(json.dumps(data, indent=2))
            logger.info(f"Zoning: Saved {outfile.name}")
        else:
            logger.warning(f"Zoning: No data extracted for {town.name}")
    except Exception as e:
        logger.error(f"Zoning: Error for {town.name}: {e}")

async def _run_mepa(town_id: str, scraper: MEPAScraper) -> None:
    town = get_town(town_id)
    if not town:
        return
        
    logger.info(f"MEPA: Extracting filings for {town.name}...")
    try:
        result = await scraper.search_projects(municipality=town.name, page_size=20)
        
        filings = result
        if filings:
            outfile = DATA_CACHE_DIR / f"{town_id}_mepa_filings.json"
            outfile.write_text(json.dumps(result, indent=2))
            logger.info(f"MEPA: Saved {len(filings)} filings to {outfile.name}")
        else:
            logger.info(f"MEPA: No filings found for {town.name}")
    except Exception as e:
        logger.error(f"MEPA: Error for {town.name}: {e}")


async def main() -> None:
    DATA_CACHE_DIR.mkdir(exist_ok=True)
    
    logger.info("Initializing scrapers...")
    zoning_scraper = ZoningBylawScraper()
    mepa_scraper = MEPAScraper()
    
    logger.info(f"Running extractors across {len(TARGET_TOWN_IDS)} towns...")
    
    for town_id in TARGET_TOWN_IDS:
        logger.info(f"\n--- Processing {town_id.upper()} ---")
        
        # 1. Zoning
        await _run_zoning(town_id, zoning_scraper)
        
        # 2. MEPA
        # MEPA Scraper uses sync HTTP requests under the hood mostly, but wait just in case
        await _run_mepa(town_id, mepa_scraper)
        
        # Rate limiting delay
        await asyncio.sleep(2)
        
    logger.info("\n=== All towns processed ===")

if __name__ == "__main__":
    asyncio.run(main())
