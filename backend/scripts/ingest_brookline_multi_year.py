#!/usr/bin/env python3
"""Ingest multi-year Brookline Accela permit data into Supabase.

Reads all brookline_permits_YYYY.json files from data_cache/permits/
and upserts them into the permits table.

Usage:
    python scripts/ingest_brookline_multi_year.py
    python scripts/ingest_brookline_multi_year.py --dry-run
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

import httpx
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

DATA_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "permits"
BATCH_SIZE = 200


def parse_date(val: str | None) -> str | None:
    """Parse date string to ISO format."""
    if not val or val.strip() in ("", "N/A", "None"):
        return None
    val = val.strip()
    # Try MM/DD/YYYY
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            from datetime import datetime
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_permit(raw: dict) -> dict:
    """Map Accela scraped record to permits table schema."""
    return {
        "town_id": "brookline",
        "permit_number": raw.get("record_number", ""),
        "permit_type": raw.get("record_type", ""),
        "permit_status": raw.get("status", ""),
        "address": raw.get("address", ""),
        "filed_date": parse_date(raw.get("date_created")),
        "source_system": "accela_brookline",
        "source_id": raw.get("record_number", ""),
    }


async def upsert_batch(client: httpx.AsyncClient, batch: list[dict]) -> int:
    """Upsert a batch of permits. Returns count inserted/updated."""
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    url = f"{SUPABASE_URL}/rest/v1/permits"
    resp = await client.post(url, headers=headers, json=batch, timeout=30.0)
    if resp.status_code in (200, 201):
        return len(batch)
    else:
        print(f"  Upsert error: {resp.status_code} {resp.text[:200]}")
        return 0


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Find all Brookline JSON files
    files = sorted(DATA_DIR.glob("brookline_permits*.json"))
    if not files:
        print("No Brookline permit files found in", DATA_DIR)
        return

    print(f"Found {len(files)} Brookline permit file(s)")

    all_permits = {}
    for f in files:
        data = json.loads(f.read_text())
        permits = data.get("permits", [])
        year = data.get("year", f.stem.split("_")[-1])
        for p in permits:
            key = p.get("record_number", "")
            if key and key not in all_permits:
                all_permits[key] = p
        print(f"  {f.name}: {len(permits)} permits (year={year})")

    print(f"\nTotal unique permits: {len(all_permits)}")

    # Normalize
    normalized = [normalize_permit(p) for p in all_permits.values()]
    # Filter out empty permit numbers
    normalized = [p for p in normalized if p["permit_number"]]
    print(f"Valid permits to upsert: {len(normalized)}")

    if args.dry_run:
        print("[DRY RUN] Would upsert", len(normalized), "permits")
        return

    # Upsert in batches
    total_upserted = 0
    async with httpx.AsyncClient() as client:
        for i in range(0, len(normalized), BATCH_SIZE):
            batch = normalized[i:i + BATCH_SIZE]
            count = await upsert_batch(client, batch)
            total_upserted += count
            print(f"  Batch {i // BATCH_SIZE + 1}: {count}/{len(batch)} upserted")

    print(f"\nDone! Total upserted: {total_upserted}")


if __name__ == "__main__":
    asyncio.run(main())
