"""
FEMA National Flood Hazard Layer (NFHL) connector.

Queries the ArcGIS REST service for flood zone designations at a given lat/lon.
Layer 28 = Flood Hazard Zones.
Free, no API key required.
"""

import httpx

NFHL_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"

# Human-readable flood zone descriptions
ZONE_DESCRIPTIONS = {
    "A": "High Risk - 1% annual chance of flooding (no BFE determined)",
    "AE": "High Risk - 1% annual chance of flooding (BFE determined)",
    "AH": "High Risk - 1% annual chance of shallow flooding (1-3ft)",
    "AO": "High Risk - 1% annual chance of shallow flooding (sheet flow)",
    "AR": "High Risk - Temporarily increased risk due to levee restoration",
    "A99": "High Risk - Federal flood protection system under construction",
    "V": "High Risk - Coastal flood zone with wave action",
    "VE": "High Risk - Coastal flood zone with wave action (BFE determined)",
    "X": "Minimal Risk - Outside the 0.2% annual chance floodplain",
    "D": "Undetermined Risk - Possible but undetermined flood hazards",
}

RISK_LEVELS = {
    "A": "high",
    "AE": "high",
    "AH": "high",
    "AO": "high",
    "AR": "high",
    "A99": "high",
    "V": "very_high",
    "VE": "very_high",
    "X": "minimal",
    "D": "undetermined",
}


async def get_flood_zone(lat: float, lon: float, timeout: float = 15.0) -> dict:
    """
    Query FEMA NFHL for the flood zone at a given coordinate.

    Returns:
        {
            "flood_zone": "AE" | "X" | "V" | etc.,
            "zone_subtype": str | None,
            "in_sfha": bool,  # Special Flood Hazard Area
            "base_flood_elevation": float | None,
            "risk_level": "minimal" | "moderate" | "high" | "very_high" | "undetermined",
            "description": str,
            "source": "FEMA NFHL",
        }
    """
    params = {
        "where": "1=1",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE",
        "returnGeometry": "false",
        "f": "json",
        "inSR": "4326",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(NFHL_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            return {
                "flood_zone": None,
                "zone_subtype": None,
                "in_sfha": False,
                "base_flood_elevation": None,
                "risk_level": "undetermined",
                "description": "No FEMA flood zone data available for this location",
                "source": "FEMA NFHL",
            }

        attrs = features[0].get("attributes", {})
        zone = attrs.get("FLD_ZONE", "")
        zone_sub = attrs.get("ZONE_SUBTY") or None
        sfha = attrs.get("SFHA_TF", "F") == "T"
        bfe = attrs.get("STATIC_BFE")

        # Clean up BFE — can be -9999 or similar sentinel values
        if bfe is not None and (bfe < -100 or bfe > 10000):
            bfe = None

        return {
            "flood_zone": zone or None,
            "zone_subtype": zone_sub,
            "in_sfha": sfha,
            "base_flood_elevation": bfe,
            "risk_level": RISK_LEVELS.get(zone, "undetermined"),
            "description": ZONE_DESCRIPTIONS.get(zone, f"Flood Zone {zone}"),
            "source": "FEMA NFHL",
        }

    except Exception as e:
        print(f"[FEMA] Error querying flood zone for ({lat}, {lon}): {e}")
        return {
            "flood_zone": None,
            "zone_subtype": None,
            "in_sfha": False,
            "base_flood_elevation": None,
            "risk_level": "undetermined",
            "description": f"Error querying FEMA: {e}",
            "source": "FEMA NFHL",
        }
