"""FastAPI routes - REST endpoints and WebSocket handler."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Query
from loguru import logger

# These will be injected by main.py at startup
_state: dict = {}

router = APIRouter()


def _get(key: str):
    return _state.get(key)


# ──────────────────────────────────────────────
# System endpoints
# ──────────────────────────────────────────────

@router.get("/health")
async def health():
    scheduler = _get("scrape_scheduler")
    scheduler_alive = scheduler.is_alive if scheduler else False
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "permit_loader": _get("permit_loader") is not None,
            "permit_search": _get("permit_search") is not None,
            "supabase": _get("supabase_client") is not None,
            "scrape_scheduler": scheduler is not None,
            "scrape_scheduler_alive": scheduler_alive,
            "firecrawl": _get("firecrawl_client") is not None,
            "llm_extractor": _get("llm_extractor") is not None,
        },
    }

# ─── Geocoding Endpoint ──────────────────────────────────────────────────────

@router.get("/geocode")
async def geocode_address(
    address: str = Query(..., min_length=3, description="Address to geocode"),
):
    """Forward geocode an address to lat/lon using Nominatim (OpenStreetMap)."""
    from scrapers.connectors.nominatim_geocoder import geocode
    result = await geocode(address)
    return result


# ─── FEMA Flood Zone Endpoint ────────────────────────────────────────────────

@router.get("/flood-zone")
async def get_flood_zone(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Get FEMA flood zone designation for a location."""
    from scrapers.connectors.fema_flood import get_flood_zone
    result = await get_flood_zone(lat, lon)
    return result


# ─── MassGIS Parcel Endpoint ────────────────────────────────────────────────

@router.get("/parcels")
async def get_parcels(
    lat: Optional[float] = Query(None, description="Latitude for spatial query"),
    lon: Optional[float] = Query(None, description="Longitude for spatial query"),
    town: Optional[str] = Query(None, description="Town name"),
    address: Optional[str] = Query(None, description="Street address"),
):
    """Get MassGIS property tax parcel info by location or address."""
    from scrapers.connectors.massgis_parcels import get_parcel_by_point, search_parcels
    if lat is not None and lon is not None:
        result = await get_parcel_by_point(lat, lon)
        return result
    elif town and address:
        results = await search_parcels(town, address)
        return {"parcels": results, "total": len(results)}
    else:
        raise HTTPException(status_code=400, detail="Provide lat/lon or town+address")


# ─── Wetlands Endpoint ────────────────────────────────────────────────────────

@router.get("/gis/wetlands")
async def get_wetlands(
    bbox: str = Query(..., description="Bounding box 'xmin,ymin,xmax,ymax'")
):
    """Get freshwater wetlands polygons within a bounding box."""
    from scrapers.connectors.massgis_wetlands import MassGISWetlandsClient
    
    client = MassGISWetlandsClient()
    result = await client.get_wetlands_in_bbox(bbox)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to fetch wetlands data from MassGIS")
    return result


# ─── Conservation/Open Space Endpoint ───────────────────────────────────────

@router.get("/gis/conservation")
async def get_conservation(
    bbox: str = Query(..., description="Bounding box 'xmin,ymin,xmax,ymax'")
):
    """Get conservation restrictions and open space polygons within a bounding box."""
    from scrapers.connectors.massgis_openspace import MassGISOpenSpaceClient
    
    client = MassGISOpenSpaceClient()
    result = await client.get_openspace_in_bbox(bbox)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to fetch conservation data from MassGIS")
    return result


# ─── Zoning Endpoint ────────────────────────────────────────────────────────

@router.get("/zoning")
async def get_zoning(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Get zoning district info for a location from the National Zoning Atlas."""
    from scrapers.connectors.zoning_atlas import get_zoning
    result = await get_zoning(lat, lon)
    return result


# ─── MEPA Environmental Filings Endpoint ───────────────────────────────────────

@router.get("/gis/mepa")
async def get_mepa_filings():
    """Get recent MEPA environmental filings as GeoJSON points."""
    supabase = _get("supabase_client")
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected")

    try:
        # Fetch the latest 100 MEPA records
        res = await supabase.fetch(
            table="municipal_documents",
            select="id,title,content_text,source_url,meeting_date,mentions",
            filters={"doc_type": "eq.MEPA Environmental Monitor"},
            order="meeting_date.desc",
            limit=100
        )
        if not res:
            return {"type": "FeatureCollection", "features": []}

        # Dynamically geocode if needed
        from scrapers.connectors.nominatim_geocoder import geocode
        features = []
        for doc in res:
            mentions = doc.get("mentions") or {}
            addr = mentions.get("address")
            if not addr:
                continue
            
            geo = await geocode(addr + ", MA")
            if not geo.get("lat") or not geo.get("lon"):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [geo["lon"], geo["lat"]]
                },
                "properties": {
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "status": mentions.get("status", "Pending"),
                    "address": addr,
                    "url": doc.get("source_url"),
                    "content_text": doc.get("content_text")
                }
            })
        
        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        logger.error(f"Error fetching MEPA data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Tax Delinquency Endpoint ────────────────────────────────────────────────

@router.get("/gis/tax-delinquency")
async def get_tax_delinquency():
    """Get recent tax delinquent properties as GeoJSON points."""
    supabase = _get("supabase_client")
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected")

    try:
        res = await supabase.fetch(
            table="municipal_documents",
            select="id,title,content_text,source_url,meeting_date,mentions",
            filters={"doc_type": "eq.Tax Collector"},
            order="meeting_date.desc",
            limit=100
        )
        if not res:
            return {"type": "FeatureCollection", "features": []}

        from scrapers.connectors.nominatim_geocoder import geocode
        features = []
        for doc in res:
            mentions = doc.get("mentions") or {}
            addr = mentions.get("address")
            if not addr:
                continue
            
            geo = await geocode(addr + ", MA")
            if not geo.get("lat") or not geo.get("lon"):
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [geo["lon"], geo["lat"]]
                },
                "properties": {
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "status": mentions.get("status", "Delinquent"),
                    "address": addr,
                    "url": doc.get("source_url"),
                    "content_text": doc.get("content_text")
                }
            })
        
        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        logger.error(f"Error fetching Tax Delinquency data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Land Records Endpoint ──────────────────────────────────────────────────

@router.get("/land-records")
async def get_land_records(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Get ownership and deed records from MassGIS assessor data."""
    from scrapers.connectors.mass_land_records import get_ownership_records
    return await get_ownership_records(lat, lon)


# ─── Comparable Sales Endpoint ──────────────────────────────────────────────

@router.get("/comps")
async def get_comps(
    lat: float = Query(..., description="Latitude of subject property"),
    lon: float = Query(..., description="Longitude of subject property"),
    radius_m: float = Query(500.0, ge=50, le=5000, description="Search radius in meters"),
    use_code: Optional[str] = Query(None, description="Filter by property use code"),
    subject_loc_id: Optional[str] = Query(None, description="LOC_ID of subject parcel to exclude"),
    max_results: int = Query(20, ge=1, le=50, description="Max comps to return"),
):
    """Get comparable sales near a location from MassGIS parcel data."""
    from scrapers.connectors.massgis_comps import get_comparable_sales
    return await get_comparable_sales(
        lat=lat, lon=lon,
        radius_m=radius_m,
        use_code=use_code,
        subject_loc_id=subject_loc_id,
        max_results=max_results,
    )


# ─── Property Endpoints ───────────────────────────────────────────────────────

@router.get("/properties/search")
async def search_properties(
    request: Request,
    q: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: float = 5.0,
    limit: int = 20,
):
    """Search for properties by address, location, or text query."""
    permit_loader = _get("permit_loader")

    if not permit_loader or not permit_loader.is_supabase:
        # Fall back to demo properties when Supabase is not connected
        return _demo_properties(q, address, city, limit)

    search_query = q or address or ""
    if not search_query and not (lat and lon):
        return {"properties": [], "total": 0}

    results = []

    # Search permits by address text
    if search_query:
        results = await permit_loader.search(
            query=search_query,
            address=search_query,
            town=city.lower() if city else None,
            limit=limit * 3,  # fetch extra for dedup
        )

    # Also try nearby search if coords provided and text search found nothing
    if not results and lat and lon:
        results = await permit_loader.get_nearby(lat, lon, radius_km=radius_km, limit=limit * 3)

    # Extract address from description field if address is empty
    import re as _re
    def _extract_address(permit: dict) -> str:
        addr = (permit.get("address") or "").strip()
        if addr:
            return addr
        # Try extracting from description: "Address: 122 Heath St"
        desc = permit.get("description") or ""
        m = _re.search(r'Address:\s*([^|]+)', desc)
        if m:
            return m.group(1).strip()
        return ""

    # Aggregate permits by address into pseudo-property objects
    address_map: dict[str, dict] = {}
    for permit in results:
        addr = _extract_address(permit)
        if not addr:
            continue
        key = addr.lower()
        if key not in address_map:
            town = permit.get("town_id") or permit.get("town") or ""
            address_map[key] = {
                "id": f"prop-{permit.get('id', '')}",
                "address": addr,
                "city": town.replace("_", " ").title() if town else "MA",
                "state": "MA",
                "zip_code": "",
                "latitude": permit.get("latitude", 0),
                "longitude": permit.get("longitude", 0),
                "property_type": "OTHER",
                "nearby_permits_count": 0,
            }
        address_map[key]["nearby_permits_count"] += 1

    # Geocode entries that have 0,0 coordinates
    from scrapers.connectors.nominatim_geocoder import geocode as _geocode_addr
    entries_needing_geocode = [
        (k, v) for k, v in address_map.items()
        if v.get("latitude", 0) == 0 and v.get("longitude", 0) == 0
    ]
    for key, entry in entries_needing_geocode[:5]:  # Max 5 geocode calls per search
        try:
            geo = await _geocode_addr(f"{entry['address']}, {entry['city']}, MA")
            if geo.get("lat") and geo.get("lon"):
                entry["latitude"] = geo["lat"]
                entry["longitude"] = geo["lon"]
        except Exception as e:
            logger.debug("Geocode failed for %s: %s", entry["address"], e)

    properties = list(address_map.values())[:limit]
    return {"properties": properties, "total": len(properties)}


def _demo_properties(q: Optional[str] = None, address: Optional[str] = None, city: Optional[str] = None, limit: int = 20):
    """Return hardcoded demo properties when Supabase is not connected."""
    from models.property import Property

    demo_properties = [
        Property(
            address="45 Harvard St, Brookline, MA 02445",
            city="Brookline", state="MA", zip_code="02445",
            latitude=42.3419, longitude=-71.1219,
            property_type="SINGLE_FAMILY",
            year_built=1920, bedrooms=4, bathrooms=2.5,
            living_area_sqft=2400, lot_size_sqft=5200,
            tax_assessment=985000, estimated_value=1150000,
            nearby_permits_count=3,
        ),
        Property(
            address="100 Binney St, Cambridge, MA 02142",
            city="Cambridge", state="MA", zip_code="02142",
            latitude=42.3662, longitude=-71.0827,
            property_type="COMMERCIAL",
            year_built=2018, living_area_sqft=50000,
            tax_assessment=25000000, estimated_value=30000000,
            nearby_permits_count=8,
        ),
        Property(
            address="456 E Broadway, Boston, MA 02127",
            city="Boston", state="MA", zip_code="02127",
            latitude=42.3371, longitude=-71.0371,
            property_type="MULTI_FAMILY",
            year_built=1905, bedrooms=9, bathrooms=3,
            living_area_sqft=3600, lot_size_sqft=2800,
            tax_assessment=720000, estimated_value=950000,
            nearby_permits_count=5,
        ),
    ]

    results = demo_properties

    # Filter by query text
    if q:
        q_lower = q.lower()
        results = [p for p in results if q_lower in p.address.lower() or q_lower in (p.city or "").lower()]

    # Filter by address
    if address:
        addr_lower = address.lower()
        results = [p for p in results if addr_lower in p.address.lower()]

    # Filter by city
    if city:
        results = [p for p in results if (p.city or "").lower() == city.lower()]

    return {"properties": [p.model_dump() for p in results[:limit]], "total": len(results)}


@router.get("/properties/{property_id}")
async def get_property(request: Request, property_id: str):
    """Get detailed property information."""
    from models.property import Property
    # Demo mode - return a sample property
    return Property(
        id=property_id,
        address="45 Harvard St, Brookline, MA 02445",
        city="Brookline", state="MA", zip_code="02445",
        latitude=42.3419, longitude=-71.1219,
        property_type="SINGLE_FAMILY",
        year_built=1920, bedrooms=4, bathrooms=2.5,
        living_area_sqft=2400, lot_size_sqft=5200,
        tax_assessment=985000, estimated_value=1150000,
    ).model_dump()


# ─── Permit Endpoints ─────────────────────────────────────────────────────────

@router.get("/permits/search")
async def search_permits(
    request: Request,
    q: Optional[str] = None,
    address: Optional[str] = None,
    town: Optional[str] = None,
    permit_type: Optional[str] = None,
    status: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: float = 1.0,
    filed_after: Optional[str] = None,
    min_value: Optional[float] = None,
    limit: int = 20,
):
    """Search building permits with flexible filtering."""
    permit_loader = _get("permit_loader")

    if not permit_loader:
        return {"permits": [], "total": 0, "error": "Permit loader not initialized"}

    results = await permit_loader.search(
        query=q,
        address=address,
        town=town,
        permit_type=permit_type,
        status=status,
        latitude=lat,
        longitude=lon,
        radius_km=radius_km,
        filed_after=filed_after,
        min_value=min_value,
        limit=limit,
    )

    return {
        "permits": results,
        "total": len(results),
        "total_available": permit_loader.count,
        "source": "supabase" if permit_loader.is_supabase else "demo",
    }


@router.get("/permits/near/{lat}/{lon}")
async def get_permits_near(
    request: Request,
    lat: float,
    lon: float,
    radius_km: float = 1.0,
    limit: int = 20,
):
    """Get permits near a geographic location."""
    permit_loader = _get("permit_loader")

    if not permit_loader:
        return {"permits": [], "total": 0}

    results = await permit_loader.get_nearby(lat, lon, radius_km, limit)
    return {"permits": results, "total": len(results)}


@router.get("/permits/viewport")
async def get_permits_in_viewport(
    request: Request,
    west: float = Query(..., description="Western longitude bound"),
    south: float = Query(..., description="Southern latitude bound"),
    east: float = Query(..., description="Eastern longitude bound"),
    north: float = Query(..., description="Northern latitude bound"),
    limit: int = Query(500, ge=1, le=2000, description="Max pins to return"),
):
    """
    Get geocoded permit pins within a viewport bounding box.

    Returns lightweight pin data for map rendering (no heavy content fields).
    """
    supabase = _get("supabase_client")
    if not supabase:
        return {"pins": [], "total": 0, "truncated": False}

    try:
        # Step 1: Get locations within the bounding box
        rows = await supabase.fetch(
            table="document_locations",
            select="document_id,latitude,longitude,address",
            filters={
                "and": (
                    f"(latitude.gte.{south},latitude.lte.{north},"
                    f"longitude.gte.{west},longitude.lte.{east})"
                ),
            },
            limit=limit,
        )

        if not rows:
            return {"pins": [], "total": 0, "truncated": False}

        # Step 2: Fetch permit content from documents table in bulk
        # Content format: "Type: Building | Address: ... | Description: ... | Cost: $627.00"
        doc_ids = list({r["document_id"] for r in rows if r.get("document_id")})
        doc_map: dict = {}
        if doc_ids:
            for i in range(0, len(doc_ids), 50):
                batch = doc_ids[i:i + 50]
                id_list = ",".join(batch)
                try:
                    docs = await supabase.fetch(
                        table="documents",
                        select="id,content,source_id,created_at",
                        filters={"id": f"in.({id_list})"},
                    )
                    for d in docs:
                        # Parse pipe-delimited content
                        content = d.get("content") or ""
                        fields = {}
                        for part in content.split("|"):
                            part = part.strip()
                            if ":" in part:
                                k, v = part.split(":", 1)
                                fields[k.strip().lower()] = v.strip()
                        # Extract cost as float
                        cost_str = fields.get("cost", "").replace("$", "").replace(",", "")
                        try:
                            cost = float(cost_str) if cost_str else None
                        except ValueError:
                            cost = None
                        doc_map[d["id"]] = {
                            "type": fields.get("type", ""),
                            "desc": fields.get("description", ""),
                            "value": cost,
                            "date": (d.get("created_at") or "")[:10] or None,
                            "source_id": d.get("source_id", ""),
                        }
                except Exception as e:
                    print(f"[Viewport Permits] Document fetch warning: {e}")

        pins = []
        for row in rows:
            doc_id = row.get("document_id")
            meta = doc_map.get(doc_id, {})
            pins.append({
                "id": doc_id,
                "lat": row.get("latitude"),
                "lon": row.get("longitude"),
                "addr": row.get("address", ""),
                "type": meta.get("type", ""),
                "status": meta.get("desc", ""),  # Use description as status label
                "value": meta.get("value"),
                "date": meta.get("date"),
            })

        return {
            "pins": pins,
            "total": len(pins),
            "truncated": len(pins) >= limit,
        }
    except Exception as e:
        print(f"[Viewport Permits] Error: {e}")
        return {"pins": [], "total": 0, "truncated": False}


@router.get("/permits/towns")
async def get_permit_towns(request: Request):
    """Get list of available towns with permit counts."""
    permit_loader = _get("permit_loader")

    if not permit_loader:
        return {"towns": []}

    towns = await permit_loader.get_towns()
    return {"towns": towns}


# ─── Coverage Endpoints ──────────────────────────────────────────────────────


@router.get("/coverage/summary")
async def get_coverage_summary(request: Request):
    """Statewide coverage matrix: 37 source types with municipality counts by status."""
    supabase = _get("supabase_client")
    if not supabase or not supabase.is_connected:
        return {"sources": [], "total_municipalities": 0, "error": "No database connection"}

    # Fetch all source requirements
    sources = await supabase.fetch("source_requirements", select="id,label,category,active", order="category,id")

    # Fetch coverage rows grouped status counts
    # PostgREST caps at 1000 rows, so use fetch_all to paginate through all 12,987
    coverage = await supabase.fetch_all(
        "municipality_source_coverage",
        select="source_requirement_id,status",
    )

    # Build lookup: source_id -> {status: count}
    source_stats: dict[str, Counter] = defaultdict(Counter)
    for row in coverage:
        src_id = row.get("source_requirement_id", "")
        status = row.get("status", "unknown")
        source_stats[src_id][status] += 1

    # Merge
    result = []
    for src in sources:
        sid = src["id"]
        stats = dict(source_stats.get(sid, {}))
        total = sum(stats.values())
        ready = stats.get("ready_for_ingestion", 0)
        result.append({
            "id": sid,
            "label": src.get("label", sid),
            "category": src.get("category", ""),
            "active": src.get("active", True),
            "total_municipalities": total,
            "ready": ready,
            "pending": total - ready,
            "status_breakdown": stats,
        })

    return {
        "sources": result,
        "total_source_types": len(sources),
        "total_municipalities": 351,
        "total_coverage_rows": len(coverage),
    }


@router.get("/coverage/municipality/{municipality_id}")
async def get_municipality_coverage(request: Request, municipality_id: str):
    """All source coverage statuses for a single municipality."""
    supabase = _get("supabase_client")
    if not supabase or not supabase.is_connected:
        return {"municipality_id": municipality_id, "sources": [], "error": "No database connection"}

    coverage = await supabase.fetch(
        "municipality_source_coverage",
        select="source_requirement_id,status,ingestion_method,source_url,source_system,priority,last_checked_at,last_ingested_at,notes",
        filters={"municipality_id": f"eq.{municipality_id}"},
        order="source_requirement_id",
    )

    # Fetch source labels for display
    sources = await supabase.fetch("source_requirements", select="id,label,category")
    source_map = {s["id"]: s for s in sources}

    result = []
    for row in coverage:
        src_id = row.get("source_requirement_id", "")
        src_info = source_map.get(src_id, {})
        result.append({
            "source_id": src_id,
            "source_label": src_info.get("label", src_id),
            "category": src_info.get("category", ""),
            "status": row.get("status", "unknown"),
            "ingestion_method": row.get("ingestion_method"),
            "source_url": row.get("source_url"),
            "source_system": row.get("source_system"),
            "priority": row.get("priority", 0),
            "last_checked_at": row.get("last_checked_at"),
            "last_ingested_at": row.get("last_ingested_at"),
            "notes": row.get("notes", ""),
        })

    return {
        "municipality_id": municipality_id,
        "sources": result,
        "total": len(result),
    }


@router.get("/towns")
async def list_towns(
    request: Request,
    q: Optional[str] = None,
    limit: int = 400,
):
    """List all 351 MA municipalities with permit counts and coverage stats."""
    supabase = _get("supabase_client")
    permit_loader = _get("permit_loader")

    if not supabase or not supabase.is_connected:
        # Fall back to permit_loader towns
        if permit_loader:
            towns = await permit_loader.get_towns()
            return {"towns": towns, "total": len(towns)}
        return {"towns": [], "total": 0}

    # Fetch all towns
    filters = {}
    if q:
        filters["or"] = f"(name.ilike.*{q}*,id.ilike.*{q}*,county.ilike.*{q}*)"

    towns_raw = await supabase.fetch(
        "towns",
        select="id,name,state,county,population,permit_portal_url",
        filters=filters if filters else None,
        order="name",
        limit=limit,
    )

    # Get coverage stats per town (ready vs total)
    coverage = await supabase.fetch_all(
        "municipality_source_coverage",
        select="municipality_id,status",
    )

    town_coverage: dict = defaultdict(lambda: {"total": 0, "ready": 0})
    for row in coverage:
        tid = row.get("municipality_id", "")
        town_coverage[tid]["total"] += 1
        if row.get("status") == "ready_for_ingestion":
            town_coverage[tid]["ready"] += 1

    # Get permit counts from loader if available
    permit_counts = {}
    if permit_loader and permit_loader.is_supabase:
        try:
            towns_with_permits = await permit_loader.get_towns()
            for t in towns_with_permits:
                permit_counts[t["id"]] = t.get("permit_count", 0)
        except Exception:
            pass

    result = []
    for town in towns_raw:
        tid = town["id"]
        cov = town_coverage.get(tid, {"total": 0, "ready": 0})
        coverage_pct = round(cov["ready"] / cov["total"] * 100, 1) if cov["total"] > 0 else 0
        result.append({
            "id": tid,
            "name": town.get("name", tid),
            "state": town.get("state", "MA"),
            "county": town.get("county"),
            "population": town.get("population"),
            "permit_count": permit_counts.get(tid, 0),
            "permit_portal_url": town.get("permit_portal_url"),
            "coverage_total": cov["total"],
            "coverage_ready": cov["ready"],
            "coverage_pct": coverage_pct,
        })

    return {
        "towns": result,
        "total": len(result),
    }


# ─── Ingestion Endpoint ──────────────────────────────────────────────────────

@router.post("/ingestion/run")
async def run_ingestion(request: Request):
    """Trigger a permit data ingestion run for a specific town + source.

    Body: { "town": "cambridge", "source": "socrata", "limit": 1000 }
    """
    body = await request.json()
    town = body.get("town", "").lower().strip()
    source = body.get("source", "socrata").lower().strip()
    limit = body.get("limit", 10000)

    if not town:
        raise HTTPException(status_code=400, detail="town is required")

    supabase = _get("supabase_client")

    if source == "socrata":
        try:
            from scrapers.connectors.socrata import SocrataConnector, SOCRATA_TOWNS
            from scrapers.connectors.normalize import normalize_batch

            if town not in SOCRATA_TOWNS:
                return {
                    "status": "error",
                    "message": f"No Socrata config for {town}. Available: {list(SOCRATA_TOWNS.keys())}",
                }

            connector = SocrataConnector()
            result = await connector.pull_town(town)
            await connector.close()

            # Normalize the raw permits
            normalized = normalize_batch(result["permits"][:limit], town)

            return {
                "status": "success",
                "town": town,
                "source": "socrata",
                "raw_count": result["permit_count"],
                "normalized_count": len(normalized),
                "sample": normalized[:3] if normalized else [],
                "pulled_at": result["pulled_at"],
            }

        except Exception as exc:
            logger.error("Ingestion failed for %s: %s", town, exc)
            return {"status": "error", "town": town, "message": str(exc)}

    elif source == "viewpointcloud":
        try:
            import httpx as httpx_lib
            from scrapers.connectors.viewpointcloud import (
                ViewpointCloudClient,
                fetch_general_settings,
            )

            community_slug = body.get("community_slug", f"{town}ma")

            async with httpx_lib.AsyncClient(timeout=30.0) as client:
                api_base, settings, error = await fetch_general_settings(
                    community_slug=community_slug, client=client
                )

                if error or not api_base:
                    return {
                        "status": "error",
                        "town": town,
                        "message": f"ViewpointCloud not available for {community_slug}: {error}",
                    }

                vpc = ViewpointCloudClient(
                    community_slug=community_slug,
                    api_base=api_base,
                    client=client,
                )

                # Check capabilities
                allow_search = settings.get("allowPublicSearch", False) if settings else False
                allow_records = settings.get("allowPublicRecordSearch", False) if settings else False

                return {
                    "status": "success",
                    "town": town,
                    "source": "viewpointcloud",
                    "community_slug": community_slug,
                    "api_base": api_base,
                    "capabilities": {
                        "public_search": allow_search,
                        "public_records": allow_records,
                    },
                    "settings_keys": list(settings.keys()) if settings else [],
                }

        except Exception as exc:
            logger.error("ViewpointCloud check failed for %s: %s", town, exc)
            return {"status": "error", "town": town, "message": str(exc)}

    else:
        return {
            "status": "error",
            "message": f"Unknown source: {source}. Available: socrata, viewpointcloud",
        }


# ─── RAG Chat Endpoint ────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(request: Request):
    """RAG-powered chat about properties, permits, and real estate intelligence."""
    body = await request.json()
    message = body.get("message", "")
    property_id = body.get("property_id")
    context = body.get("context")

    if not message:
        return {"content": "Please provide a message.", "sources": [], "confidence": 0}

    permit_loader = _get("permit_loader")
    permit_search = _get("permit_search")

    if not permit_loader or not permit_search:
        return {
            "content": "Chat service is initializing. Please try again in a moment.",
            "sources": [],
            "confidence": 0,
        }

    # Search for relevant permits
    context_permits = await permit_search.search(
        query=message,
        limit=10,
    )

    # Generate answer
    answer, suggested, confidence = await permit_search.generate_answer(
        question=message,
        context_permits=context_permits,
        property_address=context,
    )

    return {
        "content": answer,
        "sources": [{"permit_number": p.get("permit_number"), "address": p.get("address"), "relevance": p.get("relevance_score", 0)} for p in context_permits[:5]],
        "permits_found": len(context_permits),
        "suggested_questions": suggested,
        "confidence": confidence,
    }


# ─── Listing Enrichment ──────────────────────────────────────────────────────

@router.post("/listings/enrich")
async def enrich_listing(request: Request):
    """Enrich a tracked listing with nearby permit data."""
    body = await request.json()
    address = body.get("address", "")
    lat = body.get("latitude")
    lon = body.get("longitude")

    permit_loader = _state.get("permit_loader")
    if not permit_loader:
        return {"permits": [], "total": 0}

    permits = []
    # Try address search first
    if address:
        try:
            permits = await permit_loader.search(address=address, limit=20)
        except Exception as e:
            logger.warning("Enrich address search failed: %s", e)

    # Fall back to nearby search
    if not permits and lat and lon:
        try:
            permits = await permit_loader.get_nearby(float(lat), float(lon), radius_km=0.5, limit=20)
        except Exception as e:
            logger.warning("Enrich nearby search failed: %s", e)

    return {"permits": permits, "total": len(permits)}


# ─── Property Agent Endpoints ─────────────────────────────────────────────────

@router.get("/agents")
async def list_agents(request: Request):
    """List all active property monitoring agents."""
    agents = _state.get("property_agents", [])
    return {"agents": [a if isinstance(a, dict) else a.model_dump() for a in agents], "total": len(agents)}


@router.post("/agents")
async def create_agent(request: Request):
    """Create a new property monitoring agent."""
    from models.property import PropertyAgent, AgentType, AgentStatus
    body = await request.json()

    agent = PropertyAgent(
        entity_type=body.get("entity_type", "property"),
        entity_id=body.get("entity_id", ""),
        agent_type=AgentType(body.get("agent_type", "listing")),
        name=body.get("name", f"Agent for {body.get('entity_id', 'unknown')}"),
        config=body.get("config", {}),
        run_interval_seconds=body.get("run_interval_seconds", 300),
    )

    if "property_agents" not in _state:
        _state["property_agents"] = []
    _state["property_agents"].append(agent)

    return {"status": "created", "agent": agent.model_dump()}


@router.delete("/agents/{agent_id}")
async def delete_agent(request: Request, agent_id: str):
    """Delete/deactivate a property monitoring agent."""
    agents = _state.get("property_agents", [])

    for i, a in enumerate(agents):
        aid = a.id if hasattr(a, 'id') else a.get('id')
        if aid == agent_id:
            agents.pop(i)
            return {"status": "deleted", "agent_id": agent_id}

    return {"status": "not_found", "agent_id": agent_id}


# ─── Town Intelligence Endpoints ─────────────────────────────────────────────

@router.get("/target-towns")
async def list_target_towns(request: Request):
    """List all target towns with basic config info."""
    from scrapers.connectors.town_config import get_all_towns

    towns = get_all_towns()
    result = []
    for tid, t in towns.items():
        result.append({
            "id": t.id,
            "name": t.name,
            "county": t.county,
            "population": t.population,
            "median_home_value": t.median_home_value,
            "center": {"lat": t.center_lat, "lon": t.center_lon},
            "permit_portal_type": t.permit_portal_type,
            "boards": [b.name for b in t.boards],
        })
    return {"towns": result, "total": len(result)}


@router.get("/towns/{town_id}")
async def get_town(request: Request, town_id: str):
    """Get detailed info for a specific town."""
    from scrapers.connectors.town_config import get_town

    town = get_town(town_id)
    if not town:
        raise HTTPException(status_code=404, detail=f"Town not found: {town_id}")

    return {
        "id": town.id,
        "name": town.name,
        "county": town.county,
        "registry_district": town.registry_district,
        "population": town.population,
        "median_home_value": town.median_home_value,
        "center": {"lat": town.center_lat, "lon": town.center_lon},
        "bbox": {"south": town.bbox_south, "west": town.bbox_west, "north": town.bbox_north, "east": town.bbox_east},
        "permit_portal_url": town.permit_portal_url,
        "permit_portal_type": town.permit_portal_type,
        "meeting_minutes_url": town.meeting_minutes_url,
        "assessor_url": town.assessor_url,
        "zoning_bylaw_url": town.zoning_bylaw_url,
        "boards": [
            {"name": b.name, "slug": b.slug, "minutes_url": b.minutes_url, "agendas_url": b.agendas_url}
            for b in town.boards
        ],
    }


@router.get("/towns/{town_id}/dashboard")
async def get_town_dashboard(request: Request, town_id: str):
    """Get a combined dashboard for a town: recent sales, permits, stats, documents."""
    from scrapers.connectors.town_config import get_town
    from scrapers.connectors.massgis_parcels import get_recent_sales, get_town_stats

    town = get_town(town_id)
    if not town:
        raise HTTPException(status_code=404, detail=f"Town not found: {town_id}")

    supabase = _get("supabase_client")

    # Gather data in parallel
    results = {}

    # MassGIS stats
    try:
        stats = await get_town_stats(town.name)
        results["stats"] = stats
    except Exception as e:
        logger.warning("Town stats error for %s: %s", town_id, e)
        results["stats"] = {}

    # Recent sales (last 90 days)
    try:
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        sales = await get_recent_sales(town=town.name, min_sale_date=cutoff, min_price=1000, limit=20)
        results["recent_sales"] = sales
    except Exception as e:
        logger.warning("Recent sales error for %s: %s", town_id, e)
        results["recent_sales"] = []

    # Recent documents from Supabase
    if supabase:
        try:
            docs = await supabase.fetch(
                table="municipal_documents",
                select="id,title,board,meeting_date,content_summary,keywords,doc_type",
                filters={"town_id": f"eq.{town_id}"},
                order="meeting_date.desc",
                limit=10,
            )
            results["recent_documents"] = docs
        except Exception as e:
            logger.warning("Documents error for %s: %s", town_id, e)
            results["recent_documents"] = []
    else:
        results["recent_documents"] = []

    # Recent scrape jobs
    if supabase:
        try:
            jobs = await supabase.fetch(
                table="scrape_jobs",
                select="id,source_type,status,completed_at,records_found,records_new",
                filters={"town_id": f"eq.{town_id}"},
                order="completed_at.desc",
                limit=10,
            )
            results["scrape_jobs"] = jobs
        except Exception as e:
            logger.warning("Scrape jobs error for %s: %s", town_id, e)
            results["scrape_jobs"] = []
    else:
        results["scrape_jobs"] = []

    results["town"] = {
        "id": town.id,
        "name": town.name,
        "county": town.county,
        "median_home_value": town.median_home_value,
        "population": town.population,
    }

    return results


@router.get("/towns/{town_id}/activity")
async def get_town_activity(request: Request, town_id: str, limit: int = Query(default=50, le=200)):
    """Get a merged activity feed for a town: sales + documents, sorted by date."""
    from scrapers.connectors.town_config import get_town

    town = get_town(town_id)
    if not town:
        raise HTTPException(status_code=404, detail=f"Town not found: {town_id}")

    supabase = _get("supabase_client")
    activities = []

    if supabase:
        # Get recent transfers
        try:
            transfers = await supabase.fetch(
                table="property_transfers",
                select="id,site_addr,owner,sale_date,sale_price,use_code",
                filters={"town_id": f"eq.{town_id}"},
                order="sale_date.desc",
                limit=limit,
            )
            for t in transfers:
                activities.append({
                    "type": "sale",
                    "date": t.get("sale_date", ""),
                    "title": f"Property sold: {t.get('site_addr', 'Unknown')}",
                    "detail": f"${t['sale_price']:,.0f}" if t.get("sale_price") else "Price undisclosed",
                    "data": t,
                })
        except Exception as e:
            logger.warning("Transfers activity error: %s", e)

        # Get recent documents
        try:
            docs = await supabase.fetch(
                table="municipal_documents",
                select="id,title,board,meeting_date,content_summary,doc_type",
                filters={"town_id": f"eq.{town_id}"},
                order="meeting_date.desc",
                limit=limit,
            )
            for d in docs:
                activities.append({
                    "type": "document",
                    "date": d.get("meeting_date", ""),
                    "title": d.get("title", "Meeting Minutes"),
                    "detail": f"{d.get('board', '')} — {d.get('content_summary', '')[:120]}",
                    "data": d,
                })
        except Exception as e:
            logger.warning("Documents activity error: %s", e)

    # Sort combined feed by date descending
    activities.sort(key=lambda x: x.get("date", ""), reverse=True)

    return {"town_id": town_id, "activities": activities[:limit], "total": len(activities)}


@router.get("/towns/{town_id}/documents")
async def get_town_documents(
    request: Request,
    town_id: str,
    doc_type: Optional[str] = None,
    board: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Get municipal documents for a town, optionally filtered by type or board."""
    supabase = _get("supabase_client")
    if not supabase:
        return {"documents": [], "total": 0}

    filters = {"town_id": f"eq.{town_id}"}
    if doc_type:
        filters["doc_type"] = f"eq.{doc_type}"
    if board:
        filters["board"] = f"eq.{board}"

    try:
        docs = await supabase.fetch(
            table="municipal_documents",
            select="id,title,board,meeting_date,content_summary,keywords,doc_type,source_url,file_url,mentions",
            filters=filters,
            order="meeting_date.desc",
            limit=limit,
            offset=offset,
        )
        total = await supabase.count("municipal_documents", filters=filters)
        return {"documents": docs, "total": total}
    except Exception as e:
        logger.error("Documents fetch error: %s", e)
        return {"documents": [], "total": 0}


@router.get("/towns/{town_id}/transfers")
async def get_town_transfers(
    request: Request,
    town_id: str,
    min_price: Optional[int] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Get property transfers for a town from the database."""
    supabase = _get("supabase_client")
    if not supabase:
        return {"transfers": [], "total": 0}

    filters = {"town_id": f"eq.{town_id}"}
    if min_price:
        filters["sale_price"] = f"gte.{min_price}"

    try:
        transfers = await supabase.fetch(
            table="property_transfers",
            select="*",
            filters=filters,
            order="sale_date.desc",
            limit=limit,
            offset=offset,
        )
        total = await supabase.count("property_transfers", filters=filters)
        return {"transfers": transfers, "total": total}
    except Exception as e:
        logger.error("Transfers fetch error: %s", e)
        return {"transfers": [], "total": 0}


# ─── Property Search (Enhanced) ──────────────────────────────────────────────

@router.get("/parcels/search")
async def search_parcels(
    request: Request,
    town: Optional[str] = None,
    owner: Optional[str] = None,
    loc_id: Optional[str] = None,
    limit: int = Query(default=25, le=100),
):
    """Search parcels by owner name, LOC_ID, or town."""
    from scrapers.connectors.massgis_parcels import search_by_owner, search_by_loc_id

    if loc_id:
        try:
            result = await search_by_loc_id(loc_id)
            return {"parcels": [result] if result else [], "total": 1 if result else 0, "query": {"loc_id": loc_id}}
        except Exception as e:
            logger.error("LOC_ID search error: %s", e)
            return {"parcels": [], "total": 0, "error": str(e)}

    if owner and town:
        try:
            results = await search_by_owner(town=town, owner_name=owner, limit=limit)
            return {"parcels": results, "total": len(results), "query": {"town": town, "owner": owner}}
        except Exception as e:
            logger.error("Owner search error: %s", e)
            return {"parcels": [], "total": 0, "error": str(e)}

    if owner:
        return {"parcels": [], "total": 0, "error": "Owner search requires a town parameter"}

    return {"parcels": [], "total": 0, "error": "Provide owner+town or loc_id parameter"}


@router.get("/parcels/{loc_id}/mentions")
async def get_parcel_mentions(request: Request, loc_id: str):
    """Find meeting minutes that mention a specific parcel or address."""
    supabase = _get("supabase_client")
    if not supabase:
        return {"mentions": [], "total": 0}

    # First get the parcel address
    from scrapers.connectors.massgis_parcels import search_by_loc_id
    parcel = None
    try:
        parcel = await search_by_loc_id(loc_id)
    except Exception:
        pass

    if not parcel:
        return {"mentions": [], "total": 0, "error": "Parcel not found"}

    address = parcel.get("site_addr", "")
    if not address:
        return {"mentions": [], "total": 0, "error": "No address found for parcel"}

    # Search documents where mentions contain this address or loc_id
    try:
        # Use Supabase text search on content_text
        docs = await supabase.fetch(
            table="municipal_documents",
            select="id,title,board,meeting_date,content_summary,mentions,town_id",
            filters={"content_text": f"ilike.%{address}%"},
            order="meeting_date.desc",
            limit=20,
        )
        return {
            "parcel": {"loc_id": loc_id, "address": address},
            "mentions": docs,
            "total": len(docs),
        }
    except Exception as e:
        logger.error("Parcel mentions error: %s", e)
        return {"mentions": [], "total": 0, "error": str(e)}


# ─── Scrape Management Endpoints ─────────────────────────────────────────────

@router.post("/scrape/trigger/{town_id}")
async def trigger_scrape(
    request: Request,
    town_id: str,
    source_type: Optional[str] = None,
    partition: Optional[int] = None,
    num_partitions: Optional[int] = None,
):
    """Manually trigger a scrape for a specific town.

    Optional partition support for parallel scraping:
    - partition: 0-based partition index (e.g. 0, 1, 2)
    - num_partitions: total number of partitions (e.g. 3)
    Each partition scrapes a different slice of record types.
    """
    scheduler = _get("scrape_scheduler")
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scrape scheduler not initialized")

    result = await scheduler.trigger_town_scrape(
        town_id,
        source_type=source_type,
        partition=partition,
        num_partitions=num_partitions,
    )

    if "error" in result and not any(k for k in result if k != "error"):
        raise HTTPException(status_code=404, detail=result["error"])

    return {"status": "triggered", "town_id": town_id, "partition": partition, "results": result}


@router.get("/scrape/status")
async def scrape_status(request: Request, town_id: Optional[str] = None, limit: int = Query(default=20, le=100)):
    """Get recent scrape job status."""
    supabase = _get("supabase_client")
    if not supabase:
        return {"jobs": [], "total": 0}

    filters = {}
    if town_id:
        filters["town_id"] = f"eq.{town_id}"

    try:
        jobs = await supabase.fetch(
            table="scrape_jobs",
            select="*",
            filters=filters,
            order="started_at.desc",
            limit=limit,
        )
        return {"jobs": jobs, "total": len(jobs)}
    except Exception as e:
        logger.error("Scrape status error: %s", e)
        return {"jobs": [], "total": 0}


@router.get("/scrape/stats")
async def scrape_stats(request: Request):
    """Get overall scraping statistics across all towns."""
    supabase = _get("supabase_client")
    if not supabase:
        return {"stats": {}}

    try:
        # Count documents, transfers, and jobs
        doc_count = await supabase.count("municipal_documents")
        transfer_count = await supabase.count("property_transfers")
        job_count = await supabase.count("scrape_jobs")

        completed_jobs = await supabase.count("scrape_jobs", filters={"status": "eq.completed"})
        failed_jobs = await supabase.count("scrape_jobs", filters={"status": "eq.failed"})

        permit_count = 0
        try:
            permit_count = await supabase.count("permits")
        except Exception:
            pass

        return {
            "stats": {
                "total_permits": permit_count,
                "total_documents": doc_count,
                "total_transfers": transfer_count,
                "total_jobs": job_count,
                "completed_jobs": completed_jobs,
                "failed_jobs": failed_jobs,
            }
        }
    except Exception as e:
        logger.error("Scrape stats error: %s", e)
        return {"stats": {}}


@router.get("/scrape/check")
async def scrape_check():
    """Check which scrapers have completed, which are running, and which are pending.

    Returns per-town, per-source_type breakdown so you can see exactly
    which jobs still need to run.
    """
    scheduler = _get("scrape_scheduler")
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scrape scheduler not initialized")

    status = await scheduler.get_scrape_status()
    return status


@router.post("/scrape/run-pending")
async def scrape_run_pending(
    max_concurrency: int = Query(default=4, ge=1, le=12),
    source_type: Optional[str] = Query(default=None, description="Filter: permits, meeting_minutes, property_transfers"),
):
    """Find all incomplete/overdue scrape jobs and run them in parallel.

    Spawns up to ``max_concurrency`` concurrent scraper tasks for pending
    towns.  Returns results once all tasks complete.
    """
    scheduler = _get("scrape_scheduler")
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scrape scheduler not initialized")

    source_types = [source_type] if source_type else None

    result = await scheduler.run_pending_parallel(
        max_concurrency=max_concurrency,
        source_types=source_types,
    )
    return result


# ──────────────────────────────────────────────
# Scraped Permits API (new permits table)
# ──────────────────────────────────────────────


@router.get("/scraped-permits")
async def get_scraped_permits(
    request: Request,
    town_id: Optional[str] = None,
    permit_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
):
    """Query permits from the new scraped permits table."""
    supabase = _get("supabase_client")
    if not supabase:
        return {"permits": [], "total": 0}

    filters = {}
    if town_id:
        filters["town_id"] = f"eq.{town_id}"
    if permit_type:
        filters["permit_type"] = f"eq.{permit_type}"
    if status:
        filters["status"] = f"eq.{status}"

    try:
        permits = await supabase.fetch(
            table="permits",
            select="*",
            filters=filters,
            order="filed_date.desc",
            limit=limit,
        )
        return {"permits": permits, "total": len(permits)}
    except Exception as e:
        logger.error("Scraped permits query error: %s", e)
        return {"permits": [], "total": 0}


@router.get("/scraped-permits/by-town/{town_id}")
async def get_scraped_permits_by_town(
    request: Request,
    town_id: str,
    limit: int = Query(default=50, le=200),
):
    """Get recent scraped permits for a specific town."""
    supabase = _get("supabase_client")
    if not supabase:
        return {"permits": [], "total": 0}

    try:
        permits = await supabase.fetch(
            table="permits",
            select="*",
            filters={"town_id": f"eq.{town_id}"},
            order="filed_date.desc",
            limit=limit,
        )
        return {"permits": permits, "total": len(permits), "town_id": town_id}
    except Exception as e:
        logger.error("Town permits query error: %s", e)
        return {"permits": [], "total": 0, "town_id": town_id}



# ──────────────────────────────────────────────
# Notification Agent Endpoint (cron-triggered)
# ──────────────────────────────────────────────

@router.post("/notifications/check")
async def check_notifications():
    """Cron-triggered endpoint: check tracked listings for new activity.

    Queries Supabase for recent permits, sales, and meeting mentions
    relevant to tracked properties/towns, then writes notifications
    to the agent_findings table.

    Designed to be called by Vercel Cron Jobs on a schedule.
    """
    import uuid as uuid_mod

    supabase = _get("supabase_client")
    permit_loader = _get("permit_loader")

    if not supabase:
        return {"status": "skipped", "reason": "no database connection", "notifications_created": 0}

    created = 0

    try:
        # Fetch all active monitoring agents
        agents = _state.get("property_agents", [])

        if not agents or not permit_loader:
            return {"status": "ok", "notifications_created": 0, "reason": "no active agents"}

        now = datetime.utcnow()

        for agent in agents:
            try:
                config = agent.get("config", {}) if isinstance(agent, dict) else getattr(agent, "config", {})
                agent_id = agent.get("id", "") if isinstance(agent, dict) else getattr(agent, "id", "")
                entity_id = agent.get("entity_id", "") if isinstance(agent, dict) else getattr(agent, "entity_id", "")
                agent_status = agent.get("status", "active") if isinstance(agent, dict) else getattr(agent, "status", "active")

                if agent_status != "active":
                    continue

                lat = config.get("latitude")
                lon = config.get("longitude")
                address = config.get("address", "")
                town = config.get("town", "")

                if not (lat and lon):
                    continue

                # Check for recent permit activity near this property
                permits = await permit_loader.search(
                    address=address,
                    latitude=lat,
                    longitude=lon,
                    radius_km=0.5,
                    limit=5,
                )

                if not permits:
                    continue

                finding = {
                    "id": uuid_mod.uuid4().hex[:12],
                    "agent_id": agent_id,
                    "property_id": entity_id,
                    "finding_type": "PERMIT_ACTIVITY",
                    "severity": "LOW" if len(permits) < 3 else "MEDIUM" if len(permits) < 10 else "HIGH",
                    "title": f"{len(permits)} permit(s) near {address[:40] if address else 'monitored location'}",
                    "summary": (
                        f"Found {len(permits)} active permits within 0.5km."
                        + (f" Most recent: {permits[0].get('description', '')[:80]}" if permits[0].get("description") else "")
                    ),
                    "data": {"permit_count": len(permits), "town": town},
                    "latitude": lat,
                    "longitude": lon,
                    "acknowledged": False,
                    "created_at": now.isoformat(),
                }

                # Store finding in state (and Supabase if available)
                _state.setdefault("agent_findings", []).insert(0, finding)

                try:
                    await supabase.insert("agent_findings", finding)
                except Exception:
                    pass  # state-only is fine

                created += 1

                # Update agent last_run
                if isinstance(agent, dict):
                    agent["last_run"] = now.isoformat()
                    agent["findings_count"] = agent.get("findings_count", 0) + 1

            except Exception as e:
                logger.debug("Notification check error for agent %s: %s", agent_id if 'agent_id' in dir() else '?', e)

    except Exception as e:
        logger.error("Notification check error: %s", e)
        return {"status": "error", "error": str(e), "notifications_created": created}

    return {"status": "ok", "notifications_created": created}


@router.get("/notifications")
async def get_notifications(
    limit: int = Query(50, ge=1, le=200),
    acknowledged: Optional[bool] = Query(None),
):
    """Get recent notifications/findings for the current user."""
    findings = _state.get("agent_findings", [])

    if acknowledged is not None:
        findings = [f for f in findings if f.get("acknowledged") == acknowledged]

    return {
        "notifications": findings[:limit],
        "total": len(findings),
    }
