"""
Scrape Scheduler — Background job runner for recurring data pulls.

Manages scheduled scraping jobs for target towns:
- Permits: weekly pull from town portals
- Meeting minutes: weekly check for new documents
- Property transfers: daily scan of MassGIS recent sales
- Tracks all jobs in scrape_jobs table

Usage:
    scheduler = ScrapeScheduler(supabase_client, firecrawl_client)
    await scheduler.run_all_pending()  # Run in a background loop
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .connectors.town_config import TARGET_TOWNS, TownConfig, get_all_towns
from .connectors.massgis_parcels import get_recent_sales, get_town_stats
from .connectors.meeting_minutes import MeetingMinutesScraper
from .connectors.llm_extractor import LLMExtractor
from .connectors.firecrawl_client import FirecrawlClient


class ScrapeScheduler:
    """Manages recurring scrape jobs for all target towns."""

    # Maximum time (seconds) a single town scrape cycle may run before being
    # cancelled.  Prevents a hanging HTTP request from blocking the entire
    # scheduler loop.
    TOWN_TIMEOUT_S: float = 600.0  # 10 minutes

    def __init__(
        self,
        supabase: Optional[Any] = None,
        firecrawl: Optional[FirecrawlClient] = None,
        llm_extractor: Optional[LLMExtractor] = None,
        local_storage_dir: Optional[str] = None,
    ):
        self.supabase = supabase
        self.firecrawl = firecrawl
        self.llm = llm_extractor
        self._running = False
        self._last_heartbeat: Optional[datetime] = None
        self._consecutive_failures: int = 0

        # Local file storage mode: when Supabase is unavailable, buffer
        # records in memory and flush to JSON files.
        self._local_storage_dir = local_storage_dir
        self._local_buffer: Dict[str, List[dict]] = {}  # key: "permits/{town_id}" etc.

    # ── Background Loop ───────────────────────────────────────────────────

    async def start(self, check_interval_s: float = 300.0):
        """Start the scheduler background loop.

        Checks for pending jobs every `check_interval_s` seconds.
        """
        self._running = True
        self._consecutive_failures = 0
        logger.info("[Scheduler] Started — checking every %.0fs", check_interval_s)

        while self._running:
            self._last_heartbeat = datetime.now(timezone.utc)
            try:
                await self.run_all_pending()
                self._consecutive_failures = 0
            except Exception as exc:
                self._consecutive_failures += 1
                logger.error(
                    "[Scheduler] Error in run cycle (%d consecutive): %s",
                    self._consecutive_failures,
                    exc,
                )
                # Back off on repeated failures to avoid tight error loops
                if self._consecutive_failures >= 3:
                    backoff = min(check_interval_s * 2, 1800.0)
                    logger.warning(
                        "[Scheduler] %d consecutive failures — backing off %.0fs",
                        self._consecutive_failures,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

            await asyncio.sleep(check_interval_s)

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        logger.info("[Scheduler] Stopped")

    @property
    def is_alive(self) -> bool:
        """Return True if the scheduler loop has sent a heartbeat recently."""
        if not self._running or self._last_heartbeat is None:
            return False
        age = (datetime.now(timezone.utc) - self._last_heartbeat).total_seconds()
        # Should heartbeat every check_interval_s (~300s) + generous margin
        return age < 900  # 15 minutes

    # ── Status & Parallel Execution ──────────────────────────────────────

    async def get_scrape_status(self) -> Dict[str, Any]:
        """Check scrape completion status for all towns and job types.

        Returns a dict with:
          - completed: list of {town_id, source_type, completed_at}
          - pending: list of {town_id, source_type, reason}
          - running: list of {town_id, source_type, started_at}
          - summary: {total, completed, pending, running}
        """
        towns = get_all_towns()
        completed = []
        pending = []
        running = []

        job_types = [
            ("property_transfers", "transfers_scrape_interval_hours"),
            ("meeting_minutes", "minutes_scrape_interval_hours"),
            ("permits", "permits_scrape_interval_hours"),
        ]

        for town_id, town in towns.items():
            for source_type, interval_attr in job_types:
                hours = getattr(town, interval_attr)

                # Check for currently running jobs
                if self.supabase:
                    try:
                        running_rows = await self.supabase.fetch(
                            table="scrape_jobs",
                            select="id,started_at",
                            filters={
                                "town_id": f"eq.{town_id}",
                                "source_type": f"eq.{source_type}",
                                "status": "eq.running",
                            },
                            limit=1,
                        )
                        if running_rows:
                            running.append({
                                "town_id": town_id,
                                "town_name": town.name,
                                "source_type": source_type,
                                "started_at": running_rows[0].get("started_at"),
                            })
                            continue
                    except Exception:
                        pass

                due = await self._is_job_due(town_id, source_type, hours=hours)
                if due:
                    # Check if it ever ran
                    reason = "never_run"
                    if self.supabase:
                        try:
                            any_rows = await self.supabase.fetch(
                                table="scrape_jobs",
                                select="status,error_message",
                                filters={
                                    "town_id": f"eq.{town_id}",
                                    "source_type": f"eq.{source_type}",
                                },
                                order="started_at.desc",
                                limit=1,
                            )
                            if any_rows:
                                last = any_rows[0]
                                if last.get("status") == "failed":
                                    reason = f"last_failed: {last.get('error_message', 'unknown')}"
                                else:
                                    reason = "overdue"
                        except Exception:
                            reason = "unknown"

                    pending.append({
                        "town_id": town_id,
                        "town_name": town.name,
                        "source_type": source_type,
                        "portal_type": town.permit_portal_type,
                        "reason": reason,
                    })
                else:
                    # Get last completion info
                    completed_at = None
                    if self.supabase:
                        try:
                            rows = await self.supabase.fetch(
                                table="scrape_jobs",
                                select="completed_at,records_found,records_new",
                                filters={
                                    "town_id": f"eq.{town_id}",
                                    "source_type": f"eq.{source_type}",
                                    "status": "eq.completed",
                                },
                                order="completed_at.desc",
                                limit=1,
                            )
                            if rows:
                                completed_at = rows[0].get("completed_at")
                        except Exception:
                            pass

                    completed.append({
                        "town_id": town_id,
                        "town_name": town.name,
                        "source_type": source_type,
                        "completed_at": completed_at,
                    })

        total = len(completed) + len(pending) + len(running)
        return {
            "completed": completed,
            "pending": pending,
            "running": running,
            "summary": {
                "total": total,
                "completed": len(completed),
                "pending": len(pending),
                "running": len(running),
            },
        }

    async def run_pending_parallel(
        self,
        max_concurrency: int = 4,
        source_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Run all pending/overdue scrape jobs in parallel.

        Spawns up to ``max_concurrency`` concurrent tasks, each handling one
        town+source_type combination.  Returns aggregated results.

        Args:
            max_concurrency: Max simultaneous scrape tasks.
            source_types: Filter to specific types (e.g. ["permits"]).
                          Default: all types.
        """
        status = await self.get_scrape_status()
        pending_jobs = status["pending"]

        if source_types:
            allowed = set(source_types)
            pending_jobs = [j for j in pending_jobs if j["source_type"] in allowed]

        if not pending_jobs:
            logger.info("[Scheduler] No pending jobs to run in parallel")
            return {"results": [], "summary": status["summary"]}

        logger.info(
            "[Scheduler] Running %d pending jobs in parallel (max_concurrency=%d)",
            len(pending_jobs),
            max_concurrency,
        )

        semaphore = asyncio.Semaphore(max_concurrency)
        results = []

        async def _run_one(job: dict) -> dict:
            town_id = job["town_id"]
            source_type = job["source_type"]
            town = get_all_towns().get(town_id)
            if not town:
                return {"town_id": town_id, "source_type": source_type, "error": "town_not_found"}

            async with semaphore:
                logger.info(
                    "[Scheduler] Parallel: starting %s/%s",
                    town_id, source_type,
                )
                try:
                    if source_type == "property_transfers":
                        result = await asyncio.wait_for(
                            self.run_transfers_scrape(town),
                            timeout=self.TOWN_TIMEOUT_S,
                        )
                    elif source_type == "meeting_minutes":
                        result = await asyncio.wait_for(
                            self.run_minutes_scrape(town),
                            timeout=self.TOWN_TIMEOUT_S,
                        )
                    elif source_type == "permits":
                        result = await asyncio.wait_for(
                            self.run_permits_scrape(town),
                            timeout=self.TOWN_TIMEOUT_S,
                        )
                    else:
                        result = {"error": f"unknown_source_type: {source_type}"}

                    result["source_type"] = source_type
                    return result

                except asyncio.TimeoutError:
                    logger.error(
                        "[Scheduler] Parallel: %s/%s timed out after %.0fs",
                        town_id, source_type, self.TOWN_TIMEOUT_S,
                    )
                    return {
                        "town_id": town_id,
                        "source_type": source_type,
                        "error": "timeout",
                    }
                except Exception as exc:
                    logger.error(
                        "[Scheduler] Parallel: %s/%s failed: %s",
                        town_id, source_type, exc,
                    )
                    return {
                        "town_id": town_id,
                        "source_type": source_type,
                        "error": str(exc),
                    }

        tasks = [asyncio.create_task(_run_one(job)) for job in pending_jobs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Normalize exceptions into dicts
        final_results = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final_results.append({
                    "town_id": pending_jobs[i]["town_id"],
                    "source_type": pending_jobs[i]["source_type"],
                    "error": str(r),
                })
            else:
                final_results.append(r)

        succeeded = sum(1 for r in final_results if "error" not in r)
        failed = len(final_results) - succeeded

        logger.info(
            "[Scheduler] Parallel scrape complete: %d succeeded, %d failed out of %d",
            succeeded, failed, len(final_results),
        )

        return {
            "results": final_results,
            "summary": {
                "dispatched": len(final_results),
                "succeeded": succeeded,
                "failed": failed,
            },
        }

    # ── Job Execution ─────────────────────────────────────────────────────

    async def run_all_pending(self):
        """Check all towns and run any overdue scrape jobs."""
        towns = get_all_towns()

        for town_id, town in towns.items():
            try:
                await asyncio.wait_for(
                    self._check_and_run_town(town),
                    timeout=self.TOWN_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[Scheduler] Town %s timed out after %.0fs — skipping",
                    town_id,
                    self.TOWN_TIMEOUT_S,
                )
            except Exception as exc:
                logger.error("[Scheduler] Error processing %s: %s", town_id, exc)

    async def _check_and_run_town(self, town: TownConfig):
        """Check if any scrape jobs are due for a town and run them."""

        # Check property transfers (daily)
        if await self._is_job_due(town.id, "property_transfers", hours=town.transfers_scrape_interval_hours):
            await self.run_transfers_scrape(town)

        # Check meeting minutes (weekly)
        if await self._is_job_due(town.id, "meeting_minutes", hours=town.minutes_scrape_interval_hours):
            await self.run_minutes_scrape(town)

        # Check permits (weekly)
        if await self._is_job_due(town.id, "permits", hours=town.permits_scrape_interval_hours):
            await self.run_permits_scrape(town)

    async def _is_job_due(self, town_id: str, source_type: str, hours: int) -> bool:
        """Check if a scrape job is due based on last completion time."""
        if not self.supabase:
            return True  # If no DB, always run

        try:
            rows = await self.supabase.fetch(
                table="scrape_jobs",
                select="completed_at",
                filters={
                    "town_id": f"eq.{town_id}",
                    "source_type": f"eq.{source_type}",
                    "status": "eq.completed",
                },
                order="completed_at.desc",
                limit=1,
            )

            if not rows:
                return True  # Never run before

            last_completed = rows[0].get("completed_at")
            if not last_completed:
                return True

            # Parse ISO datetime
            if isinstance(last_completed, str):
                last_dt = datetime.fromisoformat(last_completed.replace("Z", "+00:00"))
            else:
                last_dt = last_completed

            due_at = last_dt + timedelta(hours=hours)
            return datetime.now(timezone.utc) >= due_at

        except Exception as exc:
            logger.warning("[Scheduler] Error checking job due status: %s", exc)
            return True  # On error, run anyway

    # ── Property Transfers Scrape ─────────────────────────────────────────

    async def run_transfers_scrape(self, town: TownConfig) -> Dict[str, Any]:
        """Scrape recent property transfers from MassGIS for a town."""
        job_id = await self._create_job(town.id, "property_transfers")

        try:
            await self._update_job(job_id, status="running")

            # Get sales from last 90 days
            cutoff = datetime.now() - timedelta(days=90)
            min_date = cutoff.strftime("%Y%m%d")

            sales = await get_recent_sales(
                town=town.name,
                min_sale_date=min_date,
                min_price=1000,
                limit=500,
            )

            # Store in property_transfers table
            new_count = 0
            if self.supabase and sales:
                for sale in sales:
                    # Check if this transfer already exists (by loc_id + sale_date)
                    loc_id = sale.get("loc_id", "")
                    sale_date = sale.get("last_sale_date")
                    if not loc_id or not sale_date:
                        continue  # Skip records without identifiers

                    existing = await self.supabase.fetch(
                        table="property_transfers",
                        select="id",
                        filters={
                            "loc_id": f"eq.{loc_id}",
                            "sale_date": f"eq.{sale_date}",
                        },
                        limit=1,
                    )

                    if not existing:
                        await self._insert_transfer(town.id, sale)
                        new_count += 1

            await self._update_job(
                job_id,
                status="completed",
                records_found=len(sales),
                records_new=new_count,
            )

            logger.info(
                "[Scheduler] Transfers for %s: %d found, %d new",
                town.name, len(sales), new_count,
            )

            return {"town": town.id, "found": len(sales), "new": new_count}

        except Exception as exc:
            await self._update_job(job_id, status="failed", error=str(exc))
            logger.error("[Scheduler] Transfers scrape failed for %s: %s", town.name, exc)
            return {"town": town.id, "error": str(exc)}

    async def _insert_transfer(self, town_id: str, sale: dict):
        """Insert a property transfer record into Supabase or local buffer."""
        bld_area = sale.get("building_area_sqft") or 0
        price = sale.get("last_sale_price") or 0
        price_per_sqft = round(price / bld_area, 2) if bld_area > 100 and price > 0 else None

        record = {
            "id": str(uuid.uuid4()),
            "town_id": town_id,
            "loc_id": sale.get("loc_id"),
            "site_addr": sale.get("site_addr"),
            "city": sale.get("city"),
            "owner": sale.get("owner"),
            "use_code": sale.get("use_code"),
            "sale_date": sale.get("last_sale_date"),
            "sale_price": price if price > 0 else None,
            "book_page": sale.get("book_page"),
            "assessed_value": sale.get("total_value"),
            "building_value": sale.get("building_value"),
            "land_value": sale.get("land_value"),
            "price_per_sqft": price_per_sqft,
            "building_area": bld_area if bld_area > 0 else None,
            "lot_size_acres": sale.get("lot_size_acres"),
            "year_built": sale.get("year_built"),
            "style": sale.get("style"),
            "fiscal_year": sale.get("fiscal_year"),
        }

        if self.supabase:
            try:
                await self.supabase.insert("property_transfers", record)
            except Exception as exc:
                logger.warning("[Scheduler] Insert transfer error: %s", exc)

        if self._local_storage_dir is not None:
            key = f"transfers/{town_id}"
            self._local_buffer.setdefault(key, []).append(record)

    # ── Meeting Minutes Scrape ────────────────────────────────────────────

    async def run_minutes_scrape(self, town: TownConfig) -> Dict[str, Any]:
        """Scrape meeting minutes for a town."""
        if not self.firecrawl:
            logger.warning("[Scheduler] Firecrawl not configured — skipping minutes scrape")
            return {"town": town.id, "error": "firecrawl_not_configured"}

        job_id = await self._create_job(town.id, "meeting_minutes")

        try:
            await self._update_job(job_id, status="running")

            scraper = MeetingMinutesScraper(
                firecrawl=self.firecrawl,
                llm_extractor=self.llm,
            )

            documents = await scraper.scrape_town(town)

            # Store documents, deduplicating by content hash
            new_count = 0
            if self.supabase and documents:
                for doc in documents:
                    content_hash = doc.get("content_hash", "")
                    if content_hash:
                        existing = await self.supabase.fetch(
                            table="municipal_documents",
                            select="id",
                            filters={"content_hash": f"eq.{content_hash}"},
                            limit=1,
                        )
                        if existing:
                            continue

                    doc["id"] = str(uuid.uuid4())
                    try:
                        await self.supabase.insert("municipal_documents", doc)
                        new_count += 1
                    except Exception as exc:
                        logger.warning("[Scheduler] Insert document error: %s", exc)

            await self._update_job(
                job_id,
                status="completed",
                records_found=len(documents),
                records_new=new_count,
            )

            logger.info(
                "[Scheduler] Minutes for %s: %d found, %d new",
                town.name, len(documents), new_count,
            )

            return {"town": town.id, "found": len(documents), "new": new_count}

        except Exception as exc:
            await self._update_job(job_id, status="failed", error=str(exc))
            logger.error("[Scheduler] Minutes scrape failed for %s: %s", town.name, exc)
            return {"town": town.id, "error": str(exc)}

    # ── Permits Scrape (placeholder) ──────────────────────────────────────

    async def run_permits_scrape(
        self,
        town: TownConfig,
        partition: Optional[int] = None,
        num_partitions: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Scrape permits for a town (dispatches to correct connector)."""
        job_id = await self._create_job(town.id, "permits")

        try:
            await self._update_job(job_id, status="running")

            if town.permit_portal_type == "viewpointcloud" and town.viewpointcloud_slug:
                result = await self._scrape_viewpointcloud_permits(
                    town, partition=partition, num_partitions=num_partitions
                )
            elif town.permit_portal_type == "permiteyes":
                result = await self._scrape_permiteyes_permits(
                    town, partition=partition, num_partitions=num_partitions
                )
            elif town.permit_portal_type == "simplicity":
                result = await self._scrape_simplicity_permits(
                    town, partition=partition, num_partitions=num_partitions
                )
            elif town.permit_portal_type == "socrata" and town.socrata_datasets:
                result = await self._scrape_socrata_permits(town)
            elif town.permit_portal_type == "firecrawl" and town.permit_portal_url:
                result = await self._scrape_firecrawl_permits(town)
            else:
                result = {"found": 0, "new": 0, "note": "no_portal_configured"}

            await self._update_job(
                job_id,
                status="completed",
                records_found=result.get("found", 0),
                records_new=result.get("new", 0),
            )

            return {"town": town.id, **result}

        except Exception as exc:
            await self._update_job(job_id, status="failed", error=str(exc))
            return {"town": town.id, "error": str(exc)}

    async def _scrape_socrata_permits(self, town: TownConfig) -> dict:
        """Scrape permits from Socrata portal and store in Supabase."""
        from .connectors.socrata import SocrataConnector, SOCRATA_TOWNS
        from .connectors.normalize import normalize_batch

        town_key = town.id.lower()
        if town_key not in SOCRATA_TOWNS:
            logger.warning("[Scheduler] No Socrata config for %s", town.name)
            return {"found": 0, "new": 0, "note": "no_socrata_config"}

        logger.info("[Scheduler] Socrata permit scrape for %s", town.name)

        connector = SocrataConnector()
        try:
            result = await connector.pull_town(town_key)
        finally:
            await connector.close()

        raw_permits = result.get("permits", [])
        normalized = normalize_batch(raw_permits, town_key)

        new_count = 0
        if self.supabase and normalized:
            for permit in normalized:
                permit_number = permit.get("permit_number", "")
                if not permit_number:
                    continue

                # Dedup by permit_number + town
                existing = await self.supabase.fetch(
                    table="permits",
                    select="id",
                    filters={
                        "permit_number": f"eq.{permit_number}",
                        "town_id": f"eq.{town.id}",
                    },
                    limit=1,
                )

                if not existing:
                    await self._insert_permit(town.id, permit)
                    new_count += 1

        logger.info(
            "[Scheduler] Socrata for %s: %d raw, %d normalized, %d new",
            town.name, len(raw_permits), len(normalized), new_count,
        )
        return {"found": len(normalized), "new": new_count}

    # Keywords that identify permit-related record types in ViewpointCloud
    VPC_PERMIT_KEYWORDS = frozenset([
        "permit", "building", "electric", "plumb", "gas", "demo",
        "mechanical", "fire", "solar", "roof", "pool", "hvac", "sign",
        "fence", "tent", "window", "insulation", "zoning", "certificate",
        "inspection", "occupancy", "sprinkler", "alarm", "fuel",
        "propane", "well", "engineering", "construction", "plan review",
        "blasting", "trench", "sewer", "water", "septic", "shed",
        "driveway", "tank", "flammab", "hazardous", "pyrotechnic",
        "heating", "transfer station", "waiver", "abandon", "title 5",
        "battery", "storage", "hot work", "weld", "grind",
    ])

    async def _scrape_viewpointcloud_permits(
        self,
        town: TownConfig,
        partition: Optional[int] = None,
        num_partitions: Optional[int] = None,
    ) -> dict:
        """Scrape permits from ViewpointCloud portal using bulk records API.

        Uses the paginated ``records?recordTypeID=X`` endpoint (up to 500
        records per page) instead of the search_results autocomplete endpoint
        which caps at ~10 results.

        Supports partitioning: if partition and num_partitions are set,
        only processes the Nth slice of record types for parallel scraping.
        """
        import httpx as httpx_lib
        from .connectors.viewpointcloud import ViewpointCloudClient, fetch_general_settings

        slug = town.viewpointcloud_slug
        if not slug:
            return {"found": 0, "new": 0, "note": "no_vpc_slug"}

        logger.info("[Scheduler] ViewpointCloud permit scrape for %s (slug=%s)", town.name, slug)

        async with httpx_lib.AsyncClient(timeout=60.0) as client:
            api_base, settings, error = await fetch_general_settings(
                community_slug=slug, client=client
            )

            if error or not api_base:
                logger.warning("[Scheduler] ViewpointCloud unavailable for %s: %s", town.name, error)
                return {"found": 0, "new": 0, "note": f"vpc_unavailable: {error}"}

            # ── Step 1: Fetch all record types and filter to permits ──
            try:
                resp = await client.get(
                    f"{api_base}/{slug}/record_types", timeout=30.0
                )
                resp.raise_for_status()
                all_types = resp.json().get("data", [])
            except Exception as exc:
                logger.warning("[Scheduler] VPC record_types failed for %s: %s", town.name, exc)
                return {"found": 0, "new": 0, "note": f"record_types_failed: {exc}"}

            permit_type_ids: List[tuple] = []
            for rt in all_types:
                attrs = rt.get("attributes") or {}
                name = (attrs.get("name") or "").lower()
                if any(kw in name for kw in self.VPC_PERMIT_KEYWORDS):
                    permit_type_ids.append((str(rt["id"]), attrs.get("name", "")))

            if not permit_type_ids:
                logger.info("[Scheduler] No permit-related record types found for %s", town.name)
                return {"found": 0, "new": 0, "note": "no_permit_types"}

            # ── Partition support for parallel scraping ──
            total_types = len(permit_type_ids)
            if partition is not None and num_partitions is not None and num_partitions > 1:
                chunk_size = (total_types + num_partitions - 1) // num_partitions
                start = partition * chunk_size
                end = min(start + chunk_size, total_types)
                permit_type_ids = permit_type_ids[start:end]
                logger.info(
                    "[Scheduler] VPC %s partition %d/%d: types %d-%d of %d (%d types)",
                    town.name, partition, num_partitions, start, end - 1, total_types,
                    len(permit_type_ids),
                )
            else:
                logger.info(
                    "[Scheduler] VPC %s: %d permit-related record types out of %d total",
                    town.name, len(permit_type_ids), len(all_types),
                )

            # ── Step 2: Fetch records for each permit type (paginated) ──
            total_found = 0
            new_count = 0
            page_size = 500  # VPC max per page

            for rt_id, rt_name in permit_type_ids:
                page = 1
                type_count = 0

                while True:
                    try:
                        resp = await client.get(
                            f"{api_base}/{slug}/records",
                            params={
                                "recordTypeID": rt_id,
                                "page[size]": str(page_size),
                                "page[number]": str(page),
                            },
                            timeout=45.0,
                        )
                        resp.raise_for_status()
                        payload = resp.json()
                    except Exception as exc:
                        logger.debug(
                            "[Scheduler] VPC records page failed type=%s page=%d: %s",
                            rt_id, page, exc,
                        )
                        break

                    records = payload.get("data") or []
                    if not records:
                        break

                    for record in records:
                        attrs = (record.get("attributes") or {})
                        record_no = str(attrs.get("recordNo") or "").strip()
                        if not record_no:
                            continue

                        total_found += 1
                        type_count += 1

                        # Dedup against Supabase
                        if self.supabase:
                            existing = await self.supabase.fetch(
                                table="permits",
                                select="id",
                                filters={
                                    "permit_number": f"eq.{record_no}",
                                    "town_id": f"eq.{town.id}",
                                },
                                limit=1,
                            )
                            if existing:
                                continue

                        # Insert — records endpoint already includes attributes
                        await self._insert_permit(town.id, {
                            "permit_number": record_no,
                            "town": town.id,
                            "address": str(attrs.get("address") or attrs.get("locationAddress") or ""),
                            "permit_type": str(attrs.get("recordTypeName") or rt_name or "Building"),
                            "status": str(attrs.get("status") or ""),
                            "description": str(attrs.get("description") or "")[:500],
                            "filed_date": str(attrs.get("dateCreated") or "")[:10] or None,
                            "issued_date": str(attrs.get("dateIssued") or "")[:10] or None,
                            "estimated_value": None,
                            "source_system": "viewpointcloud",
                        })
                        new_count += 1

                    # If we got fewer than page_size, we've exhausted this type
                    if len(records) < page_size:
                        break
                    page += 1
                    await asyncio.sleep(0.3)  # Rate limit courtesy between pages

                if type_count > 0:
                    logger.debug(
                        "[Scheduler] VPC %s type %s: %d records",
                        town.name, rt_name[:40], type_count,
                    )
                await asyncio.sleep(0.2)  # Rate limit courtesy between types

        logger.info(
            "[Scheduler] ViewpointCloud for %s: %d found, %d new",
            town.name, total_found, new_count,
        )
        return {"found": total_found, "new": new_count}

    async def _scrape_permiteyes_permits(
        self,
        town: TownConfig,
        partition: Optional[int] = None,
        num_partitions: Optional[int] = None,
    ) -> dict:
        """Scrape permits from PermitEyes (Full Circle Technologies) portal.

        Works with towns using permiteyes.us DataTables AJAX endpoints.
        Supports partitioning across department endpoints.
        """
        import httpx as httpx_lib
        from .connectors.permiteyes_client import (
            PERMITEYES_TOWNS,
            parse_permit_row,
            fetch_permits_page,
        )

        town_key = town.id.lower()
        pe_config = PERMITEYES_TOWNS.get(town_key)
        if not pe_config:
            logger.warning("[Scheduler] No PermitEyes config for %s", town.name)
            return {"found": 0, "new": 0, "note": "no_permiteyes_config"}

        logger.info("[Scheduler] PermitEyes permit scrape for %s (slug=%s)", town.name, pe_config.town_slug)

        endpoints = list(pe_config.endpoints)

        # Partition support: split endpoints across partitions
        if partition is not None and num_partitions is not None and num_partitions > 1:
            chunk_size = max(1, (len(endpoints) + num_partitions - 1) // num_partitions)
            start_idx = partition * chunk_size
            end_idx = min(start_idx + chunk_size, len(endpoints))
            endpoints = endpoints[start_idx:end_idx]
            if not endpoints:
                return {"found": 0, "new": 0, "note": "partition_empty"}

        total_found = 0
        new_count = 0
        page_size = 200

        async with httpx_lib.AsyncClient(timeout=60.0) as client:
            for endpoint_path, department in endpoints:
                offset = 0
                endpoint_total = None

                while True:
                    try:
                        rows, records_total = await fetch_permits_page(
                            client=client,
                            base_url=pe_config.base_url,
                            endpoint=endpoint_path,
                            columns=pe_config.columns,
                            start=offset,
                            length=page_size,
                        )
                    except Exception as exc:
                        logger.warning(
                            "[Scheduler] PermitEyes page failed %s/%s offset=%d: %s",
                            town.name, department, offset, exc,
                        )
                        break

                    if endpoint_total is None:
                        endpoint_total = records_total
                        logger.info(
                            "[Scheduler] PermitEyes %s %s: %d total records",
                            town.name, department, records_total,
                        )

                    if not rows:
                        break

                    for row in rows:
                        if not isinstance(row, list):
                            continue
                        permit = parse_permit_row(row, department, pe_config.columns)
                        source_id = permit.get("source_id", "")
                        if not source_id:
                            continue

                        total_found += 1

                        # Use app_number or permit_number as dedup key
                        permit_number = permit.get("permit_number") or permit.get("app_number") or source_id

                        # Dedup against Supabase
                        if self.supabase:
                            existing = await self.supabase.fetch(
                                table="permits",
                                select="id",
                                filters={
                                    "source_id": f"eq.{source_id}",
                                    "town_id": f"eq.{town.id}",
                                },
                                limit=1,
                            )
                            if existing:
                                continue

                        # Map PermitEyes fields to our permit schema
                        await self._insert_permit(town.id, {
                            "permit_number": permit_number,
                            "permit_type": permit.get("app_type") or department,
                            "status": permit.get("status") or "FILED",
                            "address": permit.get("address") or "",
                            "description": (permit.get("description") or "")[:500],
                            "applicant_name": permit.get("applicant") or "",
                            "filed_date": permit.get("app_date") or None,
                            "issued_date": permit.get("issue_date") or None,
                            "source_system": "permiteyes",
                            "source_id": source_id,
                        })
                        new_count += 1

                    offset += len(rows)
                    if offset >= (endpoint_total or 0):
                        break

                    await asyncio.sleep(0.3)  # Rate limit courtesy

        logger.info(
            "[Scheduler] PermitEyes for %s: %d found, %d new",
            town.name, total_found, new_count,
        )
        return {"found": total_found, "new": new_count}

    async def _scrape_simplicity_permits(
        self,
        town: TownConfig,
        partition: Optional[int] = None,
        num_partitions: Optional[int] = None,
    ) -> dict:
        """Scrape permits from SimpliCITY/MapsOnline (PeopleGIS) portal.

        Works with towns using mapsonline.net permit portals.
        """
        import httpx as httpx_lib
        from .connectors.simplicity_client import (
            SIMPLICITY_TOWNS,
            get_session_id,
            scrape_town_permits,
        )

        town_key = town.id.lower()
        sc_config = SIMPLICITY_TOWNS.get(town_key)
        if not sc_config:
            logger.warning("[Scheduler] No SimpliCITY config for %s", town.name)
            return {"found": 0, "new": 0, "note": "no_simplicity_config"}

        logger.info(
            "[Scheduler] SimpliCITY permit scrape for %s (client=%s)",
            town.name, sc_config.client_name,
        )

        async with httpx_lib.AsyncClient(timeout=60.0) as client:
            # Get public session
            ssid = await get_session_id(client=client, client_name=sc_config.client_name)
            if not ssid:
                return {"found": 0, "new": 0, "note": "session_failed"}

            logger.info("[Scheduler] SimpliCITY session obtained for %s", town.name)

            # Scrape all permit forms
            permits = await scrape_town_permits(
                config=sc_config,
                client=client,
                ssid=ssid,
                page_size=100,
                partition=partition,
                num_partitions=num_partitions,
            )

        total_found = len(permits)
        new_count = 0

        for permit in permits:
            source_id = permit.get("source_id", "")
            if not source_id:
                continue

            permit_number = permit.get("permit_number") or source_id

            # Dedup against Supabase
            if self.supabase:
                existing = await self.supabase.fetch(
                    table="permits",
                    select="id",
                    filters={
                        "source_id": f"eq.{source_id}",
                        "town_id": f"eq.{town.id}",
                    },
                    limit=1,
                )
                if existing:
                    continue

            await self._insert_permit(town.id, {
                "permit_number": permit_number,
                "permit_type": permit.get("permit_type") or permit.get("department") or "Building",
                "status": permit.get("status") or "FILED",
                "address": permit.get("address") or "",
                "description": (permit.get("description") or "")[:500],
                "applicant_name": permit.get("applicant") or "",
                "contractor_name": permit.get("contractor") or "",
                "filed_date": permit.get("app_date") or None,
                "issued_date": permit.get("issue_date") or None,
                "estimated_value": permit.get("estimated_value"),
                "source_system": "simplicity",
                "source_id": source_id,
            })
            new_count += 1

        logger.info(
            "[Scheduler] SimpliCITY for %s: %d found, %d new",
            town.name, total_found, new_count,
        )
        return {"found": total_found, "new": new_count}

    async def _scrape_firecrawl_permits(self, town: TownConfig) -> dict:
        """Scrape permits from town website using Firecrawl + LLM extraction."""
        if not self.firecrawl or not town.permit_portal_url:
            return {"found": 0, "new": 0, "note": "no_firecrawl_or_url"}

        logger.info("[Scheduler] Firecrawl permit scrape for %s", town.name)

        # Crawl the permit portal page (and linked pages up to 10)
        # wait_for=5000 gives JS-heavy CivicPlus sites time to render
        pages = await self.firecrawl.crawl(
            town.permit_portal_url,
            max_pages=10,
            wait_for=5000,
        )

        if not pages:
            logger.info("[Scheduler] No pages returned for %s permit portal", town.name)
            return {"found": 0, "new": 0}

        # Use LLM to extract permit data from each page
        new_count = 0
        total_found = 0

        for page in pages:
            markdown = page.get("markdown", "")
            if not markdown or len(markdown) < 100:
                continue

            if not self.llm:
                logger.info(
                    "[Scheduler] Got permit page for %s (%d chars) but no LLM extractor",
                    town.name, len(markdown),
                )
                continue

            try:
                permits = await self._extract_permits_from_page(markdown, town.name)
                total_found += len(permits)

                for permit in permits:
                    permit_number = permit.get("permit_number", "")
                    if not permit_number:
                        continue

                    # Dedup
                    if self.supabase:
                        existing = await self.supabase.fetch(
                            table="permits",
                            select="id",
                            filters={
                                "permit_number": f"eq.{permit_number}",
                                "town_id": f"eq.{town.id}",
                            },
                            limit=1,
                        )
                        if existing:
                            continue

                    await self._insert_permit(town.id, permit)
                    new_count += 1

            except Exception as exc:
                logger.warning(
                    "[Scheduler] LLM permit extraction failed for %s: %s",
                    town.name, exc,
                )

        logger.info(
            "[Scheduler] Firecrawl for %s: %d pages, %d permits found, %d new",
            town.name, len(pages), total_found, new_count,
        )
        return {"found": total_found, "new": new_count}

    async def _extract_permits_from_page(
        self, markdown: str, town_name: str
    ) -> List[Dict[str, Any]]:
        """Use LLM to extract structured permit data from a scraped page."""
        if not self.llm:
            return []

        import json

        text = markdown[:15000]

        prompt = (
            f"Extract all building/construction permit records from this {town_name} "
            f"municipal web page. For each permit found, return a JSON array of objects "
            f"with these fields:\n"
            f"- permit_number (string, required)\n"
            f"- address (string)\n"
            f"- permit_type (string: Building, Electrical, Plumbing, Gas, Demolition, etc.)\n"
            f"- status (string: Filed, Approved, Issued, Completed, Denied, etc.)\n"
            f"- description (string, brief)\n"
            f"- filed_date (string, YYYY-MM-DD if available)\n"
            f"- issued_date (string, YYYY-MM-DD if available)\n"
            f"- estimated_value (number or null)\n\n"
            f"If no permits are found, return an empty array: []\n"
            f"Return ONLY valid JSON, no explanation.\n\n"
            f"Page content:\n{text}"
        )

        try:
            client = self.llm._ensure_client()
            resp = client.messages.create(
                model=self.llm.model,
                max_tokens=self.llm.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            result_text = resp.content[0].text.strip()

            # Strip markdown code fences
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            permits = json.loads(result_text)
            if isinstance(permits, list):
                for p in permits:
                    p["source_system"] = "firecrawl"
                    p["town"] = town_name.lower().replace(" ", "_")
                return permits
        except Exception as exc:
            logger.debug("[Scheduler] LLM permit parse failed: %s", exc)

        return []

    async def _insert_permit(self, town_id: str, permit: dict):
        """Insert a normalized permit record into Supabase or local buffer."""
        from .connectors.normalize import parse_date

        record = {
            "id": str(uuid.uuid4()),
            "town_id": town_id,
            "permit_number": permit.get("permit_number", ""),
            "permit_type": permit.get("permit_type", "Building"),
            "status": (permit.get("status") or "FILED").upper(),
            "address": permit.get("address", ""),
            "description": (permit.get("description") or "")[:500],
            "estimated_value": permit.get("estimated_value"),
            "applicant_name": permit.get("applicant_name") or "",
            "contractor_name": permit.get("contractor_name") or "",
            "filed_date": parse_date(permit.get("filed_date")),
            "issued_date": parse_date(permit.get("issued_date")),
            "source_system": permit.get("source_system", "unknown"),
            "source_id": permit.get("source_id") or "",
            "latitude": permit.get("latitude") or 0,
            "longitude": permit.get("longitude") or 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if self.supabase:
            try:
                await self.supabase.insert("permits", record)
            except Exception as exc:
                logger.warning("[Scheduler] Insert permit error: %s", exc)

        # Buffer locally for JSON file export
        if self._local_storage_dir is not None:
            key = f"permits/{town_id}"
            self._local_buffer.setdefault(key, []).append(record)

    # ── Local File Storage ─────────────────────────────────────────────────

    def flush_to_files(self) -> Dict[str, int]:
        """Write buffered records to JSON files on disk.

        Returns dict mapping file paths to record counts written.
        """
        import os

        if not self._local_storage_dir:
            return {}

        os.makedirs(self._local_storage_dir, exist_ok=True)
        written = {}

        for key, records in self._local_buffer.items():
            if not records:
                continue

            # key is like "permits/newton" or "transfers/wellesley"
            parts = key.split("/", 1)
            table_name = parts[0]
            town_id = parts[1] if len(parts) > 1 else "unknown"

            subdir = os.path.join(self._local_storage_dir, table_name)
            os.makedirs(subdir, exist_ok=True)

            filepath = os.path.join(subdir, f"{town_id}.json")

            # Merge with existing file if present
            existing = []
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r") as f:
                        existing = json.load(f)
                except (json.JSONDecodeError, OSError):
                    existing = []

            # Dedup by id
            existing_ids = {r.get("id") for r in existing}
            merged = existing + [r for r in records if r.get("id") not in existing_ids]

            with open(filepath, "w") as f:
                json.dump(merged, f, indent=2, default=str)

            written[filepath] = len(merged)
            logger.info(
                "[Scheduler] Flushed %d records to %s (%d new)",
                len(merged), filepath, len(records),
            )

        # Clear buffer after flush
        self._local_buffer.clear()
        return written

    # ── Job Tracking ──────────────────────────────────────────────────────

    async def _create_job(self, town_id: str, source_type: str) -> str:
        """Create a new scrape job record."""
        job_id = str(uuid.uuid4())

        if self.supabase:
            try:
                await self.supabase.insert("scrape_jobs", {
                    "id": job_id,
                    "town_id": town_id,
                    "source_type": source_type,
                    "status": "pending",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as exc:
                logger.warning("[Scheduler] Failed to create job record: %s", exc)

        return job_id

    async def _update_job(
        self,
        job_id: str,
        status: str = "running",
        records_found: int = 0,
        records_new: int = 0,
        error: Optional[str] = None,
    ):
        """Update a scrape job record."""
        if not self.supabase:
            return

        update_data: Dict[str, Any] = {"status": status}

        if status == "running":
            update_data["started_at"] = datetime.now(timezone.utc).isoformat()
        elif status in ("completed", "failed"):
            update_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            update_data["records_found"] = records_found
            update_data["records_new"] = records_new

        if error:
            update_data["error_message"] = error

        try:
            await self.supabase.update(
                "scrape_jobs",
                filters={"id": f"eq.{job_id}"},
                data=update_data,
            )
        except Exception as exc:
            logger.warning("[Scheduler] Failed to update job %s: %s", job_id, exc)

    # ── Manual Triggers ───────────────────────────────────────────────────

    async def trigger_town_scrape(
        self,
        town_id: str,
        source_type: Optional[str] = None,
        partition: Optional[int] = None,
        num_partitions: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Manually trigger scraping for a specific town.

        Args:
            town_id: Town ID (e.g. "newton")
            source_type: Optional specific source type, or None for all
            partition: 0-based partition index for parallel scraping
            num_partitions: total number of partitions

        Returns:
            Results dict
        """
        town = TARGET_TOWNS.get(town_id.lower())
        if not town:
            return {"error": f"Unknown town: {town_id}"}

        results = {}

        if source_type is None or source_type == "property_transfers":
            results["transfers"] = await self.run_transfers_scrape(town)

        if source_type is None or source_type == "meeting_minutes":
            results["minutes"] = await self.run_minutes_scrape(town)

        if source_type is None or source_type == "permits":
            results["permits"] = await self.run_permits_scrape(
                town, partition=partition, num_partitions=num_partitions
            )

        return results
