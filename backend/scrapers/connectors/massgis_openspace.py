import httpx
import logging
import asyncio
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MassGISOpenSpaceClient:
    """Client for querying MassGIS Open Space & Conservation Restriction endpoints."""
    
    # Layer 0 might be Open Space (Public)
    # Different layers in different feature servers exist, but keeping it simple with the main open space layer
    # We'll use the Public_Conservation_Lands2 (often layer 0) and Conservation_Restriction_Areas2
    
    # Using the standard generalized feature server for conservation land
    BASE_URL = "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/Public_Conservation_Lands2/FeatureServer/0/query"
    
    async def get_openspace_in_bbox(self, bbox: str) -> Optional[Dict[str, Any]]:
        """
        Fetch open space & conservation lands intersecting the given bounding box.
        bbox format: 'xmin,ymin,xmax,ymax'
        """
        params = {
            "where": "1=1",
            "f": "geojson",
            "geometry": bbox,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": "true",
            "outSR": "4326",
            "inSR": "4326"
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.BASE_URL, params=params)
                if response.status_code != 200:
                    logger.error(f"MassGIS OpenSpace Error: {response.status_code} - {response.text}")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error fetching MassGIS open space for bbox {bbox}: {e}")
            return None
