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
from api.routes import router, websocket_endpoint, _state
from api.websocket import ConnectionManager

# ── Real Estate / Parcl Intelligence ──
from database.supabase_client import SupabaseRestClient
from scrapers.permit_loader import PermitDataLoader
from services.permit_search import PermitSearchService
from scrapers.scheduler import ScrapeScheduler
from scrapers.connectors.firecrawl_client import FirecrawlClient
from scrapers.connectors.llm_extractor import LLMExtractor


# ──────────────────────────────────────────────
# Agent execution background loop
# ──────────────────────────────────────────────

async def _agent_execution_loop(state: dict):
    """Periodically run property monitoring agents and generate findings."""
    import uuid as uuid_mod
    from datetime import datetime, timezone
    from api.routes import ws_manager

    logger.info("Agent execution loop started")

    while True:
        try:
            await asyncio.sleep(60)  # Check every 60 seconds

            agents = state.get("property_agents", [])
            permit_loader = state.get("permit_loader")

            if not agents or not permit_loader:
                continue

            now = datetime.now(timezone.utc)

            for agent in agents:
                try:
                    config = agent.get("config", {}) if isinstance(agent, dict) else getattr(agent, "config", {})
                    agent_id = agent.get("id", "") if isinstance(agent, dict) else getattr(agent, "id", "")
                    entity_id = agent.get("entity_id", "") if isinstance(agent, dict) else getattr(agent, "entity_id", "")
                    agent_status = agent.get("status", "active") if isinstance(agent, dict) else getattr(agent, "status", "active")

                    if agent_status != "active":
                        continue

                    lat = config.get("latitude")
                    lon = config.get("longitude")
                    address = config.get("address", "")

                    if not (lat and lon):
                        continue

                    interval = agent.get("run_interval_seconds", 3600) if isinstance(agent, dict) else getattr(agent, "run_interval_seconds", 3600)
                    last_run_str = agent.get("last_run") if isinstance(agent, dict) else getattr(agent, "last_run", None)

                    if last_run_str:
                        try:
                            if isinstance(last_run_str, str):
                                last_run = datetime.fromisoformat(last_run_str.replace("Z", "+00:00"))
                            else:
                                last_run = last_run_str
                            if (now - last_run).total_seconds() < interval:
                                continue
                        except Exception:
                            pass

                    permits = await permit_loader.search(
                        address=address,
                        latitude=lat,
                        longitude=lon,
                        radius_km=0.5,
                        limit=5,
                    )

                    if isinstance(agent, dict):
                        agent["last_run"] = now.isoformat()
                        agent["findings_count"] = agent.get("findings_count", 0) + (1 if permits else 0)
                    else:
                        agent.last_run = now.isoformat()
                        agent.findings_count = getattr(agent, "findings_count", 0) + (1 if permits else 0)

                    if permits and ws_manager:
                        finding = {
                            "id": uuid_mod.uuid4().hex[:12],
                            "agent_id": agent_id,
                            "property_id": entity_id,
                            "finding_type": "PERMIT_ACTIVITY",
                            "severity": "LOW" if len(permits) < 3 else "MEDIUM" if len(permits) < 10 else "HIGH",
                            "title": f"{len(permits)} permit(s) near {address[:40] if address else 'monitored location'}",
                            "summary": f"Found {len(permits)} active permits within 0.5km." + (f" Most recent: {permits[0].get('description', '')[:80]}" if permits[0].get('description') else ""),
                            "data": {"permit_count": len(permits)},
                            "latitude": lat,
                            "longitude": lon,
                            "acknowledged": False,
                            "created_at": now.isoformat(),
                        }

                        try:
                            await ws_manager.broadcast("agent_finding", {"finding": finding})
                            logger.debug("Agent %s generated finding: %s", agent_id, finding["title"])
                        except Exception as e:
                            logger.warning("Failed to broadcast finding: %s", e)

                except Exception as e:
                    logger.debug("Agent execution error for %s: %s", agent_id if 'agent_id' in dir() else '?', e)

        except asyncio.CancelledError:
            logger.info("Agent execution loop cancelled")
            break
        except Exception as e:
            logger.error("Agent execution loop error: %s", e)
            await asyncio.sleep(10)


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

    # ── Start background tasks ──
    agent_loop_task = asyncio.create_task(_agent_execution_loop(_state))
    scheduler_task = asyncio.create_task(scrape_scheduler.start(check_interval_s=300.0))

    logger.info("=" * 60)
    logger.info("  PARCL INTELLIGENCE - ONLINE")
    logger.info(f"  Backend:    http://{BACKEND_HOST}:{BACKEND_PORT}")
    logger.info(f"  Frontend:   {FRONTEND_URL}")
    logger.info(f"  WebSocket:  ws://{BACKEND_HOST}:{BACKEND_PORT}/ws")
    logger.info(f"  Permits:    {permit_loader.count:,} ({mode})")
    logger.info(f"  Database:   {'Supabase REST' if supabase_client else 'demo JSON'}")
    logger.info(f"  Firecrawl:  {'active' if firecrawl_client else 'not configured'}")
    logger.info(f"  Scheduler:  active (12 towns)")
    logger.info("=" * 60)

    yield

    # ── Shutdown ──
    logger.info("Parcl Intelligence shutting down...")
    scrape_scheduler.stop()
    scheduler_task.cancel()
    agent_loop_task.cancel()

    for task in [scheduler_task, agent_loop_task]:
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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes
app.include_router(router, prefix="/api")

# WebSocket
app.add_websocket_route("/ws", websocket_endpoint)


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
