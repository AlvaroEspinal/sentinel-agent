"""Weather Client for Sensor Orchestration (cloud cover detection)."""
import httpx
from typing import Optional
from loguru import logger
from config import OPENWEATHER_API_KEY


class WeatherCondition:
    """Parsed weather data for a location."""
    def __init__(self, data: dict):
        self.latitude = data.get("coord", {}).get("lat", 0)
        self.longitude = data.get("coord", {}).get("lon", 0)
        self.cloud_cover_pct = data.get("clouds", {}).get("all", 0)
        self.visibility_m = data.get("visibility", 10000)
        self.weather_main = data.get("weather", [{}])[0].get("main", "Clear")
        self.weather_desc = data.get("weather", [{}])[0].get("description", "")
        self.temp_k = data.get("main", {}).get("temp", 273)
        self.humidity = data.get("main", {}).get("humidity", 0)
        self.wind_speed = data.get("wind", {}).get("speed", 0)
        self.rain_1h = data.get("rain", {}).get("1h", 0)
        self.snow_1h = data.get("snow", {}).get("1h", 0)

    @property
    def is_optical_blocked(self) -> bool:
        """Returns True if cloud cover is too high for optical satellite."""
        return self.cloud_cover_pct > 60

    @property
    def has_precipitation(self) -> bool:
        return self.rain_1h > 0 or self.snow_1h > 0

    @property
    def visibility_km(self) -> float:
        return self.visibility_m / 1000.0

    def to_dict(self) -> dict:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "cloud_cover_pct": self.cloud_cover_pct,
            "visibility_km": self.visibility_km,
            "weather": self.weather_main,
            "description": self.weather_desc,
            "is_optical_blocked": self.is_optical_blocked,
            "has_precipitation": self.has_precipitation,
            "temp_celsius": round(self.temp_k - 273.15, 1),
        }


class WeatherClient:
    """OpenWeatherMap API client for sensor routing decisions."""

    BASE_URL = "https://api.openweathermap.org/data/2.5"

    def __init__(self):
        self.api_key = OPENWEATHER_API_KEY

    async def get_weather(self, lat: float, lon: float) -> Optional[WeatherCondition]:
        """Get current weather at a coordinate."""
        if not self.api_key:
            # Return mock clear weather if no API key
            logger.warning("No OpenWeather API key, returning mock clear weather")
            return WeatherCondition({
                "coord": {"lat": lat, "lon": lon},
                "clouds": {"all": 10},
                "visibility": 10000,
                "weather": [{"main": "Clear", "description": "clear sky"}],
                "main": {"temp": 293, "humidity": 50},
                "wind": {"speed": 5},
            })

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/weather",
                    params={"lat": lat, "lon": lon, "appid": self.api_key},
                )
                resp.raise_for_status()
                return WeatherCondition(resp.json())
        except Exception as e:
            logger.error(f"Weather API error for ({lat}, {lon}): {e}")
            return None

    async def check_optical_viability(self, lat: float, lon: float) -> tuple[bool, dict]:
        """Check if optical satellite imagery is viable at this location.
        Returns (is_viable, weather_data)."""
        weather = await self.get_weather(lat, lon)
        if weather is None:
            return True, {"error": "weather_unavailable", "fallback": True}
        return not weather.is_optical_blocked, weather.to_dict()

    def get_source_provenance(self) -> dict:
        return {
            "source_type": "api",
            "source_url": self.BASE_URL,
            "source_provider": "OpenWeatherMap",
            "is_publicly_available": True,
            "mnpi_classification": "PUBLIC_OSINT",
        }
