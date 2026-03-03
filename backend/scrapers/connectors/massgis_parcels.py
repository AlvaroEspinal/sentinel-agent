"""
MassGIS Property Tax Parcels connector.

Queries the ArcGIS Feature Service for property parcel data across all 351 MA towns.
Feature Service: L3_TAXPAR_POLY_ASSESS_gdb / FeatureServer / Layer 0
Free, no API key required. Max 2000 records per query.
"""
from __future__ import annotations

import httpx

PARCELS_URL = "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/L3_TAXPAR_POLY_ASSESS_gdb/FeatureServer/0/query"

# Standard fields to request
OUT_FIELDS = ",".join([
    "LOC_ID",      # Location ID (unique parcel identifier)
    "SITE_ADDR",   # Street address
    "CITY",        # Municipality name
    "OWNER1",      # Primary owner
    "LS_DATE",     # Last sale date (YYYYMMDD integer)
    "LS_PRICE",    # Last sale price
    "BLDG_VAL",    # Building assessed value
    "LAND_VAL",    # Land assessed value
    "OTHER_VAL",   # Other assessed value
    "TOTAL_VAL",   # Total assessed value
    "USE_CODE",    # Property use code
    "LOT_SIZE",    # Lot size in acres
    "YEAR_BUILT",  # Year built
    "BLD_AREA",    # Building area (sq ft)
    "UNITS",       # Number of units
    "RES_AREA",    # Residential area
    "STYLE",       # Building style
    "NUM_ROOMS",   # Number of rooms
    "FY",          # Fiscal year of assessment
])


async def get_parcel_by_point(
    lat: float,
    lon: float,
    timeout: float = 15.0,
) -> dict:
    """
    Get parcel info for the parcel containing a given point.

    Returns parcel attributes + geometry (for boundary display).
    """
    params = {
        "where": "1=1",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": OUT_FIELDS,
        "returnGeometry": "true",
        "f": "geojson",
        "inSR": "4326",
        "outSR": "4326",
        "resultRecordCount": 1,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(PARCELS_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            return _empty_parcel()

        feature = features[0]
        props = feature.get("properties", {})

        # Parse last sale date from integer YYYYMMDD
        ls_date = props.get("LS_DATE")
        ls_date_str = None
        if ls_date and isinstance(ls_date, (int, float)) and ls_date > 10000:
            ls_date_int = int(ls_date)
            try:
                ls_date_str = f"{ls_date_int // 10000}-{(ls_date_int % 10000) // 100:02d}-{ls_date_int % 100:02d}"
            except Exception:
                ls_date_str = str(ls_date_int)

        return {
            "loc_id": props.get("LOC_ID"),
            "site_addr": props.get("SITE_ADDR"),
            "city": props.get("CITY"),
            "owner": props.get("OWNER1"),
            "last_sale_date": ls_date_str,
            "last_sale_price": props.get("LS_PRICE"),
            "building_value": props.get("BLDG_VAL"),
            "land_value": props.get("LAND_VAL"),
            "total_value": props.get("TOTAL_VAL"),
            "use_code": props.get("USE_CODE"),
            "lot_size_acres": props.get("LOT_SIZE"),
            "year_built": props.get("YEAR_BUILT"),
            "building_area_sqft": props.get("BLD_AREA"),
            "units": props.get("UNITS"),
            "style": props.get("STYLE"),
            "num_rooms": props.get("NUM_ROOMS"),
            "fiscal_year": props.get("FY"),
            "geometry": feature.get("geometry"),
            "source": "MassGIS Parcels",
        }

    except Exception as e:
        print(f"[MassGIS] Error querying parcel for ({lat}, {lon}): {e}")
        return _empty_parcel()


async def search_parcels(
    town: str,
    address: str,
    limit: int = 10,
    timeout: float = 15.0,
) -> list[dict]:
    """
    Search parcels by town and address text.
    """
    # Build WHERE clause
    where_parts = []
    if town:
        where_parts.append(f"UPPER(CITY) LIKE '%{town.upper()}%'")
    if address:
        where_parts.append(f"UPPER(SITE_ADDR) LIKE '%{address.upper()}%'")

    where = " AND ".join(where_parts) if where_parts else "1=1"

    params = {
        "where": where,
        "outFields": OUT_FIELDS,
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": min(limit, 100),
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(PARCELS_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        results = []
        for feature in features:
            attrs = feature.get("attributes", {})
            results.append({
                "loc_id": attrs.get("LOC_ID"),
                "site_addr": attrs.get("SITE_ADDR"),
                "city": attrs.get("CITY"),
                "owner": attrs.get("OWNER1"),
                "total_value": attrs.get("TOTAL_VAL"),
                "use_code": attrs.get("USE_CODE"),
                "lot_size_acres": attrs.get("LOT_SIZE"),
                "source": "MassGIS Parcels",
            })
        return results

    except Exception as e:
        print(f"[MassGIS] Error searching parcels for {town}/{address}: {e}")
        return []


async def search_by_owner(
    town: str,
    owner_name: str,
    limit: int = 50,
    timeout: float = 20.0,
) -> list[dict]:
    """
    Search parcels by owner name within a town.
    Uses LIKE matching on OWNER1 field.
    """
    owner_upper = owner_name.strip().upper().replace("'", "''")
    city_upper = town.strip().upper().replace("'", "''")

    where = f"UPPER(CITY) = '{city_upper}' AND UPPER(OWNER1) LIKE '%{owner_upper}%'"

    params = {
        "where": where,
        "outFields": OUT_FIELDS,
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": min(limit, 200),
        "orderByFields": "TOTAL_VAL DESC",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(PARCELS_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        return [_attrs_to_parcel(f.get("attributes", {})) for f in features]

    except Exception as e:
        print(f"[MassGIS] Error searching owner '{owner_name}' in {town}: {e}")
        return []


async def search_by_loc_id(
    loc_id: str,
    timeout: float = 15.0,
) -> dict:
    """
    Look up a single parcel by MassGIS LOC_ID.
    """
    loc_id_clean = loc_id.strip().replace("'", "''")
    where = f"LOC_ID = '{loc_id_clean}'"

    params = {
        "where": where,
        "outFields": OUT_FIELDS,
        "returnGeometry": "true",
        "f": "geojson",
        "outSR": "4326",
        "resultRecordCount": 1,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(PARCELS_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            return _empty_parcel()

        feature = features[0]
        props = feature.get("properties", {})
        result = _attrs_to_parcel(props)
        result["geometry"] = feature.get("geometry")
        return result

    except Exception as e:
        print(f"[MassGIS] Error looking up LOC_ID '{loc_id}': {e}")
        return _empty_parcel()


async def get_recent_sales(
    town: str,
    min_sale_date: str = "20240101",
    min_price: int = 1000,
    limit: int = 500,
    timeout: float = 30.0,
) -> list[dict]:
    """
    Get recent property sales for a town.

    Args:
        town: Town name (e.g. "NEWTON")
        min_sale_date: Minimum sale date as YYYYMMDD string
        min_price: Minimum sale price to exclude nominal transfers
        limit: Maximum results (max 2000 per ArcGIS)

    Returns:
        List of parcel dicts with sale info, sorted by sale date descending.
    """
    city_upper = town.strip().upper().replace("'", "''")
    where = (
        f"UPPER(CITY) = '{city_upper}' "
        f"AND LS_DATE >= {min_sale_date} "
        f"AND LS_PRICE > {min_price}"
    )

    # Add extra sale-related fields
    sale_fields = OUT_FIELDS + ",LS_BOOK,LS_PAGE,MAP_PAR_ID"

    params = {
        "where": where,
        "outFields": sale_fields,
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": min(limit, 2000),
        "orderByFields": "LS_DATE DESC",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(PARCELS_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        results = []
        for f in features:
            attrs = f.get("attributes", {})
            parcel = _attrs_to_parcel(attrs)
            parcel["book_page"] = _format_book_page(attrs.get("LS_BOOK"), attrs.get("LS_PAGE"))
            parcel["map_par_id"] = attrs.get("MAP_PAR_ID")
            results.append(parcel)

        return results

    except Exception as e:
        print(f"[MassGIS] Error getting recent sales for {town}: {e}")
        return []


async def get_town_stats(
    town: str,
    timeout: float = 20.0,
) -> dict:
    """
    Get aggregate stats for a town (total parcels, median value, etc.).
    Uses statisticType queries for efficiency.
    """
    city_upper = town.strip().upper().replace("'", "''")

    params = {
        "where": f"UPPER(CITY) = '{city_upper}' AND TOTAL_VAL > 0",
        "outStatistics": (
            '[{"statisticType":"count","onStatisticField":"LOC_ID","outStatisticFieldName":"parcel_count"},'
            '{"statisticType":"avg","onStatisticField":"TOTAL_VAL","outStatisticFieldName":"avg_value"},'
            '{"statisticType":"avg","onStatisticField":"LS_PRICE","outStatisticFieldName":"avg_sale_price"},'
            '{"statisticType":"max","onStatisticField":"LS_DATE","outStatisticFieldName":"latest_sale_date"}]'
        ),
        "f": "json",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(PARCELS_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            return {"town": town, "parcel_count": 0}

        attrs = features[0].get("attributes", {})
        return {
            "town": town,
            "parcel_count": attrs.get("parcel_count", 0),
            "avg_assessed_value": round(attrs.get("avg_value") or 0),
            "avg_sale_price": round(attrs.get("avg_sale_price") or 0),
            "latest_sale_date": _format_ls_date(attrs.get("latest_sale_date")),
            "source": "MassGIS Parcels",
        }

    except Exception as e:
        print(f"[MassGIS] Error getting stats for {town}: {e}")
        return {"town": town, "parcel_count": 0, "error": str(e)}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _attrs_to_parcel(attrs: dict) -> dict:
    """Convert raw ArcGIS attributes to a normalized parcel dict."""
    ls_date = attrs.get("LS_DATE")
    return {
        "loc_id": attrs.get("LOC_ID"),
        "site_addr": attrs.get("SITE_ADDR"),
        "city": attrs.get("CITY"),
        "owner": attrs.get("OWNER1"),
        "last_sale_date": _format_ls_date(ls_date),
        "last_sale_price": attrs.get("LS_PRICE"),
        "building_value": attrs.get("BLDG_VAL"),
        "land_value": attrs.get("LAND_VAL"),
        "total_value": attrs.get("TOTAL_VAL"),
        "use_code": attrs.get("USE_CODE"),
        "lot_size_acres": attrs.get("LOT_SIZE"),
        "year_built": attrs.get("YEAR_BUILT"),
        "building_area_sqft": attrs.get("BLD_AREA"),
        "units": attrs.get("UNITS"),
        "style": attrs.get("STYLE"),
        "num_rooms": attrs.get("NUM_ROOMS"),
        "fiscal_year": attrs.get("FY"),
        "source": "MassGIS Parcels",
    }


def _format_ls_date(ls_date) -> str | None:
    """Convert MassGIS integer date (YYYYMMDD) to ISO date string."""
    if not ls_date or not isinstance(ls_date, (int, float)) or ls_date < 10000:
        return None
    ls_int = int(ls_date)
    try:
        return f"{ls_int // 10000}-{(ls_int % 10000) // 100:02d}-{ls_int % 100:02d}"
    except Exception:
        return str(ls_int)


def _format_book_page(book, page) -> str | None:
    """Format registry book/page reference."""
    if book and page:
        return f"{book}/{page}"
    if book:
        return str(book)
    return None


def _empty_parcel() -> dict:
    return {
        "loc_id": None,
        "site_addr": None,
        "city": None,
        "owner": None,
        "last_sale_date": None,
        "last_sale_price": None,
        "building_value": None,
        "land_value": None,
        "total_value": None,
        "use_code": None,
        "lot_size_acres": None,
        "year_built": None,
        "building_area_sqft": None,
        "units": None,
        "style": None,
        "num_rooms": None,
        "fiscal_year": None,
        "geometry": None,
        "source": "MassGIS Parcels",
    }
