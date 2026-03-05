#!/usr/bin/env python3
"""Migrate locally-scraped JSON files into Supabase.

Reads JSON files from data/scraped/{permits,transfers}/*.json and
upserts them into the corresponding Supabase tables, deduplicating
by permit_number+town_id (permits) or loc_id+sale_date (transfers).

Usage:
    python scripts/migrate_json_to_supabase.py                # all data
    python scripts/migrate_json_to_supabase.py --table permits # permits only
    python scripts/migrate_json_to_supabase.py --dry-run       # preview only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from database.supabase_client import SupabaseRestClient
from loguru import logger

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "scraped"


async def migrate_permits(supabase: SupabaseRestClient, dry_run: bool = False) -> int:
    """Migrate permit JSON files to Supabase permits table."""
    permits_dir = DATA_DIR / "permits"
    if not permits_dir.exists():
        logger.info("No permits directory found at %s", permits_dir)
        return 0

    total_inserted = 0
    for filepath in sorted(permits_dir.glob("*.json")):
        town_id = filepath.stem
        with open(filepath) as f:
            records = json.load(f)

        logger.info("Processing %s: %d records", filepath.name, len(records))
        inserted = 0

        for record in records:
            permit_number = record.get("permit_number", "")
            if not permit_number:
                continue

            # Check if already exists
            existing = await supabase.fetch(
                table="permits",
                select="id",
                filters={
                    "permit_number": f"eq.{permit_number}",
                    "town_id": f"eq.{town_id}",
                },
                limit=1,
            )
            if existing:
                continue

            if dry_run:
                inserted += 1
                continue

            try:
                await supabase.insert("permits", record)
                inserted += 1
            except Exception as exc:
                logger.warning("Insert error for %s/%s: %s", town_id, permit_number, exc)

        total_inserted += inserted
        action = "would insert" if dry_run else "inserted"
        logger.info("  %s %d new permits for %s", action, inserted, town_id)

    return total_inserted


async def migrate_transfers(supabase: SupabaseRestClient, dry_run: bool = False) -> int:
    """Migrate transfer JSON files to Supabase property_transfers table."""
    transfers_dir = DATA_DIR / "transfers"
    if not transfers_dir.exists():
        logger.info("No transfers directory found at %s", transfers_dir)
        return 0

    total_inserted = 0
    for filepath in sorted(transfers_dir.glob("*.json")):
        town_id = filepath.stem
        with open(filepath) as f:
            records = json.load(f)

        logger.info("Processing %s: %d records", filepath.name, len(records))
        inserted = 0

        for record in records:
            loc_id = record.get("loc_id", "")
            sale_date = record.get("sale_date")
            if not loc_id or not sale_date:
                continue

            existing = await supabase.fetch(
                table="property_transfers",
                select="id",
                filters={
                    "loc_id": f"eq.{loc_id}",
                    "sale_date": f"eq.{sale_date}",
                },
                limit=1,
            )
            if existing:
                continue

            if dry_run:
                inserted += 1
                continue

            try:
                await supabase.insert("property_transfers", record)
                inserted += 1
            except Exception as exc:
                logger.warning("Insert error for %s/%s: %s", town_id, loc_id, exc)

        total_inserted += inserted
        action = "would insert" if dry_run else "inserted"
        logger.info("  %s %d new transfers for %s", action, inserted, town_id)

    return total_inserted


async def main(args: argparse.Namespace):
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        return

    supabase = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    connected = await supabase.connect()
    if not connected:
        logger.error("Supabase connection failed")
        return

    logger.info("Connected to Supabase: %s", supabase.base_url)
    if args.dry_run:
        logger.info("DRY RUN — no data will be written")

    total = 0
    if args.table in (None, "permits"):
        total += await migrate_permits(supabase, dry_run=args.dry_run)
    if args.table in (None, "transfers"):
        total += await migrate_transfers(supabase, dry_run=args.dry_run)

    action = "would migrate" if args.dry_run else "migrated"
    logger.info("Done — %s %d total records", action, total)
    await supabase.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate scraped JSON to Supabase")
    parser.add_argument("--table", choices=["permits", "transfers"], help="Only migrate a specific table")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    asyncio.run(main(args))
