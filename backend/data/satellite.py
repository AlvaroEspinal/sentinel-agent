"""Satellite Imagery Client (Optical + SAR sensor routing)."""
import asyncio
import httpx
import hashlib
import math
import random
from datetime import datetime, date, timedelta
from typing import Optional
from loguru import logger
from config import (
    PLANET_API_KEY,
    CAPELLA_API_KEY,
    SENTINEL_HUB_CLIENT_ID,
    SENTINEL_HUB_CLIENT_SECRET,
)


class SatelliteImageResult:
    """Represents a satellite image capture result."""
    def __init__(
        self,
        sensor_type: str,
        provider: str,
        latitude: float,
        longitude: float,
        captured_at: datetime,
        resolution_m: float,
        cloud_cover_pct: float = 0.0,
        image_id: str = "",
        thumbnail_url: str = "",
        metadata: dict = None,
    ):
        self.sensor_type = sensor_type  # "optical" or "sar"
        self.provider = provider
        self.latitude = latitude
        self.longitude = longitude
        self.captured_at = captured_at
        self.resolution_m = resolution_m
        self.cloud_cover_pct = cloud_cover_pct
        self.image_id = image_id or hashlib.md5(
            f"{provider}:{latitude}:{longitude}:{captured_at}".encode()
        ).hexdigest()[:16]
        self.thumbnail_url = thumbnail_url
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {
            "sensor_type": self.sensor_type,
            "provider": self.provider,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "captured_at": self.captured_at.isoformat(),
            "resolution_m": self.resolution_m,
            "cloud_cover_pct": self.cloud_cover_pct,
            "image_id": self.image_id,
            "metadata": self.metadata,
        }


class SatelliteClient:
    """Unified satellite imagery client supporting optical and SAR providers.

    In production, this connects to:
    - Planet Labs (optical, 3-5m resolution, daily global coverage)
    - Capella Space (SAR, sees through clouds/night, 0.5m resolution)
    - Maxar (optical, 0.3m resolution, tasking available)
    - Umbra (SAR, 0.25m resolution)

    For POC: generates realistic mock data with proper provenance.
    """

    def __init__(self):
        self.planet_key = PLANET_API_KEY
        self.capella_key = CAPELLA_API_KEY

    async def request_optical(
        self, lat: float, lon: float, radius_km: float = 10
    ) -> Optional[SatelliteImageResult]:
        """Request optical satellite imagery for a location."""
        if self.planet_key:
            return await self._planet_search(lat, lon, radius_km)
        # Mock for POC
        return self._mock_optical(lat, lon)

    async def request_sar(
        self, lat: float, lon: float, radius_km: float = 10
    ) -> Optional[SatelliteImageResult]:
        """Request SAR imagery (weather-immune, sees through clouds)."""
        if self.capella_key:
            return await self._capella_search(lat, lon, radius_km)
        # Mock for POC
        return self._mock_sar(lat, lon)

    async def _planet_search(
        self, lat: float, lon: float, radius_km: float
    ) -> Optional[SatelliteImageResult]:
        """Search Planet Labs catalog for recent imagery."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Planet Data API v2 search
                search_body = {
                    "filter": {
                        "type": "AndFilter",
                        "config": [
                            {
                                "type": "GeometryFilter",
                                "field_name": "geometry",
                                "config": {
                                    "type": "Point",
                                    "coordinates": [lon, lat],
                                },
                            },
                            {
                                "type": "DateRangeFilter",
                                "field_name": "acquired",
                                "config": {
                                    "gte": (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z",
                                },
                            },
                        ],
                    },
                    "item_types": ["PSScene"],
                }
                resp = await client.post(
                    "https://api.planet.com/data/v1/quick-search",
                    json=search_body,
                    auth=(self.planet_key, ""),
                )
                resp.raise_for_status()
                features = resp.json().get("features", [])
                if features:
                    f = features[0]
                    props = f.get("properties", {})
                    return SatelliteImageResult(
                        sensor_type="optical",
                        provider="Planet Labs",
                        latitude=lat,
                        longitude=lon,
                        captured_at=datetime.fromisoformat(
                            props.get("acquired", datetime.utcnow().isoformat()).replace("Z", "")
                        ),
                        resolution_m=props.get("gsd", 3.7),
                        cloud_cover_pct=props.get("cloud_cover", 0) * 100,
                        image_id=f.get("id", ""),
                        metadata={"item_type": "PSScene", "provider": "Planet Labs"},
                    )
        except Exception as e:
            logger.error(f"Planet API error: {e}")
        return self._mock_optical(lat, lon)

    async def _capella_search(
        self, lat: float, lon: float, radius_km: float
    ) -> Optional[SatelliteImageResult]:
        """Search Capella Space SAR catalog."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.capellaspace.com/catalog/search",
                    headers={"Authorization": f"Bearer {self.capella_key}"},
                    json={
                        "bbox": [
                            lon - radius_km / 111,
                            lat - radius_km / 111,
                            lon + radius_km / 111,
                            lat + radius_km / 111,
                        ],
                        "datetime": f"{(datetime.utcnow() - timedelta(days=14)).isoformat()}Z/..",
                        "limit": 1,
                    },
                )
                resp.raise_for_status()
                features = resp.json().get("features", [])
                if features:
                    f = features[0]
                    props = f.get("properties", {})
                    return SatelliteImageResult(
                        sensor_type="sar",
                        provider="Capella Space",
                        latitude=lat,
                        longitude=lon,
                        captured_at=datetime.fromisoformat(
                            props.get("datetime", datetime.utcnow().isoformat()).replace("Z", "")
                        ),
                        resolution_m=props.get("sar:resolution_range", 0.5),
                        image_id=f.get("id", ""),
                        metadata={"provider": "Capella Space", "mode": "spotlight"},
                    )
        except Exception as e:
            logger.error(f"Capella API error: {e}")
        return self._mock_sar(lat, lon)

    def _mock_optical(self, lat: float, lon: float) -> SatelliteImageResult:
        """Generate realistic mock optical satellite data for POC."""
        return SatelliteImageResult(
            sensor_type="optical",
            provider="Planet Labs (Mock)",
            latitude=lat,
            longitude=lon,
            captured_at=datetime.utcnow() - timedelta(hours=random.randint(2, 48)),
            resolution_m=3.7,
            cloud_cover_pct=random.uniform(0, 30),
            metadata={
                "mock": True,
                "vehicle_count": random.randint(50, 500),
                "thermal_signature_kw": random.uniform(100, 5000),
                "activity_level": random.choice(["low", "normal", "high"]),
                "change_detected": random.choice([True, False]),
            },
        )

    def _mock_sar(self, lat: float, lon: float) -> SatelliteImageResult:
        """Generate realistic mock SAR data for POC."""
        return SatelliteImageResult(
            sensor_type="sar",
            provider="Capella Space (Mock)",
            latitude=lat,
            longitude=lon,
            captured_at=datetime.utcnow() - timedelta(hours=random.randint(1, 24)),
            resolution_m=0.5,
            cloud_cover_pct=0,  # SAR sees through clouds
            metadata={
                "mock": True,
                "backscatter_db": random.uniform(-25, -5),
                "coherence": random.uniform(0.3, 0.95),
                "change_detected": random.choice([True, False]),
                "weather_immune": True,
            },
        )

    # ── GOES-16 Real-Time (FREE, geostationary weather satellite) ──────

    async def get_goes_imagery(
        self, lat: float, lon: float, band: int = 2, domain: str = "C"
    ) -> dict:
        """Fetch the latest GOES-16 GEOCOLOR imagery URL for the sector
        closest to the given lat/lon.

        GOES-16 covers the Western Hemisphere from geostationary orbit.
        Images refresh every ~5 min for CONUS and every ~1 min for
        mesoscale sectors.  No authentication required -- data is served
        from NOAA's public CDN.

        Returns a dict suitable for the unified ``get_all_imagery_sources``
        response.
        """
        sector_map = {
            "ne":  {"label": "Northeast",          "lat_range": (37, 48), "lon_range": (-82, -66)},
            "se":  {"label": "Southeast",           "lat_range": (24, 37), "lon_range": (-90, -75)},
            "umv": {"label": "Upper Mississippi Valley", "lat_range": (40, 50), "lon_range": (-100, -82)},
            "smv": {"label": "Southern Mississippi Valley", "lat_range": (28, 40), "lon_range": (-100, -85)},
            "gm":  {"label": "Gulf of Mexico",     "lat_range": (18, 31), "lon_range": (-98, -80)},
            "nrp": {"label": "Northern Rockies",   "lat_range": (40, 50), "lon_range": (-117, -100)},
            "srp": {"label": "Southern Rockies",    "lat_range": (30, 40), "lon_range": (-115, -100)},
            "pnw": {"label": "Pacific Northwest",  "lat_range": (40, 50), "lon_range": (-130, -117)},
            "psw": {"label": "Pacific Southwest",  "lat_range": (30, 40), "lon_range": (-130, -115)},
        }

        best_sector = None
        best_dist = float("inf")
        for code, info in sector_map.items():
            lat_mid = (info["lat_range"][0] + info["lat_range"][1]) / 2
            lon_mid = (info["lon_range"][0] + info["lon_range"][1]) / 2
            dist = math.hypot(lat - lat_mid, lon - lon_mid)
            if dist < best_dist:
                best_dist = dist
                best_sector = code

        if best_sector:
            image_url = (
                f"https://cdn.star.nesdis.noaa.gov/GOES16/ABI/SECTOR/"
                f"{best_sector}/GEOCOLOR/latest.jpg"
            )
            refresh_seconds = 60  # sector imagery refreshes ~ every minute
        else:
            # Fall back to full CONUS
            best_sector = "CONUS"
            image_url = (
                "https://cdn.star.nesdis.noaa.gov/GOES16/ABI/CONUS/"
                "GEOCOLOR/latest.jpg"
            )
            refresh_seconds = 300

        return {
            "provider": "NOAA GOES-16",
            "type": "weather_geostationary",
            "image_url": image_url,
            "sector": best_sector,
            "resolution_m": 500,
            "refresh_seconds": refresh_seconds,
            "captured_at": datetime.utcnow().isoformat(),
            "source": "PUBLIC_OSINT",
        }

    # ── NASA GIBS WMTS (FREE, near-real-time browse imagery) ─────────

    @staticmethod
    def _latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
        """Convert lat/lon to Web Mercator tile x/y at the given zoom level."""
        n = 2 ** zoom
        x = int((lon + 180.0) / 360.0 * n)
        lat_rad = math.radians(lat)
        y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        # Clamp to valid range
        x = max(0, min(n - 1, x))
        y = max(0, min(n - 1, y))
        return x, y

    async def get_gibs_tile(
        self,
        lat: float,
        lon: float,
        zoom: int = 6,
        layer: str = "MODIS_Terra_CorrectedReflectance_TrueColor",
    ) -> dict:
        """Construct a NASA GIBS WMTS tile URL for the given location.

        GIBS serves browse-quality imagery from instruments such as MODIS
        (Terra/Aqua) and VIIRS (Suomi-NPP / NOAA-20).  Data is typically
        available within 3-4 hours of acquisition.  No API key required.

        ``layer`` controls which product is returned.  Some common layers:
        - MODIS_Terra_CorrectedReflectance_TrueColor  (250 m, maxzoom 9)
        - VIIRS_SNPP_CorrectedReflectance_TrueColor    (250 m, maxzoom 12)
        - MODIS_Terra_Land_Surface_Temp_Day             (1 km, maxzoom 7)
        """
        # Determine max native zoom & resolution for the chosen layer
        if "VIIRS" in layer:
            maxzoom = 12
            resolution_m = 250
        else:
            maxzoom = 9
            resolution_m = 250

        effective_zoom = min(zoom, maxzoom)
        x, y = self._latlon_to_tile(lat, lon, effective_zoom)

        # GIBS tiles are dated -- use today, fall back to yesterday
        today = date.today()
        tile_date = today.isoformat()

        tile_url = (
            f"https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
            f"{layer}/default/{tile_date}/"
            f"GoogleMapsCompatible_Level{maxzoom}/"
            f"{effective_zoom}/{y}/{x}.jpg"
        )

        return {
            "provider": "NASA GIBS",
            "type": "near_realtime_browse",
            "tile_url": tile_url,
            "image_url": tile_url,
            "layer": layer,
            "date": tile_date,
            "zoom": effective_zoom,
            "resolution_m": resolution_m,
            "refresh_seconds": 3600 * 4,  # ~4 hours latency from acquisition
            "captured_at": tile_date,
            "source": "PUBLIC_OSINT",
        }

    # ── Sentinel-2 via Sentinel Hub / Copernicus (FREE tier w/ reg) ──

    async def get_sentinel2_tile(
        self, lat: float, lon: float, width: int = 512, height: int = 512
    ) -> dict:
        """Retrieve a Sentinel-2 true-color tile centred on lat/lon.

        If ``SENTINEL_HUB_CLIENT_ID`` and ``SENTINEL_HUB_CLIENT_SECRET``
        are configured, the method authenticates against the Copernicus
        Data Space Ecosystem (CDSE) and calls the Process API to render
        a 10 m true-color composite.

        Without credentials the method returns metadata (bbox, STAC
        search URL) so the caller knows what *would* be available.
        """
        # Build bounding box (~5 km half-side at the equator)
        delta = 0.045  # ~5 km in degrees at mid-latitudes
        bbox = [lon - delta, lat - delta, lon + delta, lat + delta]

        today = date.today()
        date_from = (today - timedelta(days=30)).isoformat()
        date_to = today.isoformat()

        # ── Authenticated path (Copernicus Data Space) ───────────
        if SENTINEL_HUB_CLIENT_ID and SENTINEL_HUB_CLIENT_SECRET:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    # 1. Obtain OAuth2 token
                    token_resp = await client.post(
                        "https://identity.dataspace.copernicus.eu/auth/realms/"
                        "CDSE/protocol/openid-connect/token",
                        data={
                            "grant_type": "client_credentials",
                            "client_id": SENTINEL_HUB_CLIENT_ID,
                            "client_secret": SENTINEL_HUB_CLIENT_SECRET,
                        },
                    )
                    token_resp.raise_for_status()
                    access_token = token_resp.json()["access_token"]

                    # 2. Call Process API -- true color evalscript
                    evalscript = (
                        "//VERSION=3\n"
                        "function setup(){return{input:[\"B04\",\"B03\",\"B02\"],"
                        "output:{bands:3}}}\n"
                        "function evaluatePixel(s){"
                        "return[2.5*s.B04,2.5*s.B03,2.5*s.B02]}"
                    )
                    process_body = {
                        "input": {
                            "bounds": {
                                "bbox": bbox,
                                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                            },
                            "data": [
                                {
                                    "type": "sentinel-2-l2a",
                                    "dataFilter": {
                                        "timeRange": {
                                            "from": f"{date_from}T00:00:00Z",
                                            "to": f"{date_to}T23:59:59Z",
                                        },
                                        "maxCloudCoverage": 30,
                                    },
                                }
                            ],
                        },
                        "output": {
                            "width": width,
                            "height": height,
                            "responses": [{"identifier": "default", "format": {"type": "image/jpeg"}}],
                        },
                        "evalscript": evalscript,
                    }
                    proc_resp = await client.post(
                        "https://sh.dataspace.copernicus.eu/api/v1/process",
                        headers={"Authorization": f"Bearer {access_token}"},
                        json=process_body,
                    )
                    proc_resp.raise_for_status()

                    # The response body is the JPEG image itself.  We
                    # don't persist it here -- the caller/API layer can
                    # stream it or base64-encode it.  We return the URL
                    # that was called so the tile can be re-fetched.
                    return {
                        "provider": "ESA Sentinel-2",
                        "type": "optical_multispectral",
                        "image_url": "https://sh.dataspace.copernicus.eu/api/v1/process",
                        "bbox": bbox,
                        "resolution_m": 10,
                        "last_capture_date": date_to,
                        "width": width,
                        "height": height,
                        "refresh_seconds": 86400 * 5,  # ~5-day revisit
                        "captured_at": date_to,
                        "source": "PUBLIC_OSINT",
                        "authenticated": True,
                    }
            except Exception as e:
                logger.error(f"Sentinel Hub Process API error: {e}")
                # Fall through to unauthenticated response

        # ── Unauthenticated fallback (metadata only) ─────────────
        stac_search_url = (
            "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
            f"?$filter=Collection/Name eq 'SENTINEL-2'"
            f" and OData.CSC.Intersects(area=geography'SRID=4326;"
            f"POINT({lon} {lat})')"
            f" and ContentDate/Start gt {date_from}T00:00:00.000Z"
            f"&$top=5&$orderby=ContentDate/Start desc"
        )

        return {
            "provider": "ESA Sentinel-2",
            "type": "optical_multispectral",
            "image_url": None,
            "bbox": bbox,
            "resolution_m": 10,
            "last_capture_date": date_to,
            "refresh_seconds": 86400 * 5,
            "captured_at": date_to,
            "source": "PUBLIC_OSINT",
            "authenticated": False,
            "stac_search_url": stac_search_url,
            "note": (
                "Sentinel Hub credentials (SENTINEL_HUB_CLIENT_ID / "
                "SENTINEL_HUB_CLIENT_SECRET) are not configured.  Set "
                "them to enable direct image retrieval.  Use the "
                "stac_search_url to browse available scenes manually."
            ),
        }

    # ── Unified multi-source endpoint ────────────────────────────

    async def get_all_imagery_sources(self, lat: float, lon: float) -> list[dict]:
        """Query every available imagery source in parallel and return a
        consolidated list.

        Each entry carries a uniform shape:
        ``{provider, type, image_url, resolution_m, refresh_seconds,
          captured_at, source}``
        along with any provider-specific extras.
        """
        tasks = [
            self.get_goes_imagery(lat, lon),
            self.get_gibs_tile(lat, lon),
            self.get_sentinel2_tile(lat, lon),
        ]

        results: list[dict] = []
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                logger.warning(f"Imagery source failed: {item}")
                continue
            results.append(item)

        # Also include the existing commercial sources (Planet / Capella)
        # wrapped in the same dict shape so the caller gets one flat list.
        try:
            optical = await self.request_optical(lat, lon)
            if optical:
                d = optical.to_dict()
                d.update({
                    "type": "optical_commercial",
                    "image_url": d.get("thumbnail_url", None),
                    "refresh_seconds": 86400,
                    "source": "COMMERCIAL_LICENSE",
                })
                results.append(d)
        except Exception as e:
            logger.warning(f"Planet optical failed in unified query: {e}")

        try:
            sar = await self.request_sar(lat, lon)
            if sar:
                d = sar.to_dict()
                d.update({
                    "type": "sar_commercial",
                    "image_url": d.get("thumbnail_url", None),
                    "refresh_seconds": 86400,
                    "source": "COMMERCIAL_LICENSE",
                })
                results.append(d)
        except Exception as e:
            logger.warning(f"Capella SAR failed in unified query: {e}")

        return results

    def get_source_provenance(self, provider: str = "Planet Labs") -> dict:
        return {
            "source_type": "satellite",
            "source_url": f"https://api.{'planet.com' if 'Planet' in provider else 'capellaspace.com'}",
            "source_provider": provider,
            "is_publicly_available": False,
            "mnpi_classification": "COMMERCIAL_LICENSE",
        }
