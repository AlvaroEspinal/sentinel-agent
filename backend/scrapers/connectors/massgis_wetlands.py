import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MassGISWetlandsClient:
    """Client for querying the MassGIS DEP Wetlands ArcGIS REST endpoint."""
    
    BASE_URL = "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/Freshwater_Wetlands_Pub3/FeatureServer/0/query"
    
    async def get_wetlands_in_bbox(self, bbox: str) -> Optional[Dict[str, Any]]:
        """
        Fetch wetlands intersecting the given bounding box.
        bbox format: 'xmin,ymin,xmax,ymax' (e.g., '-71.3,42.3,-71.2,42.4')
        """
        params = {
            "where": "1=1",
            "f": "geojson",
            "geometry": bbox,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "inSR": "4326"
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.BASE_URL, params=params)
                if response.status_code != 200:
                    logger.error(f"MassGIS Wetlands Error: {response.status_code} - {response.text}")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error fetching MassGIS wetlands for bbox {bbox}: {e}")
            return None
