"""
Real-time satellite orbital tracking using CelesTrak TLE data.

Fetches Two-Line Element (TLE) sets from CelesTrak and computes satellite
positions using simplified SGP4 propagation. Provides NORAD catalog IDs,
orbital elements, and real-time lat/lon/alt positions.
"""
from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from loguru import logger

# ── CelesTrak TLE endpoints ──────────────────────────────────────────────────
CELESTRAK_BASE = "https://celestrak.org/NORAD/elements/gp.php"
TLE_CATEGORIES = {
    "active": "active",
    "stations": "stations",
    "visual": "visual",
    "starlink": "supplemental/starlink",
    "gps": "gps-ops",
    "weather": "weather",
    "science": "science",
    "military": "military",
}

# ── Simplified SGP4 constants ────────────────────────────────────────────────
MU = 398600.4418          # Earth's gravitational parameter (km³/s²)
RE = 6378.137             # Earth's equatorial radius (km)
J2 = 1.08263e-3           # Second zonal harmonic
TWO_PI = 2.0 * math.pi
DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi
MIN_PER_DAY = 1440.0
SEC_PER_DAY = 86400.0


def _parse_tle(line1: str, line2: str) -> dict:
    """Parse a TLE pair into orbital elements."""
    norad_id = int(line1[2:7].strip())
    epoch_year = int(line1[18:20])
    epoch_day = float(line1[20:32])

    # Full year
    if epoch_year < 57:
        epoch_year += 2000
    else:
        epoch_year += 1900

    inclination = float(line2[8:16].strip())
    raan = float(line2[17:25].strip())

    ecc_str = line2[26:33].strip()
    eccentricity = float(f"0.{ecc_str}")

    arg_perigee = float(line2[34:42].strip())
    mean_anomaly = float(line2[43:51].strip())
    mean_motion = float(line2[52:63].strip())  # revs/day
    rev_number = int(line2[63:68].strip()) if line2[63:68].strip() else 0

    return {
        "norad_id": norad_id,
        "epoch_year": epoch_year,
        "epoch_day": epoch_day,
        "inclination": inclination,
        "raan": raan,
        "eccentricity": eccentricity,
        "arg_perigee": arg_perigee,
        "mean_anomaly": mean_anomaly,
        "mean_motion": mean_motion,
        "rev_number": rev_number,
    }


def _propagate_simple(elements: dict, timestamp: float) -> dict:
    """Simplified orbital propagation to get lat/lon/alt at a given time.

    Uses mean-motion based Keplerian propagation (no drag perturbation).
    Good enough for visualization at ~1km accuracy.
    """
    # Time since epoch
    epoch_jd = _epoch_to_jd(elements["epoch_year"], elements["epoch_day"])
    now_jd = timestamp / SEC_PER_DAY + 2440587.5
    dt_min = (now_jd - epoch_jd) * MIN_PER_DAY

    n = elements["mean_motion"]  # revs/day
    n_rad = n * TWO_PI / MIN_PER_DAY  # rad/min

    # Semi-major axis from mean motion
    a = (MU / (n_rad / 60.0) ** 2) ** (1.0 / 3.0)

    # Mean anomaly at time t
    M = (elements["mean_anomaly"] * DEG2RAD + n_rad * dt_min) % TWO_PI

    # Solve Kepler's equation (Newton's method)
    e = elements["eccentricity"]
    E = M
    for _ in range(10):
        dE = (M - E + e * math.sin(E)) / (1.0 - e * math.cos(E))
        E += dE
        if abs(dE) < 1e-10:
            break

    # True anomaly
    sin_v = math.sqrt(1 - e * e) * math.sin(E) / (1 - e * math.cos(E))
    cos_v = (math.cos(E) - e) / (1 - e * math.cos(E))
    v = math.atan2(sin_v, cos_v)

    # Radius
    r = a * (1 - e * math.cos(E))

    # Argument of latitude
    u = v + elements["arg_perigee"] * DEG2RAD

    # RAAN with Earth rotation
    inc = elements["inclination"] * DEG2RAD
    raan = elements["raan"] * DEG2RAD

    # GMST (Greenwich Mean Sidereal Time)
    T = (now_jd - 2451545.0) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (now_jd - 2451545.0) + \
           0.000387933 * T * T
    gmst = (gmst % 360.0) * DEG2RAD

    # ECI coordinates
    x = r * (math.cos(raan) * math.cos(u) - math.sin(raan) * math.sin(u) * math.cos(inc))
    y = r * (math.sin(raan) * math.cos(u) + math.cos(raan) * math.sin(u) * math.cos(inc))
    z = r * math.sin(u) * math.sin(inc)

    # Rotate to ECEF
    x_ecef = x * math.cos(gmst) + y * math.sin(gmst)
    y_ecef = -x * math.sin(gmst) + y * math.cos(gmst)
    z_ecef = z

    # Geodetic coordinates
    lon = math.atan2(y_ecef, x_ecef) * RAD2DEG
    lat = math.atan2(z_ecef, math.sqrt(x_ecef ** 2 + y_ecef ** 2)) * RAD2DEG
    alt = r - RE  # Approximate altitude in km

    # Orbital period
    period_min = MIN_PER_DAY / n

    # Determine orbit type
    orbit_type = "LEO"
    if alt > 35000:
        orbit_type = "GEO"
    elif alt > 2000:
        orbit_type = "MEO"

    return {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "altitude_km": round(alt, 1),
        "orbit_type": orbit_type,
        "period_minutes": round(period_min, 1),
        "semi_major_axis_km": round(a, 1),
    }


def _epoch_to_jd(year: int, day_of_year: float) -> float:
    """Convert TLE epoch to Julian Date."""
    a = (14 - 1) // 12
    y = year + 4800 - a
    m = 1 + 12 * a - 3
    jd = 1 + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    return jd - 0.5 + day_of_year - 1


def _compute_orbit_path(elements: dict, timestamp: float, points: int = 72) -> list[dict]:
    """Compute a full orbital path (ground track) for visualization."""
    n = elements["mean_motion"]
    period_sec = SEC_PER_DAY / n
    path = []
    for i in range(points + 1):
        t = timestamp - period_sec / 2 + (period_sec * i / points)
        try:
            pos = _propagate_simple(elements, t)
            path.append({"lat": pos["latitude"], "lon": pos["longitude"], "alt": pos["altitude_km"]})
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
    return path


class SatelliteOrbitalClient:
    """Client for real-time satellite position tracking via CelesTrak TLE data."""

    def __init__(self):
        self._tle_cache: dict[str, list[dict]] = {}
        self._tle_cache_time: dict[str, float] = {}
        self._cache_ttl = 3600  # Refresh TLEs hourly
        self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def _fetch_tles(self, category: str = "active") -> list[dict]:
        """Fetch TLE data from CelesTrak for a given category."""
        cache_key = category
        now = time.time()

        if cache_key in self._tle_cache and (now - self._tle_cache_time.get(cache_key, 0)) < self._cache_ttl:
            return self._tle_cache[cache_key]

        try:
            cat_path = TLE_CATEGORIES.get(category, category)

            # Use GP data in JSON format when available, fall back to 3LE text
            url = f"{CELESTRAK_BASE}?GROUP={cat_path}&FORMAT=tle"
            resp = await self._http.get(url)
            resp.raise_for_status()

            text = resp.text.strip()
            lines = text.split("\n")

            satellites = []
            i = 0
            while i < len(lines) - 2:
                name = lines[i].strip()
                line1 = lines[i + 1].strip()
                line2 = lines[i + 2].strip()

                if line1.startswith("1 ") and line2.startswith("2 "):
                    try:
                        elements = _parse_tle(line1, line2)
                        elements["name"] = name
                        elements["line1"] = line1
                        elements["line2"] = line2
                        satellites.append(elements)
                    except (ValueError, IndexError) as e:
                        logger.debug(f"Skipping malformed TLE: {e}")
                    i += 3
                else:
                    i += 1

            self._tle_cache[cache_key] = satellites
            self._tle_cache_time[cache_key] = now
            logger.info(f"Fetched {len(satellites)} satellite TLEs for '{category}'")
            return satellites

        except Exception as e:
            logger.error(f"CelesTrak TLE fetch error ({category}): {e}")
            return self._tle_cache.get(cache_key, [])

    async def get_satellites(
        self,
        category: str = "stations",
        limit: int = 200,
    ) -> list[dict]:
        """Get current satellite positions for a given category.

        Returns list of satellite dicts with real-time lat/lon/alt/norad_id.
        """
        tles = await self._fetch_tles(category)
        now = time.time()

        results = []
        for elements in tles[:limit]:
            try:
                pos = _propagate_simple(elements, now)
                results.append({
                    "norad_id": elements["norad_id"],
                    "name": elements.get("name", f"NORAD {elements['norad_id']}"),
                    "latitude": pos["latitude"],
                    "longitude": pos["longitude"],
                    "altitude_km": pos["altitude_km"],
                    "orbit_type": pos["orbit_type"],
                    "period_minutes": pos["period_minutes"],
                    "inclination": elements["inclination"],
                    "category": category,
                })
            except (ValueError, ZeroDivisionError, OverflowError):
                continue

        return results

    async def get_all_tracked(self, limit: int = 500) -> list[dict]:
        """Get a combined feed of active satellites from multiple categories."""
        categories = ["stations", "visual", "science", "weather", "gps", "military"]
        per_cat = max(limit // len(categories), 20)

        tasks = [self.get_satellites(cat, limit=per_cat) for cat in categories]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        combined = []
        seen_ids = set()
        for result in all_results:
            if isinstance(result, Exception):
                continue
            for sat in result:
                if sat["norad_id"] not in seen_ids:
                    seen_ids.add(sat["norad_id"])
                    combined.append(sat)

        return combined[:limit]

    async def get_satellite_orbit(self, norad_id: int) -> Optional[dict]:
        """Get the orbital path for a specific satellite by NORAD ID."""
        # Search through cached TLEs
        for cache in self._tle_cache.values():
            for elements in cache:
                if elements["norad_id"] == norad_id:
                    now = time.time()
                    pos = _propagate_simple(elements, now)
                    path = _compute_orbit_path(elements, now)
                    return {
                        "norad_id": norad_id,
                        "name": elements.get("name", f"NORAD {norad_id}"),
                        "current_position": pos,
                        "orbit_path": path,
                        "inclination": elements["inclination"],
                        "eccentricity": elements["eccentricity"],
                        "period_minutes": pos["period_minutes"],
                    }

        # Not in cache — fetch active satellites and retry
        await self._fetch_tles("active")
        for elements in self._tle_cache.get("active", []):
            if elements["norad_id"] == norad_id:
                now = time.time()
                pos = _propagate_simple(elements, now)
                path = _compute_orbit_path(elements, now)
                return {
                    "norad_id": norad_id,
                    "name": elements.get("name", f"NORAD {norad_id}"),
                    "current_position": pos,
                    "orbit_path": path,
                    "inclination": elements["inclination"],
                    "eccentricity": elements["eccentricity"],
                    "period_minutes": pos["period_minutes"],
                }

        return None
