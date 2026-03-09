#!/usr/bin/env python3
"""Scrape permits from ViewpointCloud (OpenGov) towns via REST API.

Uses the public VPC API to enumerate record types, then paginate through
all permit/license records for each town.

Usage:
    python scripts/scrape_viewpointcloud_permits.py                # all 8 MVP towns
    python scripts/scrape_viewpointcloud_permits.py --town newton  # single town
    python scripts/scrape_viewpointcloud_permits.py --ingest-only  # just ingest cached
    python scripts/scrape_viewpointcloud_permits.py --dry-run      # scrape but don't ingest
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
from scrapers.connectors.town_config import TARGET_TOWNS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PERMITS_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "permits"
PERMITS_DIR.mkdir(parents=True, exist_ok=True)

API_BASE = "https://api-east.viewpointcloud.com/v2"
PAGE_SIZE = 50

# MVP towns that use ViewpointCloud
VPC_MVP_TOWNS = [
    "newton", "wellesley", "brookline", "needham",
    "dover", "natick", "wayland", "lexington",
]

# Keywords in record type names that indicate permits/licenses
PERMIT_KEYWORDS = {
    "permit", "license", "certificate", "inspection",
    "application", "approval", "review", "filing",
    "complaint", "violation", "enforcement",
}


def is_permit_type(name: str) -> bool:
    """Check if a record type name indicates a permit/license."""
    lower = name.lower()
    return any(kw in lower for kw in PERMIT_KEYWORDS)


async def fetch_record_types(
    client: httpx.AsyncClient, slug: str
) -> list[dict]:
    """Fetch all record types for a VPC community."""
    url = f"{API_BASE}/{slug}/record_types"
    resp = await client.get(url, timeout=30.0)
    if resp.status_code != 200:
        logger.error(f"  record_types failed for {slug}: {resp.status_code}")
        return []
    data = resp.json()
    if isinstance(data, dict):
        return data.get("data", [])
    return []


async def fetch_records_page(
    client: httpx.AsyncClient,
    slug: str,
    record_type_id: str,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> dict:
    """Fetch a page of records for a specific record type."""
    url = f"{API_BASE}/{slug}/records"
    params = {
        "recordTypeID": record_type_id,
        "page[size]": str(page_size),
        "page[number]": str(page),
    }
    resp = await client.get(url, params=params, timeout=30.0)
    if resp.status_code != 200:
        return {"data": [], "meta": {"total": 0}}
    payload = resp.json()
    return payload if isinstance(payload, dict) else {"data": [], "meta": {"total": 0}}


async def fetch_all_records_for_type(
    client: httpx.AsyncClient,
    slug: str,
    record_type_id: str,
    record_type_name: str,
    max_records: int = 5000,
) -> list[dict]:
    """Paginate through all records for a given record type."""
    all_records = []
    page = 1

    while len(all_records) < max_records:
        payload = await fetch_records_page(client, slug, record_type_id, page)
        data = payload.get("data", [])
        meta = payload.get("meta", {})
        total = meta.get("total", 0)

        if not data:
            break

        for item in data:
            if not isinstance(item, dict):
                continue
            attrs = item.get("attributes", {})
            if not isinstance(attrs, dict):
                continue

            record = {
                "record_id": str(item.get("id", "")),
                "permit_number": attrs.get("recordNo", ""),
                "permit_type": attrs.get("recordTypeName", record_type_name),
                "permit_status": attrs.get("status", ""),
                "address": attrs.get("fullAddress", ""),
                "description": (attrs.get("description") or "")[:500],
                "applicant_name": attrs.get("applicantFullName", ""),
                "filed_date": attrs.get("dateCreated", ""),
                "issued_date": attrs.get("dateSubmitted", ""),
                "completed_date": attrs.get("expirationDate", ""),
                "latitude": attrs.get("latitude"),
                "longitude": attrs.get("longitude"),
                "estimated_value": attrs.get("value"),
                "street_no": attrs.get("streetNo", ""),
                "street_name": attrs.get("streetName", ""),
                "city": attrs.get("city", ""),
                "state": attrs.get("state", ""),
                "postal_code": attrs.get("postalCode", ""),
                "zoning": attrs.get("zoning", ""),
                "mbl": attrs.get("mbl", ""),
                "last_updated": attrs.get("lastUpdatedDate", ""),
                "source_system": "viewpointcloud",
            }
            all_records.append(record)

        page += 1
        if total and (page - 1) * PAGE_SIZE >= total:
            break

        # Be polite
        await asyncio.sleep(0.3)

    return all_records


async def scrape_town(client: httpx.AsyncClient, town_id: str) -> dict:
    """Scrape all permits for a ViewpointCloud town."""
    config = TARGET_TOWNS.get(town_id)
    if not config:
        return {"town": town_id, "error": f"No config for {town_id}"}

    slug = config.viewpointcloud_slug
    if not slug:
        return {"town": town_id, "error": f"No VPC slug for {town_id}"}

    logger.info(f"  Fetching record types for {slug}...")
    record_types = await fetch_record_types(client, slug)

    if not record_types:
        return {"town": town_id, "error": "No record types returned"}

    # Filter to permit/license types
    permit_types = []
    for rt in record_types:
        attrs = rt.get("attributes", {})
        name = attrs.get("name", "")
        rt_id = str(rt.get("id", ""))
        if is_permit_type(name) and rt_id:
            permit_types.append({"id": rt_id, "name": name})

    logger.info(f"  Found {len(permit_types)} permit-related types (of {len(record_types)} total)")

    all_permits = []
    types_with_records = 0

    for pt in permit_types:
        records = await fetch_all_records_for_type(
            client, slug, pt["id"], pt["name"]
        )
        if records:
            types_with_records += 1
            all_permits.extend(records)
            logger.info(f"    {pt['name']}: {len(records)} records")

    # Add town_id to all records
    for p in all_permits:
        p["town_id"] = town_id

    logger.info(f"  Total: {len(all_permits)} permits across {types_with_records} types")

    result = {
        "town": config.name,
        "town_id": town_id,
        "total": len(all_permits),
        "source": "viewpointcloud",
        "slug": slug,
        "record_types_checked": len(permit_types),
        "types_with_records": types_with_records,
        "permits": all_permits,
    }

    outpath = PERMITS_DIR / f"{town_id}_permits.json"
    outpath.write_text(json.dumps(result, indent=2, default=str))
    logger.info(f"  Saved to {outpath.name}")

    return result


async def ingest_cached():
    """Ingest cached VPC permit files to Supabase."""
    from scripts.ingest_permits_to_supabase import ingest_town
    from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
    from database.supabase_client import SupabaseRestClient

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Supabase credentials missing")
        return

    db = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    if not await db.connect():
        logger.error("Could not connect to Supabase")
        return

    for town_id in VPC_MVP_TOWNS:
        fpath = PERMITS_DIR / f"{town_id}_permits.json"
        if not fpath.exists():
            logger.warning(f"  No cache file for {town_id}")
            continue
        result = await ingest_town(db, fpath)
        logger.info(f"  {town_id}: {result}")

    await db.disconnect()


async def main():
    parser = argparse.ArgumentParser(description="Scrape ViewpointCloud permits")
    parser.add_argument("--town", help="Only scrape a specific town")
    parser.add_argument("--ingest-only", action="store_true", help="Only ingest cached files")
    parser.add_argument("--dry-run", action="store_true", help="Scrape but don't ingest")
    args = parser.parse_args()

    if args.ingest_only:
        logger.info("=== Ingest-only mode ===")
        await ingest_cached()
        return

    towns = [args.town] if args.town else VPC_MVP_TOWNS

    logger.info(f"=== Scraping ViewpointCloud permits for {len(towns)} towns ===")
    start = time.time()

    async with httpx.AsyncClient() as client:
        for town_id in towns:
            # Skip if cache exists and is substantial
            cache_file = PERMITS_DIR / f"{town_id}_permits.json"
            if cache_file.exists() and cache_file.stat().st_size > 1000:
                logger.info(f"Skipping {town_id} — cache exists ({cache_file.stat().st_size:,} bytes)")
                continue

            logger.info(f"\n--- {town_id.upper()} ---")
            result = await scrape_town(client, town_id)
            if result.get("error"):
                logger.error(f"  FAILED: {result['error']}")
            else:
                logger.info(f"  SUCCESS: {result['total']} permits")

            # Delay between towns
            await asyncio.sleep(1.0)

    elapsed = time.time() - start
    logger.info(f"\nScraping done in {elapsed:.1f}s")

    if not args.dry_run:
        logger.info("\n=== Ingesting to Supabase ===")
        await ingest_cached()


if __name__ == "__main__":
    asyncio.run(main())
