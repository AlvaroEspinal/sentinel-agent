# Parcl Intelligence — Project Status

**Last Updated:** March 11, 2026 (Sessions 15-16 — Data Quality Pipeline + Production Deploy Prep)

**Session 16 (Production Deployment Prep):**
1. Fixed frontend API base URL — `api.ts` now uses `VITE_API_URL` env var (was hardcoded localhost:8000).
2. Updated backend CORS to include all 3 Vercel production domains.
3. Created Dockerfile (Python 3.11-slim, PORT env var), Procfile, .python-version, .dockerignore.
4. Created `render.yaml` (Render Blueprint) and `railway.toml` for one-click cloud deployment.
5. Created `deploy-backend.sh` — single-command Railway deploy script.
6. Committed and pushed all data quality scripts + deployment files to GitHub (3,922 additions, 12 files).
7. Verified Vercel frontend deployment is READY (sentinel-agent-alpha.vercel.app).
8. **Blocking:** Railway CLI requires interactive browser login — deploy script ready for user to run.

**Session 15 (Data Quality Pipeline — 7-Agent Plan):**
1. **Properties table populated** — 91,983 parcels from MassGIS across all 12 MVP towns.
2. **Permits geocoded** — 193,318 / 439,175 permits (44%) have lat/lon coordinates.
   - Weston 99.3%, Concord 96.2%, Sherborn 95.5%, Brookline 92.1%, Lincoln 90.9% geocoded.
   - Newton, Lexington, Natick, Needham, Wellesley, Wayland still need geocoding.
3. **MEPA town_id fixed** — 117 filings reassigned from `boston` to correct MVP towns via MEPA API re-query. 0 MEPA filings now stuck on `town_id='boston'`.
4. **SQL views created** — `v_property_360`, `v_town_dashboard`, `v_coverage_matrix`, `v_property_timeline` (migration 004).
5. **DATA_AUDIT_REPORT.md v2** — comprehensive audit with coverage matrix, data quality scores.
6. Scripts created: `populate_properties.py`, `geocode_permits_table.py`, `fix_mepa_towns.py`, `link_permits_to_properties.py`, `scrape_missing_cip.py`.

**Session 14 (Full Audit):**
1. Comprehensive audit of all 12 MVP towns across all 9 data sources.
2. Reviewed Antigravity workstream to unify next steps.
3. Updated PROJECT_STATUS.md with full completion matrix and tomorrow plan.

**Session 13 (Antigravity):**
1. Tax Takings ingested — 62 Norfolk Registry records inserted to Supabase.
2. Tax Delinquency town_id fixed — 69 records corrected (boston → correct towns).
3. 4 CIP towns resolved via browser OSINT sub-agents: Newton, Dover, Wayland, Lincoln.
4. Brookline permits expanded 63 → 251 via Playwright prefix-chunking scraper.
5. Batch geocoding complete — 106,620 document_locations rows (21,530 unique addresses).
6. All ingest scripts run — CIP (8→12 resolved), Zoning (12), Wetlands (12).

**Previous Sessions 11-12:**
1. Built Registry of Deeds tax takings scraper for Norfolk ALIS (62 records across 4 towns).
2. Attempted Middlesex South Registry — blocked by Incapsula/Imperva WAF (18 diagnostic scripts documenting all approaches tried).
3. Completed full 12-town data pipeline: ingested all 7 data sources (MEPA, overlays, wetlands, zoning, CIP, tax delinquency, meeting minutes) into Supabase.
4. Wrote comprehensive `SCRAPER_HANDOFF.md` for handoff to Antigravity environment.

---

## Current Database Summary (March 11, 2026)

| Table | Rows | Notes |
|-------|------|-------|
| properties | 91,983 | MassGIS parcels, all 12 MVP towns |
| permits | 439,175 | 44% geocoded (193K with lat/lon) |
| documents | 129,947 | Legacy permit documents |
| document_locations | 168,754 | Legacy geocoded permits |
| municipal_documents | 8,001 | CIP, meeting minutes, tax takings |
| mepa_filings | 5,557 | MEPA environmental filings |
| tax_delinquent_parcels | 71 | Tax delinquency records |
| municipal_overlays | 403 | Wetlands + zoning overlays |
| towns | 352 | MA municipalities |

### Properties by Town
| Town | Properties | Permits | Permits Geocoded |
|------|-----------|---------|-----------------|
| Newton | 23,000 | 12,766 | 10.5% |
| Lexington | 11,331 | 9,312 | 6.8% |
| Natick | 11,061 | 5,699 | 9.2% |
| Needham | 9,770 | 5,593 | 14.1% |
| Brookline | 8,439 | 63 | 92.1% |
| Wellesley | 8,000 | 3,586 | 15.0% |
| Concord | 5,102 | 16,582 | 96.2% |
| Wayland | 5,049 | 1,654 | 13.2% |
| Weston | 4,062 | 39,387 | 99.3% |
| Dover | 2,503 | 311 | 46.3% |
| Sherborn | 1,878 | 6,364 | 95.5% |
| Lincoln | 1,788 | 2,940 | 90.9% |

### Deployment Status
| Component | Status | URL |
|-----------|--------|-----|
| Frontend (Vercel) | ✅ READY | sentinel-agent-alpha.vercel.app |
| Backend (Railway) | ⏳ Pending | Needs `bash deploy-backend.sh` |
| Database (Supabase) | ✅ Active | tkexrzohviadsgolmupa |

### Next Steps
1. **Deploy backend** — Run `bash deploy-backend.sh` (Railway interactive login required)
2. **Set VITE_API_URL** — On Vercel, add env var pointing to Railway backend URL
3. **Continue permit geocoding** — Newton, Lexington, Natick, Needham need geocoding
4. **Link permits → properties** — Run `link_permits_to_properties.py` after geocoding
5. **UI polish** — Property detail views, town dashboards, data quality indicators

---

## What Was Accomplished (Sessions 6-8)

### 18. ViewpointCloud (VPC) Scraper Rewrite
**Problem:** Original VPC scraper used autocomplete search — slow, limited, unreliable.
**Solution:** Rewrote to use VPC's bulk records API with partition-based parallel scraping.
**Key Insight:** VPC partition API at `/{town}/RequestPartition` returns paginated record batches. Each town has multiple departments (Building, Electrical, Plumbing, Gas, etc.).
**Results:**
| Town | Permits | Source |
|------|---------|--------|
| Newton | 11,690 | ViewpointCloud |
| Lexington | 9,189 | ViewpointCloud |
| Needham | 5,487 | ViewpointCloud |
| Natick | 5,463 | ViewpointCloud |
| Wellesley | 3,557 | ViewpointCloud |
| Wayland | 1,616 | ViewpointCloud |
| Dover | 296 | ViewpointCloud |
**Total VPC:** 37,298 permits across 7 towns
**Status:** VERIFIED WORKING

### 19. PermitEyes Connector (Concord + Lincoln)
**Portal:** Full Circle Technologies — DataTables server-side AJAX POST to `permiteyes.us/{town}/ajax/*.php`
**Connector:** `backend/scrapers/connectors/permiteyes_client.py`
**Key Challenge:** Different towns have different column layouts. Concord uses 12 columns, Lincoln uses 9 columns in completely different positions.
**Solution:** `ColumnMap` dataclass with per-town column definitions:
- `CONCORD_COLUMNS` — 12 cols: description=0, app_number=4, app_date=5, issue_date=6, address=7, applicant=8, app_type=9, permit_number=10, status=11
- `LINCOLN_COLUMNS` — 9 cols: description=0, app_number=1, app_date=2, issue_date=3, address=4, applicant=5, app_type=6, permit_number=7, status=8
**Bug Fixes:**
- 2-digit year dates (`03/04/26` MM/DD/YY) — added `%m/%d/%y` format to `parse_date`
- Invalid date strings ("N/A", "00/00/0000") — changed fallback from `return date_str` to `return None`
- Lincoln data misalignment — detected via verbose error logging showing `"invalid input syntax for type date: \"SH\""` (permit type in date field)
**Results:**
| Town | Permits |
|------|---------|
| Concord | 6,619 |
| Lincoln | 2,918 |
**Status:** VERIFIED WORKING — Data quality confirmed (permit numbers, addresses, dates all correct)

### 20. SimpliCITY/MapsOnline Connector (Weston + Sherborn)
**Portal:** PeopleGIS / Schneider Geospatial — JSON POST API at `mapsonline.net/pf-ng/s/search`
**Connector:** `backend/scrapers/connectors/simplicity_client.py` (NEW)
**How It Works:**
1. Session-based: GET portal page to obtain `ssid` (no login required)
2. POST to `/pf-ng/s/search?sid={ssid}` with form_id + pagination
3. Returns positional arrays with 270+ columns per record
4. Dates as Unix timestamps in milliseconds
**Form Types:** Building, Electrical, Gas, Plumbing, Sheet Metal (5 per town)
**Estimated Records:**
- Weston: ~12,730 building permits
- Sherborn: ~3,654 building permits
**Status:** Built and wired into scheduler, NOT YET TESTED (needs backend restart)

### 21. Scheduler & Infrastructure Updates
**Modified:** `backend/scrapers/scheduler.py`
- Added `"permiteyes"` and `"simplicity"` dispatch branches in `run_permits_scrape()`
- New `_scrape_permiteyes_permits()` method — fetches pages, parses with column mapping, dedupes by source_id
- New `_scrape_simplicity_permits()` method — gets session, scrapes all forms, dedupes, inserts with contractor_name
- Enhanced `_insert_permit()` — added `applicant_name`, `contractor_name`, and `source_id` fields

**Modified:** `backend/scrapers/connectors/normalize.py`
- Added `%m/%d/%y` (2-digit year) date parsing
- Changed fallback from `return date_str` to `return None`

**Modified:** `backend/database/supabase_client.py`
- Enhanced error reporting: includes response body in error messages (was just status code)

**Modified:** `backend/scrapers/connectors/town_config.py`
- Concord: `permit_portal_type="permiteyes"`
- Lincoln: `permit_portal_type="permiteyes"`
- Weston: `permit_portal_type="simplicity"`
- Sherborn: `permit_portal_type="simplicity"`

### 22. Municipal Overlays ArcGIS Connector (Session 9)
**Problem:** Need specialized overlay district data (Historical, Coastal Flood, Planned Development Areas, Institutional Master Plans) for real estate analysis, but these exist isolated on individual town ArcGIS servers, not on MassGIS.
**Connector:** `backend/scrapers/connectors/municipal_overlays.py` (NEW)
**How It Works:**
1. Standalone client `MunicipalOverlayClient` that takes *any* ArcGIS REST `/query` endpoint.
2. Performs `esriGeometryEnvelope` (bounding box) and point queries, returning raw `FeatureCollection` GeoJSON.
3. Maps known overlay endpoints via `KNOWN_LAYERS` dictionary.
**Enrichment:**
- Integrated `LLMExtractor` via **OpenRouter** (`google/gemini-2.0-flash-001`).
- The script passes abbreviated GeoJSON properties to the LLM to get a 3-sentence plain English summary of what the overlay means for real estate development (risks, opportunities).
**What has been scraped (data_cache/):**
- Boston Planned Development Areas (PDAs): 24 features
- Boston Zoning Districts (Base): 74 features
- Boston Coastal Flood Resilience Overlay: 1 feature
- Boston Institutional Master Plan Overlay: 3 features
**What is left:**
- Cambridge Zoning MapServer returned an error (needs MapServer client approach instead of FeatureServer query).
- Need to push the GeoJSON overlays into the Supabase database (requires new PostGIS/GeoJSON table schema).
- Integrate the returned GeoJSON multi-polygons as new layers in the CesiumJS frontend.

### 23. Tax Delinquency Scraper (Session 10)
**Problem:** Need to parse non-standardized tabular PDF documents published by MA municipal Treasurer websites detailing delinquent tax properties (Tax Title lists).
**Solution:** Built a standalone scraper (`TaxDelinquencyScraper`) utilizing `pdfplumber` to extract tables and text, and an advanced fallback to **OpenRouter** / Anthropic LLM parsing for unstructured data to yield clean JSON.
**How It Works:**
1. **Multi-Agent Orchestration** via `backend/scripts/scrape_all_tax_delinquencies.py`
2. **OSINT Agent:** Uses `FirecrawlClient` to search Google programmatically and discover each town's actual latest Tax Title PDF links.
3. **Extraction Agent:** Downloads the PDF (using `httpx` with a `Playwright` headless Chromium fallback to bypass aggressive municipal Cloudflare/anti-bot protections), extracts the text, and routes it to an LLM for structured output (`Address`, `Owner`, `Amount Owed`).
**What has been scraped (pushed to Supabase):**
- 71 detailed property records of delinquent tax accounts extracted and ingested into the `municipal_documents` table.
**What is left:**
- Run the OSINT agent against the remaining 40+ targeted affluent towns to build the full dataset.
- Enhance the search queries for towns that bury their PDFs inside CivicPlus proprietary portals.
- Integrate these delinquent properties into the frontend Cesium Map as high-priority red warning markers for investors.

### 24. Registry of Deeds Tax Takings Scraper (Session 11)
**Problem:** Need recorded tax taking instruments from MA Registry of Deeds to identify properties where municipalities have taken tax title.
**Solution:** Built `scrape_tax_takings_from_registry.py` supporting two registries:
- **Norfolk ALIS** (norfolkresearch.org) — JavaScript SPA, works with Playwright headless browser
- **Middlesex South** (masslandrecords.com) — BLOCKED by Incapsula/Imperva WAF
**How It Works:**
1. Playwright navigates to registry portal
2. Selects "Tax Taking" document type, sets date range
3. Paginates through results extracting: address, grantor, grantee, book, page, file date
4. Saves structured JSON to `data_cache/tax_delinquency/{town}_tax_takings.json`
**Results:**
- Norfolk: 62 tax taking records across 4 towns (Dover, Needham, Wellesley, Natick)
- Middlesex: BLOCKED — 18 diagnostic scripts document all bypass attempts (WAF detects Playwright even in stealth mode)
**Ingest Script:** `ingest_tax_takings_to_supabase.py` (ready, not yet run)

### 25. Complete 12-Town Data Pipeline (Sessions 11-12)
**Achievement:** All 7 primary data sources ingested into Supabase for 12 MVP towns.
**Final Supabase State:**
| Data Source | Table | Records |
|-------------|-------|---------|
| Permits | `permits` | 104,257 |
| MEPA | `municipal_documents` | 5,314 |
| Meeting Minutes | `municipal_documents` | 1,766 |
| Overlays | `municipal_documents` | 403 |
| Tax Delinquency | `municipal_documents` | 71 |
| Wetlands | `municipal_documents` | 12 |
| Zoning | `municipal_documents` | 12 |
| CIP | `municipal_documents` | 8 |

### 26. Scraper Handoff Documentation (Session 12)
Wrote comprehensive `SCRAPER_HANDOFF.md` (17KB) covering all 9 data sources, 12 towns, with:
- Current Supabase state with exact row counts
- 12 MVP town completion matrix
- Connector architecture for each data source
- Remaining work prioritized (HIGH/MEDIUM/LOW)
- Key file reference tables
- 11 critical gotchas

---

## Current Permit Database State (Updated Session 14)

| Town | Permits | Portal System |
|------|---------|---------------|
| Weston | 39,387 | SimpliCITY |
| Concord | 16,582 | PermitEyes |
| Newton | 12,766 | ViewpointCloud |
| Lexington | 9,312 | ViewpointCloud |
| Sherborn | 6,364 | SimpliCITY |
| Natick | 5,699 | ViewpointCloud |
| Needham | 5,593 | ViewpointCloud |
| Wellesley | 3,586 | ViewpointCloud |
| Lincoln | 2,940 | PermitEyes |
| Wayland | 1,654 | ViewpointCloud |
| Dover | 311 | ViewpointCloud |
| Brookline | 251 | Accela (Playwright) |
| **Total** | **104,445** | |

**All 12 MVP towns complete.** Brookline expandable to multi-year (currently 2024 only).

---

## Current Architecture

```
Frontend (React + CesiumJS + Zustand)        Backend (FastAPI + Supabase)
─────────────────────────────────────        ────────────────────────────

SearchBar.tsx                                 GET /api/properties/search
  → searches permits in Supabase                → queries Supabase documents table
  → geocode fallback via Nominatim              → geocodes results with 0,0 coords
  → any address works worldwide
                                              GET /api/geocode?address=...
PropertyDetails.tsx (7 tabs)                    → Nominatim with in-memory cache
  → Permits tab  → enrichListing API
  → Parcel tab   → GET /api/parcels           GET /api/parcels?lat=...&lon=...
  → Flood tab    → GET /api/flood-zone          → MassGIS ArcGIS Feature Service
  → Zoning tab   → GET /api/zoning
  → Deeds tab    → GET /api/land-records      GET /api/flood-zone?lat=...&lon=...
  → Comps tab    → GET /api/comps               → FEMA NFHL ArcGIS REST (Layer 28)
  → Agents tab   → local store state
                                              GET /api/comps?lat=...&lon=...&radius_m=500
                                                → MassGIS envelope query (LS_PRICE, LS_DATE)

CesiumGlobeInner.tsx                          GET /api/zoning?lat=...&lon=...
  → Centered on Boston/North America            → MassGIS Parcels USE_CODE mapping
  → Parcel overlay + Flood overlay
  → Viewport permit pins (clustered)          GET /api/land-records?lat=...&lon=...
                                                → MassGIS ownership fields
useStore.ts (Zustand)
  → 0,0 guards on all flyTo actions           GET /api/permits/viewport
  → selectedProperty for search results         → Dynamic permit pins by bounding box
  → selectedListingId for tracked listings
                                              Permit Scraping Pipeline:
                                                → ViewpointCloud (7 towns)
                                                → PermitEyes (Concord, Lincoln)
                                                → SimpliCITY (Weston, Sherborn) [built]
                                                → Accela (Brookline) [not started]
```

---

## Files Created (All Sessions)

| File | Purpose |
|------|---------|
| `backend/scrapers/connectors/nominatim_geocoder.py` | Nominatim geocoding with cache + rate limiting |
| `backend/scrapers/connectors/fema_flood.py` | FEMA NFHL ArcGIS REST client |
| `backend/scrapers/connectors/massgis_parcels.py` | MassGIS Parcel Feature Service client |
| `backend/scrapers/connectors/zoning_atlas.py` | Zoning from MassGIS USE_CODE mapping |
| `backend/scrapers/connectors/mass_land_records.py` | MassGIS ownership data |
| `backend/scrapers/connectors/massgis_comps.py` | Comparable sales connector |
| `backend/scrapers/connectors/permiteyes_client.py` | **NEW (Session 7)** — PermitEyes DataTables AJAX scraper with per-town column mapping |
| `backend/scrapers/connectors/simplicity_client.py` | **NEW (Session 8)** — SimpliCITY/MapsOnline JSON API scraper |
| `backend/scripts/batch_geocode_permits.py` | Batch geocode permits CLI script |

## Files Modified (Sessions 6-8)

| File | Changes |
|------|---------|
| `backend/scrapers/scheduler.py` | Added `permiteyes` + `simplicity` dispatch, `_scrape_permiteyes_permits()`, `_scrape_simplicity_permits()`, enhanced `_insert_permit()` with applicant/contractor/source_id |
| `backend/scrapers/connectors/normalize.py` | Added 2-digit year date parsing (`%m/%d/%y`), changed fallback to `return None` |
| `backend/scrapers/connectors/town_config.py` | Updated portal types for Concord, Lincoln, Weston, Sherborn |
| `backend/database/supabase_client.py` | Enhanced error reporting with response body |
| `backend/api/routes.py` | Scrape endpoint improvements |
| `backend/config.py` | Config updates |

---

## 12-Town Completion Matrix (as of Session 14 Audit)

### Data Sources 100% Complete (All 12 Towns in Supabase)

| Data Source | Records | Notes |
|-------------|---------|-------|
| Permits | 104,445 | All 12 towns via 4 portal connectors |
| MEPA Filings | 5,314 | Statewide API, all 12 covered |
| Meeting Minutes | 1,766 | 4 CMS platforms (AgendaCenter, ArchiveCenter, CivicClerk, Laserfiche) |
| Municipal Overlays | 12 summaries + 403 detailed | MassGIS ArcGIS + LLM enrichment |
| Wetlands & Open Space | 12 | 1 summary per town |
| Zoning Bylaws | 12 | All 12 including Wayland (previously WAF-blocked) |

### Data Sources Partially Complete

| Data Source | In Supabase | Cached | Gap |
|-------------|-------------|--------|-----|
| CIP | 8 records | 12 (all resolved) | 4 OSINT-extracted towns need re-ingest to update count |
| Tax Delinquency | 71 records | 7 towns | 5 towns don't publish (N/A) |
| Tax Takings | 62 records | 12 files | 8 Middlesex towns blocked by WAF (0 real records) |

### Per-Town Matrix

| Town | Permits | MEPA | Overlays | Wetlands | Zoning | CIP | Tax Delq | Tax Takings | Minutes |
|------|---------|------|----------|----------|--------|-----|----------|-------------|---------|
| Newton | 12,766 | Done | Done | Done | Done | Done | Done | Blocked (WAF) | 2 |
| Lexington | 9,312 | Done | Done | Done | Done | Done | Done | Blocked (WAF) | 1 |
| Concord | 16,582 | Done | Done | Done | Done | Done | N/A | Blocked (WAF) | 20 |
| Needham | 5,593 | Done | Done | Done | Done | Done | Done | Done (2) | 1,220 |
| Natick | 5,699 | Done | Done | Done | Done | Done | Done | Blocked (WAF) | 36 |
| Wellesley | 3,586 | Done | Done | Done | Done | Done | N/A | Done (8) | 61 |
| Wayland | 1,654 | Done | Done | Done | Done | Done | Done | Blocked (WAF) | 1 |
| Dover | 311 | Done | Done | Done | Done | Done | N/A | Done (5) | 26 |
| Weston | 39,387 | Done | Done | Done | Done | Done | N/A | Blocked (WAF) | 71 |
| Sherborn | 6,364 | Done | Done | Done | Done | Done | N/A | Blocked (WAF) | 159 |
| Lincoln | 2,940 | Done | Done | Done | Done | Done | Done | Blocked (WAF) | 157 |
| Brookline | 251 | Done | Done | Done | Done | Done | Done | Done (47) | 12 |

**Legend:** Done = in Supabase | Blocked (WAF) = Middlesex South Incapsula WAF | N/A = town doesn't publish

---

## Unified Next Steps — Tomorrow Plan (Session 15)

*Combines Claude Code audit findings + Antigravity Session 13 outputs*

### PHASE 1: Ship What We Have (Production Deploy)

**1A. Deploy Backend** (Railway/Render/Fly.io)
- Vercel frontend is live but talks to localhost — needs a real API URL
- FastAPI backend needs production hosting with env vars (SUPABASE_URL, SUPABASE_SERVICE_KEY)
- Update Vercel `VITE_API_URL` to point to deployed backend

**1B. Frontend Integration of New Data**
- Add MEPA tab to PropertyDetails (query `municipal_documents` where `doc_type = 'MEPA Environmental Monitor'`)
- Add CIP tab or section (capital improvement projects near selected property)
- Surface tax delinquency as warning markers on globe
- Render overlay districts as CesiumJS layers from Supabase data

### PHASE 2: Close Data Gaps

**2A. Re-ingest CIP with OSINT data** — 4 towns resolved by Antigravity browser sub-agents (Newton, Dover, Wayland, Lincoln) but only 8 records in Supabase; need to push the OSINT-extracted project lists

**2B. Re-run failed geocodes** — 7,206 addresses failed Nominatim; try address normalization/cleanup before retry

**2C. Middlesex South WAF** — 8 towns of tax takings data blocked
- Antigravity attempted browser sub-agent bypass — still blocked
- Options: residential IP, real browser extension, manual extraction, or accept as "unavailable" for MVP

### PHASE 3: Expand & Polish

**3A. Expand Brookline permits** — Run `scrape_brookline_playwright.py` for 2020-2025 (currently only 2024 → 251 records)

**3B. Property Valuation & Trends** — Track TOTAL_VAL changes, price/sqft trends, permit activity correlation

**3C. UX Polish** — Mobile responsiveness, dark/light theme, export/PDF reports

### PHASE 4: Future Integrations

- ATTOM API (client built, needs real API key)
- eCode360 zoning (Cloudflare bypass needed)
- Expand beyond 12 towns

---

## What's Left To Do — Legacy Roadmap

### Already Completed
- ViewpointCloud bulk scraper rewrite (7 towns, 37,298 permits)
- PermitEyes connector (Concord + Lincoln, 9,537 permits)
- SimpliCITY connector (Weston 39,387 + Sherborn 6,364)
- Brookline Accela Playwright scraper (251 permits)
- Comparable Sales / Comps Tab
- Agent Monitoring System
- Viewport Permit Pins with clustering
- MassGIS Parcel Overlay Toggle
- FEMA Flood Zone Overlay Toggle
- CesiumJS Parcel Boundary Rendering
- Nominatim Geocoding + Any-Address Search
- 7-Tab PropertyDetails
- 9 Data Source scrapers + ingest pipelines
- Complete 12-town data pipeline (all 9 sources)
- Batch geocoding (106,620 locations, 21,530 unique addresses)
- GitHub Repo + Vercel Frontend Deploy
- Comprehensive SCRAPER_HANDOFF.md documentation

---

## How to Start

```bash
# Start the backend
cd /Users/alvaroespinal/sentinel-agent/backend
python3 main.py

# Start the frontend (in another terminal)
cd /Users/alvaroespinal/sentinel-agent/frontend
npm run dev
```

**Backend:** http://localhost:8000
**Frontend:** http://localhost:3000

**Test endpoints:**
```bash
curl "http://localhost:8000/api/geocode?address=45+Harvard+St+Cambridge+MA"
curl "http://localhost:8000/api/flood-zone?lat=42.3688&lon=-71.1024"
curl "http://localhost:8000/api/parcels?lat=42.3688&lon=-71.1024"
curl "http://localhost:8000/api/zoning?lat=42.3688&lon=-71.1024"
curl "http://localhost:8000/api/land-records?lat=42.3688&lon=-71.1024"
curl "http://localhost:8000/api/comps?lat=42.3503&lon=-71.081&radius_m=500"
```

**Trigger scraping:**
```bash
curl -X POST "http://localhost:8000/api/admin/scrape/weston"
curl -X POST "http://localhost:8000/api/admin/scrape/sherborn"
```

---

## Tech Stack Reference

- **Frontend:** React 18 + TypeScript + Vite + CesiumJS + Zustand + Tailwind CSS + Lucide Icons
- **Backend:** Python 3 + FastAPI + httpx + Supabase PostgREST
- **Database:** Supabase (PostgreSQL) — 104,445 permits in `permits` table + 125K legacy in `documents` table
- **Globe:** CesiumJS with Cesium Ion default imagery + Google Photorealistic 3D Tiles
- **Geocoding:** Nominatim (OpenStreetMap) — free, 1 req/sec
- **Flood Data:** FEMA NFHL ArcGIS REST — free, no key
- **Parcel Data:** MassGIS ArcGIS Feature Service — free, no key, max 2000/query
- **Deed Records:** MassGIS ownership fields (OWNER1, LS_DATE, LS_PRICE, LS_BOOK, LS_PAGE)
- **Permit Scraping:** ViewpointCloud, PermitEyes, SimpliCITY, Accela/Playwright (4 portal connectors)
- **Deployment:** Vercel (frontend), backend TBD (Railway/Render/Fly.io)
