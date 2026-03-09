"""
Scrapers package for Parcl Intelligence.

Provides permit data loading, search, and scheduled scraping
for Massachusetts municipalities.
"""

try:
    from backend.scrapers.permit_loader import PermitDataLoader, haversine_km
    from backend.scrapers.scheduler import ScrapeScheduler
except ImportError:
    try:
        from .permit_loader import PermitDataLoader, haversine_km
        from .scheduler import ScrapeScheduler
    except ImportError:
        PermitDataLoader = None  # type: ignore
        haversine_km = None  # type: ignore
        ScrapeScheduler = None  # type: ignore

__all__ = ["PermitDataLoader", "haversine_km", "ScrapeScheduler"]
