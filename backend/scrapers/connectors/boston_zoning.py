import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)

class BostonZoningClient:
    """
    Client for querying the City of Boston Zoning Districts ArcGIS REST endpoint.
    Source: https://gis.bostonplans.org/hosting/rest/services/Zoning_Districts/FeatureServer/0
    """
    BASE_URL = "https://gis.bostonplans.org/hosting/rest/services/Zoning_Districts/FeatureServer/0/query"
    
    async def get_zoning_in_bbox(self, bbox: str) -> Optional[Dict[str, Any]]:
        """
        Fetch zoning district polygons intersecting the given bounding box.
        bbox format: 'xmin,ymin,xmax,ymax' (e.g., '-71.1,42.3,-71.0,42.4')
        """
        params = {
            "where": "1=1",
            "f": "geojson",
            "geometry": bbox,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "DISTRICT,ARTICLE",
            "returnGeometry": "true",
            "outSR": "4326",
            "inSR": "4326"
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.BASE_URL, params=params)
                if response.status_code != 200:
                    logger.error(f"Boston Zoning Error: {response.status_code} - {response.text}")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error fetching Boston Zoning for bbox {bbox}: {e}")
            return None
