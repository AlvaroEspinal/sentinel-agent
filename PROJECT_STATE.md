# Parcl Intelligence — Project State

**Last Updated:** March 4, 2026
**Repo:** https://github.com/AlvaroEspinal/sentinel-agent
**Branch:** `main`

---

## What Is This

Parcl Intelligence is a **real estate data intelligence platform** targeting affluent Massachusetts towns. It combines:

- **CesiumJS 3D globe** with parcel overlays, flood zone layers, and permit pins
- **FastAPI backend** with 34+ REST endpoints and WebSocket real-time streaming
- **React + TypeScript + Zustand** frontend with a realtor-focused dashboard
- **Supabase** (PostgreSQL) for 125K+ permits, property transfers, municipal documents
- **Automated scraping pipeline** pulling permits, meeting minutes, and sales data from 12 target towns

The platform was originally a surveillance/hedge fund geospatial viewer ("Sentinel Agent") and was pivoted to a pure real estate MVP. All surveillance code has been removed.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript 5.3, Vite 5, Zustand 4.5, CesiumJS 1.114, Tailwind CSS 3.4, Recharts, Lucide icons |
| Backend | Python 3, FastAPI, Uvicorn, httpx, Pydantic 2, pdfplumber |
| Database | Supabase (PostgreSQL via PostgREST), SQLite fallback |
| 3D Globe | CesiumJS + Resium, ArcGIS imagery providers |
| Scraping | Firecrawl API, Socrata API, ViewpointCloud API, Nominatim geocoder |
| AI/LLM | Anthropic Claude API (document extraction, permit analysis) |
| Deployment | Vercel (frontend), backend not yet deployed |

---

## 12 Target Towns

All affluent Massachusetts municipalities configured in `backend/scrapers/connectors/town_config.py`:

| Town | County | Median Home Value | Population | Permit Portal |
|------|--------|-------------------|------------|---------------|
| Newton | Middlesex | $1,350,000 | 88,923 | ViewpointCloud |
| Wellesley | Norfolk | $1,600,000 | 29,673 | Firecrawl |
| Weston | Middlesex | $2,200,000 | 12,135 | Firecrawl |
| Brookline | Norfolk | $1,200,000 | 63,191 | Firecrawl |
| Needham | Norfolk | $1,150,000 | 31,388 | Firecrawl |
| Dover | Norfolk | $1,800,000 | 6,215 | Firecrawl |
| Sherborn | Middlesex | $1,100,000 | 4,335 | Firecrawl |
| Natick | Middlesex | $850,000 | 36,050 | Firecrawl |
| Wayland | Middlesex | $1,050,000 | 13,835 | Firecrawl |
| Lincoln | Middlesex | $1,400,000 | 7,012 | Firecrawl |
| Concord | Middlesex | $1,250,000 | 19,872 | Firecrawl |
| Lexington | Middlesex | $1,300,000 | 34,454 | Firecrawl |

Each town has boards configured: Select Board, Planning Board, ZBA, Conservation Commission.

---

## What Is Done

### Data Sources (All Working)

| Source | Endpoint | Description |
|--------|----------|-------------|
| MassGIS Parcels | `GET /api/parcels?lat=&lon=` | Owner, value, use code, lot size, building area via ArcGIS |
| MassGIS Comps | `GET /api/comps?lat=&lon=&radius_m=500` | Comparable sales with $/sqft ranking |
| FEMA Flood Zones | `GET /api/flood-zone?lat=&lon=` | Zone code, SFHA status, base flood elevation |
| Zoning (USE_CODE) | `GET /api/zoning?lat=&lon=` | Land use classification from MassGIS |
| Ownership/Deeds | `GET /api/land-records?lat=&lon=` | Owner, mailing address, assessed values |
| Nominatim Geocoder | `GET /api/geocode?address=` | Forward geocoding with in-memory cache |
| Supabase Permits | `GET /api/permits/search` | 125K+ permits (Somerville 64K, Cambridge 61K) |
| Viewport Pins | `GET /api/permits/viewport?west=&south=&east=&north=` | Dynamic permit pins on globe |

### Scraping Pipeline (Built, Needs Deployment)

| Component | Status | Notes |
|-----------|--------|-------|
| ScrapeScheduler | Built | Background loop every 300s, checks 12 towns |
| Socrata Connector | Built | Cambridge (10 datasets), Somerville (1 dataset) |
| ViewpointCloud Connector | Built | Newton (`newtonma` slug) |
| Firecrawl Client | Built | Crawl + scrape + batch, rate limiting |
| LLM Extractor | Built | Claude-powered extraction from meeting minutes |
| Meeting Minutes Scraper | Built | PDF download + pdfplumber + LLM extraction |
| Permit Normalizer | Built | Normalizes Boston, Cambridge, Somerville formats |
| Firecrawl Permit Extraction | Built | Crawl town portal + LLM extract permit records |
| `permits` table migration | Written | `002_permits_table.sql` — not yet run |
| Town Config Registry | Built | 12 towns with URLs, boards, schedules |
| Batch Geocoder Script | Built | ~8% of Somerville done, Cambridge not started |

### Frontend Features

| Feature | Status |
|---------|--------|
| CesiumJS globe with fly-to | Working |
| Parcel boundary overlay (MassGIS) | Working |
| FEMA flood zone overlay | Working |
| Viewport permit pins + clustering | Working |
| PropertyDetails 7 tabs (Permits, Parcel, Flood, Zoning, Deeds, Comps, Agents) | Working |
| Search bar with geocode fallback (any address) | Working |
| Realtor dashboard (town cards, search, activity feed) | Working |
| Town dashboard (permits, transfers, documents) | Working |
| Sidebar with 12 target towns | Working |
| Tracked listings + watchlist | Working |
| Property monitoring agents (CRUD) | Working |
| RAG chat for permit Q&A | Working |
| Map View toggle (globe as overlay) | Working |

### Globe Overlays (DATA LAYERS)

| Layer | Tile Service | Status |
|-------|-------------|--------|
| Flood Zones | FEMA NFHL MapServer | Working (alpha 0.45) |
| Parcels (MA) | MassGIS Level3 Parcels MapServer | Working (alpha 0.55, zoom 15-20) |
| Permits | Supabase viewport query | Working (color-coded by type) |

### Deployment

| Target | Status |
|--------|--------|
| Vercel (frontend) | Deployed, TypeScript strict build passes |
| Backend (Railway/Render/Fly.io) | Not yet deployed |

---

## What Is Left To Do

### Immediate (To Activate Scraping)

1. **Run `002_permits_table.sql`** in Supabase SQL Editor
2. **Deploy backend** to Railway/Render/Fly.io so scheduler runs
3. **Test scraping**: `POST /api/scrape/trigger/cambridge?source_type=permits`

### Data Pipeline

4. **Resume batch geocoding** — 124.5K permits at 0,0 need coordinates
5. **Run scraping for all 12 towns** — meeting minutes + property transfers + permits
6. **Add Socrata configs for target towns** — check if any of the 12 use Socrata (currently only Cambridge/Somerville)

### Frontend Polish

7. **Wire scraped permits to UI** — display `/api/scraped-permits` in town dashboard
8. **Meeting minutes viewer** — show extracted mentions, decisions, keywords
9. **Property transfer trends** — charts showing price/sqft over time per town
10. **Watchlist notifications** — alert when tracked properties have new permits or mentions
11. **Mobile responsive** — current layout is desktop-only

### Advanced Data Sources (Phase 3)

12. **Zoning bylaws** — Firecrawl from town websites / ecode360.com
13. **MEPA environmental filings** — `eeaonline.eea.state.ma.us`
14. **Tax delinquency lists** — town treasurer PDFs
15. **Registry of Deeds links** — construct masslandrecords.com URLs from book/page
16. **Conservation restrictions** — MassDEP + town pages
17. **Capital improvement plans** — town budget PDFs

### Backend Cleanup

18. **Remove unused API keys** from `config.py` (OPENSKY, POLYGON, PLANET, CAPELLA, etc.)
19. **Remove unused Python deps** from `requirements.txt` (yfinance, scipy, cryptography, etc.)

---

## Architecture

### Directory Structure

```
sentinel-agent/
  backend/
    main.py                         # FastAPI app, startup/shutdown, scheduler init
    config.py                       # All env vars and API keys
    api/
      routes.py                     # 34+ REST endpoints
      websocket.py                  # WebSocket connection manager
    database/
      supabase_client.py            # Async PostgREST client (fetch, insert, update, delete)
      postgres.py                   # PostgreSQL connection (legacy)
      migrations/
        001_realtor_mvp.sql         # municipal_documents, property_transfers, scrape_jobs
        002_permits_table.sql       # Dedicated permits table (not yet run)
    models/
      property.py                   # Pydantic models for all entities
    services/
      permit_search.py              # Semantic/keyword permit search (RAG)
      pdf_generator.py              # Audit PDF reports
      vector_store.py               # ChromaDB embeddings
    scrapers/
      scheduler.py                  # Background scrape job runner (300s loop)
      permit_loader.py              # Loads 125K permits from Supabase
      connectors/
        town_config.py              # 12 target towns registry
        massgis_parcels.py          # MassGIS ArcGIS parcel queries
        massgis_comps.py            # Comparable sales finder
        fema_flood.py               # FEMA NFHL flood zones
        zoning_atlas.py             # USE_CODE zoning classification
        mass_land_records.py        # Ownership/deed records
        nominatim_geocoder.py       # Forward geocoding + cache
        socrata.py                  # Socrata API (Cambridge, Somerville)
        viewpointcloud.py           # ViewpointCloud/OpenGov (Newton)
        firecrawl_client.py         # Firecrawl web scraping wrapper
        llm_extractor.py            # Claude-powered document extraction
        meeting_minutes.py          # Meeting minutes scraper + PDF parser
        normalize.py                # Permit data normalization
    scripts/
      batch_geocode_permits.py      # CLI geocoding for 125K permits
    agents/
      __init__.py                   # Empty (hedge fund agents removed)
  frontend/
    src/
      App.tsx                       # Root app, view routing
      main.tsx                      # React entry
      types/index.ts                # All TypeScript interfaces
      store/useStore.ts             # Zustand global state
      services/api.ts               # 30+ API client functions
      hooks/useWebSocket.ts         # WebSocket lifecycle hook
      components/
        Globe/
          CesiumGlobe.tsx           # Globe container
          CesiumGlobeInner.tsx      # Globe logic, overlays, entity rendering
          ShaderOverlay.tsx         # Shader effects
          MapOverlay.tsx            # Map overlay panel
          EntityLayer.tsx           # Entity rendering placeholder
        Dashboard/
          LandingPage.tsx           # Main dashboard view
        Town/
          TownDashboard.tsx         # Town analytics page
          TownCard.tsx              # Town summary card
        RealEstate/
          PropertyDetails.tsx       # 7-tab property enrichment
          PropertyPanel.tsx         # Property panel container
          PropertySearch.tsx        # Search interface
          SearchBar.tsx             # Search input with geocode fallback
          RightPanel.tsx            # Right sidebar
          IntelFeed.tsx             # Agent findings feed
          ChatPanel.tsx             # RAG chat interface
        UI/
          TopBar.tsx                # Top navigation
          LeftSidebar.tsx           # Sidebar with towns + toggles
          DataLayerPanel.tsx        # Data layer toggles
          Sidebar.tsx               # Layout sidebar
          StatusBar.tsx             # Status indicators
          ThemeToggle.tsx           # Dark/light mode
```

### API Endpoints (34+)

**Geospatial**
- `GET /api/geocode?address=` — Nominatim geocoding
- `GET /api/flood-zone?lat=&lon=` — FEMA flood zone
- `GET /api/parcels?lat=&lon=` — MassGIS parcel info
- `GET /api/zoning?lat=&lon=` — Zoning classification
- `GET /api/land-records?lat=&lon=` — Ownership/deeds
- `GET /api/comps?lat=&lon=&radius_m=` — Comparable sales

**Properties & Permits**
- `GET /api/properties/search` — Property search
- `GET /api/properties/{id}` — Single property
- `GET /api/permits/search` — Permit search
- `GET /api/permits/near/{lat}/{lon}` — Nearby permits
- `GET /api/permits/viewport` — Viewport permit pins
- `GET /api/permits/towns` — Town permit counts

**Towns**
- `GET /api/towns` — All 351 MA municipalities
- `GET /api/target-towns` — 12 target towns
- `GET /api/towns/{town_id}` — Town detail
- `GET /api/towns/{town_id}/dashboard` — Town dashboard data
- `GET /api/towns/{town_id}/activity` — Activity feed
- `GET /api/towns/{town_id}/documents` — Municipal documents
- `GET /api/towns/{town_id}/transfers` — Property transfers

**Parcels**
- `GET /api/parcels/search?town=&address=` — Parcel search
- `GET /api/parcels/{loc_id}/mentions` — Document mentions

**Scraping**
- `POST /api/scrape/trigger/{town_id}` — Manual scrape trigger
- `GET /api/scrape/status` — Job status
- `GET /api/scrape/stats` — Statistics
- `GET /api/scraped-permits` — Query scraped permits
- `GET /api/scraped-permits/by-town/{town_id}` — Town permits
- `POST /api/ingestion/run` — Trigger ingestion run

**Coverage**
- `GET /api/coverage/summary` — Source coverage matrix
- `GET /api/coverage/municipality/{id}` — Single town coverage

**Agents**
- `GET /api/agents` — List monitoring agents
- `POST /api/agents` — Create agent
- `DELETE /api/agents/{id}` — Delete agent

**Other**
- `GET /api/health` — Server health
- `POST /api/chat` — RAG property chat
- `POST /api/listings/enrich` — Listing enrichment
- `WS /ws` — WebSocket (real-time findings)

### Database Tables

**Supabase (PostgreSQL)**

| Table | Rows | Purpose |
|-------|------|---------|
| `documents` | 125K+ | Permit records (pipe-delimited content) |
| `document_locations` | ~1K | Geocoded permit coordinates |
| `document_metadata` | 125K+ | Permit metadata |
| `towns` | 351 | MA municipalities |
| `source_requirements` | 37 | Data source types |
| `municipality_source_coverage` | ~13K | Coverage matrix |
| `municipal_documents` | 0* | Meeting minutes (table created, not populated yet) |
| `property_transfers` | 0* | Sales history (table created, not populated yet) |
| `scrape_jobs` | 0* | Scrape job tracking |
| `permits` | 0* | Dedicated permits table (migration not yet run) |
| `property_agents` | dynamic | Monitoring agents |
| `agent_findings` | dynamic | Agent alerts |

*Tables exist but need backend deployment to populate via scheduler.

### Environment Variables

**Required for core functionality:**
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — Database
- `ANTHROPIC_API_KEY` — LLM extraction
- `FIRECRAWL_API_KEY` — Web scraping
- `VITE_CESIUM_ION_ACCESS_TOKEN` — 3D globe (frontend)
- `VITE_API_URL`, `VITE_WS_URL` — API connection (frontend)

**Optional / unused (from legacy):**
- OPENAI_API_KEY, POLYGON_API_KEY, PLANET_API_KEY, CAPELLA_API_KEY, WINDY_API_KEY
- ATTOM_API_KEY, FIRST_STREET_API_KEY, WALK_SCORE_API_KEY, GREATSCHOOLS_API_KEY
- SHOVELS_API_KEY, REGRID_API_KEY, AIRDNA_API_KEY
- SENTINEL_HUB_CLIENT_ID/SECRET, OPENSKY_USERNAME/PASSWORD

---

## Git History

```
45b68af Implement permit scraping pipeline for all portal types
5595c01 Remove hedge fund/surveillance code — pure realtor MVP
7b0ca60 Fix lot size display and scheduler null sale_date bug
975485e Fix duplicate /api/towns route — rename target towns endpoint
97b32e2 Realtor MVP pivot: data foundation + dashboard UI redesign
0265455 Fix TypeScript build errors for Vercel deployment
e80bd58 Initial commit: Parcl Intelligence real estate geospatial platform
```

---

## Known Issues & Gotchas

- **124.5K permits at 0,0** — need batch geocoding (script exists, ~8% Somerville done)
- **Vercel `tsc` is strict** — dev server ignores type errors, always run `npx tsc --noEmit` before pushing
- **masslandrecords.com blocks bots** — use MassGIS ownership fields instead
- **CesiumJS HMR** — hot reload destroys viewer; CustomDataSource refs must be re-validated
- **CORS** — backend must allow both `localhost` and `127.0.0.1` origins
- **Nominatim rate limit** — 1 request/second, use cache
- **`permits` table not created yet** — run `002_permits_table.sql` in Supabase first
- **Backend not deployed** — scheduler won't run until backend is on Railway/Render/Fly.io

---

## How To Run Locally

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env  # Fill in API keys
python3 main.py       # Starts on port 8000

# Frontend
cd frontend
npm install
npm run dev           # Starts on port 3000
```

## How To Deploy

**Frontend (Vercel):**
- Root Directory: `frontend`
- Build Command: `npm run build`
- Output Directory: `dist`
- Env vars: `VITE_CESIUM_ION_ACCESS_TOKEN`, `VITE_API_URL`, `VITE_WS_URL`

**Backend (Railway/Render/Fly.io):**
- Not yet configured
- Needs: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `FIRECRAWL_API_KEY`
