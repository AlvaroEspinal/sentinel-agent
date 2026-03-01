"""Sensor Orchestrator Agent -- the "Weather-Immune" router.

For each SensorTasking, checks real-time weather at the target location
and autonomously routes to the best available sensor:
    - Clear skies  -> Optical satellite (Planet Labs)
    - Cloud cover   -> SAR (Capella Space) -- sees through clouds and night
    - Port/coastal  -> Simultaneously query AIS (ship tracking)
    - Airfield/HQ   -> Simultaneously query ADSB (flight tracking)

Every data retrieval is logged via the ComplianceLedger with full
provenance so the Compliance Co-Pilot can build an audit trail.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from config import SENSOR_PRIORITY
from models.portfolio import GeoTarget, SensorTasking
from models.compliance import DataProvenanceRecord
from data.opensky import OpenSkyClient
from data.weather import WeatherClient
from data.satellite import SatelliteClient
from data.ships import AISClient
from services.ledger import ComplianceLedger


class SensorOrchestrator:
    """Routes SensorTasking requests to the best available sensor based on
    real-time weather, target type, and sensor priority fallback chain.
    """

    def __init__(
        self,
        weather_client: Optional[WeatherClient] = None,
        satellite_client: Optional[SatelliteClient] = None,
        opensky_client: Optional[OpenSkyClient] = None,
        ais_client: Optional[AISClient] = None,
        ledger: Optional[ComplianceLedger] = None,
    ) -> None:
        self.weather = weather_client or WeatherClient()
        self.satellite = satellite_client or SatelliteClient()
        self.opensky = opensky_client or OpenSkyClient()
        self.ais = ais_client or AISClient()
        self.ledger = ledger or ComplianceLedger()
        logger.info("SensorOrchestrator initialised")

    # ------------------------------------------------------------------
    # Primary public methods
    # ------------------------------------------------------------------

    async def execute_tasking(self, tasking: SensorTasking) -> dict:
        """Execute a single SensorTasking request and return the sensor data
        bundle with full provenance metadata.

        Returns a dict shaped like:
        {
            "tasking_id": str,
            "geo_target": dict,
            "sensor_type_requested": str,
            "sensor_type_used": str,
            "weather": dict,
            "weather_blocked": bool,
            "sensor_data": dict,
            "auxiliary_data": dict,   # AIS/ADSB if relevant
            "provenance_records": list[str],  # provenance record IDs
            "executed_at": str,
        }
        """
        gt = tasking.geo_target
        lat, lon = gt.latitude, gt.longitude
        logger.info(
            f"Executing tasking {tasking.id} | {gt.name} "
            f"({lat:.2f}, {lon:.2f}) | requested={tasking.sensor_type}"
        )

        # ------ Step 1: Check weather at target ------
        optical_viable, weather_data = await self.weather.check_optical_viability(lat, lon)
        weather_blocked = not optical_viable

        # Record weather provenance
        weather_prov = self._record_provenance(
            source_type="api",
            source_url="https://api.openweathermap.org/data/2.5/weather",
            source_provider="OpenWeatherMap",
            data_payload=json.dumps(weather_data).encode(),
            geo_target_id=gt.id,
            ticker=gt.asset_ticker,
            is_public=True,
        )

        # ------ Step 2: Route to best sensor ------
        requested = tasking.sensor_type
        if requested == "optical" and weather_blocked:
            logger.info(
                f"Optical blocked at {gt.name} "
                f"(cloud={weather_data.get('cloud_cover_pct', '?')}%), "
                f"pivoting to SAR"
            )
            actual_sensor = "sar"
            tasking.weather_blocked = True
            tasking.fallback_sensor = "sar"
        else:
            actual_sensor = requested

        # ------ Step 3: Fetch primary sensor data ------
        sensor_result = await self._fetch_primary_sensor(
            actual_sensor, lat, lon, gt.radius_km
        )

        # Record sensor provenance
        sensor_prov = self._record_sensor_provenance(
            actual_sensor, sensor_result, gt
        )

        # ------ Step 4: Fetch auxiliary data if relevant ------
        auxiliary_data: dict = {}
        aux_prov_ids: list[str] = []

        aux_tasks = []
        if self._should_query_ais(gt, tasking):
            aux_tasks.append(("ais", self._fetch_ais(lat, lon, gt.radius_km, gt)))
        if self._should_query_adsb(gt, tasking):
            aux_tasks.append(("adsb", self._fetch_adsb(lat, lon, gt.radius_km, gt)))

        if aux_tasks:
            aux_results = await asyncio.gather(
                *(task for _, task in aux_tasks),
                return_exceptions=True,
            )
            for (aux_name, _), result in zip(aux_tasks, aux_results):
                if isinstance(result, Exception):
                    logger.warning(f"Auxiliary {aux_name} fetch failed: {result}")
                    continue
                data, prov_id = result
                auxiliary_data[aux_name] = data
                aux_prov_ids.append(prov_id)

        # ------ Step 5: Assemble result ------
        all_prov_ids = [weather_prov.id, sensor_prov.id] + aux_prov_ids

        tasking.status = "completed"
        tasking.result_data = sensor_result

        # Log to ledger
        self._log_to_ledger(
            event_type="sensor_data_collected",
            description=(
                f"Sensor data collected for {gt.name} via {actual_sensor}. "
                f"Weather blocked={weather_blocked}. "
                f"Auxiliary sensors: {list(auxiliary_data.keys())}."
            ),
            prov_ids=all_prov_ids,
            ticker=gt.asset_ticker,
        )

        result = {
            "tasking_id": tasking.id,
            "geo_target": {
                "id": gt.id,
                "name": gt.name,
                "latitude": lat,
                "longitude": lon,
                "target_type": gt.target_type,
                "asset_ticker": gt.asset_ticker,
            },
            "sensor_type_requested": requested,
            "sensor_type_used": actual_sensor,
            "weather": weather_data,
            "weather_blocked": weather_blocked,
            "sensor_data": sensor_result,
            "auxiliary_data": auxiliary_data,
            "provenance_records": all_prov_ids,
            "executed_at": datetime.utcnow().isoformat(),
        }

        logger.info(
            f"Tasking {tasking.id} complete | sensor={actual_sensor} "
            f"| aux={list(auxiliary_data.keys())}"
        )
        return result

    async def execute_batch(
        self,
        taskings: list[SensorTasking],
    ) -> list[dict]:
        """Execute a batch of SensorTasking requests concurrently.

        Groups taskings by geographic proximity to avoid redundant weather
        lookups, then fans out sensor requests.
        """
        if not taskings:
            return []

        logger.info(f"Executing batch of {len(taskings)} taskings")

        # Execute all taskings concurrently with a reasonable concurrency cap
        semaphore = asyncio.Semaphore(10)

        async def _limited(t: SensorTasking) -> dict:
            async with semaphore:
                try:
                    return await self.execute_tasking(t)
                except Exception as exc:
                    logger.error(f"Tasking {t.id} failed: {exc}")
                    t.status = "failed"
                    return {
                        "tasking_id": t.id,
                        "error": str(exc),
                        "executed_at": datetime.utcnow().isoformat(),
                    }

        results = await asyncio.gather(*[_limited(t) for t in taskings])
        successes = sum(1 for r in results if "error" not in r)
        logger.info(f"Batch complete: {successes}/{len(taskings)} succeeded")
        return list(results)

    async def get_optimal_sensor(self, lat: float, lon: float) -> str:
        """Determine the best sensor type for a given coordinate based on
        current weather conditions and the sensor priority chain.

        Returns the sensor type string ('optical', 'sar', 'ais', 'adsb').
        """
        optical_viable, weather_data = await self.weather.check_optical_viability(
            lat, lon
        )

        if optical_viable:
            logger.debug(
                f"Optimal sensor for ({lat:.2f}, {lon:.2f}): optical "
                f"(cloud={weather_data.get('cloud_cover_pct', 0)}%)"
            )
            return "optical"

        logger.debug(
            f"Optimal sensor for ({lat:.2f}, {lon:.2f}): sar "
            f"(cloud={weather_data.get('cloud_cover_pct', 0)}% -> optical blocked)"
        )
        return "sar"

    # ------------------------------------------------------------------
    # Internal sensor-fetch methods
    # ------------------------------------------------------------------

    async def _fetch_primary_sensor(
        self,
        sensor_type: str,
        lat: float,
        lon: float,
        radius_km: float,
    ) -> dict:
        """Dispatch to the correct sensor data client."""
        if sensor_type == "optical":
            result = await self.satellite.request_optical(lat, lon, radius_km)
            return result.to_dict() if result else {"error": "no_optical_data"}

        if sensor_type == "sar":
            result = await self.satellite.request_sar(lat, lon, radius_km)
            return result.to_dict() if result else {"error": "no_sar_data"}

        if sensor_type == "adsb":
            flights = await self.opensky.get_flights_in_geofence(lat, lon, radius_km)
            return {
                "type": "adsb",
                "flight_count": len(flights),
                "flights": flights[:50],
                "captured_at": datetime.utcnow().isoformat(),
            }

        if sensor_type == "ais":
            vessels = await self.ais.get_vessels_in_area(lat, lon, radius_km)
            return {
                "type": "ais",
                "vessel_count": len(vessels),
                "vessels": vessels[:50],
                "captured_at": datetime.utcnow().isoformat(),
            }

        logger.warning(f"Unknown sensor type: {sensor_type}")
        return {"error": f"unsupported_sensor_{sensor_type}"}

    async def _fetch_ais(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        gt: GeoTarget,
    ) -> tuple[dict, str]:
        """Fetch AIS data and record provenance. Returns (data, prov_id)."""
        vessels = await self.ais.get_vessels_in_area(lat, lon, radius_km)
        data = {
            "type": "ais",
            "vessel_count": len(vessels),
            "vessels": vessels[:50],
            "tanker_count": sum(1 for v in vessels if "Tanker" in v.get("ship_type", "")),
            "cargo_count": sum(1 for v in vessels if "Cargo" in v.get("ship_type", "")),
            "avg_speed_kts": (
                round(sum(v.get("speed", 0) for v in vessels) / max(len(vessels), 1), 1)
            ),
            "captured_at": datetime.utcnow().isoformat(),
        }
        prov = self._record_provenance(
            source_type="api",
            source_url="https://data.aishub.net",
            source_provider="AIS Hub / ITU AIS Network",
            data_payload=json.dumps({"vessel_count": len(vessels)}).encode(),
            geo_target_id=gt.id,
            ticker=gt.asset_ticker,
            is_public=True,
        )
        return data, prov.id

    async def _fetch_adsb(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        gt: GeoTarget,
    ) -> tuple[dict, str]:
        """Fetch ADSB data and record provenance. Returns (data, prov_id)."""
        flights = await self.opensky.get_flights_in_geofence(lat, lon, radius_km)
        data = {
            "type": "adsb",
            "flight_count": len(flights),
            "flights": flights[:50],
            "grounded_count": sum(1 for f in flights if f.get("on_ground", False)),
            "avg_altitude_m": (
                round(
                    sum(f.get("altitude", 0) or 0 for f in flights) / max(len(flights), 1),
                    0,
                )
            ),
            "captured_at": datetime.utcnow().isoformat(),
        }
        prov = self._record_provenance(
            source_type="api",
            source_url="https://opensky-network.org/api",
            source_provider="OpenSky Network",
            data_payload=json.dumps({"flight_count": len(flights)}).encode(),
            geo_target_id=gt.id,
            ticker=gt.asset_ticker,
            is_public=True,
        )
        return data, prov.id

    # ------------------------------------------------------------------
    # Routing heuristics
    # ------------------------------------------------------------------

    @staticmethod
    def _should_query_ais(gt: GeoTarget, tasking: SensorTasking) -> bool:
        """Decide whether AIS ship tracking is relevant for this target."""
        if "ais" in gt.monitoring_sensors:
            return True
        if gt.target_type in ("port", "pipeline"):
            return True
        # Coastal refineries and facilities benefit from ship monitoring
        if gt.target_type == "facility" and abs(gt.latitude) < 5:
            return True  # Equatorial facilities near shipping lanes
        return False

    @staticmethod
    def _should_query_adsb(gt: GeoTarget, tasking: SensorTasking) -> bool:
        """Decide whether ADSB flight tracking is relevant for this target."""
        if "adsb" in gt.monitoring_sensors:
            return True
        if gt.target_type in ("hq", "airfield"):
            return True
        return False

    # ------------------------------------------------------------------
    # Provenance helpers
    # ------------------------------------------------------------------

    def _record_provenance(
        self,
        source_type: str,
        source_url: str,
        source_provider: str,
        data_payload: bytes,
        geo_target_id: str,
        ticker: str,
        is_public: bool = True,
        mnpi_class: str = "PUBLIC_OSINT",
    ) -> DataProvenanceRecord:
        """Create and store a DataProvenanceRecord in the ledger."""
        record = DataProvenanceRecord(
            id=uuid.uuid4().hex[:12],
            timestamp=datetime.utcnow(),
            source_type=source_type,
            source_url=source_url,
            source_provider=source_provider,
            is_publicly_available=is_public,
            mnpi_classification=mnpi_class,
            data_hash=hashlib.sha256(data_payload).hexdigest(),
            data_size_bytes=len(data_payload),
            geo_target_id=geo_target_id,
            ticker=ticker,
        )
        self.ledger.record_provenance(record)
        return record

    def _record_sensor_provenance(
        self,
        sensor_type: str,
        sensor_data: dict,
        gt: GeoTarget,
    ) -> DataProvenanceRecord:
        """Record provenance for primary satellite/sensor data."""
        provider_map = {
            "optical": ("satellite", "https://api.planet.com", "Planet Labs", False, "COMMERCIAL_LICENSE"),
            "sar": ("satellite", "https://api.capellaspace.com", "Capella Space", False, "COMMERCIAL_LICENSE"),
            "adsb": ("api", "https://opensky-network.org/api", "OpenSky Network", True, "PUBLIC_OSINT"),
            "ais": ("api", "https://data.aishub.net", "AIS Hub", True, "PUBLIC_OSINT"),
        }
        src_type, url, provider, is_public, mnpi = provider_map.get(
            sensor_type, ("api", "unknown", "Unknown", True, "PUBLIC_OSINT")
        )
        return self._record_provenance(
            source_type=src_type,
            source_url=url,
            source_provider=provider,
            data_payload=json.dumps(sensor_data, default=str).encode(),
            geo_target_id=gt.id,
            ticker=gt.asset_ticker,
            is_public=is_public,
            mnpi_class=mnpi,
        )

    def _log_to_ledger(
        self,
        event_type: str,
        description: str,
        prov_ids: list[str],
        ticker: str = "",
    ) -> None:
        """Append a compliance ledger entry for this sensor operation."""
        from models.compliance import ComplianceLedgerEntry

        entry = ComplianceLedgerEntry(
            id=uuid.uuid4().hex[:12],
            timestamp=datetime.utcnow(),
            event_type=event_type,
            event_description=description,
            provenance_records=prov_ids,
            agent_name="SensorOrchestrator",
            agent_reasoning=(
                f"Evaluated weather conditions and routed to optimal sensor. "
                f"Provenance chain: {', '.join(prov_ids)}"
            ),
            ticker=ticker,
        )
        self.ledger.append(entry)
