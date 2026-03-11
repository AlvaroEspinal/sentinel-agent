#!/usr/bin/env python3
"""
Geocode Permits Table — Batch geocode the `permits` table (439K rows).

Unlike the legacy batch_geocode_permits.py (which parses pipe-delimited content
from the `documents` table and inserts into `document_locations`), this script:

  1. Reads clean addresses directly from `permits.address`
  2. Updates `permits.latitude` / `permits.longitude` in place via PATCH
  3. Targets the 12 MVP towns (newton, wellesley, weston, brookline, etc.)

Pipeline:
  Phase 1 — Scan permits table, extract unique (address, town_id) pairs
  Phase 2 — Geocode unique addresses via Nominatim (1.1s rate limit)
  Phase 3 — Batch UPDATE permits.latitude/longitude for all matching rows

Usage:
    python3 scripts/geocode_permits_table.py                         # All 12 MVP towns
    python3 scripts/geocode_permits_table.py --town newton           # Single town
    python3 scripts/geocode_permits_table.py --limit 100             # Test with 100
    python3 scripts/geocode_permits_table.py --dry-run               # Preview only
    python3 scripts/geocode_permits_table.py --resume                # Resume from checkpoint
    python3 scripts/geocode_permits_table.py --town newton --limit 50 --dry-run

Rate: ~1 unique address/sec (Nominatim limit).
      Many permits share addresses, so actual throughput is much higher.
"""

import asyncio
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# .env is in project root (sentinel-agent/), not backend/
_project_root = Path(__file__).parent.parent.parent
load_dotenv(_project_root / ".env")
# Also try backend/.env as fallback
load_dotenv(Path(__file__).parent.parent / ".env")

import httpx

# -- Configuration -----------------------------------------------------------

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ParclIntelligence/1.0 (batch-geocoder)"

DATA_DIR = Path(__file__).parent.parent / "data_cache"
CACHE_FILE = DATA_DIR / "geocode_cache_permits.json"
CHECKPOINT_FILE = DATA_DIR / "geocode_permits_checkpoint.json"

TOWN_STATE = "MA"

# 12 MVP towns — town_id -> display name for geocoding suffix
MVP_TOWNS: Dict[str, str] = {
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

# Massachusetts bounding box for sanity checks
MA_LAT_MIN, MA_LAT_MAX = 41.0, 43.0
MA_LON_MIN, MA_LON_MAX = -73.5, -69.5


# -- Geocoder ----------------------------------------------------------------

class BatchGeocoder:
    """Geocoder with persistent JSON disk cache and rate limiting."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._cache: Dict[str, Dict] = {}
        self._last_request_time: float = 0.0
        self.stats = {
            "api_calls": 0,
            "cache_hits": 0,
            "geocode_success": 0,
            "geocode_failed": 0,
            "errors": 0,
        }
        self._load_cache()

    def _load_cache(self):
        """Load persistent geocode cache from disk."""
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE) as f:
                    self._cache = json.load(f)
                print(f"  Loaded {len(self._cache):,} cached geocodes from {CACHE_FILE.name}")
            except Exception as e:
                print(f"  Cache load failed: {e}")

    def save_cache(self):
        """Persist geocode cache to disk."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(self._cache, f)
        except Exception as e:
            print(f"  Cache save failed: {e}")

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @staticmethod
    def _clean_address(address: str, town_id: str) -> str:
        """
        Clean an address for geocoding:
        1. If address already contains ", MA" or state+zip, use as-is
        2. Strip "Unit XXX" suffixes that confuse Nominatim
        3. Simplify range addresses like "1093-1101 CHESTNUT ST" → "1093 CHESTNUT ST"
        4. Strip "OFF" suffix (e.g., "0 DEDHAM ST OFF" → "0 DEDHAM ST")
        """
        import re
        addr = address.strip()

        # Strip "Unit XXX", "#XXX", "Lot X" apartment/unit/lot suffixes
        addr = re.sub(r',?\s*Unit\s+\S+', '', addr, flags=re.IGNORECASE).strip()
        addr = re.sub(r'\s+#\S+', '', addr)  # " #A", " #2B", etc.
        addr = re.sub(r',?\s*Lot\s+\d+', '', addr, flags=re.IGNORECASE).strip()

        # Strip test markers
        addr = re.sub(r'--test\s+only', '', addr, flags=re.IGNORECASE).strip()

        # Simplify range addresses: "1093-1101 CHESTNUT" → "1093 CHESTNUT"
        # Also handles "100 - 309 KEYES RD" with spaces around dash
        addr = re.sub(r'^(\d+)\s*-\s*\d+\s+', r'\1 ', addr)

        # Strip "OFF" suffix (e.g., "0 DEDHAM ST OFF, ..." → "0 DEDHAM ST, ...")
        addr = re.sub(r'\s+OFF\b', '', addr, flags=re.IGNORECASE)

        # Collapse multiple commas/spaces from removals
        addr = re.sub(r',\s*,', ',', addr)
        addr = re.sub(r'\s{2,}', ' ', addr).strip().strip(',')

        # Check if address already has state info (", MA " or ", MA\d{5}")
        has_state = bool(re.search(r',\s*MA\s+\d{5}', addr, re.IGNORECASE)) or \
                    bool(re.search(r',\s*MA\s*$', addr, re.IGNORECASE))

        if not has_state:
            # Append town + state
            town_display = MVP_TOWNS.get(town_id.lower(), town_id.title())
            addr = f"{addr}, {town_display}, MA"

        return addr

    async def geocode(self, address: str, town_id: str) -> Optional[Dict]:
        """
        Geocode an address. Returns {"lat": float, "lon": float} or None.

        Cleans the address (strips units, simplifies ranges) and queries Nominatim.
        Results are cached to disk so subsequent runs skip already-geocoded addresses.
        """
        clean_addr = self._clean_address(address, town_id)
        cache_key = clean_addr.lower().strip()

        # Check cache first (new clean key format)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            self.stats["cache_hits"] += 1
            if cached.get("lat") and cached.get("lon"):
                return cached
            return None  # Previously failed geocode

        # Fallback: check old cache key format (doubled-up town+state)
        # Old format was: "{raw_address}, {TownName}, MA"
        town_display = MVP_TOWNS.get(town_id.lower(), town_id.title())
        old_key = f"{address.strip()}, {town_display}, {TOWN_STATE}".lower().strip()
        if old_key in self._cache:
            cached = self._cache[old_key]
            self.stats["cache_hits"] += 1
            if cached.get("lat") and cached.get("lon"):
                # Migrate to new key format
                self._cache[cache_key] = cached
                return cached
            return None

        if self.dry_run:
            return None

        # Rate limit: 1.1s between requests (Nominatim public API policy)
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < 1.1:
            await asyncio.sleep(1.1 - elapsed)

        try:
            params = {
                "q": clean_addr,
                "format": "json",
                "limit": 1,
                "addressdetails": 1,
                "countrycodes": "us",
            }
            headers = {"User-Agent": USER_AGENT}

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    NOMINATIM_URL, params=params, headers=headers, timeout=10.0,
                )
                self._last_request_time = time.monotonic()
                self.stats["api_calls"] += 1
                resp.raise_for_status()
                results = resp.json()

            if not results:
                self._cache[cache_key] = {"lat": None, "lon": None}
                self.stats["geocode_failed"] += 1
                return None

            top = results[0]
            lat = float(top["lat"])
            lon = float(top["lon"])

            # Sanity check: must be within Massachusetts bounds
            if not (MA_LAT_MIN <= lat <= MA_LAT_MAX and MA_LON_MIN <= lon <= MA_LON_MAX):
                self._cache[cache_key] = {"lat": None, "lon": None}
                self.stats["geocode_failed"] += 1
                return None

            result = {
                "lat": lat,
                "lon": lon,
                "display_name": top.get("display_name", ""),
            }
            self._cache[cache_key] = result
            self.stats["geocode_success"] += 1
            return result

        except Exception as e:
            self._cache[cache_key] = {"lat": None, "lon": None}
            self.stats["errors"] += 1
            return None


# -- Supabase Batch Client ---------------------------------------------------

class SupabasePermitsBatch:
    """Minimal Supabase REST client for batch permits operations."""

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
        """Initialize httpx client."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def disconnect(self):
        """Close the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def count_permits(
        self, town: Optional[str] = None, only_ungeocoded: bool = True,
    ) -> int:
        """
        Count permits, optionally filtered by town and geocode status.

        Args:
            town: Filter by town_id (e.g. "newton")
            only_ungeocoded: If True, count only rows with latitude=0
        """
        params: dict = {"select": "id"}
        if town:
            params["town_id"] = f"eq.{town.lower()}"
        if only_ungeocoded:
            params["latitude"] = "eq.0"
        resp = await self._client.get(
            f"{self._rest_url}/permits",
            headers=self._headers({"Prefer": "count=exact", "Range": "0-0"}),
            params=params,
        )
        resp.raise_for_status()
        cr = resp.headers.get("content-range", "")
        if "/" in cr:
            total = cr.split("/")[-1]
            if total != "*":
                return int(total)
        return 0

    async def count_all_permits(self) -> int:
        """Count total permits across all towns."""
        return await self.count_permits(town=None, only_ungeocoded=False)

    async def fetch_permits(
        self,
        town: Optional[str] = None,
        offset: int = 0,
        limit: int = 1000,
        only_ungeocoded: bool = True,
    ) -> List[dict]:
        """
        Fetch permits with address data.

        Returns rows with: id, town_id, address, latitude, longitude
        Skips rows with NULL/empty address or already-geocoded (lat != 0).
        """
        params: dict = {
            "select": "id,town_id,address,latitude,longitude",
            "order": "town_id.asc,address.asc",
            "limit": str(limit),
            "offset": str(offset),
            "address": "neq.",  # address is NOT empty string
        }
        if town:
            params["town_id"] = f"eq.{town.lower()}"
        if only_ungeocoded:
            params["latitude"] = "eq.0"
        resp = await self._client.get(
            f"{self._rest_url}/permits",
            headers=self._headers(),
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    async def batch_update_coords(
        self, town_id: str, address: str, lat: float, lon: float,
    ) -> int:
        """
        Update latitude/longitude for ALL permits matching (town_id, address).

        Uses PostgREST PATCH:
            PATCH /rest/v1/permits?town_id=eq.{town}&address=eq.{addr}
            Body: {"latitude": lat, "longitude": lon}

        Returns number of rows affected (from content-range header).
        """
        params = {
            "town_id": f"eq.{town_id}",
            "address": f"eq.{address}",
        }
        body = {
            "latitude": lat,
            "longitude": lon,
        }
        resp = await self._client.patch(
            f"{self._rest_url}/permits",
            headers=self._headers({"Prefer": "return=minimal,count=exact"}),
            params=params,
            json=body,
        )
        if resp.status_code >= 400:
            print(f"    PATCH failed for '{address}' in {town_id}: HTTP {resp.status_code} — {resp.text[:200]}")
            return 0
        # Parse content-range for affected count
        cr = resp.headers.get("content-range", "")
        if "/" in cr:
            total = cr.split("/")[-1]
            if total != "*":
                return int(total)
        return 1  # Assume at least 1 if no content-range


# -- Checkpoint ---------------------------------------------------------------

def load_checkpoint() -> dict:
    """Load checkpoint from disk for resume support."""
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"completed_keys": [], "town": None}


def save_checkpoint(completed_keys: List[str], town: Optional[str], **extra):
    """Save checkpoint to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "completed_keys": completed_keys,
        "town": town,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    data.update(extra)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f)


# -- Phase 1: Scan & Deduplicate ---------------------------------------------

async def scan_permits(
    db: SupabasePermitsBatch,
    town: Optional[str],
    limit: Optional[int],
    page_size: int = 1000,
) -> Dict[str, Dict]:
    """
    Phase 1: Scan the permits table and build a map of unique
    (address, town_id) pairs to the count of permits sharing that address.

    Returns:
        {
            "123 main street|newton": {
                "address": "123 Main Street",
                "town_id": "newton",
                "permit_count": 5
            },
            ...
        }
    """
    address_map: Dict[str, Dict] = {}
    scanned = 0
    max_scan = limit or 999_999_999
    offset = 0

    while scanned < max_scan:
        fetch_limit = min(page_size, max_scan - scanned)
        permits = await db.fetch_permits(
            town=town, offset=offset, limit=fetch_limit, only_ungeocoded=True,
        )
        if not permits:
            break

        for p in permits:
            address = (p.get("address") or "").strip()
            p_town = (p.get("town_id") or "").strip().lower()

            # Skip empty addresses
            if not address or len(address) < 3:
                continue

            key = f"{address.lower()}|{p_town}"
            if key not in address_map:
                address_map[key] = {
                    "address": address,
                    "town_id": p_town,
                    "permit_count": 0,
                }
            address_map[key]["permit_count"] += 1

        scanned += len(permits)
        offset += len(permits)

        if scanned % 5000 == 0:
            print(f"    Scanned {scanned:,} permits, found {len(address_map):,} unique addresses...")

    return address_map


# -- Phase 2: Geocode Unique Addresses ----------------------------------------

async def geocode_addresses(
    geocoder: BatchGeocoder,
    address_map: Dict[str, Dict],
    resume_completed: Optional[List[str]] = None,
) -> Tuple[Dict[str, Dict], List[str]]:
    """
    Phase 2: Geocode all unique addresses via Nominatim.

    Args:
        geocoder: BatchGeocoder instance (with disk cache)
        address_map: Output of scan_permits()
        resume_completed: List of address keys already completed (for resume)

    Returns:
        (geocoded_map, completed_keys)
        geocoded_map: {key: {address, town_id, lat, lon, permit_count}}
        completed_keys: List of all keys attempted (for checkpoint)
    """
    completed_set = set(resume_completed or [])
    geocoded: Dict[str, Dict] = {}
    completed_keys: List[str] = list(completed_set)

    # Filter out already-completed keys
    pending = {k: v for k, v in address_map.items() if k not in completed_set}
    total = len(pending)
    done = 0
    start_time = time.time()

    for key, info in pending.items():
        done += 1
        result = await geocoder.geocode(info["address"], info["town_id"])

        completed_keys.append(key)

        if result and result.get("lat") and result.get("lon"):
            geocoded[key] = {
                "address": info["address"],
                "town_id": info["town_id"],
                "lat": result["lat"],
                "lon": result["lon"],
                "permit_count": info["permit_count"],
            }

        # Progress every 100 addresses
        if done % 100 == 0:
            elapsed = time.time() - start_time
            rate = done / elapsed if elapsed > 0 else 0
            pct = done / total * 100 if total > 0 else 100
            eta_sec = (total - done) / rate if rate > 0 else 0
            eta_min = eta_sec / 60
            print(
                f"    Geocoded {done:,}/{total:,} ({pct:.1f}%) "
                f"| {rate:.1f} addr/sec "
                f"| API: {geocoder.stats['api_calls']} "
                f"| Cache: {geocoder.stats['cache_hits']} "
                f"| Success: {len(geocoded):,} "
                f"| ETA: {eta_min:.0f}m"
            )
            # Periodic cache + checkpoint save
            geocoder.save_cache()

    return geocoded, completed_keys


# -- Phase 3: Batch Update Permits --------------------------------------------

async def update_permits(
    db: SupabasePermitsBatch,
    geocoded: Dict[str, Dict],
    dry_run: bool = False,
) -> int:
    """
    Phase 3: Batch update permits.latitude / permits.longitude in Supabase.

    For each unique (address, town_id) pair, issue a single PATCH that updates
    ALL permits with that address+town combo.

    Returns total number of permit rows updated.
    """
    total_updated = 0
    total_addresses = len(geocoded)

    print(f"\n  Phase 3: Updating coordinates for {total_addresses:,} unique addresses")

    if dry_run:
        total_permits = sum(g["permit_count"] for g in geocoded.values())
        print(f"  [DRY RUN] Would update ~{total_permits:,} permit rows. Skipping writes.")
        return 0

    done = 0
    for key, info in geocoded.items():
        done += 1
        updated = await db.batch_update_coords(
            town_id=info["town_id"],
            address=info["address"],
            lat=info["lat"],
            lon=info["lon"],
        )
        total_updated += updated

        if done % 200 == 0:
            print(f"    Updated {done:,}/{total_addresses:,} addresses ({total_updated:,} permit rows)...")

    return total_updated


# -- Main Pipeline ------------------------------------------------------------

async def run_batch(
    town: Optional[str] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    resume: bool = False,
    page_size: int = 1000,
):
    """Run the 3-phase geocoding pipeline."""
    print("=" * 70)
    print("  PARCL INTELLIGENCE — Permits Table Geocoder")
    print("  (permits.address -> permits.latitude/longitude)")
    print("=" * 70)

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    # Validate town if specified
    if town and town.lower() not in MVP_TOWNS:
        print(f"ERROR: Unknown town '{town}'. Valid MVP towns:")
        for tid, name in sorted(MVP_TOWNS.items()):
            print(f"  {tid:12s} -> {name}")
        sys.exit(1)

    if town:
        town = town.lower()

    db = SupabasePermitsBatch()
    geocoder = BatchGeocoder(dry_run=dry_run)

    await db.connect()

    total_all = await db.count_all_permits()
    ungeocoded = await db.count_permits(town=town, only_ungeocoded=True)
    total_scope = await db.count_permits(town=town, only_ungeocoded=False)

    print(f"  Total permits in DB:       {total_all:,}")
    print(f"  Scope ({town or 'all MVP'}):  {total_scope:,} total, {ungeocoded:,} ungeocoded")
    print(f"  Geocode cache:             {geocoder.cache_size:,} entries")
    if limit:
        print(f"  Limit:                     {limit:,}")
    if dry_run:
        print(f"  Mode:                      DRY RUN")
    print()

    # Load checkpoint for resume
    resume_completed: List[str] = []
    if resume:
        cp = load_checkpoint()
        resume_completed = cp.get("completed_keys", [])
        if resume_completed:
            print(f"  Resuming: {len(resume_completed):,} addresses already completed")

    start_time = time.time()

    try:
        # Phase 1: Scan & deduplicate
        print("  Phase 1: Scanning permits table for unique addresses...")
        address_map = await scan_permits(
            db, town=town, limit=limit, page_size=page_size,
        )

        total_permits_with_addr = sum(v["permit_count"] for v in address_map.values())
        print(f"\n  Found {len(address_map):,} unique addresses across {total_permits_with_addr:,} permits")

        if not address_map:
            print("  Nothing to geocode. All permits may already be geocoded or have no address.")
            await db.disconnect()
            return

        # Phase 2: Geocode unique addresses
        pending_count = len(address_map) - len(set(resume_completed) & set(address_map.keys()))
        print(f"\n  Phase 2: Geocoding {pending_count:,} unique addresses...")
        print(f"  (Cached addresses are instant, new ones take ~1.1 sec each)")

        geocoded, completed_keys = await geocode_addresses(
            geocoder, address_map, resume_completed=resume_completed,
        )

        geocoded_count = len(geocoded)
        failed_count = len(address_map) - geocoded_count - len(
            set(resume_completed) - set(address_map.keys())
        )
        print(f"\n  Geocoded: {geocoded_count:,}/{len(address_map):,} addresses")
        if failed_count > 0:
            print(f"  Failed:   {failed_count:,} addresses (no Nominatim result)")

        # Save cache + checkpoint
        geocoder.save_cache()
        save_checkpoint(completed_keys, town)

        # Phase 3: Update permits table
        total_updated = await update_permits(db, geocoded, dry_run=dry_run)

    except KeyboardInterrupt:
        print("\n\n  Interrupted! Saving progress...")
        geocoder.save_cache()
        save_checkpoint(
            resume_completed, town, interrupted=True,
        )
        await db.disconnect()
        return

    except Exception as e:
        print(f"\n  Error: {e}")
        geocoder.save_cache()
        raise

    finally:
        geocoder.save_cache()
        await db.disconnect()

    # Summary
    elapsed = time.time() - start_time
    s = geocoder.stats

    print("\n" + "=" * 70)
    print("  PERMITS TABLE GEOCODE COMPLETE")
    print("=" * 70)
    print(f"  Scope:                 {town or 'all MVP towns'}")
    print(f"  Permits scanned:       {total_permits_with_addr:,}")
    print(f"  Unique addresses:      {len(address_map):,}")
    print(f"  Successfully geocoded: {geocoded_count:,}")
    print(f"  {'=' * 40}")
    print(f"  Nominatim API calls:   {s['api_calls']:,}")
    print(f"  Cache hits:            {s['cache_hits']:,}")
    print(f"  Geocode success:       {s['geocode_success']:,}")
    print(f"  Geocode failed:        {s['geocode_failed']:,}")
    print(f"  API errors:            {s['errors']:,}")
    if not dry_run:
        print(f"  Permit rows updated:   {total_updated:,}")
    print(f"  {'=' * 40}")
    print(f"  Elapsed time:          {elapsed:.1f}s ({elapsed / 60:.1f}m)")
    if s["api_calls"] > 0:
        print(f"  Avg geocode time:      {elapsed / max(1, s['api_calls']):.2f}s")
    print(f"  Cache file:            {CACHE_FILE}")
    print(f"  Checkpoint file:       {CHECKPOINT_FILE}")
    print("=" * 70)


# -- CLI ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Batch geocode permits in the `permits` table (12 MVP towns)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/geocode_permits_table.py --dry-run --limit 20         # Preview 20
  python3 scripts/geocode_permits_table.py --town newton --limit 500    # 500 Newton permits
  python3 scripts/geocode_permits_table.py --town brookline             # All Brookline
  python3 scripts/geocode_permits_table.py --resume                     # Resume from checkpoint
  python3 scripts/geocode_permits_table.py                              # All MVP towns

Town IDs: newton, wellesley, weston, brookline, needham, dover,
          sherborn, natick, wayland, lincoln, concord, lexington
        """,
    )
    parser.add_argument(
        "--town", type=str, default=None,
        help="Geocode a specific MVP town only (e.g. 'newton')",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max permits to scan (for testing)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview only — no Nominatim calls, no DB writes",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from checkpoint (skip already-geocoded addresses)",
    )
    parser.add_argument(
        "--page-size", type=int, default=1000,
        help="Supabase fetch page size (default: 1000)",
    )

    args = parser.parse_args()
    asyncio.run(run_batch(
        town=args.town,
        limit=args.limit,
        dry_run=args.dry_run,
        resume=args.resume,
        page_size=args.page_size,
    ))


if __name__ == "__main__":
    main()
