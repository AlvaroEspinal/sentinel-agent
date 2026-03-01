"""
Socrata API connector for MA municipal permit data.

Ported from municipal-intel for Parcl Intelligence.
Converted from synchronous requests to async httpx.

Known Socrata endpoints:
- Cambridge: data.cambridgema.gov (10 permit datasets)
- Somerville: data.somervillema.gov (1 permit dataset, 64K+ records)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


# ─── Known Socrata endpoints for MA municipalities ───────────────────────────
SOCRATA_TOWNS: Dict[str, Dict[str, Any]] = {
    "cambridge": {
        "base_url": "https://data.cambridgema.gov",
        "datasets": {
            "new_construction": "9qm7-wbdc",
            "addition_alteration": "qu2z-8suj",
            "electrical": "hvtc-3ab9",
            "plumbing": "8793-tet2",
            "gas": "5cra-jws5",
            "mechanical": "4rb4-q8tj",
            "demolition": "kcfi-ackv",
            "solar": "whpw-w55x",
            "roof": "79ih-g44d",
            "siding": "ddej-349p",
        },
    },
    "somerville": {
        "base_url": "https://data.somervillema.gov",
        "datasets": {
            "permits": "vxgw-vmky",  # Main permits dataset (64K+ records)
        },
    },
}


class SocrataConnector:
    """Async Socrata API connector for pulling municipal permit data."""

    def __init__(
        self,
        *,
        app_token: Optional[str] = None,
        timeout_s: float = 60.0,
        batch_size: int = 10000,
        max_retries: int = 3,
    ):
        self.app_token = app_token
        self.timeout_s = timeout_s
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._client: Optional[Any] = None

    async def _ensure_client(self) -> Any:
        if self._client is None:
            if httpx is None:
                raise RuntimeError("httpx is required: pip install httpx")
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s, connect=10.0),
                limits=httpx.Limits(max_connections=10),
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def pull_dataset(
        self,
        base_url: str,
        dataset_id: str,
        limit: int = 100000,
    ) -> List[Dict[str, Any]]:
        """Pull all records from a Socrata dataset with pagination and retry."""
        client = await self._ensure_client()
        url = f"{base_url}/resource/{dataset_id}.json"

        headers: Dict[str, str] = {}
        if self.app_token:
            headers["X-App-Token"] = self.app_token

        all_records: List[Dict[str, Any]] = []
        offset = 0
        consecutive_failures = 0

        while len(all_records) < limit:
            params = {
                "$limit": str(self.batch_size),
                "$offset": str(offset),
            }

            success = False
            for attempt in range(self.max_retries):
                try:
                    resp = await client.get(
                        url, params=params, headers=headers
                    )
                    if resp.status_code == 200:
                        consecutive_failures = 0
                        success = True
                        break
                    elif resp.status_code == 429:
                        wait_time = 30 * (attempt + 1)
                        logger.warning(
                            "Socrata rate limited, waiting %ds...", wait_time
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(
                            "Socrata HTTP %d on %s, retry %d/%d",
                            resp.status_code,
                            dataset_id,
                            attempt + 1,
                            self.max_retries,
                        )
                        await asyncio.sleep(5 * (attempt + 1))
                except Exception as exc:
                    logger.warning(
                        "Socrata request error: %s, retry %d/%d",
                        exc,
                        attempt + 1,
                        self.max_retries,
                    )
                    await asyncio.sleep(5 * (attempt + 1))

            if not success:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    logger.error(
                        "Too many failures for %s, stopping at %d records",
                        dataset_id,
                        len(all_records),
                    )
                    break
                continue

            try:
                records = resp.json()
            except Exception:
                logger.warning("Invalid JSON from %s, skipping batch", dataset_id)
                offset += self.batch_size
                continue

            if not records:
                break

            all_records.extend(records)
            logger.debug(
                "Socrata %s: %d records pulled so far...",
                dataset_id,
                len(all_records),
            )

            if len(records) < self.batch_size:
                break

            offset += self.batch_size
            await asyncio.sleep(0.5)  # Rate limit courtesy delay

        return all_records

    async def pull_town(self, town: str) -> Dict[str, Any]:
        """Pull all permit data for a town.

        Returns:
            Dict with keys: town, source, pulled_at, permit_count, permits
        """
        config = SOCRATA_TOWNS.get(town)
        if not config:
            raise ValueError(
                f"Unknown town: {town}. Available: {list(SOCRATA_TOWNS.keys())}"
            )

        logger.info("Pulling Socrata data for %s...", town.upper())
        all_permits: List[Dict[str, Any]] = []

        for name, dataset_id in config["datasets"].items():
            logger.info("  Dataset: %s (%s)", name, dataset_id)
            records = await self.pull_dataset(config["base_url"], dataset_id)

            # Add source metadata to each record
            for r in records:
                r["_source_dataset"] = name
                r["_source_id"] = dataset_id

            all_permits.extend(records)
            logger.info("  Total so far: %d", len(all_permits))

        result = {
            "town": town,
            "source": "socrata_api",
            "pulled_at": datetime.now(timezone.utc).isoformat(),
            "permit_count": len(all_permits),
            "permits": all_permits,
        }
        logger.info(
            "Socrata: %d permits pulled for %s", len(all_permits), town
        )
        return result

    async def pull_all(self) -> Dict[str, Dict[str, Any]]:
        """Pull permit data for all known Socrata towns.

        Returns:
            Dict mapping town name to pull result.
        """
        results: Dict[str, Dict[str, Any]] = {}
        for town in SOCRATA_TOWNS:
            try:
                results[town] = await self.pull_town(town)
            except Exception as exc:
                logger.error("Failed to pull %s: %s", town, exc)
                results[town] = {
                    "town": town,
                    "error": str(exc),
                    "permit_count": 0,
                    "permits": [],
                }
        return results
