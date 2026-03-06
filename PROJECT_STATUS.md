# Parcl Intelligence — Project Status

**Last Updated:** March 4, 2026 (Session 8)
**Session Summary:** Built PermitEyes + SimpliCITY permit scrapers for non-VPC towns, bringing total permits to 46,835 across 9 Massachusetts towns.

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

---

## Current Permit Database State

| Town | Permits | Portal System |
|------|---------|---------------|
| Newton | 11,690 | ViewpointCloud |
| Lexington | 9,189 | ViewpointCloud |
| Concord | 6,619 | PermitEyes |
| Needham | 5,487 | ViewpointCloud |
| Natick | 5,463 | ViewpointCloud |
| Wellesley | 3,557 | ViewpointCloud |
| Lincoln | 2,918 | PermitEyes |
| Wayland | 1,616 | ViewpointCloud |
| Dover | 296 | ViewpointCloud |
| **Total** | **46,835** | |

**Pending:** Weston (~12,730) and Sherborn (~3,654) via SimpliCITY connector (built, untested)
**Not Started:** Brookline via Accela Citizen Access (ASP.NET WebForms — hardest to scrape)

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

## What's Left To Do — Prioritized Roadmap

### Priority 1: Test SimpliCITY Scraping
- Restart backend, trigger Weston + Sherborn scrapes
- Verify data quality (permit numbers, addresses, dates)
- Expected: ~16,384 new permits

### Priority 2: Accela Connector for Brookline
- Brookline uses Accela Citizen Access (ASP.NET WebForms with ViewState)
- Hardest portal to scrape — requires session management, CSRF tokens, postback simulation
- ~21 permits currently in DB (from earlier Firecrawl attempt)

### Priority 3: Deploy Backend
- Railway/Render/Fly.io for production backend
- Vercel frontend already deployed (needs `VITE_API_URL` pointed to deployed backend)

### Priority 4: Batch Geocode Remaining Permits
- ~124.5K legacy permits still at 0,0 coords (Somerville/Cambridge from `documents` table)
- New `permits` table data has proper geocoding pipeline

### Priority 5: Property Valuation & Trends
- Track `TOTAL_VAL` changes across fiscal years
- Price per sqft trends for neighborhoods
- Permit activity correlation with value changes

### Priority 6: Polish & UX
- Mobile responsiveness
- Dark/light theme refinement
- Export/PDF report generation

### Already Completed
- ViewpointCloud bulk scraper rewrite (7 towns, 37,298 permits)
- PermitEyes connector (Concord + Lincoln, 9,537 permits)
- SimpliCITY connector (built, untested)
- Comparable Sales / Comps Tab
- Agent Monitoring System
- Viewport Permit Pins with clustering
- MassGIS Parcel Overlay Toggle
- FEMA Flood Zone Overlay Toggle
- CesiumJS Parcel Boundary Rendering
- Nominatim Geocoding + Any-Address Search
- 7-Tab PropertyDetails
- 6 Data Source Integrations
- GitHub Repo + Vercel Frontend Deploy

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
- **Database:** Supabase (PostgreSQL) — 46,835 permits in `permits` table + 125K legacy in `documents` table
- **Globe:** CesiumJS with Cesium Ion default imagery + Google Photorealistic 3D Tiles
- **Geocoding:** Nominatim (OpenStreetMap) — free, 1 req/sec
- **Flood Data:** FEMA NFHL ArcGIS REST — free, no key
- **Parcel Data:** MassGIS ArcGIS Feature Service — free, no key, max 2000/query
- **Deed Records:** MassGIS ownership fields (OWNER1, LS_DATE, LS_PRICE, LS_BOOK, LS_PAGE)
- **Permit Scraping:** ViewpointCloud, PermitEyes, SimpliCITY (3 portal connectors)
- **Deployment:** Vercel (frontend), backend TBD (Railway/Render/Fly.io)
