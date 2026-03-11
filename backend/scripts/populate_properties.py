#!/usr/bin/env python3
"""
Populate the `properties` table from MassGIS ArcGIS Feature Service.

Queries MassGIS L3_TAXPAR_POLY_ASSESS parcels for the 12 MVP towns,
extracts property data + geometry centroids, and upserts into Supabase.

Usage:
    python populate_properties.py                    # All 12 MVP towns
    python populate_properties.py --town dover       # Single town
    python populate_properties.py --town dover --dry-run   # Preview only
    python populate_properties.py --town dover --limit 50  # First 50 parcels
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Optional

# Add project root so we can import from backend.*
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
except ImportError:
    pass  # Fall back to env vars already set

# ── Configuration ────────────────────────────────────────────────────────────

MASSGIS_URL = (
    "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/"
    "L3_TAXPAR_POLY_ASSESS_gdb/FeatureServer/0/query"
)

OUT_FIELDS = ",".join([
    "LOC_ID", "SITE_ADDR", "CITY", "TOTAL_VAL", "LS_PRICE", "LS_DATE",
    "YEAR_BUILT", "BLD_AREA", "LOT_SIZE", "USE_CODE", "UNITS",
    "BLDG_VAL", "LAND_VAL", "OTHER_VAL", "OWNER1", "STYLE",
    "NUM_ROOMS", "RES_AREA", "FY",
])

PAGE_SIZE = 2000       # ArcGIS max per query
BATCH_SIZE = 500       # Supabase upsert batch size
REQUEST_TIMEOUT = 60.0 # seconds

MVP_TOWNS = [
    "newton", "wellesley", "weston", "brookline", "needham",
    "dover", "sherborn", "natick", "wayland", "lincoln",
    "concord", "lexington",
]

# ── USE_CODE → property_type mapping ─────────────────────────────────────────

def map_use_code(use_code: Optional[str]) -> str:
    """Map MassGIS USE_CODE to a human-readable property_type string."""
    if not use_code:
        return "Other"
    code = str(use_code).strip()
    # Pad to 3 digits if numeric
    if code.isdigit():
        code = code.zfill(3)
    try:
        code_int = int(code)
    except ValueError:
        return "Other"

    if code_int == 101:
        return "Single Family"
    elif code_int == 102:
        return "Condo"
    elif code_int == 104:
        return "Two Family"
    elif code_int == 105:
        return "Three Family"
    elif code_int == 109:
        return "Multiple Houses"
    elif 111 <= code_int <= 125:
        return "Apartment"
    elif 130 <= code_int <= 132:
        return "Mixed Use"
    elif 300 <= code_int <= 399:
        return "Commercial"
    elif 400 <= code_int <= 499:
        return "Industrial"
    elif 600 <= code_int <= 699:
        return "Institutional"
    elif 700 <= code_int <= 799:
        return "Vacant Land"
    else:
        return "Other"


# ── Geometry helpers ─────────────────────────────────────────────────────────

def centroid(geometry: Optional[dict]) -> tuple[Optional[float], Optional[float]]:
    """
    Calculate centroid (lat, lon) from GeoJSON Polygon or MultiPolygon.
    Returns (latitude, longitude) or (None, None).
    """
    if not geometry:
        return None, None

    coords = []
    geo_type = geometry.get("type", "")
    if geo_type == "Polygon":
        rings = geometry.get("coordinates", [])
        if rings:
            coords = rings[0]  # Outer ring
    elif geo_type == "MultiPolygon":
        for poly in geometry.get("coordinates", []):
            if poly:
                coords.extend(poly[0])  # Outer ring of each polygon
    elif geo_type == "Point":
        pt = geometry.get("coordinates", [])
        if len(pt) >= 2:
            return pt[1], pt[0]  # lat, lon

    if not coords:
        return None, None

    avg_lon = sum(c[0] for c in coords) / len(coords)
    avg_lat = sum(c[1] for c in coords) / len(coords)
    return avg_lat, avg_lon


# ── Date parsing ─────────────────────────────────────────────────────────────

def parse_ls_date(ls_date) -> Optional[str]:
    """Convert MassGIS LS_DATE (integer YYYYMMDD) to ISO date string YYYY-MM-DD."""
    if not ls_date:
        return None
    try:
        val = int(ls_date)
    except (ValueError, TypeError):
        return None
    if val < 19000101 or val > 20991231:
        return None
    year = val // 10000
    month = (val % 10000) // 100
    day = val % 100
    if month < 1 or month > 12 or day < 1 or day > 31:
        return None
    return f"{year}-{month:02d}-{day:02d}"


# ── ArcGIS fetcher ───────────────────────────────────────────────────────────

async def fetch_town_parcels(
    client: httpx.AsyncClient,
    town: str,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Fetch all parcels for a town from MassGIS with pagination.
    Returns list of GeoJSON features (with geometry).
    """
    all_features = []
    offset = 0
    town_upper = town.strip().upper().replace("'", "''")

    # Filter: non-null address, non-zero total value
    where = (
        f"UPPER(CITY) = '{town_upper}' "
        f"AND SITE_ADDR IS NOT NULL "
        f"AND SITE_ADDR <> '' "
        f"AND TOTAL_VAL > 0"
    )

    while True:
        params = {
            "where": where,
            "outFields": OUT_FIELDS,
            "returnGeometry": "true",
            "f": "geojson",
            "outSR": "4326",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
            "orderByFields": "LOC_ID",
        }

        try:
            resp = await client.get(
                MASSGIS_URL, params=params, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            print(f"  [ERROR] HTTP {e.response.status_code} at offset {offset}")
            break
        except Exception as e:
            print(f"  [ERROR] Request failed at offset {offset}: {e}")
            break

        features = data.get("features", [])
        if not features:
            break

        all_features.extend(features)
        fetched_so_far = len(all_features)
        print(f"  Fetched {fetched_so_far} parcels (offset={offset})...")

        # Check if we hit our limit
        if limit and fetched_so_far >= limit:
            all_features = all_features[:limit]
            break

        # If we got fewer than PAGE_SIZE, we're done
        if len(features) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

        # Small delay to be polite to ArcGIS
        await asyncio.sleep(0.5)

    return all_features


# ── Feature → properties row conversion ──────────────────────────────────────

def feature_to_row(feature: dict) -> Optional[dict]:
    """
    Convert a MassGIS GeoJSON feature to a Supabase properties row dict.
    Returns None if the feature should be skipped.
    """
    props = feature.get("properties", {})
    geometry = feature.get("geometry")

    loc_id = props.get("LOC_ID")
    site_addr = props.get("SITE_ADDR")

    # Skip if no LOC_ID or address
    if not loc_id or not site_addr:
        return None

    # Skip empty/whitespace addresses
    if not str(site_addr).strip():
        return None

    # Extract centroid
    lat, lon = centroid(geometry)

    # Lot size: acres → sqft
    lot_size_acres = props.get("LOT_SIZE")
    lot_size_sqft = None
    if lot_size_acres and isinstance(lot_size_acres, (int, float)) and lot_size_acres > 0:
        lot_size_sqft = round(lot_size_acres * 43560, 2)

    # Building area
    bld_area = props.get("BLD_AREA")
    living_area_sqft = None
    if bld_area and isinstance(bld_area, (int, float)) and bld_area > 0:
        living_area_sqft = float(bld_area)

    # Year built
    year_built = props.get("YEAR_BUILT")
    if year_built:
        try:
            year_built = int(year_built)
            if year_built < 1600 or year_built > 2030:
                year_built = None
        except (ValueError, TypeError):
            year_built = None

    # Total assessed value
    total_val = props.get("TOTAL_VAL")
    tax_assessment = None
    if total_val and isinstance(total_val, (int, float)) and total_val > 0:
        tax_assessment = float(total_val)

    # Last sale price
    ls_price = props.get("LS_PRICE")
    last_sale_price = None
    if ls_price and isinstance(ls_price, (int, float)) and ls_price > 0:
        last_sale_price = float(ls_price)

    # Last sale date
    last_sale_date = parse_ls_date(props.get("LS_DATE"))

    # Property type from USE_CODE
    property_type = map_use_code(props.get("USE_CODE"))

    # City name — title case
    city_raw = props.get("CITY", "")
    city = str(city_raw).strip().title() if city_raw else None

    # Normalized address: uppercase, strip whitespace
    normalized_address = f"{str(site_addr).strip().upper()}, {city.upper() if city else ''}, MA"

    # Raw data blob for extra fields
    raw_data = {}
    for field in ["OWNER1", "BLDG_VAL", "LAND_VAL", "OTHER_VAL", "UNITS",
                   "STYLE", "NUM_ROOMS", "RES_AREA", "FY", "USE_CODE"]:
        val = props.get(field)
        if val is not None:
            raw_data[field] = val

    row = {
        "address": str(site_addr).strip(),
        "normalized_address": normalized_address,
        "city": city,
        "state": "MA",
        "parcel_id": str(loc_id).strip(),
        "latitude": lat,
        "longitude": lon,
        "year_built": year_built,
        "lot_size_sqft": lot_size_sqft,
        "living_area_sqft": living_area_sqft,
        "property_type": property_type,
        "tax_assessment": tax_assessment,
        "last_sale_price": last_sale_price,
        "last_sale_date": last_sale_date,
        "data_sources": json.dumps(["massgis"]),
        "raw_data": json.dumps(raw_data),
    }

    return row


# ── Supabase upserter ────────────────────────────────────────────────────────

async def upsert_batch(
    client: httpx.AsyncClient,
    supabase_url: str,
    supabase_key: str,
    rows: list[dict],
    dry_run: bool = False,
) -> int:
    """
    Upsert a batch of rows into the properties table.
    Returns count of rows upserted.
    """
    if dry_run:
        return len(rows)

    url = f"{supabase_url}/rest/v1/properties?on_conflict=parcel_id"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    try:
        resp = await client.post(
            url, headers=headers, json=rows, timeout=60.0
        )
        if resp.status_code >= 400:
            print(f"  [ERROR] Upsert failed: HTTP {resp.status_code} — {resp.text[:200]}")
            return 0
        return len(rows)
    except Exception as e:
        print(f"  [ERROR] Upsert exception: {e}")
        return 0


# ── Main pipeline ────────────────────────────────────────────────────────────

async def process_town(
    town: str,
    supabase_url: str,
    supabase_key: str,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> dict:
    """Process a single town: fetch from MassGIS, transform, upsert to Supabase."""
    print(f"\n{'='*60}")
    print(f"Processing: {town.upper()}")
    print(f"{'='*60}")

    stats = {
        "town": town,
        "fetched": 0,
        "valid": 0,
        "skipped": 0,
        "upserted": 0,
        "errors": 0,
    }

    async with httpx.AsyncClient() as client:
        # 1. Fetch from MassGIS
        t0 = time.time()
        features = await fetch_town_parcels(client, town, limit=limit)
        fetch_time = time.time() - t0
        stats["fetched"] = len(features)
        print(f"  Fetched {len(features)} parcels in {fetch_time:.1f}s")

        if not features:
            print(f"  No parcels found for {town.upper()}")
            return stats

        # 2. Transform features → rows, dedup by parcel_id
        #    MassGIS can return multiple features with the same LOC_ID
        #    (e.g., multi-polygon parcels). Keep the one with highest tax_assessment.
        rows_by_parcel: dict[str, dict] = {}
        for feature in features:
            row = feature_to_row(feature)
            if not row:
                stats["skipped"] += 1
                continue
            pid = row["parcel_id"]
            existing = rows_by_parcel.get(pid)
            if existing is None:
                rows_by_parcel[pid] = row
            else:
                # Keep the row with higher tax assessment (more complete data)
                new_val = row.get("tax_assessment") or 0
                old_val = existing.get("tax_assessment") or 0
                if new_val > old_val:
                    rows_by_parcel[pid] = row
                    stats["skipped"] += 1
                else:
                    stats["skipped"] += 1

        rows = list(rows_by_parcel.values())
        stats["valid"] = len(rows)
        print(f"  Valid rows: {len(rows)} (skipped/deduped: {stats['skipped']})")

        if dry_run:
            print(f"  [DRY RUN] Would upsert {len(rows)} rows")
            if rows:
                print(f"  Sample row: {json.dumps(rows[0], indent=2, default=str)}")
            stats["upserted"] = len(rows)
            return stats

        # 3. Upsert in batches
        t1 = time.time()
        total_upserted = 0
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            count = await upsert_batch(
                client, supabase_url, supabase_key, batch, dry_run=dry_run
            )
            total_upserted += count
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"  Batch {batch_num}/{total_batches}: upserted {count} rows")

            # Small delay between batches
            if i + BATCH_SIZE < len(rows):
                await asyncio.sleep(0.3)

        upsert_time = time.time() - t1
        stats["upserted"] = total_upserted
        print(f"  Upserted {total_upserted} rows in {upsert_time:.1f}s")

    return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Populate properties table from MassGIS parcel data"
    )
    parser.add_argument(
        "--town", type=str, default=None,
        help="Specific town to process (default: all 12 MVP towns)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview mode — fetch and transform but don't write to Supabase"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max parcels to fetch per town (for testing)"
    )
    args = parser.parse_args()

    # Load env
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    # Determine towns to process
    if args.town:
        town_lower = args.town.strip().lower()
        if town_lower not in MVP_TOWNS:
            print(f"WARNING: '{args.town}' is not in the 12 MVP towns, proceeding anyway")
        towns = [town_lower]
    else:
        towns = MVP_TOWNS

    print(f"Populate Properties from MassGIS")
    print(f"  Towns: {', '.join(t.title() for t in towns)}")
    print(f"  Dry run: {args.dry_run}")
    print(f"  Limit: {args.limit or 'none'}")
    print(f"  Supabase: {supabase_url}")

    # Process each town
    all_stats = []
    total_start = time.time()

    for town in towns:
        stats = await process_town(
            town=town,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        all_stats.append(stats)

    # Summary
    total_time = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    total_fetched = sum(s["fetched"] for s in all_stats)
    total_valid = sum(s["valid"] for s in all_stats)
    total_skipped = sum(s["skipped"] for s in all_stats)
    total_upserted = sum(s["upserted"] for s in all_stats)

    for s in all_stats:
        print(f"  {s['town'].title():12s}  fetched={s['fetched']:6d}  "
              f"valid={s['valid']:6d}  upserted={s['upserted']:6d}  "
              f"skipped={s['skipped']:4d}")

    print(f"  {'─'*50}")
    print(f"  {'TOTAL':12s}  fetched={total_fetched:6d}  "
          f"valid={total_valid:6d}  upserted={total_upserted:6d}  "
          f"skipped={total_skipped:4d}")
    print(f"  Time: {total_time:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
