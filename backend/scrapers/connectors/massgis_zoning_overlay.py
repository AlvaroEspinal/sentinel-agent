"""
MassGIS Zoning Overlay Connector

Queries the MassGIS Level-3 Parcel Assessors dataset for land-use code (USE_CODE)
distributions within a town bounding box.  USE_CODE is the Massachusetts assessor
land-use classification — the closest statewide "zoning proxy" available via free
ArcGIS REST without auth.

A statewide municipal zoning-districts polygon layer does not exist as a single
public ArcGIS endpoint; MassGIS delegates zoning map hosting to individual
municipalities.  This connector therefore provides:

  1. use_code_summary   – parcel-count + total-acres per USE_CODE (fast stats query)
  2. zoning_features    – up to 2000 parcel features with USE_CODE + geometry for
                          the town's bbox (polygon overlay layer)

The USE_CODE taxonomy follows the Massachusetts DOR classification schedule:
  1000-series  Residential
  1300-series  Multi-family / mixed
  3000-series  Commercial / Industrial
  9xx          Exempt / utility / other

Endpoint:
  https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/
  L3_TAXPAR_POLY_ASSESS_gdb/FeatureServer/0/query
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

PARCELS_URL = (
    "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/"
    "L3_TAXPAR_POLY_ASSESS_gdb/FeatureServer/0/query"
)

# MA DOR use-code descriptions (abbreviated)
USE_CODE_LABELS: Dict[str, str] = {
    "101": "Single Family",
    "1010": "Single Family",
    "102": "Condominium",
    "1020": "Condominium",
    "104": "Two Family",
    "1040": "Two Family",
    "105": "Three Family",
    "1050": "Three Family",
    "111": "Apt < 8 Units",
    "112": "Apt ≥ 8 Units",
    "1110": "Apt < 8 Units",
    "1120": "Apt ≥ 8 Units",
    "121": "Mobile Home",
    "130": "Developable Land",
    "1300": "Developable Land",
    "132": "Vacant Res Land",
    "1320": "Vacant Res Land",
    "300": "General Commercial",
    "3000": "General Commercial",
    "310": "Retail",
    "3100": "Retail",
    "316": "Strip Mall",
    "320": "Office",
    "3200": "Office",
    "330": "Industrial",
    "3300": "Industrial",
    "340": "Warehouse",
    "3400": "Warehouse",
    "390": "Mixed Use",
    "3900": "Mixed Use",
    "400": "Agricultural",
    "4000": "Agricultural",
    "500": "Recreation",
    "5000": "Recreation",
    "900": "Exempt",
    "9000": "Exempt",
    "930": "Church / Religious",
    "930V": "Church / Religious (Vacant)",
    "970": "Government",
    "980": "Conservation",
    "990": "Other Exempt",
    "995": "Condo Common",
    "996": "Condo Common (Exempt)",
}

# Geometry fields to include for polygon overlay
_OVERLAY_FIELDS = "USE_CODE,SITE_ADDR,CITY,LOT_SIZE,BLDG_VAL,LAND_VAL,TOTAL_VAL"


def _describe_use_code(code: Optional[str]) -> str:
    if not code:
        return "Unknown"
    return USE_CODE_LABELS.get(code, USE_CODE_LABELS.get(code.lstrip("0"), "Other"))


# ── Client ────────────────────────────────────────────────────────────────────

class MassGISZoningOverlayClient:
    """
    Fetches zoning overlay data (via USE_CODE parcel stats) for a town bbox.
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_zoning_overlays(
        self,
        town_id: str,
        bbox_west: float,
        bbox_south: float,
        bbox_east: float,
        bbox_north: float,
    ) -> Dict[str, Any]:
        """
        Return structured zoning overlay data for the given town bbox.

        Returns
        -------
        dict with keys:
          town_id, bbox, timestamp,
          use_code_summary  (list of {use_code, label, parcel_count, total_acres}),
          zoning_features   (GeoJSON FeatureCollection — up to 2000 parcels),
          feature_count,
          error             (None on success, str on failure)
        """
        bbox_str = f"{bbox_west},{bbox_south},{bbox_east},{bbox_north}"
        timestamp = datetime.now(timezone.utc).isoformat()

        summary, summary_err = await self._fetch_use_code_summary(bbox_str)
        features, features_err = await self._fetch_parcel_features(bbox_str)

        error = summary_err or features_err

        return {
            "town_id": town_id,
            "bbox": bbox_str,
            "timestamp": timestamp,
            "source": "MassGIS L3 Parcels (USE_CODE)",
            "source_url": PARCELS_URL,
            "use_code_summary": summary,
            "zoning_features": features,
            "feature_count": len((features or {}).get("features", [])),
            "summary_count": len(summary),
            "error": error,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_use_code_summary(
        self, bbox_str: str
    ) -> tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Statistics query: parcel count + total acres per USE_CODE within bbox.
        This is a lightweight summary (no geometry).
        """
        params = {
            "where": "1=1",
            "geometry": bbox_str,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": "4326",
            "groupByFieldsForStatistics": "USE_CODE",
            "outStatistics": (
                '[{"statisticType":"count","onStatisticField":"OBJECTID",'
                '"outStatisticFieldName":"parcel_count"},'
                '{"statisticType":"sum","onStatisticField":"LOT_SIZE",'
                '"outStatisticFieldName":"total_acres"}]'
            ),
            "f": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(PARCELS_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            if "error" in data:
                return [], f"API error: {data['error']}"

            rows: List[Dict[str, Any]] = []
            for feat in data.get("features", []):
                attrs = feat.get("attributes", {})
                code = attrs.get("USE_CODE") or ""
                count = attrs.get("parcel_count") or 0
                acres = attrs.get("total_acres") or 0.0
                rows.append(
                    {
                        "use_code": code,
                        "label": _describe_use_code(code),
                        "parcel_count": int(count),
                        "total_acres": round(float(acres), 2) if acres else 0.0,
                    }
                )

            rows.sort(key=lambda r: -r["parcel_count"])
            logger.debug("USE_CODE summary: %d groups", len(rows))
            return rows, None

        except Exception as exc:
            logger.error("USE_CODE summary failed: %s", exc)
            return [], str(exc)

    async def _fetch_parcel_features(
        self, bbox_str: str
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Geometry query: return up to 2000 parcel polygons with USE_CODE for overlay.
        """
        params = {
            "where": "1=1",
            "geometry": bbox_str,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": "4326",
            "outSR": "4326",
            "outFields": _OVERLAY_FIELDS,
            "returnGeometry": "true",
            "resultRecordCount": 2000,
            "f": "geojson",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(PARCELS_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            if "error" in data:
                return None, f"GeoJSON error: {data['error']}"

            # Enrich each feature with a human-readable label
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                code = props.get("USE_CODE")
                props["USE_CODE_LABEL"] = _describe_use_code(code)

            count = len(data.get("features", []))
            logger.debug("Parcel features: %d", count)
            return data, None

        except Exception as exc:
            logger.error("Parcel features failed: %s", exc)
            return None, str(exc)
