# Municipal Intelligence System

Real estate data intelligence platform for affluent Massachusetts communities. Combines a 3D CesiumJS globe with 30+ municipal data connectors, permit tracking, and automated document scraping.

![Stack](https://img.shields.io/badge/React-18-blue) ![Stack](https://img.shields.io/badge/FastAPI-0.100+-green) ![Stack](https://img.shields.io/badge/CesiumJS-1.114-orange) ![Stack](https://img.shields.io/badge/Supabase-Backend-purple)

## Features

- **3D Globe** — CesiumJS-powered interactive map with parcel boundaries, flood zone overlays, and permit pin clustering
- **Property Analytics** — Parcel data, comparable sales, flood zones, zoning, ownership/deeds via MassGIS & FEMA
- **Permit Tracking** — 439K+ building permits across 15+ MA municipalities with geocoded map pins
- **Municipal Document Scraping** — Automated ingestion of meeting minutes, MEPA filings, CIP documents, and zoning bylaws
- **Town Dashboards** — Per-municipality views with permit breakdowns, recent activity, and data quality metrics
- **Address Search** — Geocoded search with Nominatim (OpenStreetMap) integration
- **Agent Monitoring** — Background scrape scheduling with WebSocket-powered real-time intel feed

## Architecture

```
frontend/          React 18 + TypeScript + Vite + Tailwind CSS
  CesiumGlobe      3D globe with parcel/flood overlays and permit pins
  TownDashboard    Per-town analytics and document browser
  PropertyDetails  7-tab property view (Permits, Parcel, Flood, Zoning, Deeds, Comps, Agents)

backend/           FastAPI + Python
  api/routes.py    50+ REST endpoints
  scrapers/        Scheduler + connectors for municipal data sources
  database/        Supabase client
  services/        Permit search, LLM extraction
```

## Data Connectors

| Connector | Source | Auth |
|-----------|--------|------|
| MassGIS Parcels | ArcGIS Feature Service | None |
| MassGIS Comps | ArcGIS Feature Service | None |
| FEMA Flood Zones | NFHL ArcGIS REST | None |
| Zoning Atlas | MassGIS USE_CODE mapping | None |
| Nominatim Geocoder | OpenStreetMap | None (1 req/sec) |
| Firecrawl | Web scraping | API key |
| CivicClerk | Meeting minutes | None |
| AgendaCenter | Town agendas | None |
| Laserfiche | Document archives | None |
| ViewPointCloud | Permit portals | None |
| MEPA | Environmental filings | None |
| MassGIS Wetlands | ArcGIS Feature Service | None |
| MassGIS Open Space | ArcGIS Feature Service | None |

## Getting Started

### Prerequisites

- Node.js 18+
- Python 3.10+
- [Cesium ion](https://cesium.com/ion/) access token
- Supabase project (for permit storage)

### Frontend

```bash
cd frontend
npm install
```

Create `frontend/.env`:
```env
VITE_CESIUM_ION_ACCESS_TOKEN=your_token
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws
```

```bash
npm run dev        # http://localhost:5173
```

### Backend

```bash
cd backend
pip install -r requirements.txt
```

Create `backend/.env`:
```env
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_KEY=your_service_key
ANTHROPIC_API_KEY=your_key          # optional, for LLM extraction
FIRECRAWL_API_KEY=your_key          # optional, for web scraping
```

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker

```bash
docker-compose up
```

## Deployment

- **Frontend**: Vercel (auto-deploys from `main`)
- **Backend**: Render via `render.yaml` blueprint, or any Docker host
- See [DEPLOY.md](DEPLOY.md) for detailed instructions

## API Highlights

| Endpoint | Description |
|----------|-------------|
| `GET /api/parcels?lat=&lon=` | Property parcel data |
| `GET /api/flood-zone?lat=&lon=` | FEMA flood zone lookup |
| `GET /api/comps?lat=&lon=` | Comparable sales |
| `GET /api/zoning?lat=&lon=` | Zoning designation |
| `GET /api/land-records?lat=&lon=` | Ownership/deed records |
| `GET /api/permits/viewport?west=&south=&east=&north=` | Permits in map bounds |
| `GET /api/geocode?address=` | Address geocoding |
| `GET /api/towns/{town_id}/dashboard` | Town analytics |
| `GET /api/platform-stats` | Platform-wide statistics |
| `POST /api/scrape/trigger/{town_id}` | Trigger town data scrape |

## Tech Stack

**Frontend**: React 18, TypeScript, Vite, Tailwind CSS, CesiumJS/Resium, Zustand, Recharts, Lucide Icons

**Backend**: FastAPI, Python 3.10+, httpx, Supabase, APScheduler, Anthropic SDK, Firecrawl, BeautifulSoup, pdfplumber

## License

MIT
