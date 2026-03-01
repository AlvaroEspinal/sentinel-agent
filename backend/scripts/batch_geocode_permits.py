#!/usr/bin/env python3
"""
Batch Geocode Permits — Parse addresses from 125K permit content fields
and create document_locations rows in Supabase with real coordinates.

Data structure:
  - documents table: 125,795 permits (Somerville 64K, Cambridge 61K, Brookline 21)
  - content field format: "Type: Building | Address: 516 Somerville Ave | Description: ... | Cost: $627.00"
  - document_locations table: Only 9 rows exist (Brookline demo data)
  - The 125K Somerville/Cambridge permits have NO document_locations rows

This script:
1. Fetches permits in batches from Supabase (documents table)
2. Extracts address from the content field (format: "Address: <street>")
3. Deduplicates addresses (many permits share the same address)
4. Geocodes unique addresses via Nominatim (1 req/sec rate limit)
5. Creates document_locations rows with real lat/lon coordinates
6. Tracks progress with checkpoints and persistent geocode cache

Usage:
    python3 scripts/batch_geocode_permits.py                    # Run full batch
    python3 scripts/batch_geocode_permits.py --town somerville  # Single town
    python3 scripts/batch_geocode_permits.py --limit 100        # Test with 100
    python3 scripts/batch_geocode_permits.py --dry-run          # Preview only
    python3 scripts/batch_geocode_permits.py --resume           # Resume from checkpoint

Rate: ~1 unique address/sec (Nominatim limit).
      Many permits share addresses, so actual throughput is much higher.
      With ~10K unique addresses across 125K permits, expect ~3 hours total.
"""

import asyncio
import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
# .env is in project root (sentinel-agent/), not backend/
_project_root = Path(__file__).parent.parent.parent
load_dotenv(_project_root / ".env")
# Also try backend/.env as fallback
load_dotenv(Path(__file__).parent.parent / ".env")

import httpx

# ── Configuration ──────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ParclIntelligence/1.0 (batch-geocoder)"

DATA_DIR = Path(__file__).parent.parent / "data_cache"
CHECKPOINT_FILE = DATA_DIR / "geocode_checkpoint.json"
CACHE_FILE = DATA_DIR / "geocode_cache.json"

TOWN_STATE = "MA"
TOWN_DISPLAY = {
    "somerville": "Somerville",
    "cambridge": "Cambridge",
    "brookline": "Brookline",
}

# ── Address Extraction ─────────────────────────────────────────────────

# Content format: "Type: Building | Address: 516 Somerville Ave | Description: ... | Cost: $627.00"
ADDRESS_PATTERN = re.compile(r'Address:\s*([^|]+)', re.I)


def extract_address(content: str) -> Optional[str]:
    """Extract a street address from permit content field."""
    if not content:
        return None
    m = ADDRESS_PATTERN.search(content)
    if m:
        addr = m.group(1).strip().rstrip(',').rstrip('.')
        if len(addr) >= 5:
            return addr
    return None


# ── Geocoding ──────────────────────────────────────────────────────────

class BatchGeocoder:
    """Geocoder with persistent disk cache and rate limiting."""

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
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE) as f:
                    self._cache = json.load(f)
                print(f"  Loaded {len(self._cache):,} cached geocodes")
            except Exception as e:
                print(f"  Cache load failed: {e}")

    def save_cache(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(self._cache, f)
        except Exception as e:
            print(f"  Cache save failed: {e}")

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    async def geocode(self, address: str, town: str) -> Optional[Dict]:
        """Geocode an address. Returns {lat, lon} or None."""
        town_display = TOWN_DISPLAY.get(town.lower(), town.title())
        full_address = f"{address}, {town_display}, {TOWN_STATE}"
        cache_key = full_address.lower().strip()

        # Check cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            self.stats["cache_hits"] += 1
            if cached.get("lat") and cached.get("lon"):
                return cached
            return None  # Previously failed

        if self.dry_run:
            return None

        # Rate limit
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < 1.1:
            await asyncio.sleep(1.1 - elapsed)

        try:
            params = {
                "q": full_address,
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

            # Sanity check: Massachusetts bounds
            if not (41.0 <= lat <= 43.0 and -73.5 <= lon <= -69.5):
                self._cache[cache_key] = {"lat": None, "lon": None}
                self.stats["geocode_failed"] += 1
                return None

            result = {"lat": lat, "lon": lon, "display_name": top.get("display_name", "")}
            self._cache[cache_key] = result
            self.stats["geocode_success"] += 1
            return result

        except Exception as e:
            self._cache[cache_key] = {"lat": None, "lon": None}
            self.stats["errors"] += 1
            return None


# ── Supabase Client ────────────────────────────────────────────────────

class SupabaseBatch:
    """Minimal Supabase client for batch operations."""

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

    async def connect(self) -> int:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        resp = await self._client.get(
            f"{self._rest_url}/documents",
            headers=self._headers({"Prefer": "count=exact", "Range": "0-0"}),
            params={"source_type": "eq.permit", "select": "id"},
        )
        resp.raise_for_status()
        cr = resp.headers.get("content-range", "")
        return int(cr.split("/")[-1]) if "/" in cr else 0

    async def disconnect(self):
        if self._client:
            await self._client.aclose()

    async def count_permits(self, town: Optional[str] = None) -> int:
        params: dict = {"source_type": "eq.permit", "select": "id"}
        if town:
            params["town_id"] = f"eq.{town.lower()}"
        resp = await self._client.get(
            f"{self._rest_url}/documents",
            headers=self._headers({"Prefer": "count=exact", "Range": "0-0"}),
            params=params,
        )
        resp.raise_for_status()
        cr = resp.headers.get("content-range", "")
        return int(cr.split("/")[-1]) if "/" in cr and cr.split("/")[-1] != "*" else 0

    async def fetch_permits(
        self, town: Optional[str] = None, offset: int = 0, limit: int = 1000,
    ) -> List[dict]:
        """Fetch permits (documents only, no joins — faster)."""
        params: dict = {
            "source_type": "eq.permit",
            "select": "id,town_id,content",
            "order": "created_at.asc",
            "limit": str(limit),
            "offset": str(offset),
        }
        if town:
            params["town_id"] = f"eq.{town.lower()}"
        resp = await self._client.get(
            f"{self._rest_url}/documents",
            headers=self._headers(),
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    async def check_location_exists(self, document_id: str) -> bool:
        """Check if a document_locations row already exists for this document."""
        resp = await self._client.get(
            f"{self._rest_url}/document_locations",
            headers=self._headers({"Prefer": "count=exact", "Range": "0-0"}),
            params={"document_id": f"eq.{document_id}", "select": "id"},
        )
        cr = resp.headers.get("content-range", "")
        count = int(cr.split("/")[-1]) if "/" in cr and cr.split("/")[-1] != "*" else 0
        return count > 0

    async def insert_location(
        self, document_id: str, address: str, lat: float, lon: float,
    ) -> bool:
        """Insert a new document_locations row."""
        data = {
            "id": str(uuid.uuid4()),
            "document_id": document_id,
            "address": address,
            "latitude": lat,
            "longitude": lon,
            "confidence": 0.85,
            "geocode_source": "nominatim_batch",
        }
        resp = await self._client.post(
            f"{self._rest_url}/document_locations",
            headers=self._headers({"Prefer": "return=minimal"}),
            json=data,
        )
        return resp.status_code in (200, 201)

    async def batch_insert_locations(self, rows: List[dict]) -> int:
        """Insert multiple document_locations rows in one request."""
        if not rows:
            return 0
        resp = await self._client.post(
            f"{self._rest_url}/document_locations",
            headers=self._headers({"Prefer": "return=minimal"}),
            json=rows,
        )
        if resp.status_code in (200, 201):
            return len(rows)
        else:
            print(f"    ✗ Batch insert failed: HTTP {resp.status_code} — {resp.text[:200]}")
            return 0


# ── Checkpoint ─────────────────────────────────────────────────────────

def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"offset": 0, "town": None}


def save_checkpoint(offset: int, town: Optional[str], **extra):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {"offset": offset, "town": town, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    data.update(extra)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f)


# ── Phase 1: Scan & Deduplicate ───────────────────────────────────────

async def scan_addresses(
    db: SupabaseBatch,
    town: Optional[str],
    limit: Optional[int],
    start_offset: int = 0,
    page_size: int = 1000,
) -> Dict[str, List[str]]:
    """
    Scan all permits, extract addresses, and build address → [doc_ids] map.
    This is fast since we don't make any API calls, just read from Supabase.
    Returns: {address_key: [doc_id, doc_id, ...]}
    """
    address_map: Dict[str, Dict] = {}  # address_key → {address, town, doc_ids}
    scanned = 0
    max_scan = limit or 999_999_999
    offset = start_offset

    while scanned < max_scan:
        fetch_limit = min(page_size, max_scan - scanned)
        permits = await db.fetch_permits(town=town, offset=offset, limit=fetch_limit)
        if not permits:
            break

        for doc in permits:
            content = doc.get("content", "")
            address = extract_address(content)
            if not address:
                continue

            doc_town = doc.get("town_id", "")
            key = f"{address.lower()}|{doc_town.lower()}"

            if key not in address_map:
                address_map[key] = {
                    "address": address,
                    "town": doc_town,
                    "doc_ids": [],
                }
            address_map[key]["doc_ids"].append(doc.get("id", ""))

        scanned += len(permits)
        offset += len(permits)

        if scanned % 10000 == 0:
            print(f"    Scanned {scanned:,} permits, found {len(address_map):,} unique addresses...")

    return address_map


# ── Phase 2: Geocode Unique Addresses ─────────────────────────────────

async def geocode_addresses(
    geocoder: BatchGeocoder,
    address_map: Dict[str, Dict],
) -> Dict[str, Dict]:
    """
    Geocode all unique addresses. Returns geocoded results.
    {address_key: {address, town, lat, lon, doc_ids}}
    """
    geocoded: Dict[str, Dict] = {}
    total = len(address_map)
    done = 0
    start_time = time.time()

    for key, info in address_map.items():
        done += 1
        result = await geocoder.geocode(info["address"], info["town"])

        if result and result.get("lat") and result.get("lon"):
            geocoded[key] = {
                **info,
                "lat": result["lat"],
                "lon": result["lon"],
            }

        # Progress every 100 addresses
        if done % 100 == 0:
            elapsed = time.time() - start_time
            rate = done / elapsed if elapsed > 0 else 0
            pct = done / total * 100
            print(
                f"    Geocoded {done:,}/{total:,} ({pct:.1f}%) "
                f"| {rate:.1f} addr/sec "
                f"| API: {geocoder.stats['api_calls']} "
                f"| Cache: {geocoder.stats['cache_hits']} "
                f"| Success: {len(geocoded):,}"
            )

    return geocoded


# ── Phase 3: Write to Supabase ─────────────────────────────────────────

async def write_locations(
    db: SupabaseBatch,
    geocoded: Dict[str, Dict],
    dry_run: bool = False,
) -> int:
    """Create document_locations rows for all geocoded permits."""
    total_inserts = 0
    batch: List[dict] = []
    batch_size = 50  # PostgREST batch insert limit
    total_docs = sum(len(g["doc_ids"]) for g in geocoded.values())

    print(f"\n  Phase 3: Writing {total_docs:,} location rows for {len(geocoded):,} unique addresses")

    if dry_run:
        print("  [DRY RUN] Skipping database writes")
        return 0

    processed = 0
    for key, info in geocoded.items():
        for doc_id in info["doc_ids"]:
            row = {
                "id": str(uuid.uuid4()),
                "document_id": doc_id,
                "address": info["address"],
                "latitude": info["lat"],
                "longitude": info["lon"],
                "confidence": 0.85,
                "geocode_source": "nominatim_batch",
            }
            batch.append(row)

            if len(batch) >= batch_size:
                inserted = await db.batch_insert_locations(batch)
                total_inserts += inserted
                processed += len(batch)
                batch = []

                if processed % 500 == 0:
                    print(f"    Inserted {processed:,}/{total_docs:,} location rows...")

    # Flush remaining
    if batch:
        inserted = await db.batch_insert_locations(batch)
        total_inserts += inserted

    return total_inserts


# ── Main ───────────────────────────────────────────────────────────────

async def run_batch(
    town: Optional[str] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    resume: bool = False,
    page_size: int = 1000,
):
    print("=" * 60)
    print("  PARCL INTELLIGENCE — Batch Permit Geocoder")
    print("=" * 60)

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    db = SupabaseBatch()
    geocoder = BatchGeocoder(dry_run=dry_run)

    total_permits = await db.connect()
    scope_count = await db.count_permits(town)

    print(f"  Total permits in DB:  {total_permits:,}")
    print(f"  Scope:                {scope_count:,}" + (f" ({town})" if town else " (all towns)"))
    print(f"  Geocode cache:        {geocoder.cache_size:,} entries")
    if dry_run:
        print("  Mode:                 DRY RUN")
    print()

    start_offset = 0
    if resume:
        cp = load_checkpoint()
        if cp.get("offset", 0) > 0:
            start_offset = cp["offset"]
            print(f"  Resuming from offset {start_offset:,}")

    start_time = time.time()

    try:
        # Phase 1: Scan all permits and extract unique addresses
        print("  Phase 1: Scanning permits and extracting addresses...")
        address_map = await scan_addresses(
            db, town=town, limit=limit, start_offset=start_offset, page_size=page_size,
        )

        total_docs = sum(len(v["doc_ids"]) for v in address_map.values())
        no_address = (limit or scope_count) - total_docs
        print(f"\n  Found {len(address_map):,} unique addresses across {total_docs:,} permits")
        print(f"  Permits without extractable address: {no_address:,}")

        if not address_map:
            print("  Nothing to geocode.")
            await db.disconnect()
            return

        # Phase 2: Geocode unique addresses
        print(f"\n  Phase 2: Geocoding {len(address_map):,} unique addresses...")
        print(f"  (Cached addresses are instant, new ones take ~1 sec each)")
        geocoded = await geocode_addresses(geocoder, address_map)

        print(f"\n  Geocoded: {len(geocoded):,}/{len(address_map):,} addresses")
        failed = len(address_map) - len(geocoded)
        if failed > 0:
            print(f"  Failed:   {failed:,} addresses (no Nominatim result)")

        # Save cache after geocoding
        geocoder.save_cache()

        # Phase 3: Write to Supabase
        inserts = await write_locations(db, geocoded, dry_run=dry_run)

    except KeyboardInterrupt:
        print("\n\n  ⚡ Interrupted! Saving progress...")
        geocoder.save_cache()
    except Exception as e:
        print(f"\n  ✗ Error: {e}")
        geocoder.save_cache()
        raise
    finally:
        geocoder.save_cache()
        await db.disconnect()

    # Summary
    elapsed = time.time() - start_time
    s = geocoder.stats

    print("\n" + "=" * 60)
    print("  BATCH GEOCODE COMPLETE")
    print("=" * 60)
    print(f"  Permits scanned:      {total_docs:,}")
    print(f"  Unique addresses:     {len(address_map):,}")
    print(f"  Successfully geocoded: {len(geocoded):,}")
    print(f"  ─────────────────────────────────")
    print(f"  Nominatim API calls:  {s['api_calls']:,}")
    print(f"  Cache hits:           {s['cache_hits']:,}")
    print(f"  Geocode success:      {s['geocode_success']:,}")
    print(f"  Geocode failed:       {s['geocode_failed']:,}")
    if not dry_run:
        print(f"  DB rows inserted:     {inserts:,}")
    print(f"  ─────────────────────────────────")
    print(f"  Elapsed time:         {elapsed:.1f}s ({elapsed/60:.1f}m)")
    if s['api_calls'] > 0:
        print(f"  Avg geocode time:     {elapsed/max(1, s['api_calls']):.2f}s")
    print(f"  Cache file:           {CACHE_FILE}")
    print("=" * 60)


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Batch geocode 125K+ permits in Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/batch_geocode_permits.py --dry-run --limit 20    # Preview 20
  python3 scripts/batch_geocode_permits.py --town somerville --limit 500  # 500 Somerville
  python3 scripts/batch_geocode_permits.py --town cambridge        # All Cambridge
  python3 scripts/batch_geocode_permits.py --resume                # Resume from checkpoint
  python3 scripts/batch_geocode_permits.py                         # Full batch (all 125K)
        """,
    )
    parser.add_argument("--town", type=str, help="Geocode a specific town only")
    parser.add_argument("--limit", type=int, help="Max permits to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview without DB writes")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--page-size", type=int, default=1000, help="Supabase fetch page size")

    args = parser.parse_args()
    asyncio.run(run_batch(
        town=args.town, limit=args.limit, dry_run=args.dry_run,
        resume=args.resume, page_size=args.page_size,
    ))


if __name__ == "__main__":
    main()
