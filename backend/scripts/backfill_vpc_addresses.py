#!/usr/bin/env python3
"""Backfill missing addresses for ViewpointCloud permits via the VPC detail API.

Strategy:
  1. Query Supabase for VPC permits missing addresses (per town)
  2. Use VPC search API to resolve permit_number -> record_id
  3. Fetch record detail to get address, lat/lon, MBL
  4. Update the Supabase permit row

The VPC bulk records API doesn't return all records (many are auth-gated),
but the search + detail endpoints CAN access records that the bulk API misses.

Usage:
    python scripts/backfill_vpc_addresses.py                  # all 7 MVP towns
    python scripts/backfill_vpc_addresses.py --town newton     # single town
    python scripts/backfill_vpc_addresses.py --town newton --limit 100  # test run
    python scripts/backfill_vpc_addresses.py --dry-run         # don't update DB
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
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from scrapers.connectors.town_config import TARGET_TOWNS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

VPC_API_BASE = "https://api-east.viewpointcloud.com/v2"

MVP_TOWNS = [
    "newton", "lexington", "needham", "natick",
    "wellesley", "wayland", "dover",
]

# Rate limiting: VPC API is public, be respectful
SEARCH_DELAY = 0.3   # seconds between search calls
DETAIL_DELAY = 0.3   # seconds between detail calls
BATCH_SIZE = 50       # update Supabase in batches


class Stats:
    """Track backfill statistics."""
    def __init__(self):
        self.searched = 0
        self.found = 0
        self.detail_ok = 0
        self.detail_has_addr = 0
        self.detail_has_latlon = 0
        self.updated = 0
        self.search_failed = 0
        self.detail_failed = 0
        self.not_found = 0

    def __str__(self):
        return (
            f"searched={self.searched}, found={self.found}, "
            f"detail_ok={self.detail_ok}, has_addr={self.detail_has_addr}, "
            f"has_latlon={self.detail_has_latlon}, updated={self.updated}, "
            f"not_found={self.not_found}, search_fail={self.search_failed}, "
            f"detail_fail={self.detail_failed}"
        )


async def fetch_no_address_permits(
    supabase: httpx.AsyncClient,
    town_id: str,
    limit: int | None = None,
) -> list[dict]:
    """Fetch permits missing addresses from Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/permits"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    params = {
        "select": "id,permit_number,town_id,permit_type",
        "town_id": f"eq.{town_id}",
        "source_system": "eq.viewpointcloud",
        "or": "(address.is.null,address.eq.)",
        "permit_number": "neq.",
        "order": "filed_date.desc.nullslast",
    }
    if limit:
        params["limit"] = str(limit)
    else:
        params["limit"] = "50000"

    resp = await supabase.get(url, headers=headers, params=params, timeout=60.0)
    if resp.status_code != 200:
        logger.error(f"Supabase fetch failed: {resp.status_code} {resp.text[:200]}")
        return []
    return resp.json()


async def vpc_search_record(
    client: httpx.AsyncClient,
    slug: str,
    permit_number: str,
) -> str | None:
    """Search VPC for a permit number, return record entity ID or None."""
    url = f"{VPC_API_BASE}/{slug}/search_results"
    params = {
        "criteria": "record",
        "key": permit_number,
        "timeStamp": str(int(time.time() * 1000)),
        "ignoreCommunity": "true",
    }
    try:
        resp = await client.get(url, params=params, timeout=20.0)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if isinstance(data, list) and data:
            # Find exact match (search can return fuzzy results)
            for item in data:
                result_text = str(item.get("resultText", ""))
                entity_id = str(item.get("entityID", "")).strip()
                # Check for exact permit number match
                if permit_number in result_text and entity_id:
                    return entity_id
            # Fallback: take first result if only one
            if len(data) == 1:
                entity_id = str(data[0].get("entityID", "")).strip()
                return entity_id if entity_id else None
        return None
    except Exception as e:
        logger.debug(f"Search error for {permit_number}: {e}")
        return None


async def vpc_fetch_detail(
    client: httpx.AsyncClient,
    slug: str,
    record_id: str,
) -> dict | None:
    """Fetch record detail from VPC, return address fields or None."""
    url = f"{VPC_API_BASE}/{slug}/records/{record_id}"
    try:
        resp = await client.get(url, timeout=20.0)
        if resp.status_code != 200:
            return None
        payload = resp.json()
        if not isinstance(payload, dict):
            return None
        data = payload.get("data", {})
        if not isinstance(data, dict):
            return None
        attrs = data.get("attributes", {})
        if not isinstance(attrs, dict):
            return None

        return {
            "address": attrs.get("fullAddress", "") or "",
            "latitude": attrs.get("latitude"),
            "longitude": attrs.get("longitude"),
            "street_no": attrs.get("streetNo", ""),
            "street_name": attrs.get("streetName", ""),
            "city": attrs.get("city", ""),
            "state": attrs.get("state", ""),
            "postal_code": attrs.get("postalCode", ""),
            "mbl": attrs.get("mbl", ""),
            "zoning": attrs.get("zoning", ""),
            "location_id": attrs.get("locationID"),
        }
    except Exception as e:
        logger.debug(f"Detail error for {record_id}: {e}")
        return None


async def update_permit_batch(
    supabase: httpx.AsyncClient,
    updates: list[dict],
    dry_run: bool = False,
) -> int:
    """Update a batch of permits in Supabase. Returns count updated."""
    if dry_run or not updates:
        return 0

    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    updated = 0
    for u in updates:
        permit_id = u.pop("id")
        url = f"{SUPABASE_URL}/rest/v1/permits?id=eq.{permit_id}"
        try:
            resp = await supabase.patch(url, headers=headers, json=u, timeout=10.0)
            if resp.status_code in (200, 204):
                updated += 1
            else:
                logger.debug(f"Update failed for {permit_id}: {resp.status_code}")
        except Exception as e:
            logger.debug(f"Update error for {permit_id}: {e}")
    return updated


async def backfill_town(
    vpc_client: httpx.AsyncClient,
    supabase: httpx.AsyncClient,
    town_id: str,
    limit: int | None = None,
    dry_run: bool = False,
) -> Stats:
    """Backfill addresses for a single town."""
    config = TARGET_TOWNS.get(town_id)
    if not config or not config.viewpointcloud_slug:
        logger.error(f"No VPC config for {town_id}")
        return Stats()

    slug = config.viewpointcloud_slug
    stats = Stats()

    # Fetch permits needing addresses
    permits = await fetch_no_address_permits(supabase, town_id, limit)
    logger.info(f"  {town_id}: {len(permits)} permits missing addresses")

    if not permits:
        return stats

    pending_updates: list[dict] = []

    for i, permit in enumerate(permits):
        permit_number = permit["permit_number"]
        permit_id = permit["id"]
        stats.searched += 1

        # Step 1: Search for record ID
        entity_id = await vpc_search_record(vpc_client, slug, permit_number)
        await asyncio.sleep(SEARCH_DELAY)

        if not entity_id:
            stats.not_found += 1
            if stats.searched % 200 == 0:
                logger.info(f"    Progress: {stats.searched}/{len(permits)} searched, {stats}")
            continue

        stats.found += 1

        # Step 2: Fetch detail for address
        detail = await vpc_fetch_detail(vpc_client, slug, entity_id)
        await asyncio.sleep(DETAIL_DELAY)

        if not detail:
            stats.detail_failed += 1
            continue

        stats.detail_ok += 1

        # Build update payload
        update = {"id": permit_id}
        addr = detail.get("address", "").strip()
        lat = detail.get("latitude")
        lon = detail.get("longitude")

        if addr:
            update["address"] = addr
            stats.detail_has_addr += 1
        if lat and lon:
            try:
                update["latitude"] = float(lat)
                update["longitude"] = float(lon)
                stats.detail_has_latlon += 1
            except (ValueError, TypeError):
                pass

        # Only update if we got something useful
        if len(update) > 1:  # more than just "id"
            pending_updates.append(update)

        # Batch update
        if len(pending_updates) >= BATCH_SIZE:
            count = await update_permit_batch(supabase, pending_updates, dry_run)
            stats.updated += count
            pending_updates = []

        # Progress logging
        if stats.searched % 100 == 0:
            logger.info(f"    Progress: {stats.searched}/{len(permits)} searched, {stats}")

    # Final batch
    if pending_updates:
        count = await update_permit_batch(supabase, pending_updates, dry_run)
        stats.updated += count

    return stats


async def main():
    parser = argparse.ArgumentParser(description="Backfill VPC permit addresses")
    parser.add_argument("--town", help="Only process a specific town")
    parser.add_argument("--limit", type=int, help="Limit permits per town (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Don't update Supabase")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    towns = [args.town] if args.town else MVP_TOWNS
    mode = "DRY RUN" if args.dry_run else "LIVE"

    logger.info(f"=== VPC Address Backfill ({mode}) for {len(towns)} towns ===")
    if args.limit:
        logger.info(f"  Limit: {args.limit} permits per town")

    start = time.time()
    total_stats = Stats()

    async with httpx.AsyncClient() as vpc_client, httpx.AsyncClient() as supabase:
        for town_id in towns:
            logger.info(f"\n--- {town_id.upper()} ---")
            stats = await backfill_town(
                vpc_client, supabase, town_id,
                limit=args.limit, dry_run=args.dry_run,
            )
            # Accumulate stats
            for attr in vars(stats):
                setattr(total_stats, attr, getattr(total_stats, attr) + getattr(stats, attr))
            logger.info(f"  {town_id} DONE: {stats}")

    elapsed = time.time() - start
    logger.info(f"\n=== TOTAL: {total_stats} ===")
    logger.info(f"Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}m)")

    # Summary
    if total_stats.searched > 0:
        find_rate = total_stats.found / total_stats.searched * 100
        addr_rate = total_stats.detail_has_addr / max(total_stats.searched, 1) * 100
        logger.info(f"Find rate: {find_rate:.1f}% | Address recovery rate: {addr_rate:.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
