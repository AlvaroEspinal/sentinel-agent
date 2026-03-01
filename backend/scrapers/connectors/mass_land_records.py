"""
Ownership & deed data from MassGIS Property Tax Parcels.

Provides current owner, mailing address, last sale date/price,
and registry book/page references using MassGIS ArcGIS Feature Service.

Note: masslandrecords.com blocks automated access (IP-level bot detection),
so we derive ownership data from the MassGIS assessor records instead.
"""

import httpx
from typing import Dict, List, Optional
from datetime import datetime

PARCELS_URL = (
    "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/"
    "L3_TAXPAR_POLY_ASSESS_gdb/FeatureServer/0/query"
)

OWNERSHIP_FIELDS = (
    "OWNER1,OWN_ADDR,OWN_CITY,OWN_STATE,OWN_ZIP,OWN_CO,"
    "LS_DATE,LS_PRICE,LS_BOOK,LS_PAGE,"
    "SITE_ADDR,CITY,TOTAL_VAL,BLDG_VAL,LAND_VAL,USE_CODE,YEAR_BUILT,LOT_SIZE"
)

# Cache: "lat|lon" → result dict
_cache: Dict[str, Dict] = {}


def _format_date(raw: Optional[str]) -> Optional[str]:
    """Convert MassGIS date string 'YYYYMMDD' to 'MM/DD/YYYY'."""
    if not raw or len(raw) < 8:
        return raw
    try:
        dt = datetime.strptime(raw.strip(), "%Y%m%d")
        return dt.strftime("%m/%d/%Y")
    except ValueError:
        return raw


async def get_ownership_records(lat: float, lon: float) -> Dict:
    """
    Get ownership and deed records for a parcel at the given coordinates.

    Returns:
        {
            "ownership": { owner, address, city, state, zip },
            "records": [ { doc_type, grantee, recording_date, book_page, consideration, ... } ],
            "total": int,
            "source": "MassGIS Property Tax Parcels"
        }
    """
    cache_key = f"{lat:.6f}|{lon:.6f}"
    if cache_key in _cache:
        return _cache[cache_key]

    params = {
        "where": "1=1",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": OWNERSHIP_FIELDS,
        "returnGeometry": "false",
        "f": "json",
        "inSR": "4326",
        "outSR": "4326",
        "resultRecordCount": 1,
    }

    result = {
        "ownership": None,
        "records": [],
        "total": 0,
        "source": "MassGIS Property Tax Parcels",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(PARCELS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            _cache[cache_key] = result
            return result

        attrs = features[0].get("attributes", {})

        # Build ownership info
        owner = attrs.get("OWNER1", "")
        result["ownership"] = {
            "owner": owner or "Unknown",
            "mailing_address": attrs.get("OWN_ADDR", ""),
            "mailing_city": attrs.get("OWN_CITY", ""),
            "mailing_state": attrs.get("OWN_STATE", ""),
            "mailing_zip": attrs.get("OWN_ZIP", ""),
            "site_address": attrs.get("SITE_ADDR", ""),
            "city": attrs.get("CITY", ""),
            "total_assessed_value": attrs.get("TOTAL_VAL"),
            "building_value": attrs.get("BLDG_VAL"),
            "land_value": attrs.get("LAND_VAL"),
        }

        # Build deed record from last sale data
        ls_date = attrs.get("LS_DATE")
        ls_price = attrs.get("LS_PRICE")
        ls_book = attrs.get("LS_BOOK")
        ls_page = attrs.get("LS_PAGE")

        if ls_date or ls_price:
            book_page = None
            if ls_book and ls_page:
                book_page = f"{ls_book}/{ls_page}"
            elif ls_book:
                book_page = ls_book

            record = {
                "doc_type": "DEED",
                "grantor": None,
                "grantee": owner or None,
                "recording_date": _format_date(ls_date),
                "book_page": book_page,
                "consideration": ls_price if ls_price and ls_price > 0 else None,
                "description": f"Last recorded sale — {attrs.get('SITE_ADDR', 'N/A')}, {attrs.get('CITY', '')}",
                "source": "MassGIS",
            }
            result["records"].append(record)
            result["total"] = 1

        _cache[cache_key] = result
        return result

    except Exception as e:
        print(f"[LandRecords] MassGIS query failed: {e}")
        return result
