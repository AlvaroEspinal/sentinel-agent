#!/usr/bin/env python3
"""Batch-ingest scraped permit JSON files directly into Supabase.

Reads pre-formatted JSON files from data/scraped/permits/ and upserts them
into the `permits` table in batches of 500 using PostgREST batch upsert.

Requires: UNIQUE constraint on (town_id, permit_number) in permits table.

Usage:
    python scripts/ingest_permits_to_supabase.py                # all towns
    python scripts/ingest_permits_to_supabase.py --town newton   # single town
    python scripts/ingest_permits_to_supabase.py --dry-run       # preview only
    python scripts/ingest_permits_to_supabase.py --concurrency 4 # parallel towns
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from database.supabase_client import SupabaseRestClient

DATA_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "permits"

# Fields that the permits table accepts
VALID_FIELDS = {
    "id", "town_id", "permit_number", "permit_type", "permit_status",
    "status", "address", "latitude", "longitude", "description",
    "estimated_value", "permit_value", "applicant_name", "contractor_name",
    "filed_date", "issued_date", "completed_date", "source_system",
    "source_id", "raw_data", "created_at", "updated_at", "property_id",
}


def normalize_record(raw: dict, town_id: str) -> dict:
    """Map scraped permit fields to the permits table schema."""
    # Field mapping: scraped_name -> db_name
    r = {}
    r["town_id"] = raw.get("town_id") or town_id
    r["permit_number"] = (
        raw.get("permit_number")
        or raw.get("record_number")
        or raw.get("source_id")
        or ""
    )
    r["permit_type"] = raw.get("permit_type") or raw.get("record_type") or raw.get("app_type") or ""
    r["permit_status"] = raw.get("permit_status") or raw.get("status") or ""
    r["address"] = raw.get("address") or ""
    r["description"] = raw.get("description") or ""
    r["applicant_name"] = raw.get("applicant_name") or raw.get("applicant") or ""
    r["contractor_name"] = raw.get("contractor_name") or raw.get("contractor") or ""
    ev = raw.get("estimated_value") or raw.get("permit_value")
    if isinstance(ev, (int, float)):
        r["estimated_value"] = ev
    elif isinstance(ev, str):
        # Strip $ and commas, convert to float
        cleaned_val = ev.replace("$", "").replace(",", "").strip()
        try:
            r["estimated_value"] = float(cleaned_val) if cleaned_val else None
        except ValueError:
            r["estimated_value"] = None
    else:
        r["estimated_value"] = None
    r["source_system"] = raw.get("source_system") or raw.get("source") or ""

    # Date mapping — parse MM/DD/YYYY to YYYY-MM-DD
    r["filed_date"] = _parse_date(raw.get("filed_date") or raw.get("app_date") or raw.get("date_created"))
    r["issued_date"] = _parse_date(raw.get("issued_date") or raw.get("issue_date"))
    r["completed_date"] = _parse_date(raw.get("completed_date"))

    return r


def _parse_date(val: str | None) -> str | None:
    """Normalize date strings to YYYY-MM-DD. Returns None for empty/invalid."""
    if not val or not isinstance(val, str) or not val.strip():
        return None
    val = val.strip()
    # Already ISO format
    if len(val) >= 10 and val[4] == "-":
        return val[:10]
    # MM/DD/YYYY
    if "/" in val:
        parts = val.split("/")
        if len(parts) == 3:
            try:
                m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
                return f"{y:04d}-{m:02d}-{d:02d}"
            except ValueError:
                return None
    return None


def clean_record(record: dict) -> dict:
    """Strip fields not in the permits table schema."""
    cleaned = {k: v for k, v in record.items() if k in VALID_FIELDS}
    # Remove id — let Supabase generate it; avoids PK conflict during upsert
    cleaned.pop("id", None)
    # Ensure required fields
    if not cleaned.get("town_id") or not cleaned.get("permit_number"):
        return {}
    # Sanitize dates — empty strings to None
    for date_field in ("filed_date", "issued_date", "completed_date"):
        val = cleaned.get(date_field)
        if val is not None and (not isinstance(val, str) or not val.strip()):
            cleaned[date_field] = None
    # Clamp description
    if cleaned.get("description"):
        cleaned["description"] = cleaned["description"][:500]
    return cleaned


async def ingest_town(
    supabase: SupabaseRestClient,
    filepath: Path,
    dry_run: bool = False,
    batch_size: int = 500,
) -> dict:
    """Ingest a single town's permit JSON file into Supabase."""
    town_id = filepath.stem.replace("_permits", "")
    with open(filepath) as f:
        data = json.load(f)

    # Handle wrapper dict format (town, permits[]) or flat list
    if isinstance(data, dict):
        records = data.get("permits", data.get("results", []))
    elif isinstance(data, list):
        records = data
    else:
        return {"town": town_id, "total": 0, "ingested": 0, "errors": 0}

    # Normalize field names
    records = [normalize_record(r, town_id) for r in records]

    total = len(records)
    if total == 0:
        return {"town": town_id, "total": 0, "ingested": 0, "errors": 0}

    # Clean, validate, and deduplicate by (town_id, permit_number)
    seen = set()
    cleaned = []
    for r in records:
        c = clean_record(r)
        if not c:
            continue
        key = (c["town_id"], c["permit_number"])
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(c)

    if dry_run:
        print(f"  [DRY RUN] {town_id:25s} {len(cleaned):>8,} records (of {total:,} raw)")
        return {"town": town_id, "total": total, "ingested": len(cleaned), "errors": 0}

    ingested = 0
    errors = 0

    for i in range(0, len(cleaned), batch_size):
        batch = cleaned[i:i + batch_size]
        try:
            await supabase.insert("permits", batch, upsert=True, minimal=True, on_conflict="town_id,permit_number")
            ingested += len(batch)
        except Exception as exc:
            error_msg = str(exc)
            # If batch fails, try smaller chunks
            for j in range(0, len(batch), 50):
                mini_batch = batch[j:j + 50]
                try:
                    await supabase.insert("permits", mini_batch, upsert=True, minimal=True, on_conflict="town_id,permit_number")
                    ingested += len(mini_batch)
                except Exception as inner_exc:
                    errors += len(mini_batch)
                    if errors <= 5:
                        print(f"  [ERROR] {town_id}: batch at offset {i+j}: {str(inner_exc)[:200]}")

    print(f"  {town_id:25s} {ingested:>8,} ingested, {errors:>5,} errors (of {total:,} total)")
    return {"town": town_id, "total": total, "ingested": ingested, "errors": errors}


async def main(args: argparse.Namespace):
    if not DATA_DIR.exists():
        print(f"Data directory not found: {DATA_DIR}")
        return

    # Find JSON files
    files = sorted(DATA_DIR.glob("*.json"))
    if args.town:
        files = [f for f in files if f.stem == args.town]
    if not files:
        print("No JSON files found")
        return

    print(f"\nFound {len(files)} town files in {DATA_DIR}")

    # Connect to Supabase
    if not args.dry_run:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
            return
        supabase = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
        if not await supabase.connect():
            print("ERROR: Supabase connection failed")
            return
        print(f"Connected to Supabase: {supabase.base_url}\n")
    else:
        supabase = None
        print("[DRY RUN MODE]\n")

    start = time.time()
    semaphore = asyncio.Semaphore(args.concurrency)

    async def _run(filepath: Path):
        async with semaphore:
            return await ingest_town(supabase, filepath, dry_run=args.dry_run)

    tasks = [_run(f) for f in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.time() - start

    # Summary
    total_ingested = 0
    total_errors = 0
    total_records = 0
    for r in results:
        if isinstance(r, dict):
            total_records += r["total"]
            total_ingested += r["ingested"]
            total_errors += r["errors"]
        else:
            print(f"  [EXCEPTION] {r}")

    print(f"\n{'='*60}")
    print(f"  DONE in {elapsed:.1f}s")
    print(f"  Towns:    {len(files)}")
    print(f"  Records:  {total_records:,}")
    print(f"  Ingested: {total_ingested:,}")
    print(f"  Errors:   {total_errors:,}")
    print(f"{'='*60}\n")

    if supabase:
        await supabase.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch ingest permit JSON files into Supabase")
    parser.add_argument("--town", help="Only ingest a specific town")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--concurrency", type=int, default=4, help="Max parallel town ingestions (default: 4)")
    args = parser.parse_args()
    asyncio.run(main(args))
