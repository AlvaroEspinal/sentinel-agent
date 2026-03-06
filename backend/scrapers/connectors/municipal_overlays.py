"""
Municipal Overlay District connector for Massachusetts.

Queries individual town ArcGIS REST FeatureServer endpoints for
specialized overlay districts (Historic, 40R Smart Growth,
Transit-Oriented Development, Planned Development Areas, etc.)

Each municipality publishes its own ArcGIS FeatureServer with overlay
polygons. This connector accepts a parameterized URL and returns
standard GeoJSON FeatureCollection dictionaries.

Usage:
    client = MunicipalOverlayClient(base_url)
    geojson = await client.query_bbox("-71.08,42.34,-71.05,42.36")
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known Massachusetts municipal overlay FeatureServer layers
# ---------------------------------------------------------------------------
# Each entry maps a human-readable key to a dict with the query URL,
# a description, and suggested outFields.
#
# To discover more layers, visit the municipality's ArcGIS REST
# services directory (e.g. https://gis.bostonplans.org/hosting/rest/services)
# and look for overlay / district FeatureServer layers.
# ---------------------------------------------------------------------------

KNOWN_LAYERS: Dict[str, Dict[str, str]] = {
    "boston_planned_development_areas": {
        "url": (
            "https://gis.bostonplans.org/hosting/rest/services/"
            "Planned_Development_Areas/FeatureServer/0/query"
        ),
        "description": "Boston Planned Development Areas (PDAs)",
        "out_fields": "PDA_NAME,STATUS,APPLICANT",
    },
    "boston_neighborhood_districts": {
        "url": (
            "https://gis.bostonplans.org/hosting/rest/services/Hosted/"
            "Boston_Neighborhood_Boundaries/FeatureServer/5/query"
        ),
        "description": "Boston Neighborhood Design Overlay Districts",
        "out_fields": "Neighborho",
    },
    "boston_coastal_flood_overlay": {
        "url": (
            "https://gis.bostonplans.org/hosting/rest/services/"
            "Coastal_Flood_Resilience_Overlay_District/FeatureServer/0/query"
        ),
        "description": "Boston Coastal Flood Resilience Overlay District",
        "out_fields": "*",
    },
    "boston_institutional_overlay": {
        "url": (
            "https://gis.bostonplans.org/hosting/rest/services/"
            "Institutional_Master_Plan_Overlay_District/FeatureServer/0/query"
        ),
        "description": "Boston Institutional Master Plan Overlay District",
        "out_fields": "*",
    },
    "boston_historic_districts": {
        "url": (
            "https://gis.bostonplans.org/hosting/rest/services/"
            "MHC_Historic_Inventory/MapServer/2/query"
        ),
        "description": "MHC Historic Inventory Polygon Layer",
        "out_fields": "HISTORIC_N",
    },
    # "cambridge_zoning_districts": {
    #     "url": (
    #         "https://gis.cambridgema.gov/arcgis/rest/services/"
    #         "Zoning/FeatureServer/0/query"
    #     ),
    #     "description": "Cambridge, MA Zoning Districts (includes overlays)",
    #     "out_fields": "*",
    # },
}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MunicipalOverlayClient:
    """
    Generic async client for querying any ArcGIS REST FeatureServer
    that publishes municipal overlay-district polygons.

    Parameters
    ----------
    base_url : str
        The full ``/query`` endpoint URL of the ArcGIS FeatureServer layer.
        Example: ``"https://gis.bostonplans.org/.../FeatureServer/0/query"``
    timeout : float
        Request timeout in seconds (default 20).
    """

    def __init__(self, base_url: str, *, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def query_bbox(
        self,
        bbox: str,
        *,
        out_fields: str = "*",
        max_records: int = 1000,
        where: str = "1=1",
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch overlay-district features intersecting a bounding box.

        Parameters
        ----------
        bbox : str
            Comma-separated envelope: ``"xmin,ymin,xmax,ymax"``
            in WGS-84 (EPSG:4326).  Example: ``"-71.08,42.34,-71.05,42.36"``
        out_fields : str
            Comma-separated attribute fields to return (default ``"*"``).
        max_records : int
            Maximum number of features to return.
        where : str
            Optional SQL WHERE filter (default ``"1=1"``).

        Returns
        -------
        dict | None
            A GeoJSON ``FeatureCollection`` dictionary, or ``None`` on error.
        """
        params = {
            "where": where,
            "geometry": bbox,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": "4326",
            "inSR": "4326",
            "f": "geojson",
            "resultRecordCount": max_records,
        }
        return await self._execute(params)

    async def query_point(
        self,
        lat: float,
        lon: float,
        *,
        out_fields: str = "*",
        buffer_deg: float = 0.0005,
    ) -> Optional[Dict[str, Any]]:
        """
        Convenience method: query overlays at a single point.

        Internally constructs a tiny bounding box around the point and
        delegates to :meth:`query_bbox`.

        Parameters
        ----------
        lat, lon : float
            WGS-84 coordinates.
        out_fields : str
            Attribute fields to return.
        buffer_deg : float
            Half-width of the envelope in degrees (~55 m at Boston's
            latitude).  Increase for broader searches.

        Returns
        -------
        dict | None
            GeoJSON ``FeatureCollection``, or ``None`` on error.
        """
        bbox = (
            f"{lon - buffer_deg},{lat - buffer_deg},"
            f"{lon + buffer_deg},{lat + buffer_deg}"
        )
        return await self.query_bbox(bbox, out_fields=out_fields)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _execute(self, params: dict) -> Optional[Dict[str, Any]]:
        """Send the query and return parsed GeoJSON."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.base_url, params=params)
                if resp.status_code != 200:
                    logger.error(
                        "[MunicipalOverlay] HTTP %s from %s — %s",
                        resp.status_code,
                        self.base_url,
                        resp.text[:300],
                    )
                resp.raise_for_status()
                data = resp.json()

            # ArcGIS may return an error object instead of GeoJSON
            if "error" in data:
                logger.error(
                    "[MunicipalOverlay] ArcGIS error: %s",
                    data["error"].get("message", data["error"]),
                )
                return None

            return data

        except httpx.HTTPStatusError as exc:
            logger.error(
                "[MunicipalOverlay] HTTP error querying %s: %s",
                self.base_url,
                exc,
            )
            return None
        except Exception as exc:
            logger.error(
                "[MunicipalOverlay] Unexpected error querying %s: %s",
                self.base_url,
                exc,
            )
            return None


# ---------------------------------------------------------------------------
# Helper – list available known layers
# ---------------------------------------------------------------------------

def list_known_layers() -> List[Dict[str, str]]:
    """Return a list of known MA overlay FeatureServer layers."""
    return [
        {"key": k, "url": v["url"], "description": v["description"]}
        for k, v in KNOWN_LAYERS.items()
    ]
