# Sentinel Agent -- Build Log & Development Roadmap

**Project**: Sentinel Agent -- Geospatial Intelligence Platform
**Author**: Alvaro Espinal
**Last Updated**: 2026-02-26

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Work Completed](#work-completed)
4. [Current State](#current-state)
5. [Known Issues & Bugs](#known-issues--bugs)
6. [Next Phases](#next-phases)

---

## Project Overview

Sentinel Agent is a Palantir-style geospatial intelligence platform designed for hedge fund portfolio managers. It combines real-time physical-world sensor data (satellite imagery, ADS-B flights, AIS shipping, traffic cameras, seismic data) with AI-driven analysis to generate trade signals from observable anomalies at company facilities worldwide.

**Core Thesis**: Physical-world activity at factories, ports, mines, and HQs is a leading indicator of financial performance. Monitor it in real-time, detect anomalies, and translate them into actionable trade recommendations.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite |
| 3D Globe | Cesium.js + Resium |
| State | Zustand |
| Styling | Tailwind CSS (custom sentinel theme) |
| Backend | Python FastAPI |
| AI Agents | 6-agent pipeline (Anthropic Claude + OpenAI) |
| Vector Store | ChromaDB |
| Data Sources | 11 real-time feeds (OpenSky, AIS, USGS, Caltrans, Planet Labs, etc.) |

---

## Architecture

### Data Flow

```
PM writes thesis ("TSLA production ramp looks strong, long 50k shares")
    |
    v
Thesis Orchestrator ---- maps TSLA -> 5 physical facilities (Shanghai, Fremont, Austin, Berlin, Lathrop)
    |
    v
Sensor Orchestrator ---- allocates optical/ADS-B/AIS sensors per facility, checks weather blockers
    |
    v
[Parallel Agent Processing]
  - Consensus Vision Agent ---- multi-model anomaly detection (optical/SAR/thermal)
  - Quant Regression Agent ---- historical correlation, R-squared, predicted price impact
  - Omnichannel RAG Agent ---- SEC filing analysis, digital vs physical revenue split
    |
    v
Compliance CoPilot ---- generates immutable audit trail, data provenance, MNPI classification
    |
    v
SentinelAlert (enriched) ---- broadcast via WebSocket to dashboard
    |
    v
Dashboard UI ---- 3D globe, camera feeds, alerts, portfolio management
```

### Agent Pipeline

| Agent | Role | Output |
|-------|------|--------|
| **Thesis Orchestrator** | Parses PM natural-language theses into sensor taskings via 37-ticker facility knowledge base (113 facilities) | TradeProposal with geo_targets |
| **Sensor Orchestrator** | Dispatches multi-source sensor collection (weather-aware, priority-ranked, fallback chains) | Active sensor feeds per facility |
| **Consensus Vision Agent** | Multi-model anomaly detection with consensus scoring (>=5% variance threshold) | AnomalyDetection with magnitude + consensus_score |
| **Quant Regression Agent** | Backtests historical correlation (R² >= 0.3), predicts price impact % | QuantBacktest with is_material flag |
| **Omnichannel RAG Agent** | Analyzes SEC 10-K/10-Q for digital vs physical revenue to adjust alert severity | OmnichannelAdjustment with adjusted_severity |
| **Compliance CoPilot** | Chain-of-custody audit trails, MNPI classification, SEC-ready reports | ComplianceLedgerEntry + AuditReport PDF |

### Facility Knowledge Base

37 tickers mapped to 113 physical facilities across sectors:

- **Automotive/EV**: TSLA (5), F (3), GM (3)
- **Tech/Semicon**: AAPL (4), NVDA (3), AMD (2), INTC (3), QCOM (2), TSM (4)
- **E-Commerce/Retail**: AMZN (5), WMT (4), TGT (3), COST (2)
- **Energy/Mining**: XOM (4), CVX (3), FCX (4), NEM (3), VALE (4), BHP (3), RIO (3)
- **Aerospace/Defense**: BA (4), LMT (3), RTX (2)
- **Logistics**: FDX (3), UPS (3)
- **Pharma**: PFE (3), JNJ (3)
- **Social/Search**: META (2), GOOGL (3)

---

## Work Completed

### Phase 1: Core Platform (Prior Sessions)

**Backend Foundation**
- FastAPI server with CORS, background data refresh (30s), WebSocket broadcasting
- Pydantic models: Portfolio, Position, GeoTarget, SentinelAlert, TradeProposal, ComplianceLedger
- 11 real-time data clients: OpenSky ADS-B, AIS maritime, orbital satellites, military flights, traffic cameras, SEC filings, satellite imagery, weather, stock prices, earthquakes
- RESTful API with 20+ endpoints for portfolio management, data feeds, compliance, and alerts

**AI Agent Pipeline**
- Thesis Orchestrator with 37-ticker / 113-facility knowledge base
- Sensor Orchestrator with weather-aware sensor allocation and fallback chains
- Consensus Vision Agent with multi-model anomaly detection
- Quant Regression Agent with historical correlation backtesting
- Omnichannel RAG Agent with SEC filing analysis
- Compliance CoPilot with immutable audit trails and PDF generation

**Frontend Dashboard**
- Cesium.js 3D globe with view modes (STD, FLIR, NVG, CRT)
- Data layer toggles: Satellites, ADS-B Flights, Military, AIS Ships, Earthquakes, Cameras, Geo-Fences, Swarm Monitor
- POI navigation system (Washington DC, New York, London, Dubai, Tokyo, Shanghai, Austin, Moscow)
- Real-time WebSocket connection with auto-reconnect
- Zustand state management for all data feeds
- Tactical HUD with NAV, P&L, feed counts

### Phase 2: Trade Tracking & Portfolio Management (Today)

**Trade Proposal System**
- `TradeProposal` model added to backend (ticker, side, shares, thesis, geo_targets, confidence)
- Orchestrator-side inference: parses thesis text for ticker, side, share count, price targets
- `/api/thesis` endpoint returns proposals alongside orchestrator analysis
- Position modification endpoint: `PATCH /api/portfolio/position/{ticker}` (SIZE_UP, SIZE_DOWN, EXIT)
- Price refresh from yfinance on portfolio fetch
- Frontend types: `TradeProposal`, `ThesisResponse` interfaces
- API methods: `submitThesis()`, `confirmTradeProposal()`, `modifyPosition()`
- Store actions: `submitThesis`, `confirmProposal`, `modifyPosition`
- `TradeProposalCard` component: confirms/rejects proposals with animated UI
- `ThesisInput` component: expanded text area with thesis submission flow

### Phase 3: Geospatial Intelligence Views (Today)

**Most Profitable Monitoring Area Analysis**
- Analyzed 37-ticker facility knowledge base for geographic market cap density
- Identified Silicon Valley / Bay Area as highest-value cluster (~$14T combined market cap)
  - NVDA, AAPL, TSLA, GOOGL, META, AMD, CVX all within 30-mile radius
- Created live "Nearby Cameras" view centered on Silicon Valley (37.38, -122.06)
- Loaded 56 Caltrans traffic camera feeds covering the tech corridor

**Satellite Imagery Recon Strip**
- Added `SatelliteReconStrip` component to `CameraGridPanel.tsx`
- Uses ESRI World Imagery export API (free, no auth required) for satellite tiles
- 7 Silicon Valley facilities tracked: Tesla Fremont, Apple Park, NVIDIA HQ, Googleplex, Meta HQ, AMD Santa Clara, Chevron San Ramon
- Auto-refreshes every 10 seconds with cache-busting query params
- Scan-line animation effect + vignette overlay for tactical aesthetic
- Countdown timer and progress bar for refresh cycle
- Bounding box calculation from lat/lon + zoom level for tile fetching

### Phase 4: Agent Swarm Visualization (Today -- In Progress)

**Backend**
- `GET /api/portfolio/position/{ticker}/agents` endpoint
- Returns all 6 agents per position with: id, name, role, status, icon, color, monitoring targets, metrics
- Agent monitoring targets derived from position's geo_targets and facility sensors
- Includes position details, facilities list, alerts count

**Frontend**
- `AgentInfo` and `PositionAgentsResponse` TypeScript interfaces
- `fetchPositionAgents(ticker)` API method
- `selectedPosition` + `selectPosition()` in Zustand store
- `PositionDetailPanel` component:
  - Position summary bar (shares, entry price, current price, P&L)
  - Thesis display
  - Agent swarm header with counts (agents, facilities, alerts)
  - 6 color-coded agent cards (cyan/emerald/purple/amber/blue/rose)
  - Expandable cards showing: role description, active monitoring targets, metrics grid
  - Facilities footer listing all monitored locations
- `PortfolioPanel` positions made clickable with selected state highlight (cyan border)
- Wired into `App.tsx` via lazy loading with error boundary

---

## Current State

### What Works
- Full 3D globe with all data layers (satellites, flights, ships, cameras, earthquakes)
- Live camera feeds via Swarm Monitor (4500+ feeds) and Nearby Cameras mode
- Satellite imagery recon strip with auto-refresh
- Portfolio panel displaying 8 demo positions with real-time prices
- Thesis submission flow with orchestrator analysis
- Trade proposal confirmation workflow
- Compliance audit generation with PDF export
- Alert system with severity filtering
- Position detail panel opens on click (renders, calls API)

### What Needs Fixing
- Position detail panel stuck on "Loading agent swarm..." -- the API endpoint works (verified via curl) but the frontend fetch may have a proxy/CORS issue in the preview context
- WebSocket reconnection warnings in console (non-critical, auto-retries)
- Demo data does not persist across server restarts (in-memory only)

### Running Services
- Frontend: `http://localhost:3000` (Vite dev server)
- Backend: `http://localhost:8000` (FastAPI with uvicorn)
- WebSocket: `ws://localhost:8000/ws`

---

## Known Issues & Bugs

| Issue | Severity | Details |
|-------|----------|---------|
| Agent panel loading state | Medium | `PositionDetailPanel` shows "Loading agent swarm..." indefinitely. Backend endpoint works (curl confirms 200 response). Likely a frontend proxy routing issue with the API fallback mechanism. |
| WebSocket reconnect noise | Low | `[WS] Error: [object Event]` in console. Normal reconnection behavior when WS drops. |
| In-memory state | Low | All positions/alerts are in-memory. Lost on backend restart. Demo can be re-seeded via `GET /api/demo/seed`. |
| Price fetch null | Low | Some positions show `current_price: null` when yfinance rate-limits or ticker lookup fails. |

---

## Next Phases

### Phase 5: Agent Swarm Polish & Live Data

**Priority: HIGH**

1. **Fix agent panel loading bug** -- Debug the `fetchPositionAgents` call in PositionDetailPanel to resolve the loading state issue. The backend returns correct data; the frontend fetch needs proxy/fallback adjustment.

2. **Live agent status** -- Connect agents to WebSocket so their status updates in real-time (idle -> active -> processing -> complete). Currently all agents show "active" statically.

3. **Agent activity timeline** -- Add a timeline/log view inside each expanded agent card showing recent actions:
   - "Sensor Orchestrator dispatched optical feed to Tesla Fremont at 14:23:05"
   - "Consensus Vision detected 12% parking lot variance at Apple Park"
   - "Quant Regression computed R²=0.87 for TSLA production vs stock price"

4. **Inter-agent communication visualization** -- Show data flowing between agents (e.g., Thesis Orchestrator -> Sensor Orchestrator -> Consensus Vision) with animated connection lines.

### Phase 6: Enhanced Satellite & Camera Intelligence

**Priority: HIGH**

1. **Per-position satellite view** -- When clicking a position, show satellite imagery of all its facilities (not just Silicon Valley). Pull from the position's `geo_targets`.

2. **Camera-to-position linking** -- Auto-find nearby cameras for each facility in a position and show them in the detail panel.

3. **Historical satellite comparison** -- Side-by-side satellite imagery (current vs. 30/60/90 days ago) to visualize construction progress, parking lot changes, shipping container volumes.

4. **Anomaly heatmaps** -- Overlay heatmap on the globe showing where anomalies are detected most frequently across all monitored facilities.

### Phase 7: Real-Time Alert Pipeline

**Priority: HIGH**

1. **End-to-end alert flow** -- When the Consensus Vision Agent detects an anomaly, automatically trigger Quant Regression + Omnichannel RAG analysis and produce a SentinelAlert that appears in the Alert panel with a globe fly-to animation.

2. **Alert-to-trade workflow** -- Clicking an actionable alert (confidence >= 0.75, severity HIGH/CRITICAL) should offer a one-click trade execution path: Alert -> Review -> Confirm -> Position Modified.

3. **Alert clustering** -- Group related alerts by ticker/facility to prevent alert fatigue. Show "3 new alerts for TSLA facilities" instead of 3 individual alerts.

4. **Push notifications** -- Browser notifications for CRITICAL alerts even when the tab is in background.

### Phase 8: Persistence & Production

**Priority: MEDIUM**

1. **Database migration** -- Move from in-memory state to SQLite/PostgreSQL for positions, alerts, compliance records.

2. **User authentication** -- JWT-based auth for the dashboard. Role-based access (PM, Analyst, Compliance Officer).

3. **Historical data storage** -- Store all sensor readings, anomaly detections, and alert history for backtesting and compliance audit trails.

4. **API rate limiting** -- Implement rate limiting for external data source APIs (OpenSky, yfinance, USGS) to avoid bans.

### Phase 9: Advanced Analytics

**Priority: MEDIUM**

1. **Portfolio risk dashboard** -- VaR calculations, sector exposure heatmap, geographic concentration risk.

2. **Backtesting engine** -- Replay historical facility data against past stock performance to validate the physical-signal thesis.

3. **Multi-factor scoring** -- Combine anomaly magnitude, consensus score, quant materiality, and omnichannel adjustment into a single conviction score.

4. **Natural language alerts** -- Use Claude to generate human-readable alert summaries: "Parking lot at Tesla Shanghai shows 23% more vehicles than seasonal average, suggesting production acceleration. Historical correlation: 0.87 R². Suggested action: Size up TSLA long position."

### Phase 10: Scale & Deployment

**Priority: LOW**

1. **Docker compose production** -- Production-ready Docker configuration with nginx reverse proxy, SSL, and health checks.

2. **Real satellite imagery** -- Integrate Planet Labs and Capella SAR APIs (currently stubbed) for actual satellite imagery instead of ESRI tiles.

3. **Real AI inference** -- Connect Consensus Vision Agent to actual vision models (GPT-4V, Claude Vision) for real parking lot / construction site analysis.

4. **Multi-user support** -- Multiple PMs with separate portfolios, shared compliance ledger.

5. **Mobile companion** -- React Native app for critical alerts on the go.

---

## File Reference

### Backend

```
backend/
  main.py                     -- FastAPI entry, background refresh loop, route injection
  config.py                   -- Environment vars, API keys, thresholds
  api/
    routes.py                 -- 20+ REST endpoints (portfolio, thesis, data, compliance, agents)
    websocket.py              -- Real-time WS broadcasting (flights, ships, cameras, alerts)
  agents/
    orchestrator.py           -- Thesis Orchestrator (37 tickers, 113 facilities)
    sensor_orchestrator.py    -- Weather-aware sensor allocation
    consensus_vision.py       -- Multi-model anomaly detection
    quant_regression.py       -- Financial materiality backtesting
    omnichannel_rag.py        -- SEC filing revenue analysis
    compliance_copilot.py     -- Audit trail generation
  models/
    portfolio.py              -- Position, Portfolio, TradeProposal, GeoTarget, SensorTasking
    alerts.py                 -- SentinelAlert, AnomalyDetection, QuantBacktest
    compliance.py             -- DataProvenance, ComplianceLedger, AuditReport
  data/
    opensky.py                -- ADS-B flight tracking
    ships.py                  -- AIS maritime vessel data
    satellites_orbital.py     -- Orbital satellite tracking
    military_flights.py       -- Military aircraft detection
    traffic_cameras.py        -- Caltrans + global camera feeds
    sec_filings.py            -- SEC 10-K/10-Q parsing
    satellite.py              -- Planet Labs / Capella SAR (stubbed)
    weather.py                -- OpenWeather for sensor blocking
    stocks.py                 -- yfinance price data
    earthquakes.py            -- USGS earthquake feeds
  services/
    ledger.py                 -- Immutable compliance ledger
    pdf_generator.py          -- SEC audit report PDF generation
    vector_store.py           -- ChromaDB semantic search
```

### Frontend

```
frontend/src/
  App.tsx                     -- Main app, lazy-loaded components, error boundaries
  main.tsx                    -- React DOM entry
  types/index.ts              -- TypeScript interfaces (Position, Alert, TradeProposal, AgentInfo, etc.)
  services/api.ts             -- HTTP client with proxy/direct fallback
  store/useStore.ts           -- Zustand global state (portfolio, alerts, all data feeds)
  hooks/useWebSocket.ts       -- WebSocket hook with auto-reconnect
  components/
    Dashboard/
      PortfolioPanel.tsx      -- Fund NAV, positions list, clickable rows
      AlertPanel.tsx          -- Real-time alerts with severity filtering
      CameraGridPanel.tsx     -- Multi-camera grid + satellite recon strip
      CameraPreviewPanel.tsx  -- Single camera preview
      PositionDetailPanel.tsx -- Agent swarm visualization per position
      ThesisInput.tsx         -- PM thesis text input
      TradeProposalCard.tsx   -- Trade confirmation UI
      TacticalHUD.tsx         -- Tactical display overlay
    Globe/
      CesiumGlobe.tsx         -- 3D Cesium globe with entity rendering
    Compliance/
      ComplianceModal.tsx     -- Audit trail viewer + PDF export
    UI/
      ModeSelector.tsx        -- View mode toggle (STD/FLIR/NVG/CRT)
      StatusBar.tsx           -- System status indicators
```
