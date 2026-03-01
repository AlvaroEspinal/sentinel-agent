"""
Parcl Intelligence — Scraper Connectors

Municipal permit data connectors for Massachusetts municipalities.
Each connector implements async data fetching from a specific source type.
"""

from .viewpointcloud import ViewpointCloudClient, fetch_general_settings
from .socrata import SocrataConnector, SOCRATA_TOWNS
from .normalize import normalize_permit, parse_date

__all__ = [
    "ViewpointCloudClient",
    "fetch_general_settings",
    "SocrataConnector",
    "SOCRATA_TOWNS",
    "normalize_permit",
    "parse_date",
]
