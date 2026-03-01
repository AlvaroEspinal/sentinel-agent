"""
Zoning information connector for Massachusetts.

Since the National Zoning Atlas does not expose a public REST API
(it uses proprietary vector tiles), we derive zoning classification
from the MassGIS Property Tax Parcels USE_CODE field, which classifies
every parcel in all 351 MA municipalities by land use type.

USE_CODEs are standardized 3-digit codes defined by MA DOR:
  https://www.mass.gov/doc/property-type-classification-codes

This gives us a functional equivalent of zoning data: what the land
is classified and used as, which directly reflects the underlying
zoning district designation.
"""

import httpx

# MassGIS Parcels Feature Service — same service used by massgis_parcels.py
PARCELS_URL = "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/L3_TAXPAR_POLY_ASSESS_gdb/FeatureServer/0/query"

# Massachusetts DOR Property Type Classification Codes
# Source: https://www.mass.gov/doc/property-type-classification-codes
USE_CODE_MAP = {
    # Residential
    "101": {"name": "Single Family Residential", "category": "Residential", "desc": "Single family home on a single lot"},
    "102": {"name": "Condominium", "category": "Residential", "desc": "Individual condominium unit"},
    "103": {"name": "Mobile Home / Trailer Park", "category": "Residential", "desc": "Mobile home or trailer park"},
    "104": {"name": "Two-Family Residential", "category": "Residential", "desc": "Two-family dwelling (duplex)"},
    "105": {"name": "Three-Family Residential", "category": "Residential", "desc": "Three-family dwelling (triple decker)"},
    "109": {"name": "Multiple Houses", "category": "Residential", "desc": "Multiple houses on single lot"},
    "111": {"name": "Four-Eight Family", "category": "Residential", "desc": "Apartment building, 4-8 units"},
    "112": {"name": "Apartment Building", "category": "Residential", "desc": "Apartment building, 8+ units"},
    "121": {"name": "Rooming House", "category": "Residential", "desc": "Rooming or boarding house"},
    "130": {"name": "Residential Development", "category": "Residential", "desc": "Residential developable land"},
    "131": {"name": "Residential Undevelopable", "category": "Residential", "desc": "Residential potentially developable land"},
    "132": {"name": "Residential Undevelopable", "category": "Residential", "desc": "Residential undevelopable land"},
    # Commercial
    "300": {"name": "Hotel / Motel", "category": "Commercial", "desc": "Hotel or motel"},
    "310": {"name": "Retail Store", "category": "Commercial", "desc": "Retail store or shopping center"},
    "316": {"name": "Supermarket", "category": "Commercial", "desc": "Supermarket"},
    "320": {"name": "Office Building", "category": "Commercial", "desc": "Office building"},
    "321": {"name": "Medical Office", "category": "Commercial", "desc": "Medical or dental office"},
    "325": {"name": "Small Retail", "category": "Commercial", "desc": "Small retail / services"},
    "326": {"name": "Retail / Office", "category": "Commercial", "desc": "Combined retail and office space"},
    "330": {"name": "Restaurant", "category": "Commercial", "desc": "Restaurant or food service"},
    "340": {"name": "Gas Station", "category": "Commercial", "desc": "Gasoline station / auto service"},
    "350": {"name": "Mixed Use", "category": "Mixed Use", "desc": "Mixed-use commercial and residential"},
    "353": {"name": "Mixed Use", "category": "Mixed Use", "desc": "Mixed-use building"},
    "370": {"name": "Theater / Entertainment", "category": "Commercial", "desc": "Theater or entertainment venue"},
    "375": {"name": "Parking Lot", "category": "Commercial", "desc": "Commercial parking lot"},
    "380": {"name": "Marina", "category": "Commercial", "desc": "Marina or boat yard"},
    "390": {"name": "Commercial Developable", "category": "Commercial", "desc": "Commercial developable land"},
    # Industrial
    "400": {"name": "Manufacturing", "category": "Industrial", "desc": "Manufacturing / processing facility"},
    "401": {"name": "Warehouse", "category": "Industrial", "desc": "Warehouse or distribution center"},
    "402": {"name": "Lumber Yard", "category": "Industrial", "desc": "Lumber yard or building materials"},
    "410": {"name": "Sand & Gravel", "category": "Industrial", "desc": "Sand and gravel extraction"},
    "420": {"name": "R&D Facility", "category": "Industrial", "desc": "Research and development facility"},
    "430": {"name": "Industrial Developable", "category": "Industrial", "desc": "Industrial developable land"},
    # Exempt / Institutional
    "900": {"name": "Government", "category": "Institutional", "desc": "Federal, state, or local government"},
    "903": {"name": "Municipal", "category": "Institutional", "desc": "Municipal / city owned property"},
    "910": {"name": "Education", "category": "Institutional", "desc": "School or educational institution"},
    "920": {"name": "Religious", "category": "Institutional", "desc": "Church or religious organization"},
    "930": {"name": "Charitable", "category": "Institutional", "desc": "Charitable organization"},
    "950": {"name": "Open Space", "category": "Open Space", "desc": "Public open space, park, or recreation"},
    "960": {"name": "Conservation", "category": "Open Space", "desc": "Conservation land"},
}

# Broader category mapping for 3-digit codes by first digit
CATEGORY_MAP = {
    "1": {"category": "Residential", "allowed_uses": ["Single-Family", "Two-Family", "Multi-Family", "Condominiums"]},
    "2": {"category": "Open Space / Agriculture", "allowed_uses": ["Agriculture", "Open Space", "Conservation"]},
    "3": {"category": "Commercial", "allowed_uses": ["Retail", "Office", "Restaurant", "Services"]},
    "4": {"category": "Industrial", "allowed_uses": ["Manufacturing", "Warehouse", "R&D"]},
    "5": {"category": "Personal Property", "allowed_uses": []},
    "6": {"category": "Chapter Land", "allowed_uses": ["Agriculture", "Forestry", "Recreation"]},
    "7": {"category": "Other", "allowed_uses": []},
    "8": {"category": "Exempt – Non-Profit", "allowed_uses": ["Institutional", "Religious", "Charitable"]},
    "9": {"category": "Exempt – Government", "allowed_uses": ["Government", "Education", "Parks"]},
}


async def get_zoning(lat: float, lon: float, timeout: float = 15.0) -> dict:
    """
    Get zoning / land use classification for a coordinate point.

    Queries MassGIS Property Tax Parcels and interprets the USE_CODE
    field to provide zoning-equivalent classification data.

    Returns:
        {
            "zone_code": str | None,        -- MA DOR use code (e.g. "101")
            "zone_name": str | None,        -- Human-readable name
            "jurisdiction": str | None,     -- Town/city name
            "allowed_uses": list[str],      -- Typical allowed uses for this zone
            "min_lot_size_sqft": float|None, -- From parcel LOT_SIZE
            "max_height_ft": float | None,
            "description": str | None,
            "source": str,
        }
    """
    params = {
        "where": "1=1",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "USE_CODE,CITY,LOT_SIZE,SITE_ADDR,TOTAL_VAL,YEAR_BUILT",
        "returnGeometry": "false",
        "f": "json",
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
            return _empty_zoning()

        attrs = features[0].get("attributes", {})
        use_code = str(attrs.get("USE_CODE", "") or "").strip()
        city = attrs.get("CITY") or None
        lot_size_acres = attrs.get("LOT_SIZE")

        # Look up the USE_CODE
        code_info = USE_CODE_MAP.get(use_code)
        if code_info:
            zone_name = code_info["name"]
            category = code_info["category"]
            description = code_info["desc"]
        elif use_code and use_code[0] in CATEGORY_MAP:
            cat = CATEGORY_MAP[use_code[0]]
            zone_name = cat["category"]
            category = cat["category"]
            description = f"Property use code {use_code}"
        else:
            zone_name = None
            category = None
            description = "Unknown use code"

        # Build allowed uses list
        allowed_uses = []
        if category:
            cat_key = use_code[0] if use_code else None
            if cat_key and cat_key in CATEGORY_MAP:
                allowed_uses = CATEGORY_MAP[cat_key]["allowed_uses"]

        # Convert lot size from acres to sqft
        lot_size_sqft = None
        if lot_size_acres and isinstance(lot_size_acres, (int, float)) and lot_size_acres > 0:
            lot_size_sqft = round(lot_size_acres * 43560, 0)

        zone_code = f"USE-{use_code}" if use_code else None

        return {
            "zone_code": zone_code,
            "zone_name": zone_name,
            "jurisdiction": city,
            "state": "MA",
            "allowed_uses": allowed_uses,
            "min_lot_size_sqft": lot_size_sqft,
            "max_height_ft": None,  # Not available from parcel data
            "max_units": None,
            "max_density": None,
            "description": description,
            "source": "MassGIS Parcels (MA DOR Use Codes)",
        }

    except Exception as e:
        print(f"[Zoning] Error querying zoning for ({lat}, {lon}): {e}")
        return _empty_zoning()


def _empty_zoning() -> dict:
    return {
        "zone_code": None,
        "zone_name": None,
        "jurisdiction": None,
        "state": None,
        "allowed_uses": [],
        "min_lot_size_sqft": None,
        "max_height_ft": None,
        "max_units": None,
        "max_density": None,
        "description": "No zoning data available for this location",
        "source": "MassGIS Parcels (MA DOR Use Codes)",
    }
