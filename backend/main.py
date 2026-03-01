"""
Parcl Intelligence - Backend Entry Point

Real estate geospatial intelligence platform combining OSINT data feeds,
building permits, property analytics, and AI monitoring agents.

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
from fastapi.staticfiles import StaticFiles
from loguru import logger

from config import (
    BACKEND_HOST, BACKEND_PORT, FRONTEND_URL, BASE_DIR,
    SUPABASE_URL, SUPABASE_SERVICE_KEY,
)
from models.portfolio import Portfolio, PositionSide, Position
from api.routes import router, websocket_endpoint, _state
from api.websocket import ConnectionManager

# ── Data Clients ──
from data.opensky import OpenSkyClient
from data.weather import WeatherClient
from data.satellite import SatelliteClient
from data.ships import AISClient
from data.stocks import StockDataClient
from data.sec_filings import SECFilingsClient
from data.traffic_cameras import TrafficCameraClient
from data.satellites_orbital import SatelliteOrbitalClient
from data.military_flights import MilitaryFlightClient
from data.earthquakes import EarthquakeClient

# ── Services ──
from services.ledger import ComplianceLedger
from services.pdf_generator import AuditPDFGenerator
from services.vector_store import VectorStore

# ── Agents ──
from agents.orchestrator import ThesisOrchestrator
from agents.sensor_orchestrator import SensorOrchestrator
from agents.consensus_vision import ConsensusVisionAgent
from agents.quant_regression import QuantRegressionAgent
from agents.omnichannel_rag import OmnichannelRAGAgent
from agents.compliance_copilot import ComplianceCoPilot

# ── Real Estate / Parcl Intelligence ──
from database.supabase_client import SupabaseRestClient
from scrapers.permit_loader import PermitDataLoader
from services.permit_search import PermitSearchService


# ──────────────────────────────────────────────
# Background data refresh task
# ──────────────────────────────────────────────

async def _background_data_loop():
    """Periodically refresh flight, ship, and camera data and broadcast to clients."""
    from api.routes import ws_manager
    opensky = _state.get("opensky_client")
    ais = _state.get("ais_client")
    camera_client = _state.get("camera_client")

    while True:
        try:
            await asyncio.sleep(30)  # Refresh every 30 seconds

            if ws_manager.client_count == 0:
                continue  # Don't fetch if nobody is listening

            if opensky:
                flights = await opensky.get_all_states()
                if flights:
                    await ws_manager.broadcast_flights(flights)

            if ais:
                # Default to Rotterdam shipping lane
                ships = await ais.get_vessels_in_area(51.9, 4.5, 200)
                if ships:
                    await ws_manager.broadcast_ships(ships)

            if camera_client:
                cameras = await camera_client.get_all_cameras()
                if cameras:
                    await ws_manager.broadcast_cameras(cameras)

            # Satellites (orbital tracking)
            sat_client = _state.get("satellite_orbital_client")
            if sat_client:
                satellites = await sat_client.get_all_tracked(limit=300)
                if satellites:
                    await ws_manager.broadcast("satellites_update", {"satellites": satellites, "count": len(satellites)})

            # Military flights
            mil_client = _state.get("military_flight_client")
            if mil_client:
                mil_flights = await mil_client.get_military_flights(limit=200)
                if mil_flights:
                    await ws_manager.broadcast("military_flights_update", {"flights": mil_flights, "count": len(mil_flights)})

            # Earthquakes
            eq_client = _state.get("earthquake_client")
            if eq_client:
                quakes = await eq_client.get_earthquakes(feed="m2.5_week", limit=300)
                if quakes:
                    await ws_manager.broadcast("earthquakes_update", {"earthquakes": quakes, "count": len(quakes)})

            # Portfolio price refresh
            portfolio = _state.get("portfolio")
            stock_client = _state.get("stock_client")
            if portfolio and stock_client and portfolio.positions:
                updated = False
                for pos in portfolio.positions:
                    try:
                        price = stock_client.get_current_price(pos.ticker)
                        if price:
                            pos.current_price = price
                            pos.pnl = (price - pos.avg_entry_price) * pos.shares
                            if pos.side == PositionSide.SHORT:
                                pos.pnl = -pos.pnl
                            updated = True
                    except Exception:
                        pass
                if updated:
                    await ws_manager.broadcast_portfolio(portfolio.model_dump())

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Background data loop error: {e}")
            await asyncio.sleep(5)


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
                    # Get agent config
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

                    # Check if agent is due to run
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

                    # Run agent: search for permits near location
                    permits = await permit_loader.search(
                        address=address,
                        latitude=lat,
                        longitude=lon,
                        radius_km=0.5,
                        limit=5,
                    )

                    # Update last_run
                    if isinstance(agent, dict):
                        agent["last_run"] = now.isoformat()
                        agent["findings_count"] = agent.get("findings_count", 0) + (1 if permits else 0)
                    else:
                        agent.last_run = now.isoformat()
                        agent.findings_count = getattr(agent, "findings_count", 0) + (1 if permits else 0)

                    # Generate finding if permits found
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

    # ── Initialize Data Clients ──
    opensky_client = OpenSkyClient()
    weather_client = WeatherClient()
    satellite_client = SatelliteClient()
    ais_client = AISClient()
    stock_client = StockDataClient()
    sec_client = SECFilingsClient()
    camera_client = TrafficCameraClient()
    satellite_orbital_client = SatelliteOrbitalClient()
    military_flight_client = MilitaryFlightClient()
    earthquake_client = EarthquakeClient()
    logger.info("Data clients initialized (incl. cameras, satellites, military, earthquakes)")

    # ── Initialize Services ──
    compliance_ledger = ComplianceLedger()
    pdf_generator = AuditPDFGenerator()
    vector_store = VectorStore()
    logger.info("Services initialized")

    # ── Initialize Agents ──
    orchestrator = ThesisOrchestrator()
    sensor_orchestrator = SensorOrchestrator(
        weather_client=weather_client,
        satellite_client=satellite_client,
        opensky_client=opensky_client,
        ais_client=ais_client,
        ledger=compliance_ledger,
    )
    vision_agent = ConsensusVisionAgent()
    quant_agent = QuantRegressionAgent(stock_client=stock_client)
    rag_agent = OmnichannelRAGAgent(
        sec_client=sec_client,
        vector_store=vector_store,
    )
    compliance_copilot = ComplianceCoPilot(ledger=compliance_ledger)
    logger.info("6-Agent pipeline initialized")

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

    # ── Initialize Real Estate / Parcl Intelligence ──
    permit_loader = PermitDataLoader(supabase=supabase_client)
    await permit_loader.load()
    permit_search = PermitSearchService(permit_loader)
    mode = "Supabase" if permit_loader.is_supabase else "demo JSON"
    logger.info(f"Parcl Intelligence: {permit_loader.count:,} permits ({mode}), RAG search ready")

    # ── Initialize Portfolio ──
    portfolio = Portfolio(fund_name="Sentinel Fund")

    # ── Inject into route state ──
    _state.update({
        "opensky_client": opensky_client,
        "weather_client": weather_client,
        "satellite_client": satellite_client,
        "ais_client": ais_client,
        "stock_client": stock_client,
        "sec_client": sec_client,
        "camera_client": camera_client,
        "satellite_orbital_client": satellite_orbital_client,
        "military_flight_client": military_flight_client,
        "earthquake_client": earthquake_client,
        "compliance_ledger": compliance_ledger,
        "pdf_generator": pdf_generator,
        "vector_store": vector_store,
        "orchestrator": orchestrator,
        "sensor_orchestrator": sensor_orchestrator,
        "vision_agent": vision_agent,
        "quant_agent": quant_agent,
        "rag_agent": rag_agent,
        "compliance_copilot": compliance_copilot,
        "portfolio": portfolio,
        "alerts_store": [],
        # Parcl Intelligence
        "permit_loader": permit_loader,
        "permit_search": permit_search,
        "property_agents": [],
        "supabase_client": supabase_client,
    })

    # ── Start background data refresh ──
    bg_task = asyncio.create_task(_background_data_loop())

    # ── Start agent execution loop ──
    agent_loop_task = asyncio.create_task(_agent_execution_loop(_state))

    logger.info("=" * 60)
    logger.info("  PARCL INTELLIGENCE - ONLINE")
    logger.info(f"  Backend:   http://{BACKEND_HOST}:{BACKEND_PORT}")
    logger.info(f"  Frontend:  {FRONTEND_URL}")
    logger.info(f"  WebSocket: ws://{BACKEND_HOST}:{BACKEND_PORT}/ws")
    logger.info(f"  Permits:   {permit_loader.count:,} ({mode})")
    logger.info(f"  Database:  {'Supabase REST' if supabase_client else 'demo JSON'}")
    logger.info("=" * 60)

    yield

    # ── Shutdown ──
    logger.info("Parcl Intelligence shutting down...")
    bg_task.cancel()
    agent_loop_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        pass
    try:
        await agent_loop_task
    except asyncio.CancelledError:
        pass
    if supabase_client:
        await supabase_client.disconnect()


# ──────────────────────────────────────────────
# FastAPI Application
# ──────────────────────────────────────────────

app = FastAPI(
    title="Parcl Intelligence",
    description="Real Estate Geospatial Intelligence Platform — Property, Permit, and Market Analytics",
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

# Serve audit PDFs
audit_dir = BASE_DIR / "audit_reports"
audit_dir.mkdir(exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(audit_dir)), name="reports")


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
