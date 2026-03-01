"""
Nominatim (OpenStreetMap) forward geocoder with in-memory caching.

Converts address strings → lat/lon coordinates.
Public API: 1 request/second limit.
"""

import asyncio
import time
from typing import Dict, Optional

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ParclIntelligence/1.0 (real-estate-platform)"

# In-memory cache: address_key → geocode result
_cache: Dict[str, Dict] = {}
_last_request_time: float = 0.0


async def geocode(
    address: str,
    country_codes: str = "us",
    timeout: float = 10.0,
) -> Dict:
    """
    Forward geocode an address string to lat/lon.

    Returns:
        {
            "lat": float | None,
            "lon": float | None,
            "display_name": str | None,
            "city": str | None,
            "state": str | None,
            "zip": str | None,
        }
    """
    global _last_request_time

    if not address or len(address.strip()) < 3:
        return _empty_result()

    # Check cache
    cache_key = address.lower().strip()
    if cache_key in _cache:
        return _cache[cache_key]

    # Rate limit: 1 req/sec for Nominatim public API
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < 1.1:
        await asyncio.sleep(1.1 - elapsed)

    try:
        params = {
            "q": address,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
            "countrycodes": country_codes,
        }
        headers = {"User-Agent": USER_AGENT}

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                NOMINATIM_URL,
                params=params,
                headers=headers,
                timeout=timeout,
            )
            _last_request_time = time.monotonic()
            resp.raise_for_status()
            results = resp.json()

        if not results:
            result = _empty_result()
            _cache[cache_key] = result
            return result

        top = results[0]
        addr_details = top.get("address", {})
        result = {
            "lat": float(top["lat"]),
            "lon": float(top["lon"]),
            "display_name": top.get("display_name", address),
            "city": (
                addr_details.get("city")
                or addr_details.get("town")
                or addr_details.get("village")
            ),
            "state": addr_details.get("state"),
            "zip": addr_details.get("postcode"),
        }
        _cache[cache_key] = result
        return result

    except Exception as e:
        print(f"[Geocoder] Error geocoding '{address}': {e}")
        return _empty_result()


async def geocode_batch(
    addresses: list[str],
    max_concurrent: int = 5,
    country_codes: str = "us",
) -> list[Dict]:
    """
    Geocode multiple addresses sequentially (respecting rate limit).
    Cached addresses return instantly.
    """
    results = []
    for addr in addresses[:max_concurrent]:
        result = await geocode(addr, country_codes=country_codes)
        results.append(result)
    return results


def get_cache_stats() -> Dict:
    """Return cache statistics."""
    return {
        "cached_addresses": len(_cache),
        "hit_rate": "N/A",
    }


def clear_cache():
    """Clear the geocode cache."""
    _cache.clear()


def _empty_result() -> Dict:
    return {
        "lat": None,
        "lon": None,
        "display_name": None,
        "city": None,
        "state": None,
        "zip": None,
    }
