"""
Parcl Intelligence - Backend Entry Point

Real estate data intelligence platform for affluent Massachusetts communities.
Property analytics, permit tracking, municipal document scraping, and market monitoring.

Usage:
    python main.py
    # or
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from config import (
    BACKEND_HOST, BACKEND_PORT, FRONTEND_URL,
    SUPABASE_URL, SUPABASE_SERVICE_KEY,
    FIRECRAWL_API_KEY,
)
from api.routes import router, _state

# ── Real Estate / Parcl Intelligence ──
from database.supabase_client import SupabaseRestClient
from scrapers.permit_loader import PermitDataLoader
from services.permit_search import PermitSearchService
from scrapers.scheduler import ScrapeScheduler
from scrapers.connectors.firecrawl_client import FirecrawlClient
from scrapers.connectors.llm_extractor import LLMExtractor


# ──────────────────────────────────────────────
# Application lifecycle
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize all clients, services, and agents on startup."""
    logger.info("=" * 60)
    logger.info("  PARCL INTELLIGENCE - Initializing")
    logger.info("=" * 60)

    # ── Initialize Supabase (municipal-intel data) ──
    supabase_client = None
    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        supabase_client = SupabaseRestClient(
            url=SUPABASE_URL,
            service_key=SUPABASE_SERVICE_KEY,
        )
        connected = await supabase_client.connect()
        if connected:
            logger.info(f"Supabase REST API: {supabase_client.base_url}")
        else:
            logger.warning("Supabase connection failed — falling back to demo data")
            supabase_client = None
    else:
        logger.info("No Supabase credentials — using demo data")

    # ── Initialize Permit Data ──
    permit_loader = PermitDataLoader(supabase=supabase_client)
    await permit_loader.load()
    permit_search = PermitSearchService(permit_loader)
    mode = "Supabase" if permit_loader.is_supabase else "demo JSON"
    logger.info(f"Parcl Intelligence: {permit_loader.count:,} permits ({mode}), RAG search ready")

    # ── Initialize Scrape Scheduler ──
    firecrawl_client = None
    llm_extractor = None

    if FIRECRAWL_API_KEY:
        firecrawl_client = FirecrawlClient(api_key=FIRECRAWL_API_KEY)
        logger.info("Firecrawl client initialized")

    try:
        llm_extractor = LLMExtractor()
        logger.info("LLM extractor initialized (Claude API)")
    except Exception as exc:
        logger.warning("LLM extractor not available: %s", exc)

    scrape_scheduler = ScrapeScheduler(
        supabase=supabase_client,
        firecrawl=firecrawl_client,
        llm_extractor=llm_extractor,
    )
    logger.info("Scrape scheduler initialized")

    # ── Inject into route state ──
    _state.update({
        "permit_loader": permit_loader,
        "permit_search": permit_search,
        "property_agents": [],
        "supabase_client": supabase_client,
        "scrape_scheduler": scrape_scheduler,
        "firecrawl_client": firecrawl_client,
        "llm_extractor": llm_extractor,
    })

    # ── Start background scrape scheduler with watchdog ──
    check_interval = 300.0

    def _start_scheduler_task() -> asyncio.Task:
        task = asyncio.create_task(
            scrape_scheduler.start(check_interval_s=check_interval)
        )
        task.set_name("scrape-scheduler")
        return task

    scheduler_task = _start_scheduler_task()

    async def _watchdog(interval: float = 60.0):
        """Monitor the scheduler task and restart it if it exits unexpectedly."""
        nonlocal scheduler_task
        while True:
            await asyncio.sleep(interval)
            if scheduler_task.done():
                exc = scheduler_task.exception() if not scheduler_task.cancelled() else None
                if exc:
                    logger.error("[Watchdog] Scheduler died with: %s — restarting", exc)
                else:
                    logger.warning("[Watchdog] Scheduler exited unexpectedly — restarting")
                scrape_scheduler._running = False
                scheduler_task = _start_scheduler_task()
            elif not scrape_scheduler.is_alive:
                logger.warning("[Watchdog] Scheduler heartbeat stale — restarting")
                scrape_scheduler.stop()
                scheduler_task.cancel()
                try:
                    await scheduler_task
                except asyncio.CancelledError:
                    pass
                scheduler_task = _start_scheduler_task()

    watchdog_task = asyncio.create_task(_watchdog())
    watchdog_task.set_name("scheduler-watchdog")

    logger.info("=" * 60)
    logger.info("  PARCL INTELLIGENCE - ONLINE")
    logger.info(f"  Backend:    http://{BACKEND_HOST}:{BACKEND_PORT}")
    logger.info(f"  Frontend:   {FRONTEND_URL}")
    logger.info(f"  Permits:    {permit_loader.count:,} ({mode})")
    logger.info(f"  Database:   {'Supabase REST' if supabase_client else 'demo JSON'}")
    logger.info(f"  Firecrawl:  {'active' if firecrawl_client else 'not configured'}")
    logger.info(f"  Scheduler:  active (12 towns, watchdog enabled)")
    logger.info("=" * 60)

    yield

    # ── Shutdown ──
    logger.info("Parcl Intelligence shutting down...")
    watchdog_task.cancel()
    scrape_scheduler.stop()
    scheduler_task.cancel()

    for task in (watchdog_task, scheduler_task):
        try:
            await task
        except asyncio.CancelledError:
            pass

    if supabase_client:
        await supabase_client.disconnect()


# ──────────────────────────────────────────────
# FastAPI Application
# ──────────────────────────────────────────────

app = FastAPI(
    title="Parcl Intelligence",
    description="Real Estate Data Intelligence Platform — Property, Permit, and Market Analytics for Massachusetts",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow Vercel production + local dev
_cors_origins = [
    FRONTEND_URL,
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "https://sentinel-agent-alpha.vercel.app",
    "https://sentinel-agent-alvaro-espinals-projects.vercel.app",
    "https://sentinel-agent-git-main-alvaro-espinals-projects.vercel.app",
]
# Filter out empty strings
_cors_origins = [o for o in _cors_origins if o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes
app.include_router(router, prefix="/api")


# ──────────────────────────────────────────────
# Dev server entry
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        reload=True,
        log_level="info",
    )
