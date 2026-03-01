"""FastAPI routes - REST endpoints and WebSocket handler."""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from loguru import logger

from models.portfolio import Portfolio, Position, PositionSide, AssetClass, GeoTarget, ThesisInput
from models.alerts import SentinelAlert, AlertSeverity, AlertCategory, RecommendedAction
from models.compliance import DataProvenanceRecord, AuditReport
from api.websocket import ConnectionManager

# These will be injected by main.py at startup
_state: dict = {}
_vision_store: dict = {"plates": [], "faces": []}

router = APIRouter()
ws_manager = ConnectionManager()


def _get(key: str):
    return _state.get(key)


# ──────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────

class ThesisRequest(BaseModel):
    text: str
    ticker: Optional[str] = None
    priority: str = "normal"


class PositionRequest(BaseModel):
    ticker: str
    name: str
    side: str = "LONG"
    shares: int = 100
    avg_entry_price: float = 0.0
    sector: Optional[str] = None
    thesis: Optional[str] = None


class ThesisResponse(BaseModel):
    status: str
    message: str
    geo_targets: list[dict] = []
    taskings_created: int = 0
    trade_proposal: Optional[dict] = None


class PositionModifyRequest(BaseModel):
    action: str  # SIZE_UP, SIZE_DOWN, EXIT
    shares_delta: Optional[int] = None


# ──────────────────────────────────────────────
# Portfolio endpoints
# ──────────────────────────────────────────────

@router.get("/portfolio")
async def get_portfolio():
    """Get the current portfolio state."""
    portfolio: Portfolio = _get("portfolio")
    if not portfolio:
        return {"fund_name": "Sentinel Fund", "positions": [], "last_synced": None, "total_nav": 0}

    # Update current prices
    stock_client = _get("stock_client")
    if stock_client:
        for pos in portfolio.positions:
            if pos.current_price is None:
                price = stock_client.get_current_price(pos.ticker)
                if price:
                    pos.current_price = price
                    pos.pnl = (price - pos.avg_entry_price) * pos.shares
                    if pos.side == PositionSide.SHORT:
                        pos.pnl = -pos.pnl

    return portfolio.model_dump()


@router.post("/portfolio/position")
async def add_position(req: PositionRequest):
    """Add a new position to the portfolio."""
    portfolio: Portfolio = _get("portfolio")
    if not portfolio:
        portfolio = Portfolio()
        _state["portfolio"] = portfolio

    # Get geo targets from orchestrator
    orchestrator = _get("orchestrator")
    geo_targets = []
    if orchestrator:
        geo_targets = orchestrator.get_geo_targets_for_ticker(req.ticker)

    # Auto-fetch price if not provided
    entry_price = req.avg_entry_price
    current_price = None
    stock_client = _get("stock_client")
    if entry_price == 0 and stock_client:
        price = stock_client.get_current_price(req.ticker.upper())
        if price:
            entry_price = price
            current_price = price

    position = Position(
        ticker=req.ticker.upper(),
        name=req.name,
        side=PositionSide(req.side.upper()),
        shares=req.shares,
        avg_entry_price=entry_price,
        current_price=current_price,
        sector=req.sector,
        thesis=req.thesis,
        geo_targets=geo_targets,
    )

    # Remove existing position with same ticker
    portfolio.positions = [p for p in portfolio.positions if p.ticker != position.ticker]
    portfolio.positions.append(position)
    portfolio.last_synced = datetime.utcnow()

    # Broadcast update
    await ws_manager.broadcast_portfolio(portfolio.model_dump())

    return {"status": "ok", "ticker": position.ticker, "geo_targets": len(geo_targets)}


@router.delete("/portfolio/position/{ticker}")
async def remove_position(ticker: str):
    """Remove a position from the portfolio."""
    portfolio: Portfolio = _get("portfolio")
    if not portfolio:
        raise HTTPException(404, "No portfolio loaded")

    before = len(portfolio.positions)
    portfolio.positions = [p for p in portfolio.positions if p.ticker.upper() != ticker.upper()]
    if len(portfolio.positions) == before:
        raise HTTPException(404, f"Position {ticker} not found")

    await ws_manager.broadcast_portfolio(portfolio.model_dump())
    return {"status": "ok", "removed": ticker}


@router.patch("/portfolio/position/{ticker}")
async def modify_position(ticker: str, req: PositionModifyRequest):
    """Modify a position based on alert action (SIZE_UP, SIZE_DOWN, EXIT)."""
    portfolio: Portfolio = _get("portfolio")
    if not portfolio:
        raise HTTPException(404, "No portfolio loaded")

    position = portfolio.get_position(ticker)
    if not position:
        raise HTTPException(404, f"Position {ticker} not found")

    action = req.action.upper()

    if action == "EXIT":
        portfolio.positions = [p for p in portfolio.positions if p.ticker.upper() != ticker.upper()]
        await ws_manager.broadcast_portfolio(portfolio.model_dump())
        return {"status": "ok", "action": "EXIT", "ticker": ticker}

    delta = req.shares_delta or max(1, int(position.shares * 0.10))

    if action == "SIZE_UP":
        position.shares += delta
    elif action == "SIZE_DOWN":
        position.shares = max(1, position.shares - delta)
    else:
        raise HTTPException(400, f"Unknown action: {action}")

    # Recalculate PnL
    if position.current_price and position.avg_entry_price:
        position.pnl = (position.current_price - position.avg_entry_price) * position.shares
        if position.side == PositionSide.SHORT:
            position.pnl = -position.pnl

    await ws_manager.broadcast_portfolio(portfolio.model_dump())
    return {"status": "ok", "action": action, "ticker": ticker, "new_shares": position.shares}


# ──────────────────────────────────────────────
# Thesis / Agent endpoints
# ──────────────────────────────────────────────

@router.post("/thesis", response_model=ThesisResponse)
async def submit_thesis(req: ThesisRequest):
    """Submit a natural language thesis for the agent to process."""
    orchestrator = _get("orchestrator")
    portfolio: Portfolio = _get("portfolio")

    if not orchestrator:
        return ThesisResponse(
            status="error", message="Orchestrator not initialized", geo_targets=[], taskings_created=0
        )

    thesis = ThesisInput(text=req.text, ticker=req.ticker, priority=req.priority)

    try:
        taskings = await orchestrator.process_thesis(thesis, portfolio)

        geo_targets = []
        for t in taskings:
            gt = t.geo_target
            geo_targets.append(gt.model_dump())

        # Kick off the full agent pipeline in the background
        asyncio.create_task(_run_agent_pipeline(taskings))

        # Build trade proposal for user confirmation
        stock_client = _get("stock_client")
        proposal = orchestrator.build_trade_proposal(thesis, portfolio, stock_client)
        proposal_dict = proposal.model_dump() if proposal else None

        return ThesisResponse(
            status="ok",
            message=f"Thesis processed. Monitoring {len(taskings)} locations.",
            geo_targets=geo_targets,
            taskings_created=len(taskings),
            trade_proposal=proposal_dict,
        )

    except Exception as e:
        logger.error(f"Thesis processing error: {e}")
        return ThesisResponse(status="error", message=str(e))


async def _run_agent_pipeline(taskings):
    """Run the full 6-agent pipeline for a set of sensor taskings."""
    sensor_orch = _get("sensor_orchestrator")
    vision_agent = _get("vision_agent")
    quant_agent = _get("quant_agent")
    rag_agent = _get("rag_agent")
    compliance = _get("compliance_copilot")
    portfolio: Portfolio = _get("portfolio")
    alerts_store: list = _get("alerts_store")

    if not all([sensor_orch, vision_agent, quant_agent, rag_agent, compliance]):
        logger.error("Agent pipeline incomplete, skipping")
        return

    for tasking in taskings:
        try:
            # Step 1: Sensor Orchestrator - get data
            sensor_data = await sensor_orch.execute_tasking(tasking)
            if not sensor_data:
                continue

            # Step 2: Consensus Vision Agent - detect anomalies
            anomaly = await vision_agent.analyze(sensor_data, tasking.geo_target)
            if not anomaly or anomaly.consensus_score < 0.5:
                continue

            # Step 3: Quant Regression Agent - check financial materiality
            backtest = await quant_agent.backtest_anomaly(anomaly, tasking.geo_target.asset_ticker)
            if not backtest.is_material:
                logger.info(f"Anomaly for {tasking.geo_target.asset_ticker} suppressed (R²={backtest.r_squared:.3f})")
                continue

            # Step 4: Omnichannel RAG Agent - adjust for digital revenue
            omnichannel = await rag_agent.adjust_for_digital(anomaly, tasking.geo_target.asset_ticker)

            # Step 5: Determine recommendation
            position = portfolio.get_position(tasking.geo_target.asset_ticker) if portfolio else None
            position_side = position.side.value if position else "UNKNOWN"
            shares = position.shares if position else 0

            action, rationale = quant_agent._recommend_action(backtest, position_side)

            # Adjust severity based on omnichannel
            severity = AlertSeverity.HIGH
            if anomaly.consensus_score >= 0.95 and backtest.r_squared >= 0.5:
                severity = AlertSeverity.CRITICAL
            elif backtest.r_squared < 0.4:
                severity = AlertSeverity.MEDIUM
            if omnichannel and omnichannel.adjusted_severity:
                severity = omnichannel.adjusted_severity

            # Step 6: Create the alert
            alert = SentinelAlert(
                ticker=tasking.geo_target.asset_ticker,
                position_side=position_side,
                shares=shares,
                title=f"{anomaly.anomaly_type.replace('_', ' ').title()} detected at {tasking.geo_target.name}",
                summary=_generate_alert_summary(anomaly, backtest, omnichannel, tasking.geo_target),
                severity=severity,
                category=_infer_category(anomaly.anomaly_type),
                confidence_score=anomaly.consensus_score * (0.5 + 0.5 * backtest.r_squared),
                latitude=tasking.geo_target.latitude,
                longitude=tasking.geo_target.longitude,
                location_name=tasking.geo_target.name,
                anomaly=anomaly,
                backtest=backtest,
                omnichannel=omnichannel,
                recommended_action=action,
                action_rationale=rationale,
                data_sources=sensor_data.get("provenance_urls", []),
                camera_target={
                    "lat": tasking.geo_target.latitude,
                    "lon": tasking.geo_target.longitude,
                    "altitude": 50000,
                    "heading": 0,
                    "pitch": -45,
                },
            )

            # Step 7: Compliance logging
            compliance_hash = await compliance.validate_and_log(
                sensor_data.get("provenance_records", []), alert
            )
            alert.compliance_hash = compliance_hash

            # Store and broadcast
            alerts_store.append(alert)
            await ws_manager.broadcast_alert(alert.model_dump())
            logger.info(f"ALERT FIRED: [{severity.value}] {alert.title} ({alert.ticker})")

        except Exception as e:
            logger.error(f"Agent pipeline error for {tasking.geo_target.name}: {e}")
            import traceback
            traceback.print_exc()


def _generate_alert_summary(anomaly, backtest, omnichannel, geo_target) -> str:
    """Generate a natural language alert summary."""
    parts = []
    parts.append(
        f"{anomaly.anomaly_type.replace('_', ' ').title()} detected at {geo_target.name}. "
        f"Magnitude: {anomaly.magnitude:.1f}% change."
    )

    if backtest.is_material:
        parts.append(
            f"Historical regression (R²={backtest.r_squared:.2f}) shows a "
            f"{abs(backtest.predicted_price_impact_pct):.1f}% predicted price impact "
            f"within {backtest.prediction_window_days} days."
        )

    if omnichannel and omnichannel.digital_revenue_pct > 20:
        parts.append(
            f"Note: {omnichannel.digital_revenue_pct:.0f}% of revenue is digital. "
            f"{omnichannel.adjustment_rationale}"
        )

    return " ".join(parts)


def _infer_category(anomaly_type: str) -> AlertCategory:
    """Infer alert category from anomaly type."""
    mapping = {
        "vehicle_count": AlertCategory.FOOT_TRAFFIC,
        "thermal": AlertCategory.PRODUCTION,
        "ship": AlertCategory.SUPPLY_CHAIN,
        "flight": AlertCategory.CORPORATE_ACTIVITY,
        "traffic": AlertCategory.LOGISTICS,
        "production": AlertCategory.PRODUCTION,
        "construction": AlertCategory.PRODUCTION,
    }
    for key, cat in mapping.items():
        if key in anomaly_type.lower():
            return cat
    return AlertCategory.PRODUCTION


# ──────────────────────────────────────────────
# Alert endpoints
# ──────────────────────────────────────────────

@router.get("/alerts")
async def get_alerts():
    """Get all current alerts."""
    alerts_store: list = _get("alerts_store") or []
    return {
        "alerts": [a.model_dump() for a in alerts_store],
        "count": len(alerts_store),
        "critical": sum(1 for a in alerts_store if a.severity == AlertSeverity.CRITICAL),
        "high": sum(1 for a in alerts_store if a.severity == AlertSeverity.HIGH),
    }


@router.get("/alerts/{alert_id}")
async def get_alert(alert_id: str):
    """Get a specific alert by ID."""
    alerts_store: list = _get("alerts_store") or []
    for a in alerts_store:
        if a.id == alert_id:
            return a.model_dump()
    raise HTTPException(404, "Alert not found")


# ──────────────────────────────────────────────
# Data endpoints (flights, ships)
# ──────────────────────────────────────────────

@router.get("/data/flights")
async def get_flights(
    lat_min: Optional[float] = None,
    lat_max: Optional[float] = None,
    lon_min: Optional[float] = None,
    lon_max: Optional[float] = None,
):
    """Get current ADSB flight data."""
    opensky = _get("opensky_client")
    if not opensky:
        return {"flights": [], "count": 0}

    bbox = None
    if all(v is not None for v in [lat_min, lat_max, lon_min, lon_max]):
        bbox = (lat_min, lat_max, lon_min, lon_max)

    flights = await opensky.get_all_states(bbox=bbox)
    return {"flights": flights, "count": len(flights)}


@router.get("/data/ships")
async def get_ships(
    lat: float = 51.9,
    lon: float = 4.5,
    radius_km: float = 200,
):
    """Get AIS vessel data around a point."""
    ais = _get("ais_client")
    if not ais:
        return {"ships": [], "count": 0}

    ships = await ais.get_vessels_in_area(lat, lon, radius_km)
    return {"ships": ships, "count": len(ships)}


@router.get("/data/cameras")
async def get_cameras(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: float = 50,
):
    """Get public traffic/webcam camera feeds."""
    camera_client = _get("camera_client")
    if not camera_client:
        return {"cameras": [], "count": 0}

    if lat is not None and lon is not None:
        cameras = await camera_client.get_cameras_near(lat, lon, radius_km)
    else:
        cameras = await camera_client.get_all_cameras()
    return {"cameras": cameras, "count": len(cameras)}


@router.get("/data/cameras/proxy")
async def proxy_camera_image(url: str = Query(..., description="Camera image URL to proxy")):
    """Proxy a camera image to avoid CORS/mixed-content issues."""
    import httpx
    from urllib.parse import urlparse

    ALLOWED_DOMAINS = [
        "cwwp2.dot.ca.gov",
        "wzmedia.dot.ca.gov",
        "webcams.nyctmc.org",
        "images.wsdot.wa.gov",
        "its.txdot.gov",
        "fl511.com",
        "navigator.dot.ga.gov",
        "images.marinetraffic.com",
        "chicagoweathercenter.com",
        "www.portofrotterdam.com",
        "chart.maryland.gov",
        "strmr1.sha.maryland.gov",
        "strmr2.sha.maryland.gov",
        "strmr3.sha.maryland.gov",
        "strmr4.sha.maryland.gov",
        "strmr5.sha.maryland.gov",
        "api.windy.com",
        "www.thebostonwebcam.com",
        "www.mwra.com",
        "weathercams.faa.gov",
        "services.arcgis.com",
        "mass511.com",
    ]
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=403, detail=f"Domain {parsed.hostname} not in allowed list")

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Upstream error")
            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(content=resp.content, media_type=content_type)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Camera feed timeout")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Proxy error: {str(e)[:100]}")


# ──────────────────────────────────────────────
# Satellite orbital tracking
# ──────────────────────────────────────────────

@router.get("/data/satellites")
async def get_satellites(
    category: str = "stations",
    limit: int = 300,
):
    """Get real-time satellite orbital positions from CelesTrak TLE data."""
    sat_client = _get("satellite_orbital_client")
    if not sat_client:
        return {"satellites": [], "count": 0}

    if category == "all":
        satellites = await sat_client.get_all_tracked(limit=limit)
    else:
        satellites = await sat_client.get_satellites(category=category, limit=limit)
    return {"satellites": satellites, "count": len(satellites)}


@router.get("/data/satellites/{norad_id}/orbit")
async def get_satellite_orbit(norad_id: int):
    """Get the orbital path for a specific satellite by NORAD ID."""
    sat_client = _get("satellite_orbital_client")
    if not sat_client:
        raise HTTPException(404, "Satellite client not available")

    orbit = await sat_client.get_satellite_orbit(norad_id)
    if not orbit:
        raise HTTPException(404, f"Satellite NORAD {norad_id} not found")
    return orbit


# ──────────────────────────────────────────────
# Military flight tracking
# ──────────────────────────────────────────────

@router.get("/data/military-flights")
async def get_military_flights(limit: int = 200):
    """Get currently tracked military flights via ADS-B Exchange."""
    mil_client = _get("military_flight_client")
    if not mil_client:
        return {"flights": [], "count": 0}

    flights = await mil_client.get_military_flights(limit=limit)
    return {"flights": flights, "count": len(flights)}


# ──────────────────────────────────────────────
# Earthquake / Seismic data
# ──────────────────────────────────────────────

@router.get("/data/earthquakes")
async def get_earthquakes(
    feed: str = "m2.5_week",
    min_magnitude: Optional[float] = None,
    limit: int = 500,
):
    """Get real-time earthquake data from USGS."""
    eq_client = _get("earthquake_client")
    if not eq_client:
        return {"earthquakes": [], "count": 0}

    quakes = await eq_client.get_earthquakes(
        feed=feed,
        min_magnitude=min_magnitude,
        limit=limit,
    )
    return {"earthquakes": quakes, "count": len(quakes)}


# ──────────────────────────────────────────────
# Compliance endpoints
# ──────────────────────────────────────────────

@router.post("/compliance/audit/{alert_id}")
async def generate_audit(alert_id: str):
    """Generate a 1-click SEC audit PDF for an alert."""
    alerts_store: list = _get("alerts_store") or []
    compliance = _get("compliance_copilot")
    pdf_gen = _get("pdf_generator")

    alert = None
    for a in alerts_store:
        if a.id == alert_id:
            alert = a
            break

    if not alert:
        raise HTTPException(404, "Alert not found")

    try:
        report = await compliance.generate_audit_report(alert_id)

        filepath = pdf_gen.generate_full(
            alert=alert,
            provenance_records=report.provenance_records,
            ledger_entries=report.ledger_entries,
            chain_valid=True,
        )

        return {
            "status": "ok",
            "report_id": report.id,
            "pdf_path": filepath,
            "provenance_count": len(report.provenance_records),
            "all_sources_public": report.all_sources_public,
        }

    except Exception as e:
        logger.error(f"Audit generation error: {e}")
        raise HTTPException(500, f"Audit generation failed: {e}")


@router.get("/compliance/audit/{alert_id}/pdf")
async def download_audit_pdf(alert_id: str):
    """Download the audit PDF file."""
    import glob
    from config import BASE_DIR
    pattern = str(BASE_DIR / "audit_reports" / f"sentinel_audit_{alert_id}_*.pdf")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        raise HTTPException(404, "No audit PDF found for this alert")
    return FileResponse(files[0], media_type="application/pdf", filename=f"sentinel_audit_{alert_id}.pdf")


@router.get("/compliance/stats")
async def get_compliance_stats():
    """Get compliance ledger statistics."""
    ledger = _get("compliance_ledger")
    if not ledger:
        return {"error": "Ledger not initialized"}

    return {
        "chain_valid": ledger.verify_chain(),
        "total_entries": ledger.size,
        "last_hash": ledger.last_hash[:16] + "...",
    }


# ──────────────────────────────────────────────
# Agent Swarm Status for a Position
# ──────────────────────────────────────────────

@router.get("/portfolio/position/{ticker}/agents")
async def get_position_agents(ticker: str):
    """Return the 6-agent swarm status and monitoring details for a position."""
    portfolio: Portfolio = _get("portfolio")
    if not portfolio:
        raise HTTPException(404, "No portfolio loaded")

    position = portfolio.get_position(ticker)
    if not position:
        raise HTTPException(404, f"Position {ticker} not found")

    orchestrator = _get("orchestrator")
    geo_targets = orchestrator.get_geo_targets_for_ticker(ticker) if orchestrator else []
    facilities = []
    for gt in geo_targets:
        facilities.append({
            "name": gt.name,
            "lat": gt.latitude,
            "lon": gt.longitude,
            "type": gt.target_type,
            "sensors": gt.monitoring_sensors,
        })

    # Count alerts for this ticker
    alerts_store: list = _get("alerts_store") or []
    ticker_alerts = [a for a in alerts_store if a.ticker.upper() == ticker.upper()]

    agents = [
        {
            "id": "thesis_orchestrator",
            "name": "Thesis Orchestrator",
            "role": "Parses PM natural-language theses into concrete sensor taskings by mapping tickers to real-world physical facilities (factories, mines, ports, HQs).",
            "status": "active",
            "icon": "brain",
            "color": "cyan",
            "monitoring": [f["name"] for f in facilities],
            "metrics": {
                "facilities_tracked": len(facilities),
                "sensor_types": list({s for f in facilities for s in f["sensors"]}),
                "tickers_mapped": [ticker],
            },
        },
        {
            "id": "sensor_orchestrator",
            "name": "Sensor Orchestrator",
            "role": "Dispatches and manages multi-source sensor data collection — weather, satellite imagery, ADS-B flight tracking, and AIS maritime vessel monitoring.",
            "status": "active",
            "icon": "radar",
            "color": "emerald",
            "monitoring": [f"{s.upper()} feed at {f['name']}" for f in facilities for s in f["sensors"]],
            "metrics": {
                "active_feeds": sum(len(f["sensors"]) for f in facilities),
                "sensor_types": list({s for f in facilities for s in f["sensors"]}),
                "coverage_km2": len(facilities) * 50,
            },
        },
        {
            "id": "consensus_vision",
            "name": "Consensus Vision Agent",
            "role": "Analyzes satellite and visual sensor data to detect physical anomalies — vehicle count changes, thermal signatures, construction activity, and inventory levels.",
            "status": "active",
            "icon": "eye",
            "color": "purple",
            "monitoring": [f"Visual anomaly detection at {f['name']}" for f in facilities if "optical" in f["sensors"]],
            "metrics": {
                "optical_targets": sum(1 for f in facilities if "optical" in f["sensors"]),
                "sar_targets": sum(1 for f in facilities if "sar" in f["sensors"]),
                "anomalies_detected": len(ticker_alerts),
            },
        },
        {
            "id": "quant_regression",
            "name": "Quant Regression Agent",
            "role": "Backtests detected anomalies against historical price data to determine financial materiality. Uses regression models to predict price impact magnitude and timing.",
            "status": "active",
            "icon": "chart",
            "color": "amber",
            "monitoring": [f"{ticker} price correlation analysis", f"{ticker} historical regression model"],
            "metrics": {
                "current_price": position.current_price,
                "entry_price": position.avg_entry_price,
                "pnl": position.pnl,
                "materiality_threshold": "R² > 0.3",
            },
        },
        {
            "id": "omnichannel_rag",
            "name": "Omnichannel RAG Agent",
            "role": "Searches SEC filings, news, and financial documents via vector retrieval to adjust anomaly severity for digital revenue mix and public disclosures.",
            "status": "active",
            "icon": "search",
            "color": "blue",
            "monitoring": [f"SEC filings for {ticker}", f"News sentiment for {ticker}", "Earnings call transcripts"],
            "metrics": {
                "documents_indexed": "10K, 10Q, 8K filings",
                "digital_revenue_check": True,
                "last_filing_scan": "continuous",
            },
        },
        {
            "id": "compliance_copilot",
            "name": "Compliance CoPilot",
            "role": "Validates all data provenance is from public sources, maintains an immutable audit ledger with SHA-256 hash chains, and generates 1-click SEC audit PDFs.",
            "status": "active",
            "icon": "shield",
            "color": "rose",
            "monitoring": ["Data provenance validation", "Audit hash chain integrity", f"Compliance log for {ticker}"],
            "metrics": {
                "alerts_logged": len(ticker_alerts),
                "chain_valid": True,
                "all_sources_public": True,
            },
        },
    ]

    return {
        "ticker": ticker,
        "position": {
            "name": position.name,
            "side": position.side.value,
            "shares": position.shares,
            "avg_entry_price": position.avg_entry_price,
            "current_price": position.current_price,
            "pnl": position.pnl,
            "sector": position.sector,
            "thesis": position.thesis,
        },
        "agents": agents,
        "facilities": facilities,
        "alerts_count": len(ticker_alerts),
    }


# ──────────────────────────────────────────────
# Satellite Imagery endpoints
# ──────────────────────────────────────────────

@router.get("/data/satellite/imagery")
async def get_satellite_imagery(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Get all available satellite imagery sources for a location."""
    sat_client = _get("satellite_client")
    if not sat_client:
        raise HTTPException(503, "Satellite client not available")
    try:
        sources = await sat_client.get_all_imagery_sources(lat, lon)
        return {"lat": lat, "lon": lon, "sources": sources, "count": len(sources)}
    except Exception as e:
        logger.error(f"Satellite imagery error: {e}")
        return {"lat": lat, "lon": lon, "sources": [], "count": 0, "error": str(e)}


@router.get("/data/satellite/goes")
async def get_goes_image(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Get GOES-16 real-time geostationary imagery for a location."""
    sat_client = _get("satellite_client")
    if not sat_client:
        raise HTTPException(503, "Satellite client not available")
    return await sat_client.get_goes_imagery(lat, lon)


@router.get("/data/satellite/gibs")
async def get_gibs_tile(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    zoom: int = Query(6, description="Zoom level 1-9"),
    layer: str = Query("MODIS_Terra_CorrectedReflectance_TrueColor", description="GIBS layer"),
):
    """Get NASA GIBS WMTS tile for a location."""
    sat_client = _get("satellite_client")
    if not sat_client:
        raise HTTPException(503, "Satellite client not available")
    return await sat_client.get_gibs_tile(lat, lon, zoom, layer)


# ── Vision Intelligence endpoints ────────────────────────────────────────────
@router.post("/vision/analyze-frame")
async def analyze_frame(request: dict):
    """Analyze a camera frame for license plates and/or faces."""
    from models.identifications import FrameAnalysisRequest, FrameAnalysisResult
    from agents.vision_processor import VisionProcessorAgent

    req = FrameAnalysisRequest(
        image_url=request.get("image_url"),
        image_base64=request.get("image_base64"),
        camera_id=request.get("camera_id"),
        camera_name=request.get("camera_name"),
        latitude=request.get("latitude"),
        longitude=request.get("longitude"),
        run_lpr=request.get("run_lpr", True),
        run_face_detection=request.get("run_face_detection", False),
    )

    processor = VisionProcessorAgent()
    result = await processor.analyze_frame(req)
    return result.model_dump()


@router.get("/vision/plates")
async def get_plate_detections(
    camera_id: Optional[str] = Query(None),
    plate_text: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Search recent plate detections. Returns in-memory store (resets on restart)."""
    detections = _vision_store.get("plates", [])

    if camera_id:
        detections = [d for d in detections if d.get("camera_id") == camera_id]
    if plate_text:
        pt = plate_text.upper()
        detections = [d for d in detections if pt in (d.get("plate_text") or "").upper()]

    return {"detections": detections[-limit:], "total": len(detections)}


@router.get("/vision/status")
async def get_vision_status():
    """Return vision processor status and capabilities."""
    from agents.vision_processor import VisionProcessorAgent
    processor = VisionProcessorAgent()
    return {
        "status": "ok",
        **processor.status(),
        "detections_stored": len(_vision_store.get("plates", [])),
    }


# ──────────────────────────────────────────────
# System endpoints
# ──────────────────────────────────────────────

@router.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "websocket_clients": ws_manager.client_count,
        "agents": {
            "orchestrator": _get("orchestrator") is not None,
            "sensor_orchestrator": _get("sensor_orchestrator") is not None,
            "vision_agent": _get("vision_agent") is not None,
            "quant_agent": _get("quant_agent") is not None,
            "rag_agent": _get("rag_agent") is not None,
            "compliance_copilot": _get("compliance_copilot") is not None,
        },
    }


@router.get("/demo/seed")
async def seed_demo_data():
    """Seed the portfolio with demo positions for showcasing."""
    portfolio: Portfolio = _get("portfolio")
    if not portfolio:
        portfolio = Portfolio()
        _state["portfolio"] = portfolio

    orchestrator = _get("orchestrator")

    demo_positions = [
        ("TSLA", "Tesla Inc", "LONG", 50000, 245.00, "Technology"),
        ("XOM", "Exxon Mobil", "SHORT", 30000, 108.50, "Energy"),
        ("TGT", "Target Corp", "LONG", 25000, 142.30, "Consumer Cyclical"),
        ("FCX", "Freeport-McMoRan", "LONG", 100000, 42.80, "Basic Materials"),
        ("AAPL", "Apple Inc", "LONG", 20000, 198.50, "Technology"),
        ("WMT", "Walmart Inc", "LONG", 15000, 178.20, "Consumer Defensive"),
        ("BA", "Boeing Co", "SHORT", 10000, 182.40, "Industrials"),
        ("VALE", "Vale SA", "LONG", 75000, 12.50, "Basic Materials"),
    ]

    portfolio.positions = []
    for ticker, name, side, shares, price, sector in demo_positions:
        geo_targets = orchestrator.get_geo_targets_for_ticker(ticker) if orchestrator else []
        portfolio.positions.append(Position(
            ticker=ticker,
            name=name,
            side=PositionSide(side),
            shares=shares,
            avg_entry_price=price,
            sector=sector,
            geo_targets=geo_targets,
        ))

    portfolio.total_nav = sum(p.shares * p.avg_entry_price for p in portfolio.positions)
    portfolio.last_synced = datetime.utcnow()

    await ws_manager.broadcast_portfolio(portfolio.model_dump())

    return {
        "status": "ok",
        "positions": len(portfolio.positions),
        "total_geo_targets": sum(len(p.geo_targets) for p in portfolio.positions),
        "nav": portfolio.total_nav,
    }


@router.get("/demo/seed-alerts")
async def seed_demo_alerts():
    """Seed realistic demo alerts for showcasing the UI."""
    import uuid
    import hashlib

    alerts_store: list = _get("alerts_store")
    if alerts_store is None:
        alerts_store = []
        _state["alerts_store"] = alerts_store

    demo_alerts = [
        SentinelAlert(
            id=uuid.uuid4().hex[:12],
            ticker="TSLA",
            position_side="LONG",
            shares=50000,
            title="Vehicle Count Anomaly at Tesla Shanghai Gigafactory",
            summary="Satellite imagery shows a 34.2% increase in finished vehicle inventory at the Shanghai "
                    "Gigafactory parking lot compared to the 30-day rolling average. Historical regression "
                    "(R²=0.72) shows a 4.8% predicted price impact within 14 days. This surge correlates "
                    "with production ramp data from supply chain trackers.",
            severity=AlertSeverity.HIGH,
            category=AlertCategory.PRODUCTION,
            confidence_score=0.87,
            latitude=31.1,
            longitude=121.6,
            location_name="Tesla Shanghai Gigafactory",
            recommended_action="SIZE_UP",
            action_rationale="Strong production ramp signal detected. Inventory build suggests accelerated "
                             "deliveries. Position is LONG, consider increasing allocation by 5-10%.",
            data_sources=["Planet Labs Satellite", "OpenSky ADS-B", "Sentinel-2 Optical"],
            compliance_hash=hashlib.sha256(f"tsla-shanghai-{datetime.utcnow().isoformat()}".encode()).hexdigest(),
        ),
        SentinelAlert(
            id=uuid.uuid4().hex[:12],
            ticker="XOM",
            position_side="SHORT",
            shares=30000,
            title="Thermal Anomaly at ExxonMobil Baytown Refinery",
            summary="Thermal IR sensors detected a 41.7% drop in heat signature at the Baytown Refinery "
                    "catalytic cracking unit. This is consistent with an unplanned shutdown. Historical "
                    "regression (R²=0.65) indicates a 3.2% downward price pressure within 7 days. "
                    "AIS data shows 3 tankers diverted from the Houston Ship Channel.",
            severity=AlertSeverity.CRITICAL,
            category=AlertCategory.PRODUCTION,
            confidence_score=0.93,
            latitude=29.74,
            longitude=-95.01,
            location_name="ExxonMobil Baytown Refinery",
            recommended_action="SIZE_UP",
            action_rationale="Refinery shutdown detected. Position is SHORT — signal is favorable. "
                             "Consider increasing short exposure as production disruption may impact earnings.",
            data_sources=["Sentinel-2 Thermal", "MarineTraffic AIS", "OpenWeather"],
            compliance_hash=hashlib.sha256(f"xom-baytown-{datetime.utcnow().isoformat()}".encode()).hexdigest(),
        ),
        SentinelAlert(
            id=uuid.uuid4().hex[:12],
            ticker="TSLA",
            position_side="LONG",
            shares=50000,
            title="Increased Flight Activity near Tesla Austin Gigafactory",
            summary="ADS-B data shows 8 corporate jets landing at Austin-Bergstrom within 15km of the "
                    "Gigafactory in the past 48 hours — 3.5x the normal rate. Pattern matches pre-announcement "
                    "executive travel surges seen before Tesla Q3 2025 earnings. Optical imagery confirms "
                    "expanded construction activity on the east campus.",
            severity=AlertSeverity.MEDIUM,
            category=AlertCategory.CORPORATE_ACTIVITY,
            confidence_score=0.72,
            latitude=30.22,
            longitude=-97.62,
            location_name="Tesla Austin Gigafactory",
            recommended_action="MONITOR",
            action_rationale="Corporate jet activity spike detected. Not yet material but warrants continued "
                             "monitoring. Could signal upcoming announcement or board meeting.",
            data_sources=["OpenSky ADS-B", "Planet Labs Optical", "FlightRadar24"],
            compliance_hash=hashlib.sha256(f"tsla-austin-{datetime.utcnow().isoformat()}".encode()).hexdigest(),
        ),
        SentinelAlert(
            id=uuid.uuid4().hex[:12],
            ticker="FCX",
            position_side="LONG",
            shares=100000,
            title="Ship Traffic Surge at Grasberg Mine Port",
            summary="AIS tracking shows 12 bulk carriers queueing at Amamapare Port (Grasberg Mine export "
                    "terminal) — a 67% increase over the 90-day average. This indicates higher-than-expected "
                    "copper concentrate exports. Historical regression (R²=0.58) suggests a 2.9% positive "
                    "price impact within 21 days.",
            severity=AlertSeverity.HIGH,
            category=AlertCategory.SUPPLY_CHAIN,
            confidence_score=0.81,
            latitude=-4.85,
            longitude=136.92,
            location_name="Amamapare Port, Papua",
            recommended_action="HOLD",
            action_rationale="Bullish supply chain signal for copper exports. Position is already LONG. "
                             "Current position size is appropriate. Continue monitoring.",
            data_sources=["MarineTraffic AIS", "Copernicus SAR", "Sentinel-2 Optical"],
            compliance_hash=hashlib.sha256(f"fcx-grasberg-{datetime.utcnow().isoformat()}".encode()).hexdigest(),
        ),
        SentinelAlert(
            id=uuid.uuid4().hex[:12],
            ticker="BA",
            position_side="SHORT",
            shares=10000,
            title="Parking Lot Emptying at Boeing Everett Factory",
            summary="Optical satellite imagery shows the Boeing 737 MAX delivery lot at Everett has decreased "
                    "from ~142 aircraft to ~89 aircraft over the past 30 days. This 37.3% reduction suggests "
                    "accelerated deliveries to airlines. Historical data (R²=0.61) correlates lot clearance "
                    "with positive earnings surprises.",
            severity=AlertSeverity.HIGH,
            category=AlertCategory.PRODUCTION,
            confidence_score=0.78,
            latitude=47.92,
            longitude=-122.27,
            location_name="Boeing Everett Factory",
            recommended_action="EXIT",
            action_rationale="CAUTION: Delivery acceleration is bearish for SHORT position. Consider "
                             "reducing or exiting short exposure. Production recovery may be underway.",
            data_sources=["Maxar Optical", "Planet Labs Satellite", "FAA Registry"],
            compliance_hash=hashlib.sha256(f"ba-everett-{datetime.utcnow().isoformat()}".encode()).hexdigest(),
        ),
        SentinelAlert(
            id=uuid.uuid4().hex[:12],
            ticker="VALE",
            position_side="LONG",
            shares=75000,
            title="Environmental Alert — Tailings Dam Monitoring",
            summary="Sentinel-2 SAR interferometry detected 2.3mm ground subsidence near Vale's Carajás "
                    "S11D mine tailings dam in the past 14 days. While within normal parameters, the rate "
                    "has accelerated 1.8x compared to the previous quarter. No immediate production risk, "
                    "but regulatory scrutiny may increase.",
            severity=AlertSeverity.LOW,
            category=AlertCategory.PRODUCTION,
            confidence_score=0.65,
            latitude=-6.07,
            longitude=-50.17,
            location_name="Carajás S11D Mine, Brazil",
            recommended_action="MONITOR",
            action_rationale="Ground subsidence within tolerance but accelerating. Low immediate risk to "
                             "position. Monitor for regulatory response from IBAMA/ANM.",
            data_sources=["Copernicus SAR", "Sentinel-2 InSAR", "IBAMA Registry"],
            compliance_hash=hashlib.sha256(f"vale-carajas-{datetime.utcnow().isoformat()}".encode()).hexdigest(),
        ),
    ]

    for alert in demo_alerts:
        alert.created_at = datetime.utcnow()
        alerts_store.append(alert)
        await ws_manager.broadcast_alert(alert.model_dump())
        logger.info(f"DEMO ALERT: [{alert.severity.value}] {alert.title}")

    return {
        "status": "ok",
        "alerts_created": len(demo_alerts),
        "total_alerts": len(alerts_store),
    }


# ─── Geocoding Endpoint ──────────────────────────────────────────────────────

@router.get("/geocode")
async def geocode_address(
    address: str = Query(..., min_length=3, description="Address to geocode"),
):
    """Forward geocode an address to lat/lon using Nominatim (OpenStreetMap)."""
    from scrapers.connectors.nominatim_geocoder import geocode
    result = await geocode(address)
    return result


# ─── FEMA Flood Zone Endpoint ────────────────────────────────────────────────

@router.get("/flood-zone")
async def get_flood_zone(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Get FEMA flood zone designation for a location."""
    from scrapers.connectors.fema_flood import get_flood_zone
    result = await get_flood_zone(lat, lon)
    return result


# ─── MassGIS Parcel Endpoint ────────────────────────────────────────────────

@router.get("/parcels")
async def get_parcels(
    lat: Optional[float] = Query(None, description="Latitude for spatial query"),
    lon: Optional[float] = Query(None, description="Longitude for spatial query"),
    town: Optional[str] = Query(None, description="Town name"),
    address: Optional[str] = Query(None, description="Street address"),
):
    """Get MassGIS property tax parcel info by location or address."""
    from scrapers.connectors.massgis_parcels import get_parcel_by_point, search_parcels
    if lat is not None and lon is not None:
        result = await get_parcel_by_point(lat, lon)
        return result
    elif town and address:
        results = await search_parcels(town, address)
        return {"parcels": results, "total": len(results)}
    else:
        raise HTTPException(status_code=400, detail="Provide lat/lon or town+address")


# ─── Zoning Endpoint ────────────────────────────────────────────────────────

@router.get("/zoning")
async def get_zoning(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Get zoning district info for a location from the National Zoning Atlas."""
    from scrapers.connectors.zoning_atlas import get_zoning
    result = await get_zoning(lat, lon)
    return result


# ─── Land Records Endpoint ──────────────────────────────────────────────────

@router.get("/land-records")
async def get_land_records(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Get ownership and deed records from MassGIS assessor data."""
    from scrapers.connectors.mass_land_records import get_ownership_records
    return await get_ownership_records(lat, lon)


# ─── Comparable Sales Endpoint ──────────────────────────────────────────────

@router.get("/comps")
async def get_comps(
    lat: float = Query(..., description="Latitude of subject property"),
    lon: float = Query(..., description="Longitude of subject property"),
    radius_m: float = Query(500.0, ge=50, le=5000, description="Search radius in meters"),
    use_code: Optional[str] = Query(None, description="Filter by property use code"),
    subject_loc_id: Optional[str] = Query(None, description="LOC_ID of subject parcel to exclude"),
    max_results: int = Query(20, ge=1, le=50, description="Max comps to return"),
):
    """Get comparable sales near a location from MassGIS parcel data."""
    from scrapers.connectors.massgis_comps import get_comparable_sales
    return await get_comparable_sales(
        lat=lat, lon=lon,
        radius_m=radius_m,
        use_code=use_code,
        subject_loc_id=subject_loc_id,
        max_results=max_results,
    )


# ─── Property Endpoints ───────────────────────────────────────────────────────

@router.get("/properties/search")
async def search_properties(
    request: Request,
    q: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: float = 5.0,
    limit: int = 20,
):
    """Search for properties by address, location, or text query."""
    permit_loader = _get("permit_loader")

    if not permit_loader or not permit_loader.is_supabase:
        # Fall back to demo properties when Supabase is not connected
        return _demo_properties(q, address, city, limit)

    search_query = q or address or ""
    if not search_query and not (lat and lon):
        return {"properties": [], "total": 0}

    results = []

    # Search permits by address text
    if search_query:
        results = await permit_loader.search(
            query=search_query,
            address=search_query,
            town=city.lower() if city else None,
            limit=limit * 3,  # fetch extra for dedup
        )

    # Also try nearby search if coords provided and text search found nothing
    if not results and lat and lon:
        results = await permit_loader.get_nearby(lat, lon, radius_km=radius_km, limit=limit * 3)

    # Extract address from description field if address is empty
    import re as _re
    def _extract_address(permit: dict) -> str:
        addr = (permit.get("address") or "").strip()
        if addr:
            return addr
        # Try extracting from description: "Address: 122 Heath St"
        desc = permit.get("description") or ""
        m = _re.search(r'Address:\s*([^|]+)', desc)
        if m:
            return m.group(1).strip()
        return ""

    # Aggregate permits by address into pseudo-property objects
    address_map: dict[str, dict] = {}
    for permit in results:
        addr = _extract_address(permit)
        if not addr:
            continue
        key = addr.lower()
        if key not in address_map:
            town = permit.get("town_id") or permit.get("town") or ""
            address_map[key] = {
                "id": f"prop-{permit.get('id', '')}",
                "address": addr,
                "city": town.replace("_", " ").title() if town else "MA",
                "state": "MA",
                "zip_code": "",
                "latitude": permit.get("latitude", 0),
                "longitude": permit.get("longitude", 0),
                "property_type": "OTHER",
                "nearby_permits_count": 0,
            }
        address_map[key]["nearby_permits_count"] += 1

    # Geocode entries that have 0,0 coordinates
    from scrapers.connectors.nominatim_geocoder import geocode as _geocode_addr
    entries_needing_geocode = [
        (k, v) for k, v in address_map.items()
        if v.get("latitude", 0) == 0 and v.get("longitude", 0) == 0
    ]
    for key, entry in entries_needing_geocode[:5]:  # Max 5 geocode calls per search
        try:
            geo = await _geocode_addr(f"{entry['address']}, {entry['city']}, MA")
            if geo.get("lat") and geo.get("lon"):
                entry["latitude"] = geo["lat"]
                entry["longitude"] = geo["lon"]
        except Exception as e:
            logger.debug("Geocode failed for %s: %s", entry["address"], e)

    properties = list(address_map.values())[:limit]
    return {"properties": properties, "total": len(properties)}


def _demo_properties(q: Optional[str] = None, address: Optional[str] = None, city: Optional[str] = None, limit: int = 20):
    """Return hardcoded demo properties when Supabase is not connected."""
    from models.property import Property

    demo_properties = [
        Property(
            address="45 Harvard St, Brookline, MA 02445",
            city="Brookline", state="MA", zip_code="02445",
            latitude=42.3419, longitude=-71.1219,
            property_type="SINGLE_FAMILY",
            year_built=1920, bedrooms=4, bathrooms=2.5,
            living_area_sqft=2400, lot_size_sqft=5200,
            tax_assessment=985000, estimated_value=1150000,
            nearby_permits_count=3, nearby_cameras_count=5,
        ),
        Property(
            address="100 Binney St, Cambridge, MA 02142",
            city="Cambridge", state="MA", zip_code="02142",
            latitude=42.3662, longitude=-71.0827,
            property_type="COMMERCIAL",
            year_built=2018, living_area_sqft=50000,
            tax_assessment=25000000, estimated_value=30000000,
            nearby_permits_count=8, nearby_cameras_count=12,
        ),
        Property(
            address="456 E Broadway, Boston, MA 02127",
            city="Boston", state="MA", zip_code="02127",
            latitude=42.3371, longitude=-71.0371,
            property_type="MULTI_FAMILY",
            year_built=1905, bedrooms=9, bathrooms=3,
            living_area_sqft=3600, lot_size_sqft=2800,
            tax_assessment=720000, estimated_value=950000,
            nearby_permits_count=5, nearby_cameras_count=8,
        ),
    ]

    results = demo_properties

    # Filter by query text
    if q:
        q_lower = q.lower()
        results = [p for p in results if q_lower in p.address.lower() or q_lower in (p.city or "").lower()]

    # Filter by address
    if address:
        addr_lower = address.lower()
        results = [p for p in results if addr_lower in p.address.lower()]

    # Filter by city
    if city:
        results = [p for p in results if (p.city or "").lower() == city.lower()]

    return {"properties": [p.model_dump() for p in results[:limit]], "total": len(results)}


@router.get("/properties/{property_id}")
async def get_property(request: Request, property_id: str):
    """Get detailed property information."""
    from models.property import Property
    # Demo mode - return a sample property
    return Property(
        id=property_id,
        address="45 Harvard St, Brookline, MA 02445",
        city="Brookline", state="MA", zip_code="02445",
        latitude=42.3419, longitude=-71.1219,
        property_type="SINGLE_FAMILY",
        year_built=1920, bedrooms=4, bathrooms=2.5,
        living_area_sqft=2400, lot_size_sqft=5200,
        tax_assessment=985000, estimated_value=1150000,
    ).model_dump()


# ─── Permit Endpoints ─────────────────────────────────────────────────────────

@router.get("/permits/search")
async def search_permits(
    request: Request,
    q: Optional[str] = None,
    address: Optional[str] = None,
    town: Optional[str] = None,
    permit_type: Optional[str] = None,
    status: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: float = 1.0,
    filed_after: Optional[str] = None,
    min_value: Optional[float] = None,
    limit: int = 20,
):
    """Search building permits with flexible filtering."""
    permit_loader = _get("permit_loader")

    if not permit_loader:
        return {"permits": [], "total": 0, "error": "Permit loader not initialized"}

    results = await permit_loader.search(
        query=q,
        address=address,
        town=town,
        permit_type=permit_type,
        status=status,
        latitude=lat,
        longitude=lon,
        radius_km=radius_km,
        filed_after=filed_after,
        min_value=min_value,
        limit=limit,
    )

    return {
        "permits": results,
        "total": len(results),
        "total_available": permit_loader.count,
        "source": "supabase" if permit_loader.is_supabase else "demo",
    }


@router.get("/permits/near/{lat}/{lon}")
async def get_permits_near(
    request: Request,
    lat: float,
    lon: float,
    radius_km: float = 1.0,
    limit: int = 20,
):
    """Get permits near a geographic location."""
    permit_loader = _get("permit_loader")

    if not permit_loader:
        return {"permits": [], "total": 0}

    results = await permit_loader.get_nearby(lat, lon, radius_km, limit)
    return {"permits": results, "total": len(results)}


@router.get("/permits/viewport")
async def get_permits_in_viewport(
    request: Request,
    west: float = Query(..., description="Western longitude bound"),
    south: float = Query(..., description="Southern latitude bound"),
    east: float = Query(..., description="Eastern longitude bound"),
    north: float = Query(..., description="Northern latitude bound"),
    limit: int = Query(500, ge=1, le=2000, description="Max pins to return"),
):
    """
    Get geocoded permit pins within a viewport bounding box.

    Returns lightweight pin data for map rendering (no heavy content fields).
    """
    supabase = _get("supabase_client")
    if not supabase:
        return {"pins": [], "total": 0, "truncated": False}

    try:
        # Step 1: Get locations within the bounding box
        rows = await supabase.fetch(
            table="document_locations",
            select="document_id,latitude,longitude,address",
            filters={
                "and": (
                    f"(latitude.gte.{south},latitude.lte.{north},"
                    f"longitude.gte.{west},longitude.lte.{east})"
                ),
            },
            limit=limit,
        )

        if not rows:
            return {"pins": [], "total": 0, "truncated": False}

        # Step 2: Fetch permit content from documents table in bulk
        # Content format: "Type: Building | Address: ... | Description: ... | Cost: $627.00"
        doc_ids = list({r["document_id"] for r in rows if r.get("document_id")})
        doc_map: dict = {}
        if doc_ids:
            for i in range(0, len(doc_ids), 50):
                batch = doc_ids[i:i + 50]
                id_list = ",".join(batch)
                try:
                    docs = await supabase.fetch(
                        table="documents",
                        select="id,content,source_id,created_at",
                        filters={"id": f"in.({id_list})"},
                    )
                    for d in docs:
                        # Parse pipe-delimited content
                        content = d.get("content") or ""
                        fields = {}
                        for part in content.split("|"):
                            part = part.strip()
                            if ":" in part:
                                k, v = part.split(":", 1)
                                fields[k.strip().lower()] = v.strip()
                        # Extract cost as float
                        cost_str = fields.get("cost", "").replace("$", "").replace(",", "")
                        try:
                            cost = float(cost_str) if cost_str else None
                        except ValueError:
                            cost = None
                        doc_map[d["id"]] = {
                            "type": fields.get("type", ""),
                            "desc": fields.get("description", ""),
                            "value": cost,
                            "date": (d.get("created_at") or "")[:10] or None,
                            "source_id": d.get("source_id", ""),
                        }
                except Exception as e:
                    print(f"[Viewport Permits] Document fetch warning: {e}")

        pins = []
        for row in rows:
            doc_id = row.get("document_id")
            meta = doc_map.get(doc_id, {})
            pins.append({
                "id": doc_id,
                "lat": row.get("latitude"),
                "lon": row.get("longitude"),
                "addr": row.get("address", ""),
                "type": meta.get("type", ""),
                "status": meta.get("desc", ""),  # Use description as status label
                "value": meta.get("value"),
                "date": meta.get("date"),
            })

        return {
            "pins": pins,
            "total": len(pins),
            "truncated": len(pins) >= limit,
        }
    except Exception as e:
        print(f"[Viewport Permits] Error: {e}")
        return {"pins": [], "total": 0, "truncated": False}


@router.get("/permits/towns")
async def get_permit_towns(request: Request):
    """Get list of available towns with permit counts."""
    permit_loader = _get("permit_loader")

    if not permit_loader:
        return {"towns": []}

    towns = await permit_loader.get_towns()
    return {"towns": towns}


# ─── Coverage Endpoints ──────────────────────────────────────────────────────


@router.get("/coverage/summary")
async def get_coverage_summary(request: Request):
    """Statewide coverage matrix: 37 source types with municipality counts by status."""
    supabase = _get("supabase_client")
    if not supabase or not supabase.is_connected:
        return {"sources": [], "total_municipalities": 0, "error": "No database connection"}

    # Fetch all source requirements
    sources = await supabase.fetch("source_requirements", select="id,label,category,active", order="category,id")

    # Fetch coverage rows grouped status counts
    # PostgREST caps at 1000 rows, so use fetch_all to paginate through all 12,987
    coverage = await supabase.fetch_all(
        "municipality_source_coverage",
        select="source_requirement_id,status",
    )

    # Build lookup: source_id -> {status: count}
    source_stats: dict[str, Counter] = defaultdict(Counter)
    for row in coverage:
        src_id = row.get("source_requirement_id", "")
        status = row.get("status", "unknown")
        source_stats[src_id][status] += 1

    # Merge
    result = []
    for src in sources:
        sid = src["id"]
        stats = dict(source_stats.get(sid, {}))
        total = sum(stats.values())
        ready = stats.get("ready_for_ingestion", 0)
        result.append({
            "id": sid,
            "label": src.get("label", sid),
            "category": src.get("category", ""),
            "active": src.get("active", True),
            "total_municipalities": total,
            "ready": ready,
            "pending": total - ready,
            "status_breakdown": stats,
        })

    return {
        "sources": result,
        "total_source_types": len(sources),
        "total_municipalities": 351,
        "total_coverage_rows": len(coverage),
    }


@router.get("/coverage/municipality/{municipality_id}")
async def get_municipality_coverage(request: Request, municipality_id: str):
    """All source coverage statuses for a single municipality."""
    supabase = _get("supabase_client")
    if not supabase or not supabase.is_connected:
        return {"municipality_id": municipality_id, "sources": [], "error": "No database connection"}

    coverage = await supabase.fetch(
        "municipality_source_coverage",
        select="source_requirement_id,status,ingestion_method,source_url,source_system,priority,last_checked_at,last_ingested_at,notes",
        filters={"municipality_id": f"eq.{municipality_id}"},
        order="source_requirement_id",
    )

    # Fetch source labels for display
    sources = await supabase.fetch("source_requirements", select="id,label,category")
    source_map = {s["id"]: s for s in sources}

    result = []
    for row in coverage:
        src_id = row.get("source_requirement_id", "")
        src_info = source_map.get(src_id, {})
        result.append({
            "source_id": src_id,
            "source_label": src_info.get("label", src_id),
            "category": src_info.get("category", ""),
            "status": row.get("status", "unknown"),
            "ingestion_method": row.get("ingestion_method"),
            "source_url": row.get("source_url"),
            "source_system": row.get("source_system"),
            "priority": row.get("priority", 0),
            "last_checked_at": row.get("last_checked_at"),
            "last_ingested_at": row.get("last_ingested_at"),
            "notes": row.get("notes", ""),
        })

    return {
        "municipality_id": municipality_id,
        "sources": result,
        "total": len(result),
    }


@router.get("/towns")
async def list_towns(
    request: Request,
    q: Optional[str] = None,
    limit: int = 400,
):
    """List all 351 MA municipalities with permit counts and coverage stats."""
    supabase = _get("supabase_client")
    permit_loader = _get("permit_loader")

    if not supabase or not supabase.is_connected:
        # Fall back to permit_loader towns
        if permit_loader:
            towns = await permit_loader.get_towns()
            return {"towns": towns, "total": len(towns)}
        return {"towns": [], "total": 0}

    # Fetch all towns
    filters = {}
    if q:
        filters["or"] = f"(name.ilike.*{q}*,id.ilike.*{q}*,county.ilike.*{q}*)"

    towns_raw = await supabase.fetch(
        "towns",
        select="id,name,state,county,population,permit_portal_url",
        filters=filters if filters else None,
        order="name",
        limit=limit,
    )

    # Get coverage stats per town (ready vs total)
    coverage = await supabase.fetch_all(
        "municipality_source_coverage",
        select="municipality_id,status",
    )

    town_coverage: dict = defaultdict(lambda: {"total": 0, "ready": 0})
    for row in coverage:
        tid = row.get("municipality_id", "")
        town_coverage[tid]["total"] += 1
        if row.get("status") == "ready_for_ingestion":
            town_coverage[tid]["ready"] += 1

    # Get permit counts from loader if available
    permit_counts = {}
    if permit_loader and permit_loader.is_supabase:
        try:
            towns_with_permits = await permit_loader.get_towns()
            for t in towns_with_permits:
                permit_counts[t["id"]] = t.get("permit_count", 0)
        except Exception:
            pass

    result = []
    for town in towns_raw:
        tid = town["id"]
        cov = town_coverage.get(tid, {"total": 0, "ready": 0})
        coverage_pct = round(cov["ready"] / cov["total"] * 100, 1) if cov["total"] > 0 else 0
        result.append({
            "id": tid,
            "name": town.get("name", tid),
            "state": town.get("state", "MA"),
            "county": town.get("county"),
            "population": town.get("population"),
            "permit_count": permit_counts.get(tid, 0),
            "permit_portal_url": town.get("permit_portal_url"),
            "coverage_total": cov["total"],
            "coverage_ready": cov["ready"],
            "coverage_pct": coverage_pct,
        })

    return {
        "towns": result,
        "total": len(result),
    }


# ─── Ingestion Endpoint ──────────────────────────────────────────────────────

@router.post("/ingestion/run")
async def run_ingestion(request: Request):
    """Trigger a permit data ingestion run for a specific town + source.

    Body: { "town": "cambridge", "source": "socrata", "limit": 1000 }
    """
    body = await request.json()
    town = body.get("town", "").lower().strip()
    source = body.get("source", "socrata").lower().strip()
    limit = body.get("limit", 10000)

    if not town:
        raise HTTPException(status_code=400, detail="town is required")

    supabase = _get("supabase_client")

    if source == "socrata":
        try:
            from scrapers.connectors.socrata import SocrataConnector, SOCRATA_TOWNS
            from scrapers.connectors.normalize import normalize_batch

            if town not in SOCRATA_TOWNS:
                return {
                    "status": "error",
                    "message": f"No Socrata config for {town}. Available: {list(SOCRATA_TOWNS.keys())}",
                }

            connector = SocrataConnector()
            result = await connector.pull_town(town)
            await connector.close()

            # Normalize the raw permits
            normalized = normalize_batch(result["permits"][:limit], town)

            return {
                "status": "success",
                "town": town,
                "source": "socrata",
                "raw_count": result["permit_count"],
                "normalized_count": len(normalized),
                "sample": normalized[:3] if normalized else [],
                "pulled_at": result["pulled_at"],
            }

        except Exception as exc:
            logger.error("Ingestion failed for %s: %s", town, exc)
            return {"status": "error", "town": town, "message": str(exc)}

    elif source == "viewpointcloud":
        try:
            import httpx as httpx_lib
            from scrapers.connectors.viewpointcloud import (
                ViewpointCloudClient,
                fetch_general_settings,
            )

            community_slug = body.get("community_slug", f"{town}ma")

            async with httpx_lib.AsyncClient(timeout=30.0) as client:
                api_base, settings, error = await fetch_general_settings(
                    community_slug=community_slug, client=client
                )

                if error or not api_base:
                    return {
                        "status": "error",
                        "town": town,
                        "message": f"ViewpointCloud not available for {community_slug}: {error}",
                    }

                vpc = ViewpointCloudClient(
                    community_slug=community_slug,
                    api_base=api_base,
                    client=client,
                )

                # Check capabilities
                allow_search = settings.get("allowPublicSearch", False) if settings else False
                allow_records = settings.get("allowPublicRecordSearch", False) if settings else False

                return {
                    "status": "success",
                    "town": town,
                    "source": "viewpointcloud",
                    "community_slug": community_slug,
                    "api_base": api_base,
                    "capabilities": {
                        "public_search": allow_search,
                        "public_records": allow_records,
                    },
                    "settings_keys": list(settings.keys()) if settings else [],
                }

        except Exception as exc:
            logger.error("ViewpointCloud check failed for %s: %s", town, exc)
            return {"status": "error", "town": town, "message": str(exc)}

    else:
        return {
            "status": "error",
            "message": f"Unknown source: {source}. Available: socrata, viewpointcloud",
        }


# ─── RAG Chat Endpoint ────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(request: Request):
    """RAG-powered chat about properties, permits, and real estate intelligence."""
    body = await request.json()
    message = body.get("message", "")
    property_id = body.get("property_id")
    context = body.get("context")

    if not message:
        return {"content": "Please provide a message.", "sources": [], "confidence": 0}

    permit_loader = _get("permit_loader")
    permit_search = _get("permit_search")

    if not permit_loader or not permit_search:
        return {
            "content": "Chat service is initializing. Please try again in a moment.",
            "sources": [],
            "confidence": 0,
        }

    # Search for relevant permits
    context_permits = await permit_search.search(
        query=message,
        limit=10,
    )

    # Generate answer
    answer, suggested, confidence = await permit_search.generate_answer(
        question=message,
        context_permits=context_permits,
        property_address=context,
    )

    return {
        "content": answer,
        "sources": [{"permit_number": p.get("permit_number"), "address": p.get("address"), "relevance": p.get("relevance_score", 0)} for p in context_permits[:5]],
        "permits_found": len(context_permits),
        "suggested_questions": suggested,
        "confidence": confidence,
    }


# ─── Listing Enrichment ──────────────────────────────────────────────────────

@router.post("/listings/enrich")
async def enrich_listing(request: Request):
    """Enrich a tracked listing with nearby permit data."""
    body = await request.json()
    address = body.get("address", "")
    lat = body.get("latitude")
    lon = body.get("longitude")

    permit_loader = _state.get("permit_loader")
    if not permit_loader:
        return {"permits": [], "total": 0}

    permits = []
    # Try address search first
    if address:
        try:
            permits = await permit_loader.search(address=address, limit=20)
        except Exception as e:
            logger.warning("Enrich address search failed: %s", e)

    # Fall back to nearby search
    if not permits and lat and lon:
        try:
            permits = await permit_loader.get_nearby(float(lat), float(lon), radius_km=0.5, limit=20)
        except Exception as e:
            logger.warning("Enrich nearby search failed: %s", e)

    return {"permits": permits, "total": len(permits)}


# ─── Property Agent Endpoints ─────────────────────────────────────────────────

@router.get("/agents")
async def list_agents(request: Request):
    """List all active property monitoring agents."""
    agents = _state.get("property_agents", [])
    return {"agents": [a if isinstance(a, dict) else a.model_dump() for a in agents], "total": len(agents)}


@router.post("/agents")
async def create_agent(request: Request):
    """Create a new property monitoring agent."""
    from models.property import PropertyAgent, AgentType, AgentStatus
    body = await request.json()

    agent = PropertyAgent(
        entity_type=body.get("entity_type", "property"),
        entity_id=body.get("entity_id", ""),
        agent_type=AgentType(body.get("agent_type", "listing")),
        name=body.get("name", f"Agent for {body.get('entity_id', 'unknown')}"),
        config=body.get("config", {}),
        run_interval_seconds=body.get("run_interval_seconds", 300),
    )

    if "property_agents" not in _state:
        _state["property_agents"] = []
    _state["property_agents"].append(agent)

    return {"status": "created", "agent": agent.model_dump()}


@router.delete("/agents/{agent_id}")
async def delete_agent(request: Request, agent_id: str):
    """Delete/deactivate a property monitoring agent."""
    agents = _state.get("property_agents", [])

    for i, a in enumerate(agents):
        aid = a.id if hasattr(a, 'id') else a.get('id')
        if aid == agent_id:
            agents.pop(i)
            return {"status": "deleted", "agent_id": agent_id}

    return {"status": "not_found", "agent_id": agent_id}


# ──────────────────────────────────────────────
# WebSocket handler
# ──────────────────────────────────────────────

async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint for real-time data streaming."""
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming commands from the frontend
            try:
                msg = __import__("json").loads(data)
                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat()})

                elif msg_type == "request_flights":
                    opensky = _get("opensky_client")
                    if opensky:
                        flights = await opensky.get_all_states()
                        await websocket.send_json({
                            "type": "flights_update",
                            "timestamp": datetime.utcnow().isoformat(),
                            "data": {"flights": flights, "count": len(flights)},
                        })

                elif msg_type == "request_ships":
                    ais = _get("ais_client")
                    if ais:
                        lat = msg.get("lat", 51.9)
                        lon = msg.get("lon", 4.5)
                        ships = await ais.get_vessels_in_area(lat, lon)
                        await websocket.send_json({
                            "type": "ships_update",
                            "timestamp": datetime.utcnow().isoformat(),
                            "data": {"ships": ships, "count": len(ships)},
                        })

                elif msg_type == "request_cameras":
                    camera_client = _get("camera_client")
                    if camera_client:
                        cameras = await camera_client.get_all_cameras()
                        await websocket.send_json({
                            "type": "cameras_update",
                            "timestamp": datetime.utcnow().isoformat(),
                            "data": {"cameras": cameras, "count": len(cameras)},
                        })

                elif msg_type == "request_satellites":
                    sat_client = _get("satellite_orbital_client")
                    if sat_client:
                        satellites = await sat_client.get_all_tracked(limit=300)
                        await websocket.send_json({
                            "type": "satellites_update",
                            "timestamp": datetime.utcnow().isoformat(),
                            "data": {"satellites": satellites, "count": len(satellites)},
                        })

                elif msg_type == "request_military_flights":
                    mil_client = _get("military_flight_client")
                    if mil_client:
                        mil_flights = await mil_client.get_military_flights(limit=200)
                        await websocket.send_json({
                            "type": "military_flights_update",
                            "timestamp": datetime.utcnow().isoformat(),
                            "data": {"flights": mil_flights, "count": len(mil_flights)},
                        })

                elif msg_type == "request_earthquakes":
                    eq_client = _get("earthquake_client")
                    if eq_client:
                        quakes = await eq_client.get_earthquakes(feed="m2.5_week", limit=300)
                        await websocket.send_json({
                            "type": "earthquakes_update",
                            "timestamp": datetime.utcnow().isoformat(),
                            "data": {"earthquakes": quakes, "count": len(quakes)},
                        })

            except Exception as e:
                logger.warning(f"WebSocket message parse error: {e}")

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)
