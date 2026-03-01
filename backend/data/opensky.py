"""OpenSky Network ADSB Flight Tracking Client"""
import httpx
import asyncio
from datetime import datetime
from typing import Optional
from loguru import logger
from config import OPENSKY_USERNAME, OPENSKY_PASSWORD


class FlightData:
    """Parsed flight state vector."""
    def __init__(self, raw: list):
        self.icao24: str = raw[0] or ""
        self.callsign: str = (raw[1] or "").strip()
        self.origin_country: str = raw[2] or ""
        self.time_position: Optional[int] = raw[3]
        self.last_contact: Optional[int] = raw[4]
        self.longitude: Optional[float] = raw[5]
        self.latitude: Optional[float] = raw[6]
        self.baro_altitude: Optional[float] = raw[7]
        self.on_ground: bool = raw[8] or False
        self.velocity: Optional[float] = raw[9]
        self.true_track: Optional[float] = raw[10]  # heading in degrees
        self.vertical_rate: Optional[float] = raw[11]
        self.sensors: Optional[list] = raw[12]
        self.geo_altitude: Optional[float] = raw[13]
        self.squawk: Optional[str] = raw[14]
        self.spi: bool = raw[15] or False
        self.position_source: int = raw[16] or 0
        self.category: int = raw[17] if len(raw) > 17 else 0

    def to_dict(self) -> dict:
        return {
            "icao24": self.icao24,
            "callsign": self.callsign,
            "origin_country": self.origin_country,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "altitude": self.baro_altitude or self.geo_altitude,
            "velocity": self.velocity,
            "heading": self.true_track,
            "on_ground": self.on_ground,
            "vertical_rate": self.vertical_rate,
            "category": self.category,
        }


class OpenSkyClient:
    """Client for the OpenSky Network REST API (free, public OSINT)."""

    BASE_URL = "https://opensky-network.org/api"

    def __init__(self):
        auth = None
        if OPENSKY_USERNAME and OPENSKY_PASSWORD:
            auth = (OPENSKY_USERNAME, OPENSKY_PASSWORD)
        self._auth = auth

    async def get_all_states(
        self,
        bbox: Optional[tuple[float, float, float, float]] = None,
    ) -> list[dict]:
        """Get all current flight state vectors. bbox = (lat_min, lat_max, lon_min, lon_max)."""
        params = {}
        if bbox:
            params["lamin"] = bbox[0]
            params["lamax"] = bbox[1]
            params["lomin"] = bbox[2]
            params["lomax"] = bbox[3]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                kwargs = {"params": params}
                if self._auth:
                    kwargs["auth"] = self._auth
                resp = await client.get(f"{self.BASE_URL}/states/all", **kwargs)
                resp.raise_for_status()
                data = resp.json()

                if not data or not data.get("states"):
                    return []

                flights = []
                for state in data["states"]:
                    try:
                        fd = FlightData(state)
                        if fd.latitude is not None and fd.longitude is not None:
                            flights.append(fd.to_dict())
                    except (IndexError, TypeError):
                        continue
                logger.info(f"OpenSky: fetched {len(flights)} flights")
                return flights

        except httpx.HTTPStatusError as e:
            logger.warning(f"OpenSky API error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"OpenSky fetch failed: {e}")
            return []

    async def get_flights_in_geofence(
        self, lat: float, lon: float, radius_km: float = 50
    ) -> list[dict]:
        """Get flights within a radius of a point."""
        # Approximate bounding box from center + radius
        deg_offset = radius_km / 111.0  # ~111km per degree
        bbox = (
            lat - deg_offset,
            lat + deg_offset,
            lon - deg_offset,
            lon + deg_offset,
        )
        return await self.get_all_states(bbox=bbox)

    async def track_corporate_jets(
        self, icao_list: list[str]
    ) -> list[dict]:
        """Track specific aircraft by ICAO24 addresses (e.g., corporate jets)."""
        all_states = await self.get_all_states()
        return [f for f in all_states if f["icao24"] in icao_list]

    def get_source_provenance(self) -> dict:
        return {
            "source_type": "api",
            "source_url": self.BASE_URL,
            "source_provider": "OpenSky Network",
            "is_publicly_available": True,
            "mnpi_classification": "PUBLIC_OSINT",
        }
