"""Plate Lookup Service - Vehicle info from license plate text.

Supports:
  - Plate Recognizer API ($75/mo) - plate text -> make/model/color/year
  - Mock mode (no API key configured) - returns plausible fake vehicle data
"""
from __future__ import annotations
import asyncio
import random
import httpx
from typing import Optional
from datetime import datetime

try:
    from config import PLATE_RECOGNIZER_API_KEY
except ImportError:
    PLATE_RECOGNIZER_API_KEY = ""


# ── Mock vehicle data for demo mode ──────────────────────────────────────────
_MOCK_MAKES = ["Toyota", "Ford", "Honda", "Chevrolet", "BMW", "Tesla", "Hyundai", "Nissan", "Kia", "Subaru"]
_MOCK_MODELS = {
    "Toyota": ["Camry", "Corolla", "RAV4", "Tacoma"],
    "Ford": ["F-150", "Explorer", "Mustang", "Escape"],
    "Honda": ["Civic", "Accord", "CR-V", "Pilot"],
    "Chevrolet": ["Silverado", "Equinox", "Malibu", "Tahoe"],
    "BMW": ["3 Series", "5 Series", "X5", "X3"],
    "Tesla": ["Model 3", "Model Y", "Model S", "Model X"],
    "Hyundai": ["Elantra", "Tucson", "Sonata", "Santa Fe"],
    "Nissan": ["Altima", "Rogue", "Sentra", "Pathfinder"],
    "Kia": ["Forte", "Sportage", "Soul", "Telluride"],
    "Subaru": ["Outback", "Forester", "Impreza", "Crosstrek"],
}
_MOCK_COLORS = ["White", "Black", "Silver", "Gray", "Red", "Blue", "Green", "Brown"]
_MOCK_TYPES = ["car", "suv", "truck", "car", "car", "suv"]


def _mock_vehicle(plate_text: str) -> dict:
    """Generate deterministic mock vehicle data from plate text."""
    seed = sum(ord(c) for c in plate_text)
    rng = random.Random(seed)
    make = rng.choice(_MOCK_MAKES)
    model = rng.choice(_MOCK_MODELS[make])
    color = rng.choice(_MOCK_COLORS)
    year = rng.randint(2012, 2024)
    vtype = rng.choice(_MOCK_TYPES)
    return {
        "make": make,
        "model": model,
        "color": color,
        "year": year,
        "vehicle_type": vtype,
        "region": "US",
        "vin": None,
        "provider": "mock",
        "raw": {"mock": True, "plate": plate_text},
    }


class PlateLookupClient:
    """
    Async client for vehicle lookups from plate text.

    Uses Plate Recognizer API when PLATE_RECOGNIZER_API_KEY is set,
    otherwise falls back to deterministic mock data.
    """

    BASE_URL = "https://api.platerecognizer.com/v1/plate-reader/"

    def __init__(self):
        self.api_key = PLATE_RECOGNIZER_API_KEY
        self._mock = not bool(self.api_key)

    async def lookup(self, plate_text: str, region: Optional[str] = "us") -> dict:
        """
        Look up vehicle info for a plate.

        Returns dict with keys: make, model, color, year, vehicle_type,
        region, vin, provider, raw.
        """
        if self._mock:
            # Tiny async delay to simulate network
            await asyncio.sleep(0.05)
            return _mock_vehicle(plate_text)

        return await self._plate_recognizer_lookup(plate_text, region)

    async def _plate_recognizer_lookup(self, plate_text: str, region: Optional[str]) -> dict:
        """Call Plate Recognizer API."""
        headers = {"Authorization": f"Token {self.api_key}"}
        data = {"plate": plate_text}
        if region:
            data["regions"] = [region]

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(self.BASE_URL, headers=headers, data=data)
                resp.raise_for_status()
                result = resp.json()

                # Parse Plate Recognizer response format
                if result.get("results"):
                    r = result["results"][0]
                    vehicle = r.get("vehicle", {})
                    return {
                        "make": vehicle.get("make", [{}])[0].get("name") if vehicle.get("make") else None,
                        "model": vehicle.get("model", [{}])[0].get("name") if vehicle.get("model") else None,
                        "color": vehicle.get("color", [{}])[0].get("name") if vehicle.get("color") else None,
                        "year": vehicle.get("year", [{}])[0].get("name") if vehicle.get("year") else None,
                        "vehicle_type": vehicle.get("type", [{}])[0].get("name") if vehicle.get("type") else None,
                        "region": r.get("region", {}).get("code"),
                        "vin": None,
                        "provider": "plate_recognizer",
                        "raw": result,
                    }
                return {"provider": "plate_recognizer", "raw": result, "make": None, "model": None}

            except httpx.HTTPError as e:
                return {"provider": "plate_recognizer_error", "error": str(e), "raw": {}, "make": None, "model": None}

    async def bulk_lookup(self, plates: list[str], region: Optional[str] = "us") -> list[dict]:
        """Look up multiple plates concurrently."""
        tasks = [self.lookup(p, region) for p in plates]
        return await asyncio.gather(*tasks)

    @property
    def is_mock(self) -> bool:
        return self._mock
