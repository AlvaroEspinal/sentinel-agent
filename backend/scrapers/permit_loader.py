"""
Permit Data Loader for Parcl Intelligence.

Connects to Supabase PostgREST API to query the municipal-intel permit database
(125K+ real permits across 351 Massachusetts municipalities).

Falls back to local JSON demo data when Supabase is not available.

The municipal-intel system uses a three-table schema:
  documents (source_type='permit') -> document_metadata -> document_locations

This loader JOINs them via PostgREST embedded resources and flattens
the result into the flat permit format the Parcl API expects.
"""

import json
import math
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────────────────


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _flatten_permit(doc: dict) -> dict:
    """
    Transform a municipal-intel 3-table JOIN result into a flat permit dict.

    Input (from PostgREST):
    {
        "id": "uuid",
        "source_id": "BRK-2024-0001",
        "town_id": "brookline",
        "content": "Building permit for...",
        "created_at": "2024-06-15T...",
        "document_metadata": {"permit_number": "...", ...} or null,
        "document_locations": [{"address": "...", "latitude": 42.3, ...}] or []
    }

    Output:
    {
        "id": "uuid", "permit_number": "BRK-2024-0001", "permit_type": "Building",
        "status": "APPROVED", "description": "...", "address": "...",
        "town": "brookline", "latitude": 42.3, "longitude": -71.1, ...
    }
    """
    # document_metadata is 1-to-1 (single object or null)
    meta = doc.get("document_metadata") or {}
    if isinstance(meta, list):
        meta = meta[0] if meta else {}

    # document_locations is 1-to-many (array)
    locs = doc.get("document_locations") or []
    loc = locs[0] if locs else {}

    # Extract raw_data safely
    raw = meta.get("raw_data") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = {}

    content = doc.get("content", "")

    return {
        "id": doc.get("id", ""),
        "permit_number": meta.get("permit_number") or doc.get("source_id", ""),
        "permit_type": (meta.get("permit_type") or "Building").title(),
        "status": (meta.get("permit_status") or "FILED").upper(),
        "description": meta.get("project_description") or content[:500],
        "address": loc.get("address") or raw.get("address", ""),
        "town": doc.get("town_id", "unknown"),
        "latitude": loc.get("latitude") or raw.get("latitude", 0) or 0,
        "longitude": loc.get("longitude") or raw.get("longitude", 0) or 0,
        "estimated_value": meta.get("permit_value"),
        "applicant_name": meta.get("applicant_name") or raw.get("applicant_name"),
        "contractor_name": meta.get("contractor_name") or raw.get("contractor_name"),
        "filed_date": raw.get("filed_date"),
        "issued_date": raw.get("issued_date"),
        "completed_date": raw.get("completed_date"),
        "source_system": raw.get("source_system", "municipal-intel"),
        "source_id": doc.get("source_id"),
        "raw_data": raw,
        "created_at": doc.get("created_at"),
    }


# ─── PermitDataLoader ──────────────────────────────────────────────────────


class PermitDataLoader:
    """
    Loads and searches permit data.

    Primary:  Supabase PostgREST API (125K+ real permits)
    Fallback: Local JSON files (15 demo permits)
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        supabase: Any = None,
    ):
        self.data_dir = data_dir or Path(__file__).parent.parent / "data_cache" / "permits"
        self._supabase = supabase
        self._use_supabase = False
        self._permit_count = 0

        # Town cache
        self._town_cache: list[dict] = []
        self._town_cache_time: float = 0

        # Fallback: in-memory demo permits
        self.permits: list[dict] = []
        self._loaded = False

    # ── Load ────────────────────────────────────────────────────────────

    async def load(self):
        """Load permit data — try Supabase first, fall back to JSON."""
        # Try Supabase
        if self._supabase and self._supabase.is_connected:
            try:
                count = await self._supabase.count(
                    "documents",
                    filters={"source_type": "eq.permit"},
                )
                if count > 0:
                    self._use_supabase = True
                    self._permit_count = count
                    self._loaded = True
                    logger.info(
                        "Supabase connected: %s permits available via REST API",
                        f"{count:,}",
                    )
                    return
            except Exception as e:
                logger.warning("Supabase query failed, falling back to JSON: %s", e)

        # Fallback: load from JSON
        await self._load_json()

    async def _load_json(self):
        """Load permits from local JSON files (demo mode)."""
        self.permits = []
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._seed_demo_permits()
            self._loaded = True
            return

        for json_file in self.data_dir.glob("*.json"):
            try:
                with open(json_file) as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.permits.extend(data)
                elif isinstance(data, dict) and "permits" in data:
                    self.permits.extend(data["permits"])
            except Exception as e:
                logger.error("Failed to load %s: %s", json_file, e)

        if not self.permits:
            self._seed_demo_permits()

        self._permit_count = len(self.permits)
        self._loaded = True
        logger.info("Loaded %d permits from JSON (demo mode)", len(self.permits))

    # ── Search ──────────────────────────────────────────────────────────

    async def search(
        self,
        query: Optional[str] = None,
        address: Optional[str] = None,
        town: Optional[str] = None,
        permit_type: Optional[str] = None,
        status: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: float = 1.0,
        filed_after: Optional[str] = None,
        min_value: Optional[float] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search permits with flexible filtering."""
        if not self._loaded:
            await self.load()

        if self._use_supabase:
            return await self._search_supabase(
                query=query, address=address, town=town,
                permit_type=permit_type, status=status,
                latitude=latitude, longitude=longitude,
                radius_km=radius_km, filed_after=filed_after,
                min_value=min_value, limit=limit,
            )
        return await self._search_local(
            query=query, address=address, town=town,
            permit_type=permit_type, status=status,
            latitude=latitude, longitude=longitude,
            radius_km=radius_km, filed_after=filed_after,
            min_value=min_value, limit=limit,
        )

    async def _search_supabase(
        self,
        query: Optional[str] = None,
        address: Optional[str] = None,
        town: Optional[str] = None,
        permit_type: Optional[str] = None,
        status: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: float = 1.0,
        filed_after: Optional[str] = None,
        min_value: Optional[float] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search permits via Supabase PostgREST API.

        Improved search strategy:
        1. If an address-like pattern is detected, search by address in
           document_locations (via inner join) AND content (via or filter).
        2. If query is a recognizable town name, search by town_id.
        3. For general queries, search content with individual key words
           using PostgREST ``or`` filter for broader matching.
        4. Falls back to the original full-query ilike on content.
        """
        import re as _re

        filters: dict[str, str] = {"source_type": "eq.permit"}

        # Use !inner join when filtering on metadata fields (INNER JOIN)
        need_inner_meta = bool(permit_type or status or min_value)
        meta_join = "document_metadata!inner(*)" if need_inner_meta else "document_metadata(*)"

        # Determine if we should inner-join document_locations for address search
        need_inner_loc = False

        # Town filter
        if town:
            filters["town_id"] = "eq.{}".format(town.lower())

        # -- Detect address pattern in query ---------------------------------
        _addr_pattern = _re.compile(
            r'\d+\s+[\w\s]+(st|street|ave|avenue|rd|road|dr|drive|way|blvd|pl|ct|ln|lane)',
            _re.I,
        )

        # Known MA town names (lowercase) for town extraction
        _known_towns = {
            "boston", "cambridge", "somerville", "brookline", "newton",
            "quincy", "watertown", "arlington", "medford", "malden",
            "chelsea", "revere", "waltham", "natick", "needham",
            "wellesley", "framingham", "worcester", "springfield",
            "braintree", "weymouth", "milton", "dedham", "norwood",
        }

        if query:
            safe_q = query.replace("%", "").replace("*", "")

            # Check if query looks like an address
            addr_match = _addr_pattern.search(safe_q)

            if addr_match:
                # Strategy A: Address search — extract street address and search content
                # Note: PostgREST does not support or-filter on embedded resource columns,
                # so we search the content field directly (addresses are embedded there).
                addr_term = addr_match.group(0).strip()
                safe_addr = addr_term.replace(",", "").strip()
                # Also check if there's a town name to filter by
                _q_lower = safe_q.lower()
                for t in _known_towns:
                    if t in _q_lower:
                        filters["town_id"] = "eq.{}".format(t)
                        break
                filters["content"] = "ilike.*{}*".format(safe_addr)

            elif not town:
                # Check if query contains a town name
                query_lower = safe_q.lower()
                matched_town = None
                for t in _known_towns:
                    if t in query_lower:
                        matched_town = t
                        break

                if matched_town:
                    # Strategy B: Town-based search
                    filters["town_id"] = "eq.{}".format(matched_town)
                    # Also search content for remaining terms
                    remaining = query_lower.replace(matched_town, "").strip()
                    if remaining and len(remaining) > 2:
                        safe_remaining = remaining.replace(",", "").strip()
                        filters["content"] = "ilike.*{}*".format(safe_remaining)
                else:
                    # Strategy C: Split query into individual key words for broader matching
                    stop_words = {
                        "what", "are", "the", "near", "in", "at", "for", "is",
                        "any", "there", "how", "many", "about", "can", "you",
                        "tell", "me", "should", "know", "do", "does", "have",
                        "has", "been", "this", "that", "with", "from", "on",
                        "of", "and", "or", "a", "an", "to", "my", "all",
                        "show", "find", "get", "i",
                    }
                    terms = [
                        w for w in safe_q.lower().split()
                        if w not in stop_words and len(w) > 2
                    ]

                    if terms:
                        # Build an ``or`` filter so any term matching content hits
                        or_clauses = ",".join(
                            "content.ilike.*{}*".format(t) for t in terms[:4]
                        )
                        filters["or"] = "({})".format(or_clauses)
                    else:
                        # Fall back to full query ilike
                        filters["content"] = "ilike.*{}*".format(safe_q)

        # Address search via content (when address param is provided directly)
        if address and not query:
            safe_addr = address.replace("%", "").replace("*", "").replace(",", "").strip()
            filters["content"] = "ilike.*{}*".format(safe_addr)

        # Metadata filters (require !inner join set above)
        if permit_type:
            filters["document_metadata.permit_type"] = "ilike.{}".format(permit_type)
        if status:
            filters["document_metadata.permit_status"] = "ilike.{}".format(status)
        if min_value is not None:
            filters["document_metadata.permit_value"] = "gte.{}".format(min_value)

        # Build select with appropriate join types
        if need_inner_loc:
            loc_join = "document_locations!inner(*)"
        else:
            loc_join = "document_locations(*)"
        select = "id,source_id,town_id,content,created_at,{},{}".format(meta_join, loc_join)

        try:
            docs = await self._supabase.fetch(
                table="documents",
                select=select,
                filters=filters,
                order="created_at.desc",
                limit=limit,
            )

            # Flatten 3-table result to flat permit dicts
            results = [_flatten_permit(doc) for doc in docs]

            # If inner-join on locations returned nothing, retry without it
            if not results and need_inner_loc:
                select_fallback = "id,source_id,town_id,content,created_at,{},document_locations(*)".format(meta_join)
                filters_fallback = dict(filters)
                if "or" in filters_fallback:
                    del filters_fallback["or"]

                # Build smarter fallback: use just address part OR individual terms
                _fallback_q = query or address or ""
                _fallback_q = _fallback_q.replace("%", "").replace("*", "").replace(",", "").strip()

                # Extract just the street address (remove town names)
                _fb_lower = _fallback_q.lower()
                for t in _known_towns:
                    _fb_lower = _fb_lower.replace(t, "").strip()
                _fb_addr = _fb_lower.strip()

                if _fb_addr and len(_fb_addr) > 2:
                    # Try content search with address-only (town removed)
                    filters_fallback["content"] = "ilike.*{}*".format(_fb_addr)
                elif _fallback_q:
                    filters_fallback["content"] = "ilike.*{}*".format(_fallback_q)

                docs = await self._supabase.fetch(
                    table="documents",
                    select=select_fallback,
                    filters=filters_fallback,
                    order="created_at.desc",
                    limit=limit,
                )
                results = [_flatten_permit(doc) for doc in docs]

                # If still nothing, try splitting into individual key terms
                if not results and _fallback_q:
                    _terms = [w for w in _fallback_q.lower().split()
                              if w not in _known_towns and len(w) > 2]
                    if _terms:
                        or_clauses = ",".join("content.ilike.*{}*".format(t) for t in _terms[:4])
                        filters_terms = {"source_type": "eq.permit", "or": "({})".format(or_clauses)}
                        select_simple = "id,source_id,town_id,content,created_at,document_metadata(*),document_locations(*)"
                        docs = await self._supabase.fetch(
                            table="documents",
                            select=select_simple,
                            filters=filters_terms,
                            order="created_at.desc",
                            limit=limit,
                        )
                        results = [_flatten_permit(doc) for doc in docs]

            # Apply geo filter client-side (document_locations is sparse,
            # many coordinates live in raw_data or are absent)
            if latitude is not None and longitude is not None:
                filtered = []
                for p in results:
                    p_lat = p.get("latitude", 0)
                    p_lon = p.get("longitude", 0)
                    if p_lat and p_lon:
                        dist = haversine_km(latitude, longitude, p_lat, p_lon)
                        if dist <= radius_km:
                            p["distance_km"] = round(dist, 2)
                            filtered.append(p)
                results = sorted(filtered, key=lambda x: x.get("distance_km", 999))

            return results

        except Exception as e:
            logger.error("Supabase search failed: %s", e)
            # If the enhanced query failed (e.g. or filter not supported),
            # fall back to simple content ilike
            try:
                fallback_filters: dict[str, str] = {"source_type": "eq.permit"}
                if town:
                    fallback_filters["town_id"] = "eq.{}".format(town.lower())
                if query:
                    safe_q = query.replace("%", "").replace("*", "")
                    fallback_filters["content"] = "ilike.*{}*".format(safe_q)
                elif address:
                    safe_addr = address.replace("%", "").replace("*", "").replace(",", "").strip()
                    fallback_filters["content"] = "ilike.*{}*".format(safe_addr)

                simple_select = "id,source_id,town_id,content,created_at,document_metadata(*),document_locations(*)"
                docs = await self._supabase.fetch(
                    table="documents",
                    select=simple_select,
                    filters=fallback_filters,
                    order="created_at.desc",
                    limit=limit,
                )
                return [_flatten_permit(doc) for doc in docs]
            except Exception as e2:
                logger.error("Supabase fallback search also failed: %s", e2)
                return []

    async def _search_local(
        self,
        query: Optional[str] = None,
        address: Optional[str] = None,
        town: Optional[str] = None,
        permit_type: Optional[str] = None,
        status: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: float = 1.0,
        filed_after: Optional[str] = None,
        min_value: Optional[float] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search in-memory demo permits (original logic)."""
        results = []
        for p in self.permits:
            # Text search
            if query:
                words = query.lower().split()
                searchable = (
                    f"{p.get('description', '')} {p.get('address', '')} "
                    f"{p.get('applicant_name', '')} {p.get('permit_type', '')} "
                    f"{p.get('town', '')}"
                ).lower()
                if not any(w in searchable for w in words):
                    continue

            if address and address.lower() not in p.get("address", "").lower():
                continue
            if town and town.lower() != p.get("town", "").lower():
                continue
            if permit_type and permit_type.lower() != p.get("permit_type", "").lower():
                continue
            if status and status.upper() != p.get("status", "").upper():
                continue

            # Geo filter
            if latitude is not None and longitude is not None:
                p_lat = p.get("latitude")
                p_lon = p.get("longitude")
                if p_lat and p_lon:
                    dist = haversine_km(latitude, longitude, p_lat, p_lon)
                    if dist > radius_km:
                        continue
                    p["distance_km"] = round(dist, 2)

            if filed_after:
                filed = p.get("filed_date", "")
                if filed and filed < filed_after:
                    continue

            if min_value is not None:
                val = p.get("estimated_value", 0)
                if val is None or val < min_value:
                    continue

            results.append(p)

        if latitude is not None:
            results.sort(key=lambda x: x.get("distance_km", 999))
        else:
            results.sort(key=lambda x: x.get("filed_date", ""), reverse=True)

        return results[:limit]

    # ── Convenience methods ─────────────────────────────────────────────

    async def get_nearby(
        self, latitude: float, longitude: float, radius_km: float = 1.0, limit: int = 20
    ) -> list[dict]:
        """Get permits near a location."""
        return await self.search(
            latitude=latitude, longitude=longitude, radius_km=radius_km, limit=limit
        )

    async def get_by_town(self, town: str, limit: int = 50) -> list[dict]:
        """Get permits for a specific town."""
        return await self.search(town=town, limit=limit)

    async def get_towns(self) -> list[dict]:
        """Get list of available towns with permit counts."""
        if not self._loaded:
            await self.load()

        if self._use_supabase:
            return await self._get_towns_supabase()
        return self._get_towns_local()

    async def _get_towns_supabase(self) -> list[dict]:
        """Get towns from Supabase with permit counts."""
        now = time.time()

        # Return cache if fresh (5 minute TTL)
        if self._town_cache and (now - self._town_cache_time) < 300:
            return self._town_cache

        try:
            # 1) Fetch all towns from towns table
            towns_raw = await self._supabase.fetch(
                table="towns",
                select="id,name,state,county,active",
                order="name.asc",
                limit=400,
            )

            # 2) Get permit counts for ALL towns in parallel
            #    Each count query is very fast (reads Content-Range header only).
            #    With 351 towns in batches of 20, this takes ~2-3 seconds total.
            town_counts: dict[str, int] = {}

            async def _count_town(tid: str) -> tuple[str, int]:
                try:
                    c = await self._supabase.count(
                        "documents",
                        filters={"source_type": "eq.permit", "town_id": f"eq.{tid}"},
                    )
                    return (tid, c)
                except Exception:
                    return (tid, 0)

            # Run counts in parallel (batches of 20)
            town_ids = [t.get("id", "") for t in towns_raw if t.get("id")]
            for i in range(0, len(town_ids), 20):
                batch = town_ids[i : i + 20]
                results = await asyncio.gather(*[_count_town(t) for t in batch])
                for tid, cnt in results:
                    if cnt > 0:
                        town_counts[tid] = cnt

            # 3) Build result list
            result = []
            for t in towns_raw:
                tid = t.get("id", "")
                result.append({
                    "id": tid,
                    "name": t.get("name", tid.title()),
                    "state": t.get("state", "MA"),
                    "county": t.get("county"),
                    "permit_count": town_counts.get(tid, 0),
                    "active": t.get("active", True),
                })

            # Sort: towns with permits first, then alphabetical
            result.sort(key=lambda x: (-x["permit_count"], x["name"]))

            self._town_cache = result
            self._town_cache_time = now
            logger.info(
                "Towns cached: %d total, %d with permits",
                len(result), len(town_counts),
            )
            return result

        except Exception as e:
            logger.error("Supabase towns query failed: %s", e)
            return []

    def _get_towns_local(self) -> list[dict]:
        """Get towns from in-memory data."""
        town_counts: dict[str, int] = {}
        for p in self.permits:
            t = p.get("town", "unknown")
            town_counts[t] = town_counts.get(t, 0) + 1
        return [
            {"id": t, "name": t.title(), "permit_count": c}
            for t, c in sorted(town_counts.items())
        ]

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return self._permit_count

    @property
    def is_supabase(self) -> bool:
        return self._use_supabase

    # ── Demo data seed ──────────────────────────────────────────────────

    def _seed_demo_permits(self):
        """Seed demo permit data for Boston/Brookline/Cambridge/Newton."""
        demo_permits = [
            # Brookline
            {"id": "BRK-2024-0001", "permit_number": "BRK-2024-0001", "permit_type": "Building", "status": "ISSUED", "description": "Kitchen renovation and addition of 200 sq ft sunroom", "address": "45 Harvard St, Brookline, MA 02445", "town": "brookline", "latitude": 42.3419, "longitude": -71.1219, "estimated_value": 85000, "applicant_name": "John Smith", "filed_date": "2024-06-15", "source_system": "accela"},
            {"id": "BRK-2024-0002", "permit_number": "BRK-2024-0002", "permit_type": "Demolition", "status": "APPROVED", "description": "Full demolition of existing single-family home for new construction", "address": "122 Beacon St, Brookline, MA 02446", "town": "brookline", "latitude": 42.3481, "longitude": -71.1175, "estimated_value": 45000, "applicant_name": "ABC Developers LLC", "filed_date": "2024-07-20", "source_system": "accela"},
            {"id": "BRK-2024-0003", "permit_number": "BRK-2024-0003", "permit_type": "Building", "status": "FILED", "description": "New 12-unit residential building with underground parking", "address": "300 Harvard St, Brookline, MA 02446", "town": "brookline", "latitude": 42.3403, "longitude": -71.1282, "estimated_value": 4500000, "applicant_name": "Brookline Development Partners", "filed_date": "2024-09-01", "source_system": "accela"},
            {"id": "BRK-2024-0004", "permit_number": "BRK-2024-0004", "permit_type": "Electrical", "status": "COMPLETED", "description": "Solar panel installation - 24 panel array, 8.4kW system", "address": "67 Walnut St, Brookline, MA 02445", "town": "brookline", "latitude": 42.3382, "longitude": -71.1230, "estimated_value": 22000, "applicant_name": "SunRun Inc", "filed_date": "2024-03-10", "source_system": "accela"},
            # Cambridge
            {"id": "CAM-2024-0001", "permit_number": "CAM-2024-0001", "permit_type": "Building", "status": "ISSUED", "description": "Lab space conversion - 50,000 sq ft biotech facility", "address": "100 Binney St, Cambridge, MA 02142", "town": "cambridge", "latitude": 42.3662, "longitude": -71.0827, "estimated_value": 12000000, "applicant_name": "Alexandria Real Estate", "filed_date": "2024-04-15", "source_system": "opengov"},
            {"id": "CAM-2024-0002", "permit_number": "CAM-2024-0002", "permit_type": "Building", "status": "IN_PROGRESS", "description": "Mixed-use development - 200 residential units + retail ground floor", "address": "500 Mass Ave, Cambridge, MA 02139", "town": "cambridge", "latitude": 42.3651, "longitude": -71.1035, "estimated_value": 45000000, "applicant_name": "Twining Properties", "filed_date": "2024-01-20", "source_system": "opengov"},
            {"id": "CAM-2024-0003", "permit_number": "CAM-2024-0003", "permit_type": "Plumbing", "status": "COMPLETED", "description": "Complete bathroom renovation - 3 bathrooms", "address": "22 Ellery St, Cambridge, MA 02138", "town": "cambridge", "latitude": 42.3729, "longitude": -71.1196, "estimated_value": 18000, "applicant_name": "Maria Garcia", "filed_date": "2024-05-03", "source_system": "opengov"},
            # Newton
            {"id": "NEW-2024-0001", "permit_number": "NEW-2024-0001", "permit_type": "Building", "status": "APPROVED", "description": "Two-story addition to existing colonial - 800 sq ft", "address": "155 Woodward St, Newton, MA 02461", "town": "newton", "latitude": 42.3310, "longitude": -71.2085, "estimated_value": 350000, "applicant_name": "Robert Chen", "filed_date": "2024-08-10", "source_system": "accela"},
            {"id": "NEW-2024-0002", "permit_number": "NEW-2024-0002", "permit_type": "Building", "status": "FILED", "description": "New single-family home - 4BR 3BA 3200 sq ft", "address": "88 Lake Ave, Newton, MA 02459", "town": "newton", "latitude": 42.3280, "longitude": -71.1953, "estimated_value": 1200000, "applicant_name": "Toll Brothers", "filed_date": "2024-10-01", "source_system": "accela"},
            # Boston
            {"id": "BOS-2024-0001", "permit_number": "BOS-2024-0001", "permit_type": "Building", "status": "ISSUED", "description": "Seaport mixed-use tower - 400 units, 30 stories, retail + office", "address": "One Congress St, Boston, MA 02210", "town": "boston", "latitude": 42.3551, "longitude": -71.0517, "estimated_value": 180000000, "applicant_name": "Related Beal", "filed_date": "2024-02-14", "source_system": "boston"},
            {"id": "BOS-2024-0002", "permit_number": "BOS-2024-0002", "permit_type": "Building", "status": "IN_PROGRESS", "description": "South Boston triple-decker gut renovation to luxury condos", "address": "456 E Broadway, Boston, MA 02127", "town": "boston", "latitude": 42.3371, "longitude": -71.0371, "estimated_value": 950000, "applicant_name": "Southie Condos LLC", "filed_date": "2024-05-20", "source_system": "boston"},
            {"id": "BOS-2024-0003", "permit_number": "BOS-2024-0003", "permit_type": "Building", "status": "FILED", "description": "Dorchester affordable housing - 85 units, mixed income", "address": "200 Hancock St, Boston, MA 02125", "town": "boston", "latitude": 42.3130, "longitude": -71.0560, "estimated_value": 32000000, "applicant_name": "Codman Square NDC", "filed_date": "2024-11-01", "source_system": "boston"},
            {"id": "BOS-2024-0004", "permit_number": "BOS-2024-0004", "permit_type": "Mechanical", "status": "APPROVED", "description": "HVAC system replacement - commercial office building", "address": "100 Federal St, Boston, MA 02110", "town": "boston", "latitude": 42.3545, "longitude": -71.0552, "estimated_value": 420000, "applicant_name": "Boston Properties Inc", "filed_date": "2024-07-15", "source_system": "boston"},
            {"id": "BOS-2024-0005", "permit_number": "BOS-2024-0005", "permit_type": "Building", "status": "ISSUED", "description": "Fenway apartment renovation - convert 2BR to 3BR", "address": "65 Park Dr, Boston, MA 02215", "town": "boston", "latitude": 42.3422, "longitude": -71.0969, "estimated_value": 75000, "applicant_name": "Sarah Kim", "filed_date": "2024-08-25", "source_system": "boston"},
        ]
        self.permits = demo_permits
        self._permit_count = len(demo_permits)
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.data_dir / "demo_permits.json", "w") as f:
                json.dump(demo_permits, f, indent=2)
        except Exception as e:
            logger.error("Failed to save demo permits: %s", e)
