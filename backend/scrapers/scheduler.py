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

    def __init__(
        self,
        supabase: Optional[Any] = None,
        firecrawl: Optional[FirecrawlClient] = None,
        llm_extractor: Optional[LLMExtractor] = None,
    ):
        self.supabase = supabase
        self.firecrawl = firecrawl
        self.llm = llm_extractor
        self._running = False

    # ── Background Loop ───────────────────────────────────────────────────

    async def start(self, check_interval_s: float = 300.0):
        """Start the scheduler background loop.

        Checks for pending jobs every `check_interval_s` seconds.
        """
        self._running = True
        logger.info("[Scheduler] Started — checking every %.0fs", check_interval_s)

        while self._running:
            try:
                await self.run_all_pending()
            except Exception as exc:
                logger.error("[Scheduler] Error in run cycle: %s", exc)

            await asyncio.sleep(check_interval_s)

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        logger.info("[Scheduler] Stopped")

    # ── Job Execution ─────────────────────────────────────────────────────

    async def run_all_pending(self):
        """Check all towns and run any overdue scrape jobs."""
        towns = get_all_towns()

        for town_id, town in towns.items():
            try:
                await self._check_and_run_town(town)
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
        """Insert a property transfer record into Supabase."""
        if not self.supabase:
            return

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

        try:
            await self.supabase.insert("property_transfers", record)
        except Exception as exc:
            logger.warning("[Scheduler] Insert transfer error: %s", exc)

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

    async def run_permits_scrape(self, town: TownConfig) -> Dict[str, Any]:
        """Scrape permits for a town (dispatches to correct connector)."""
        job_id = await self._create_job(town.id, "permits")

        try:
            await self._update_job(job_id, status="running")

            if town.permit_portal_type == "viewpointcloud" and town.viewpointcloud_slug:
                result = await self._scrape_viewpointcloud_permits(town)
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

    async def _scrape_viewpointcloud_permits(self, town: TownConfig) -> dict:
        """Scrape permits from ViewpointCloud portal."""
        # TODO: Implement using existing viewpointcloud.py connector
        logger.info("[Scheduler] ViewpointCloud scrape for %s — not yet implemented", town.name)
        return {"found": 0, "new": 0, "note": "viewpointcloud_todo"}

    async def _scrape_socrata_permits(self, town: TownConfig) -> dict:
        """Scrape permits from Socrata portal."""
        # TODO: Use existing socrata.py connector
        logger.info("[Scheduler] Socrata scrape for %s — not yet implemented", town.name)
        return {"found": 0, "new": 0, "note": "socrata_todo"}

    async def _scrape_firecrawl_permits(self, town: TownConfig) -> dict:
        """Scrape permits from town website using Firecrawl."""
        if not self.firecrawl or not town.permit_portal_url:
            return {"found": 0, "new": 0}

        logger.info("[Scheduler] Firecrawl permit scrape for %s", town.name)
        # Scrape the permit page for any structured permit data
        result = await self.firecrawl.scrape(town.permit_portal_url)
        if result:
            # Parse and store — implementation depends on town-specific format
            logger.info("[Scheduler] Got permit page content for %s (%d chars)",
                       town.name, len(result.get("markdown", "")))
        return {"found": 0, "new": 0, "note": "firecrawl_basic"}

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
    ) -> Dict[str, Any]:
        """Manually trigger scraping for a specific town.

        Args:
            town_id: Town ID (e.g. "newton")
            source_type: Optional specific source type, or None for all

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
            results["permits"] = await self.run_permits_scrape(town)

        return results
