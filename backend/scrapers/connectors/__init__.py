"""
Parcl Intelligence — Scraper Connectors

Municipal permit data connectors for Massachusetts municipalities.
Each connector implements async data fetching from a specific source type.
"""

from .viewpointcloud import ViewpointCloudClient, fetch_general_settings
from .socrata import SocrataConnector, SOCRATA_TOWNS
from .normalize import normalize_permit, parse_date
from .town_config import TARGET_TOWNS, TownConfig, get_all_towns, get_town
from .firecrawl_client import FirecrawlClient
from .meeting_minutes import MeetingMinutesScraper
from .llm_extractor import LLMExtractor

__all__ = [
    "ViewpointCloudClient",
    "fetch_general_settings",
    "SocrataConnector",
    "SOCRATA_TOWNS",
    "normalize_permit",
    "parse_date",
    # Realtor MVP
    "TARGET_TOWNS",
    "TownConfig",
    "get_all_towns",
    "get_town",
    "FirecrawlClient",
    "MeetingMinutesScraper",
    "LLMExtractor",
]
