"""
MassGIS Comparable Sales connector.

Queries the same ArcGIS Feature Service as massgis_parcels.py but with
an envelope (bounding-box) spatial query and WHERE LS_PRICE > 0 to find
recent sales near a subject property.
"""

from __future__ import annotations

import math
import statistics
from typing import Optional, Tuple

import httpx

PARCELS_URL = (
    "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/"
    "L3_TAXPAR_POLY_ASSESS_gdb/FeatureServer/0/query"
)

OUT_FIELDS = ",".join([
    "LOC_ID", "SITE_ADDR", "CITY",
    "LS_DATE", "LS_PRICE",
    "BLDG_VAL", "LAND_VAL", "TOTAL_VAL",
    "LOT_SIZE", "BLD_AREA", "RES_AREA",
    "UNITS", "STYLE", "USE_CODE", "YEAR_BUILT",
])


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two WGS-84 points."""
    R = 6_371_000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _parse_ls_date(raw) -> Optional[str]:
    """Convert YYYYMMDD (string or int) → ISO date string."""
    if not raw:
        return None
    try:
        d = int(raw)
    except (ValueError, TypeError):
        return None
    if d < 19000101:
        return None
    try:
        return f"{d // 10000}-{(d % 10000) // 100:02d}-{d % 100:02d}"
    except Exception:
        return None


def _centroid(geometry: Optional[dict]) -> Optional[Tuple[float, float]]:
    """Compute centroid from a GeoJSON Polygon/MultiPolygon geometry."""
    if not geometry:
        return None
    coords = geometry.get("coordinates")
    if not coords:
        return None

    gtype = geometry.get("type", "")
    rings: list = []
    if gtype == "Polygon" and coords:
        rings = coords[0]  # outer ring
    elif gtype == "MultiPolygon" and coords:
        rings = coords[0][0]
    else:
        return None

    if not rings:
        return None

    sum_lon = sum(p[0] for p in rings)
    sum_lat = sum(p[1] for p in rings)
    n = len(rings)
    return (sum_lat / n, sum_lon / n)


async def get_comparable_sales(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    use_code: str | None = None,
    subject_loc_id: str | None = None,
    max_results: int = 20,
    timeout: float = 20.0,
) -> dict:
    """
    Find comparable sales near (lat, lon) from MassGIS parcel data.

    Returns dict with 'comps' list and 'summary' stats.
    """
    # Build bounding-box envelope
    delta_lat = radius_m / 111_320
    delta_lon = radius_m / (111_320 * math.cos(math.radians(lat)))
    envelope = (
        f"{lon - delta_lon},{lat - delta_lat},"
        f"{lon + delta_lon},{lat + delta_lat}"
    )

    # WHERE clause: only parcels with a recorded sale (LS_DATE is a string field)
    where = "LS_PRICE > 1000 AND LS_DATE > '19000101'"
    if use_code:
        where += f" AND USE_CODE = '{use_code}'"

    params = {
        "where": where,
        "geometry": envelope,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": OUT_FIELDS,
        "returnGeometry": "true",
        "f": "geojson",
        "inSR": "4326",
        "outSR": "4326",
        "resultRecordCount": 200,  # fetch up to 200, we trim later
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(PARCELS_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            return _empty_response(radius_m, subject_loc_id)

        comps: list[dict] = []
        for f in features:
            props = f.get("properties", {})
            loc_id = props.get("LOC_ID")

            # Skip subject parcel
            if subject_loc_id and loc_id == subject_loc_id:
                continue

            sale_price = props.get("LS_PRICE")
            if not sale_price or sale_price <= 0:
                continue

            bld_area = props.get("BLD_AREA")
            price_per_sqft = (
                round(sale_price / bld_area, 2)
                if bld_area and bld_area > 100
                else None
            )

            # Distance from subject
            cent = _centroid(f.get("geometry"))
            distance_m = (
                round(_haversine(lat, lon, cent[0], cent[1]), 1)
                if cent else None
            )

            # Filter to actual radius (envelope is a square, clip to circle)
            if distance_m is not None and distance_m > radius_m:
                continue

            lot_size = props.get("LOT_SIZE")

            comps.append({
                "loc_id": loc_id,
                "site_addr": props.get("SITE_ADDR"),
                "city": props.get("CITY"),
                "sale_date": _parse_ls_date(props.get("LS_DATE")),
                "sale_price": sale_price,
                "price_per_sqft": price_per_sqft,
                "building_area_sqft": bld_area,
                "lot_size_acres": round(lot_size, 3) if lot_size else None,
                "year_built": props.get("YEAR_BUILT"),
                "style": props.get("STYLE"),
                "use_code": props.get("USE_CODE"),
                "total_assessed_value": props.get("TOTAL_VAL"),
                "distance_m": distance_m,
            })

        # Sort by distance (nulls last)
        comps.sort(key=lambda c: c["distance_m"] if c["distance_m"] is not None else 1e9)
        comps = comps[:max_results]

        # Summary stats
        prices = [c["sale_price"] for c in comps if c["sale_price"]]
        ppsf = [c["price_per_sqft"] for c in comps if c["price_per_sqft"]]
        dates = [c["sale_date"] for c in comps if c["sale_date"]]

        summary = {
            "comp_count": len(comps),
            "median_price_per_sqft": round(statistics.median(ppsf), 2) if ppsf else None,
            "avg_sale_price": round(statistics.mean(prices), 2) if prices else None,
            "min_sale_price": min(prices) if prices else None,
            "max_sale_price": max(prices) if prices else None,
            "date_range_start": min(dates) if dates else None,
            "date_range_end": max(dates) if dates else None,
        }

        return {
            "comps": comps,
            "summary": summary,
            "subject_loc_id": subject_loc_id,
            "radius_m": radius_m,
            "source": "MassGIS Parcels",
        }

    except Exception as e:
        print(f"[MassGIS Comps] Error querying comps for ({lat}, {lon}): {e}")
        return _empty_response(radius_m, subject_loc_id)


def _empty_response(radius_m: float, subject_loc_id: str | None) -> dict:
    return {
        "comps": [],
        "summary": {
            "comp_count": 0,
            "median_price_per_sqft": None,
            "avg_sale_price": None,
            "min_sale_price": None,
            "max_sale_price": None,
            "date_range_start": None,
            "date_range_end": None,
        },
        "subject_loc_id": subject_loc_id,
        "radius_m": radius_m,
        "source": "MassGIS Parcels",
    }
