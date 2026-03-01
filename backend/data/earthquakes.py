"""
USGS Earthquake / Seismic Activity Feed.

Provides real-time earthquake data from the United States Geological Survey (USGS)
GeoJSON feed. Includes magnitude, depth, location, and tsunami warnings.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx
from loguru import logger

# ── USGS GeoJSON Feed endpoints ──────────────────────────────────────────────
# These are real, free, no-auth-required endpoints
USGS_BASE = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary"
USGS_FEEDS = {
    "significant_hour": f"{USGS_BASE}/significant_hour.geojson",
    "significant_day": f"{USGS_BASE}/significant_day.geojson",
    "significant_week": f"{USGS_BASE}/significant_week.geojson",
    "significant_month": f"{USGS_BASE}/significant_month.geojson",
    "m4.5_day": f"{USGS_BASE}/4.5_day.geojson",
    "m4.5_week": f"{USGS_BASE}/4.5_week.geojson",
    "m2.5_day": f"{USGS_BASE}/2.5_day.geojson",
    "m2.5_week": f"{USGS_BASE}/2.5_week.geojson",
    "m1.0_day": f"{USGS_BASE}/1.0_day.geojson",
    "m1.0_week": f"{USGS_BASE}/1.0_week.geojson",
    "all_hour": f"{USGS_BASE}/all_hour.geojson",
    "all_day": f"{USGS_BASE}/all_day.geojson",
    "all_week": f"{USGS_BASE}/all_week.geojson",
}


class EarthquakeClient:
    """Client for real-time earthquake/seismic data from USGS."""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._cache: dict[str, list[dict]] = {}
        self._cache_time: dict[str, float] = {}
        self._cache_ttl = 300  # 5 minute cache

    async def get_earthquakes(
        self,
        feed: str = "m2.5_day",
        min_magnitude: Optional[float] = None,
        limit: int = 500,
    ) -> list[dict]:
        """Fetch earthquake data from USGS GeoJSON feed.

        Args:
            feed: Feed name from USGS_FEEDS (e.g. 'm4.5_week', 'all_day')
            min_magnitude: Optional minimum magnitude filter
            limit: Maximum number of earthquakes to return

        Returns:
            List of earthquake dicts with lat/lon/depth/magnitude/etc.
        """
        now = time.time()
        cache_key = f"{feed}_{min_magnitude}"

        if cache_key in self._cache and (now - self._cache_time.get(cache_key, 0)) < self._cache_ttl:
            return self._cache[cache_key][:limit]

        url = USGS_FEEDS.get(feed)
        if not url:
            logger.warning(f"Unknown USGS feed: {feed}, defaulting to m2.5_day")
            url = USGS_FEEDS["m2.5_day"]

        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
            data = resp.json()

            features = data.get("features", [])
            earthquakes = []

            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [0, 0, 0])

                magnitude = props.get("mag", 0)
                if min_magnitude is not None and (magnitude is None or magnitude < min_magnitude):
                    continue

                earthquake = {
                    "id": feature.get("id", ""),
                    "magnitude": magnitude,
                    "longitude": coords[0] if len(coords) > 0 else 0,
                    "latitude": coords[1] if len(coords) > 1 else 0,
                    "depth_km": coords[2] if len(coords) > 2 else 0,
                    "place": props.get("place", "Unknown"),
                    "time": props.get("time", 0),
                    "updated": props.get("updated", 0),
                    "tsunami": props.get("tsunami", 0) == 1,
                    "significance": props.get("sig", 0),
                    "felt": props.get("felt"),
                    "alert_level": props.get("alert"),  # green, yellow, orange, red
                    "status": props.get("status", "automatic"),
                    "event_type": props.get("type", "earthquake"),
                    "url": props.get("url", ""),
                    "detail_url": props.get("detail", ""),
                    "magnitude_type": props.get("magType", ""),
                    "severity": self._magnitude_to_severity(magnitude),
                }

                earthquakes.append(earthquake)

            # Sort by magnitude descending
            earthquakes.sort(key=lambda x: x.get("magnitude", 0) or 0, reverse=True)

            self._cache[cache_key] = earthquakes
            self._cache_time[cache_key] = now
            logger.info(f"Fetched {len(earthquakes)} earthquakes from USGS ({feed})")
            return earthquakes[:limit]

        except Exception as e:
            logger.error(f"USGS earthquake fetch error: {e}")
            return self._cache.get(cache_key, [])[:limit]

    async def get_significant_earthquakes(self, timeframe: str = "week") -> list[dict]:
        """Get only significant earthquakes (felt, damage potential)."""
        feed = f"significant_{timeframe}"
        return await self.get_earthquakes(feed=feed)

    async def get_earthquakes_near(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 500,
        feed: str = "all_week",
    ) -> list[dict]:
        """Get earthquakes near a specific point."""
        all_quakes = await self.get_earthquakes(feed=feed, limit=5000)

        nearby = []
        for quake in all_quakes:
            dist = self._haversine(
                latitude, longitude,
                quake["latitude"], quake["longitude"],
            )
            if dist <= radius_km:
                quake["distance_km"] = round(dist, 1)
                nearby.append(quake)

        return nearby

    @staticmethod
    def _magnitude_to_severity(mag: Optional[float]) -> str:
        """Convert earthquake magnitude to severity label."""
        if mag is None:
            return "unknown"
        if mag >= 7.0:
            return "major"
        if mag >= 6.0:
            return "strong"
        if mag >= 5.0:
            return "moderate"
        if mag >= 4.0:
            return "light"
        if mag >= 3.0:
            return "minor"
        return "micro"

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance in km between two lat/lon points."""
        import math
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + \
            math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
            math.sin(dlon / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
