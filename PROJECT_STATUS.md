# Parcl Intelligence — Project Status

**Last Updated:** February 28, 2026 (Session 5)
**Session Summary:** Comparable Sales ("Comps") feature — new backend connector, API route, and 7th PropertyDetails tab showing nearby comparable sales with summary stats and individual comp cards.

---

## What Was Accomplished Today

### Part A: Three Critical Bug Fixes

#### 1. Globe Centering Fix
**Problem:** When zoomed all the way out, the globe sank to the bottom of the viewport.
**Root Cause:** Initial camera was at `(-10, 15, 20M meters)` with `pitch: -90` (pure nadir), causing the globe disc to render off-center.
**Fix:** Changed initial camera to center on Boston `(-71.06, 42.36, 15M meters)` with `pitch: -89`. Added `Camera.DEFAULT_VIEW_RECTANGLE = Rectangle.fromDegrees(-130, 20, -60, 55)` to center the home view on North America.
**File:** `frontend/src/components/Globe/CesiumGlobeInner.tsx`
**Status:** VERIFIED WORKING

#### 2. Fly-to-Ocean Fix (Null Island)
**Problem:** Selecting a Somerville address flew the camera to 0,0 in the Atlantic Ocean.
**Root Cause:** All 125,795 permits in Supabase have `latitude: 0, longitude: 0`. The store's `selectProperty()` called `flyTo(0, 0)`.
**Fix:**
- Added Nominatim geocoding service that converts addresses to coordinates
- Backend enriches search results with geocoded coordinates before returning them
- Store guards: `addTrackedListing`, `selectListing`, `selectProperty` all skip `flyTo` when coords are (0,0)

**Files:**
- `backend/scrapers/connectors/nominatim_geocoder.py` (NEW)
- `backend/api/routes.py` (added geocode endpoint + search enrichment)
- `frontend/src/store/useStore.ts` (0,0 guards)
**Status:** VERIFIED WORKING — Cambridge addresses fly to Cambridge

#### 3. Any-Address Search (Google Maps Behavior)
**Problem:** Could only search addresses that existed in the permit database. No results for other addresses.
**Fix:** Added geocode fallback in SearchBar. When no permits match the query, it calls `geocodeAddress(query)` via Nominatim and creates a virtual location pin result. Works for ANY address worldwide.
**Files:**
- `frontend/src/components/RealEstate/SearchBar.tsx` (geocode fallback)
- `frontend/src/services/api.ts` (added `geocodeAddress()` function)
- `backend/api/routes.py` (added `GET /api/geocode` endpoint)
**Status:** VERIFIED WORKING — "1600 Pennsylvania Ave Washington DC" finds and flies to the White House

### Part B: Four Data Source Integrations

#### 4. FEMA Flood Zones (ArcGIS REST API)
**Connector:** `backend/scrapers/connectors/fema_flood.py`
**Endpoint:** `GET /api/flood-zone?lat=42.36&lon=-71.06`
**API:** `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query`
**Returns:** `{flood_zone, zone_subtype, in_sfha, base_flood_elevation, risk_level, description}`
**Cost:** Free, no API key needed
**Status:** VERIFIED WORKING — Cambridge returns "Zone X, Minimal Risk"

#### 5. MassGIS Property Tax Parcels (ArcGIS Feature Service)
**Connector:** `backend/scrapers/connectors/massgis_parcels.py`
**Endpoint:** `GET /api/parcels?lat=42.36&lon=-71.06`
**API:** `https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/L3_TAXPAR_POLY_ASSESS_gdb/FeatureServer/0/query`
**Returns:** `{loc_id, site_addr, city, owner, last_sale_date, last_sale_price, building_value, land_value, total_value, use_code, lot_size_acres, year_built, building_area_sqft, units, style, geometry}`
**Cost:** Free, no API key, max 2000 records/query
**Status:** VERIFIED WORKING — Returns full parcel data with polygon geometry

#### 6. Zoning Classification (from MassGIS USE_CODE)
**Connector:** `backend/scrapers/connectors/zoning_atlas.py`
**Endpoint:** `GET /api/zoning?lat=42.36&lon=-71.06`
**Data Source:** MassGIS Parcels USE_CODE field, mapped to MA DOR Property Type Classification Codes
**Why not National Zoning Atlas:** NZA uses proprietary vector tiles at `tiles.zoningatlas1.org`, has no public REST API, and S3 data downloads are access-restricted (403).
**Returns:** `{zone_code, zone_name, jurisdiction, allowed_uses[], min_lot_size_sqft, description}`
**Status:** VERIFIED WORKING — USE-199 -> "Residential", allowed uses shown as badges

#### 7. Ownership & Deed Records (MassGIS)
**Connector:** `backend/scrapers/connectors/mass_land_records.py`
**Endpoint:** `GET /api/land-records?lat=42.36&lon=-71.10`
**Data Source:** MassGIS Property Tax Parcels (same ArcGIS Feature Service as parcel data)
**Fields Used:** `OWNER1, OWN_ADDR, OWN_CITY, OWN_STATE, OWN_ZIP, LS_DATE, LS_PRICE, LS_BOOK, LS_PAGE, TOTAL_VAL, BLDG_VAL, LAND_VAL`
**Returns:** `{ownership: {owner, mailing_address, ...}, records: [{doc_type, grantee, recording_date, book_page, consideration}], total}`
**Why not masslandrecords.com:** Site actively blocks automated access with IP-level bot detection. Tested Feb 28 — Playwright gets blocked after first `__doPostBack` request.
**Status:** VERIFIED WORKING — Shows current owner, mailing address, assessed values, last sale date/price, registry book/page

### Part C: Frontend Integration

#### 8. PropertyDetails Enrichment UI (6 tabs)
**File:** `frontend/src/components/RealEstate/PropertyDetails.tsx`
**Tabs:**
1. **Permits** — Nearby building permits from Supabase
2. **Parcel** — Owner, assessed values, lot size, year built, building area, use code (from MassGIS)
3. **Flood** — Zone designation with color-coded risk level, SFHA status, BFE (from FEMA)
4. **Zoning** — Zone code/name, allowed uses as badges, min lot size, jurisdiction (from MassGIS USE_CODE)
5. **Deeds** — Ownership chain timeline with doc type, grantor/grantee, date, consideration (from Mass Land Records)
6. **Agents** — Monitoring agent status for tracked listings

**Key Design:** Each tab lazy-loads data only when selected. Works for both tracked listings (via `listingId`) AND search results (via `selectedProperty` from store).

**File:** `frontend/src/components/RealEstate/RightPanel.tsx`
**Change:** Shows PropertyDetails when either `selectedListingId` or `selectedProperty` is set.

### Part D: Infrastructure Fixes

#### 9. CORS Fix
**Problem:** Frontend at `127.0.0.1:3000` couldn't reach backend at `127.0.0.1:8000` due to CORS.
**Fix:** Added `http://127.0.0.1:3000` and `http://127.0.0.1:5173` to `allow_origins` in `backend/main.py`.

#### 10. Vite IPv4 Binding
**Problem:** Vite dev server bound to IPv6 only, preview browser uses IPv4.
**Fix:** Added `host: true` to `server` config in `frontend/vite.config.ts`.

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
  → DEFAULT_VIEW_RECTANGLE for US
                                              GET /api/land-records?address=...&city=...
useStore.ts (Zustand)                           → Playwright scraper → masslandrecords.com
  → 0,0 guards on all flyTo actions
  → selectedProperty for search results       GET /api/permits/search
  → selectedListingId for tracked listings      → Supabase full-text search
```

---

## Database State

- **Supabase table:** `documents` — 125,795 permits
- **Towns with data:** Somerville (64,521), Cambridge (61,253), Brookline (21)
- **Known issue:** All permits have `address: ""` and `latitude: 0, longitude: 0`. Address info is embedded in the `description` field as "Address: 122 Heath St". Backend parses this and geocodes on-the-fly.
- **Supabase URL:** `https://tkexrzohviadsgolmupa.supabase.co`

---

## Files Created (All Sessions)

| File | Purpose |
|------|---------|
| `backend/scrapers/connectors/nominatim_geocoder.py` | Nominatim geocoding with cache + rate limiting |
| `backend/scrapers/connectors/fema_flood.py` | FEMA NFHL ArcGIS REST client |
| `backend/scrapers/connectors/massgis_parcels.py` | MassGIS Parcel Feature Service client |
| `backend/scrapers/connectors/zoning_atlas.py` | Zoning from MassGIS USE_CODE mapping |
| `backend/scrapers/connectors/mass_land_records.py` | MassGIS ownership data (was Playwright, rewritten) |
| `backend/scrapers/connectors/massgis_comps.py` | **NEW (Session 5)** — Comparable sales connector (envelope query, Haversine, $/sqft) |
| `backend/scripts/batch_geocode_permits.py` | **NEW (Session 3)** — Batch geocode 125K permits CLI script |

## Files Modified (All Sessions)

| File | Changes |
|------|---------|
| `frontend/src/components/Globe/CesiumGlobeInner.tsx` | Globe centering + FEMA flood overlay + parcel boundary rendering + MassGIS parcel overlay (Session 1+3+4) |
| `frontend/src/components/UI/LeftSidebar.tsx` | **Session 4:** Added "Parcels (MA)" to DATA LAYERS |
| `frontend/src/components/RealEstate/SearchBar.tsx` | Geocode fallback for any address |
| `frontend/src/components/RealEstate/PropertyDetails.tsx` | Full rewrite — 7 enrichment tabs (added Comps, Session 5), works for search + tracked listings |
| `frontend/src/components/RealEstate/RightPanel.tsx` | Shows PropertyDetails for both selectedListingId and selectedProperty |
| `frontend/src/services/api.ts` | Added geocodeAddress, getFloodZone, getParcelInfo, getZoning, getLandRecords, getComps (Session 5) |
| `frontend/src/store/useStore.ts` | 0,0 coordinate guards + showParcels/toggleParcels (Session 1+4) |
| `frontend/vite.config.ts` | Added `host: true` for IPv4 binding |
| `backend/api/routes.py` | Added 6 new endpoints (geocode, flood-zone, parcels, zoning, land-records, comps) + geocode enrichment in search |
| `backend/main.py` | Added 127.0.0.1 to CORS origins |
| `backend/database/supabase_client.py` | **Session 3:** Added `update()` method for PostgREST PATCH |

---

## What Was Accomplished Today (Session 3)

### 11. FEMA Flood Zone Globe Overlay
**Feature:** Toggle FEMA NFHL flood zones as a semi-transparent overlay on the CesiumJS globe.
**Implementation:** `ArcGisMapServerImageryProvider.fromUrl("https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer")` with alpha 0.45. Toggled by the "Flood Zones" switch in DATA LAYERS sidebar.
**File:** `frontend/src/components/Globe/CesiumGlobeInner.tsx` (useEffect on `showFloodZones`)
**Status:** VERIFIED WORKING — Toggle on shows colored flood zones on globe, toggle off removes them.

### 12. CesiumJS Parcel Boundary Rendering
**Feature:** When a property is selected, render its MassGIS parcel boundary on the 3D globe.
**Challenge:** Google Photorealistic 3D Tiles block standard CesiumJS entities (polygons, clamped polylines, ClassificationType.BOTH all invisible).
**Solution:** Cyan point markers at each parcel corner with `disableDepthTestDistance: Number.POSITIVE_INFINITY` (always visible through 3D tiles) + polyline with `depthFailMaterial` (renders even when occluded by 3D mesh).
**File:** `frontend/src/components/Globe/CesiumGlobeInner.tsx` (inline in main sync effect)
**Status:** VERIFIED WORKING — Cyan markers and outline visible on Google 3D Tiles at 345 Harvard St, Cambridge.

### 13. Batch Permit Geocoding Script
**Feature:** Standalone Python script to geocode all 125K permits (all at 0,0) by parsing addresses from content fields and calling Nominatim.
**Key insight:** The 125K Somerville/Cambridge permits have NO `document_locations` rows — the script must INSERT new rows, not update existing ones.
**Data format:** Content field = `"Type: Building | Address: 516 Somerville Ave | Description: ... | Cost: $627.00"`
**Approach:** 3-phase: (1) Scan & deduplicate addresses, (2) Geocode unique addresses via Nominatim with persistent disk cache, (3) Batch-insert `document_locations` rows.
**Files:**
- `backend/scripts/batch_geocode_permits.py` (NEW — standalone CLI script)
- `backend/database/supabase_client.py` (added `update()` method)
**Test Results:**
- 500 Somerville permits → 350 unique addresses → 341 geocoded (97.4%) → 489 rows inserted
- Cache persists to `data_cache/geocode_cache.json` (350 entries after test)
- 548 total `document_locations` rows now in Supabase (was 9)
- Resume from checkpoint supported for interrupted runs
**Status:** VERIFIED WORKING — Searched "174 Hudson St Somerville", globe flew to correct location, all 6 tabs populated.

## What Was Accomplished (Session 4)

### 14. MassGIS Parcel Boundaries Globe Overlay Toggle
**Feature:** Full Massachusetts parcel boundary map overlay on the CesiumJS globe, toggled via "Parcels (MA)" in the DATA LAYERS sidebar. Same pattern as the existing FEMA Flood Zones toggle.
**Tile Service:** `https://tiles.arcgis.com/tiles/hGdibHYSPO59RG1h/arcgis/rest/services/MassGIS_Level3_Parcels/MapServer` — pre-rendered cached tiles, zoom levels 15-20, free, no auth.
**Implementation:** `ArcGisMapServerImageryProvider.fromUrl()` with alpha 0.55. Parcel boundary lines appear when zoomed to neighborhood/street level over Massachusetts.
**Files Modified:**
- `frontend/src/store/useStore.ts` — Added `showParcels: boolean` state + `toggleParcels()` action
- `frontend/src/components/UI/LeftSidebar.tsx` — Added "Parcels (MA)" entry with amber `Layers` icon to DATA LAYERS
- `frontend/src/components/Globe/CesiumGlobeInner.tsx` — Added `parcelLayerRef` + useEffect for MassGIS tile overlay
**Status:** VERIFIED WORKING — Toggle activates overlay, console confirms "MassGIS Parcel Boundaries overlay added", tiles load at street-level zoom.

## What Was Accomplished (Session 5)

### 15. Comparable Sales Feature (Full Stack)
**Feature:** 7th "Comps" tab in PropertyDetails showing nearby comparable sales with summary statistics and individual comp cards.
**Backend Connector:** `backend/scrapers/connectors/massgis_comps.py` (NEW)
- Queries MassGIS ArcGIS Feature Service with envelope geometry (bounding box)
- WHERE clause: `LS_PRICE > 1000 AND LS_DATE > '19000101'` (filters nominal transfers and null dates)
- Haversine distance from subject to each comp's polygon centroid
- $/sqft = `LS_PRICE / BLD_AREA` (minimum 100 sqft to avoid parking spaces)
- Returns sorted comps (by distance) + summary stats (median $/sqft, avg price, price range, date range)

**Backend Route:** `GET /api/comps?lat=&lon=&radius_m=500&use_code=&subject_loc_id=&max_results=20`
**Frontend API:** `getComps()` function with `CompSale`, `CompsSummary`, `CompsResponse` types
**Frontend UI:** Comps tab with TrendingUp icon — summary card (4-cell grid) + scrollable comp list
**Key Data Fixes:**
- `LS_DATE` is a string field (not int) in ArcGIS — must use string comparison in WHERE
- `LS_PRICE > 1000` to exclude $1/$9 nominal transfers
- `BLD_AREA > 100` to exclude parking spaces/storage units with area=1
**Status:** VERIFIED WORKING — 205 Newbury St Boston shows $2,182 median $/sqft, $2,635,850 avg sale price, 20 nearby comps

### 16. Agent Monitoring System (Already Built)
**Finding:** Investigated agent monitoring system (originally Priority 2) and discovered it was already fully implemented in prior sessions:
- Backend: execution loop (every 60s), WebSocket `agent_finding` broadcasts, full CRUD endpoints
- Frontend: Intel Feed, WebSocket handler, auto-agent creation on tracked listings
**Status:** No work needed — already functional

### 17. Somerville Batch Geocode (In Progress)
**Status:** Running in background (PID active), 1,100/13,748 unique addresses geocoded (~8%), ~3.5 hours remaining

---

## What's Left To Do — Prioritized Roadmap

### Priority 1: Geocoded Permit Map Pins
Once all permits are geocoded, render them as clustered map pins on the CesiumJS globe:
- Use Cesium clustering with `EntityCluster` or `DataSourceDisplay`
- Click a cluster → expand to individual permit pins
- Click a pin → open PropertyDetails for that address

### Priority 5: Property Valuation & Trends
- Track `TOTAL_VAL` changes across fiscal years from MassGIS data
- Price per sqft trends for neighborhoods
- Permit activity correlation with value changes

### Priority 6: Polish & UX
- National Zoning Atlas integration (monitor for future API availability)
- Mobile responsiveness for the sidebar/panels
- Dark/light theme refinement
- Export/PDF report generation for properties

### Already Completed (Reference)
- ~~Comparable Sales / Comps Tab~~ (Session 5)
- ~~Agent Monitoring System~~ (already built, confirmed Session 5)
- ~~Batch Geocode — Somerville running~~ (Session 5, in progress)
- ~~Mass Land Records → MassGIS Ownership~~ (Session 2)
- ~~Permit Batch Geocoding Script~~ (Session 3)
- ~~MassGIS Parcel Overlay Toggle~~ (Session 4)
- ~~FEMA Flood Zone Overlay Toggle~~ (Session 3)
- ~~CesiumJS Parcel Boundary Rendering~~ (Session 3)
- ~~Nominatim Geocoding + Any-Address Search~~ (Session 1)
- ~~6-Tab PropertyDetails~~ (Session 2)
- ~~4 Data Source Integrations~~ (Session 2)

---

## How to Start Tomorrow

```bash
# Start the backend
cd /Users/alvaroespinal/sentinel-agent/backend
python3 main.py

# Start the frontend (in another terminal)
cd /Users/alvaroespinal/sentinel-agent/frontend
npm run dev

# Or use Claude Preview:
# Backend: preview_start name="backend"
# Frontend: preview_start name="frontend"
```

**Backend runs on:** http://localhost:8000
**Frontend runs on:** http://localhost:3000

**Test endpoints:**
```bash
curl "http://localhost:8000/api/geocode?address=45+Harvard+St+Cambridge+MA"
curl "http://localhost:8000/api/flood-zone?lat=42.3688&lon=-71.1024"
curl "http://localhost:8000/api/parcels?lat=42.3688&lon=-71.1024"
curl "http://localhost:8000/api/zoning?lat=42.3688&lon=-71.1024"
curl "http://localhost:8000/api/land-records?lat=42.3688&lon=-71.1024"
curl "http://localhost:8000/api/comps?lat=42.3503&lon=-71.081&radius_m=500"
```

---

## Tech Stack Reference

- **Frontend:** React 18 + TypeScript + Vite + CesiumJS + Zustand + Tailwind CSS + Lucide Icons
- **Backend:** Python 3 + FastAPI + httpx + Supabase PostgREST
- **Database:** Supabase (PostgreSQL) — 125K permits in `documents` table
- **Globe:** CesiumJS with Cesium Ion default imagery
- **Geocoding:** Nominatim (OpenStreetMap) — free, 1 req/sec
- **Flood Data:** FEMA NFHL ArcGIS REST — free, no key
- **Parcel Data:** MassGIS ArcGIS Feature Service — free, no key, max 2000/query
- **Deed Records:** MassGIS ownership fields (OWNER1, LS_DATE, LS_PRICE, LS_BOOK, LS_PAGE)
- **Batch Geocoder:** `scripts/batch_geocode_permits.py` — 3-phase: scan → geocode → insert (persistent cache)
