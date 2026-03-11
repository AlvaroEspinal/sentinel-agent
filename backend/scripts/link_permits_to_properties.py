#!/usr/bin/env python3
"""
Link Permits to Properties — Match permits to properties by normalized address.

For each MVP town, this script:
  1. Fetches all permits and all properties from Supabase
  2. Normalizes addresses (strips apt/unit, normalizes street suffixes)
  3. Matches permits → properties by normalized address + town
  4. Falls back to spatial proximity (nearest property within 50m) for geocoded permits
  5. Updates permits.property_id with the matched properties.id

Key challenge: properties.city is Title Case ("Newton"), permits.town_id is
lowercase ("newton"). The script bridges this gap.

Usage:
    python3 link_permits_to_properties.py                        # All 12 MVP towns
    python3 link_permits_to_properties.py --town newton          # Single town
    python3 link_permits_to_properties.py --town newton --dry-run  # Preview only
    python3 link_permits_to_properties.py --limit 500            # First 500 permits per town
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root so we can import from backend.*
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    _project_root = Path(__file__).parent.parent.parent
    load_dotenv(_project_root / ".env")
    load_dotenv(Path(__file__).parent.parent / ".env")  # fallback
except ImportError:
    pass  # Fall back to env vars already set


# ── Configuration ────────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

PAGE_SIZE = 1000        # Supabase REST page size
BATCH_SIZE = 200        # PATCH batch size
PROXIMITY_METERS = 50   # Spatial fallback radius

MVP_TOWNS = [
    "newton", "wellesley", "weston", "brookline", "needham",
    "dover", "sherborn", "natick", "wayland", "lincoln",
    "concord", "lexington",
]

# Town ID (lowercase) → display name (Title Case, as stored in properties.city)
TOWN_DISPLAY: Dict[str, str] = {
    "newton": "Newton",
    "wellesley": "Wellesley",
    "weston": "Weston",
    "brookline": "Brookline",
    "needham": "Needham",
    "dover": "Dover",
    "sherborn": "Sherborn",
    "natick": "Natick",
    "wayland": "Wayland",
    "lincoln": "Lincoln",
    "concord": "Concord",
    "lexington": "Lexington",
}


# ── Address Normalization ────────────────────────────────────────────────────

# Street suffix normalization map (abbreviated → full)
SUFFIX_MAP = {
    "ST": "STREET",
    "AVE": "AVENUE",
    "AV": "AVENUE",
    "DR": "DRIVE",
    "RD": "ROAD",
    "LN": "LANE",
    "CT": "COURT",
    "PL": "PLACE",
    "CIR": "CIRCLE",
    "BLVD": "BOULEVARD",
    "TER": "TERRACE",
    "TERR": "TERRACE",
    "PKY": "PARKWAY",
    "PKWY": "PARKWAY",
    "HWY": "HIGHWAY",
    "SQ": "SQUARE",
    # WAY stays WAY — no expansion needed
}

# Regex to strip unit/apt/suite/floor numbers
_UNIT_PATTERN = re.compile(
    r'\s*(?:'
    r'(?:APT|APARTMENT|UNIT|SUITE|STE|#|FL|FLOOR|RM|ROOM|BLDG|BUILDING|NO)\s*\.?\s*'
    r'[A-Z0-9\-]*'
    r')'
    r'\s*$',
    re.IGNORECASE,
)

# Regex to match a trailing suffix token
_SUFFIX_PATTERN = re.compile(
    r'\b(' + '|'.join(SUFFIX_MAP.keys()) + r')\.?\b',
    re.IGNORECASE,
)


def _strip_city_state_zip(addr: str) -> str:
    """
    Strip trailing city, state, and zip from a full address.

    Handles patterns like:
        "161 BROOKLINE ST, CHESTNUT HILL, MA 02467"  → "161 BROOKLINE ST"
        "74 MEADOWBROOK RD, NEWTON CENTRE, MA 02459" → "74 MEADOWBROOK RD"
        "100 MAIN ST, NEWTON, MA"                     → "100 MAIN ST"
        "458 GLEN RD"                                  → "458 GLEN RD" (unchanged)
    """
    # Pattern: ", CITY, ST ZIPCODE" at end — strip from the first comma that leads
    # to a state abbreviation + optional zip
    # Match: ", <words>, <2-letter-state> <optional-zip>" at end
    stripped = re.sub(
        r',\s*[A-Z][A-Z\s]+,\s*[A-Z]{2}\s*\d{0,5}(?:-\d{4})?\s*$',
        '', addr,
    )
    if stripped != addr:
        return stripped.strip()

    # Also match: ", <2-letter-state> <zip>" at end (no city between commas)
    stripped = re.sub(
        r',\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$',
        '', addr,
    )
    if stripped != addr:
        return stripped.strip()

    # Also match: ", <CITY>" at end (just city, no state/zip)
    # Be careful — only strip if the part after comma looks like a city name
    # (all letters/spaces, at least 3 chars)
    stripped = re.sub(
        r',\s*[A-Z][A-Z\s]{2,}$',
        '', addr,
    )
    if stripped != addr:
        return stripped.strip()

    return addr


def normalize_address(raw_address: Optional[str]) -> str:
    """
    Normalize an address for comparison.

    Rules:
    - Uppercase everything
    - Strip city/state/zip (e.g. ", NEWTON, MA 02459")
    - Strip unit/apt/suite numbers
    - Normalize common street suffixes (ST→STREET, AVE→AVENUE, etc.)
    - Strip trailing periods and extra spaces
    - Strip leading/trailing whitespace

    Returns empty string if input is None/empty.
    """
    if not raw_address:
        return ""

    addr = str(raw_address).strip().upper()

    # Remove trailing periods
    addr = addr.rstrip(".")

    # Strip city/state/zip from full addresses (e.g. Socrata permits)
    addr = _strip_city_state_zip(addr)

    # Strip unit/apt/suite/floor numbers (iteratively — some have "APT 2 UNIT B")
    for _ in range(3):
        prev = addr
        addr = _UNIT_PATTERN.sub("", addr).strip()
        if addr == prev:
            break

    # Also strip patterns like "#2", "#2A" that might appear mid-string after house number
    addr = re.sub(r'\s*#\s*[A-Z0-9\-]+\s*$', '', addr)

    # Normalize street suffixes
    def _replace_suffix(m: re.Match) -> str:
        token = m.group(1).upper().rstrip(".")
        return SUFFIX_MAP.get(token, token)

    addr = _SUFFIX_PATTERN.sub(_replace_suffix, addr)

    # Collapse multiple spaces
    addr = re.sub(r'\s+', ' ', addr).strip()

    # Strip trailing periods again (suffix expansion might leave some)
    addr = addr.rstrip(".")

    return addr


# ── Haversine Distance ───────────────────────────────────────────────────────

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two lat/lon points."""
    R = 6_371_000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# ── Supabase REST Client ────────────────────────────────────────────────────

class SupabaseClient:
    """Minimal async Supabase REST client for permit linking."""

    def __init__(self):
        self._rest_url = f"{SUPABASE_URL.rstrip('/')}/rest/v1"
        self._client: Optional[httpx.AsyncClient] = None

    def _headers(self, extra: Optional[dict] = None) -> dict:
        h = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    async def connect(self):
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def disconnect(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_permits_for_town(
        self, town_id: str, limit: Optional[int] = None,
    ) -> List[dict]:
        """
        Fetch all permits for a town (unlinked ones first).
        Returns list of dicts with: id, address, latitude, longitude, property_id
        """
        all_rows: List[dict] = []
        offset = 0
        page_limit = PAGE_SIZE

        while True:
            if limit and len(all_rows) >= limit:
                break

            if limit:
                page_limit = min(PAGE_SIZE, limit - len(all_rows))

            params = {
                "select": "id,address,latitude,longitude,property_id",
                "town_id": f"eq.{town_id}",
                "order": "address.asc",
                "limit": str(page_limit),
                "offset": str(offset),
            }

            resp = await self._client.get(
                f"{self._rest_url}/permits",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            rows = resp.json()

            if not rows:
                break

            all_rows.extend(rows)
            offset += len(rows)

            if len(rows) < page_limit:
                break

        return all_rows

    async def fetch_properties_for_town(self, city_name: str) -> List[dict]:
        """
        Fetch all properties for a town by city name (Title Case).
        Returns list of dicts with: id, address, latitude, longitude
        """
        all_rows: List[dict] = []
        offset = 0

        while True:
            params = {
                "select": "id,address,latitude,longitude",
                "city": f"eq.{city_name}",
                "order": "address.asc",
                "limit": str(PAGE_SIZE),
                "offset": str(offset),
            }

            resp = await self._client.get(
                f"{self._rest_url}/properties",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            rows = resp.json()

            if not rows:
                break

            all_rows.extend(rows)
            offset += len(rows)

            if len(rows) < PAGE_SIZE:
                break

        return all_rows

    async def update_permit_property_id(
        self, permit_id: str, property_id: str,
    ) -> bool:
        """Update a single permit's property_id."""
        resp = await self._client.patch(
            f"{self._rest_url}/permits",
            headers=self._headers({"Prefer": "return=minimal"}),
            params={"id": f"eq.{permit_id}"},
            json={"property_id": property_id},
        )
        return resp.status_code < 400

    async def batch_update_property_ids(
        self, updates: List[Tuple[str, str]],
    ) -> int:
        """
        Batch update permit property_id assignments.

        Args:
            updates: list of (permit_id, property_id) tuples

        Returns count of successfully updated permits.
        """
        success_count = 0

        for i in range(0, len(updates), BATCH_SIZE):
            batch = updates[i:i + BATCH_SIZE]

            # PostgREST doesn't support bulk PATCH with different values per row,
            # so we issue individual PATCHes. But we can parallelize within a batch.
            tasks = []
            for permit_id, property_id in batch:
                tasks.append(self.update_permit_property_id(permit_id, property_id))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, bool) and result:
                    success_count += 1

            # Small delay between batches to avoid hammering the API
            if i + BATCH_SIZE < len(updates):
                await asyncio.sleep(0.3)

        return success_count


# ── Matching Engine ──────────────────────────────────────────────────────────

def build_property_index(
    properties: List[dict],
) -> Tuple[Dict[str, str], List[dict]]:
    """
    Build a normalized address → property_id lookup index,
    and a list of geocoded properties for spatial fallback.

    Returns:
        (addr_index, geocoded_props)
        addr_index: {normalized_address: property_id}
        geocoded_props: [{id, lat, lon}, ...] for properties with valid coords
    """
    addr_index: Dict[str, str] = {}
    geocoded_props: List[dict] = []

    for prop in properties:
        prop_id = prop["id"]
        raw_addr = prop.get("address", "")
        norm = normalize_address(raw_addr)

        if norm:
            # If multiple properties share the same normalized address,
            # keep the first one (they should be the same property)
            if norm not in addr_index:
                addr_index[norm] = prop_id

        # Track geocoded properties for spatial fallback
        lat = prop.get("latitude")
        lon = prop.get("longitude")
        if lat and lon and lat != 0 and lon != 0:
            geocoded_props.append({"id": prop_id, "lat": lat, "lon": lon})

    return addr_index, geocoded_props


def find_nearest_property(
    lat: float, lon: float,
    geocoded_props: List[dict],
    max_distance_m: float = PROXIMITY_METERS,
) -> Optional[str]:
    """
    Find the nearest property within max_distance_m meters.
    Returns property_id or None.
    """
    best_id = None
    best_dist = float("inf")

    for prop in geocoded_props:
        dist = haversine_meters(lat, lon, prop["lat"], prop["lon"])
        if dist < best_dist:
            best_dist = dist
            best_id = prop["id"]

    if best_dist <= max_distance_m:
        return best_id
    return None


def match_permits_to_properties(
    permits: List[dict],
    addr_index: Dict[str, str],
    geocoded_props: List[dict],
) -> Tuple[List[Tuple[str, str]], dict]:
    """
    Match permits to properties.

    Strategy:
      1. Normalize permit address, look up in addr_index
      2. If no address match and permit is geocoded, try spatial proximity

    Returns:
        (updates, stats)
        updates: list of (permit_id, property_id) tuples
        stats: {address_matches, spatial_matches, already_linked, no_match, no_address}
    """
    updates: List[Tuple[str, str]] = []
    stats = {
        "address_matches": 0,
        "spatial_matches": 0,
        "already_linked": 0,
        "no_match": 0,
        "no_address": 0,
    }

    for permit in permits:
        permit_id = permit["id"]
        existing_prop_id = permit.get("property_id")

        # Skip already-linked permits
        if existing_prop_id:
            stats["already_linked"] += 1
            continue

        raw_addr = permit.get("address", "")
        norm_addr = normalize_address(raw_addr)

        # Strategy 1: Address matching
        if norm_addr:
            prop_id = addr_index.get(norm_addr)
            if prop_id:
                updates.append((permit_id, prop_id))
                stats["address_matches"] += 1
                continue

        # Strategy 2: Spatial proximity (if permit is geocoded)
        lat = permit.get("latitude", 0)
        lon = permit.get("longitude", 0)
        if lat and lon and lat != 0 and lon != 0 and geocoded_props:
            prop_id = find_nearest_property(lat, lon, geocoded_props)
            if prop_id:
                updates.append((permit_id, prop_id))
                stats["spatial_matches"] += 1
                continue

        # No match
        if not norm_addr:
            stats["no_address"] += 1
        else:
            stats["no_match"] += 1

    return updates, stats


# ── Town Processing ──────────────────────────────────────────────────────────

async def process_town(
    db: SupabaseClient,
    town_id: str,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> dict:
    """Process a single town: fetch, match, update."""
    city_name = TOWN_DISPLAY.get(town_id, town_id.title())

    print(f"\n{'='*60}")
    print(f"  {city_name} (town_id={town_id})")
    print(f"{'='*60}")

    town_stats = {
        "town": town_id,
        "permits_fetched": 0,
        "properties_fetched": 0,
        "address_matches": 0,
        "spatial_matches": 0,
        "already_linked": 0,
        "no_match": 0,
        "no_address": 0,
        "updated": 0,
    }

    # 1. Fetch permits
    t0 = time.time()
    permits = await db.fetch_permits_for_town(town_id, limit=limit)
    town_stats["permits_fetched"] = len(permits)
    print(f"  Permits fetched:    {len(permits):,} ({time.time() - t0:.1f}s)")

    if not permits:
        print(f"  No permits found for {city_name}")
        return town_stats

    # 2. Fetch properties
    t1 = time.time()
    properties = await db.fetch_properties_for_town(city_name)
    town_stats["properties_fetched"] = len(properties)
    print(f"  Properties fetched: {len(properties):,} ({time.time() - t1:.1f}s)")

    if not properties:
        print(f"  No properties found for {city_name} — cannot link permits")
        town_stats["no_match"] = len(permits)
        return town_stats

    # 3. Build property index
    addr_index, geocoded_props = build_property_index(properties)
    print(f"  Property index:     {len(addr_index):,} normalized addresses, "
          f"{len(geocoded_props):,} geocoded")

    # 4. Match permits → properties
    updates, match_stats = match_permits_to_properties(
        permits, addr_index, geocoded_props,
    )

    town_stats.update(match_stats)

    total_permits = len(permits)
    match_total = match_stats["address_matches"] + match_stats["spatial_matches"]
    match_pct = (match_total / total_permits * 100) if total_permits > 0 else 0

    print(f"  Already linked:     {match_stats['already_linked']:,}")
    print(f"  Address matches:    {match_stats['address_matches']:,}")
    print(f"  Spatial matches:    {match_stats['spatial_matches']:,}")
    print(f"  No match:           {match_stats['no_match']:,}")
    print(f"  No address:         {match_stats['no_address']:,}")
    print(f"  Match rate:         {match_pct:.1f}% ({match_total:,}/{total_permits:,})")

    # 5. Apply updates
    if updates and not dry_run:
        t2 = time.time()
        print(f"\n  Updating {len(updates):,} permit records...")
        updated = await db.batch_update_property_ids(updates)
        town_stats["updated"] = updated
        print(f"  Updated:            {updated:,} permits ({time.time() - t2:.1f}s)")
    elif updates and dry_run:
        print(f"\n  [DRY RUN] Would update {len(updates):,} permits")
        town_stats["updated"] = 0
    else:
        print(f"\n  No new links to create")

    return town_stats


# ── Main Pipeline ────────────────────────────────────────────────────────────

async def run(
    town: Optional[str] = None,
    dry_run: bool = False,
    limit: Optional[int] = None,
):
    """Run the permit-to-property linking pipeline."""
    print("=" * 60)
    print("  PARCL INTELLIGENCE — Link Permits to Properties")
    print("  (permits.property_id ← properties.id)")
    print("=" * 60)

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    # Determine towns
    if town:
        town_lower = town.strip().lower()
        if town_lower not in MVP_TOWNS:
            print(f"WARNING: '{town}' is not in the 12 MVP towns, proceeding anyway")
            # Add it to TOWN_DISPLAY if missing
            if town_lower not in TOWN_DISPLAY:
                TOWN_DISPLAY[town_lower] = town.strip().title()
        towns = [town_lower]
    else:
        towns = MVP_TOWNS

    print(f"  Towns:    {', '.join(t.title() for t in towns)}")
    print(f"  Dry run:  {dry_run}")
    print(f"  Limit:    {limit or 'none'}")
    print(f"  Supabase: {SUPABASE_URL}")

    db = SupabaseClient()
    await db.connect()

    all_stats: List[dict] = []
    total_start = time.time()

    try:
        for t in towns:
            stats = await process_town(
                db=db,
                town_id=t,
                dry_run=dry_run,
                limit=limit,
            )
            all_stats.append(stats)
    except KeyboardInterrupt:
        print("\n\n  Interrupted!")
    finally:
        await db.disconnect()

    # Summary
    total_time = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")

    total_permits = sum(s["permits_fetched"] for s in all_stats)
    total_addr_match = sum(s["address_matches"] for s in all_stats)
    total_spatial = sum(s["spatial_matches"] for s in all_stats)
    total_already = sum(s["already_linked"] for s in all_stats)
    total_no_match = sum(s["no_match"] for s in all_stats)
    total_no_addr = sum(s["no_address"] for s in all_stats)
    total_updated = sum(s["updated"] for s in all_stats)
    total_matched = total_addr_match + total_spatial

    for s in all_stats:
        matched = s["address_matches"] + s["spatial_matches"]
        pct = (matched / s["permits_fetched"] * 100) if s["permits_fetched"] > 0 else 0
        print(
            f"  {s['town'].title():12s}  "
            f"permits={s['permits_fetched']:6,}  "
            f"addr={s['address_matches']:5,}  "
            f"spatial={s['spatial_matches']:4,}  "
            f"linked={s['already_linked']:5,}  "
            f"noMatch={s['no_match']:5,}  "
            f"updated={s['updated']:5,}  "
            f"({pct:.0f}%)"
        )

    print(f"  {'─'*70}")

    total_match_pct = (total_matched / total_permits * 100) if total_permits > 0 else 0
    print(f"  {'TOTAL':12s}  "
          f"permits={total_permits:6,}  "
          f"addr={total_addr_match:5,}  "
          f"spatial={total_spatial:4,}  "
          f"linked={total_already:5,}  "
          f"noMatch={total_no_match:5,}  "
          f"updated={total_updated:5,}  "
          f"({total_match_pct:.0f}%)")
    print(f"  Time: {total_time:.1f}s ({total_time / 60:.1f}m)")
    print(f"{'='*60}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Link permits to properties by normalized address matching",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 link_permits_to_properties.py --dry-run              # Preview all towns
  python3 link_permits_to_properties.py --town newton           # Link Newton only
  python3 link_permits_to_properties.py --town newton --dry-run # Preview Newton
  python3 link_permits_to_properties.py --limit 100 --dry-run   # Test with 100 permits/town
  python3 link_permits_to_properties.py                         # All 12 MVP towns

Town IDs: newton, wellesley, weston, brookline, needham, dover,
          sherborn, natick, wayland, lincoln, concord, lexington
        """,
    )
    parser.add_argument(
        "--town", type=str, default=None,
        help="Process a specific town only (e.g. 'newton')",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview mode — match but don't write to Supabase",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max permits to fetch per town (for testing)",
    )

    args = parser.parse_args()
    asyncio.run(run(
        town=args.town,
        dry_run=args.dry_run,
        limit=args.limit,
    ))


if __name__ == "__main__":
    main()
