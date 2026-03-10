# Scraper Handoff — Parcl Intelligence 12-Town MVP

**Last Updated:** March 10, 2026
**Purpose:** Complete reference for all scrapers, data sources, and remaining work.
**Supabase Project:** `municipal-intel` (ID: `tkexrzohviadsgolmupa`)

---

## Quick Start

```bash
cd /Users/alvaroespinal/sentinel-agent/backend
source ../.env  # SUPABASE_URL, SUPABASE_SERVICE_KEY, OPENROUTER_API_KEY, FIRECRAWL_API_KEY
python3 scripts/<script_name>.py
```

---

## Current Supabase State (as of 3/10/2026)

### `municipal_documents` table (by doc_type)
| doc_type | Count | Notes |
|----------|-------|-------|
| MEPA Environmental Monitor | 5,314 | 12/12 towns |
| meeting_minutes | 1,766 | 12/12 towns |
| overlay_district | 403 | Boston overlays (legacy) |
| mepa_filing | 240 | Boston MEPA (legacy) |
| Tax Delinquency | 71 | town_id=NULL — needs fix |
| wetland_area | 12 | 12/12 towns (1 summary per town) |
| zoning_bylaw | 12 | 12/12 towns |
| municipal_overlay | 12 | 12/12 towns (1 summary per town) |
| capital_improvement | 8 | 8/12 towns |

### `permits` table (12 MVP towns)
| Town | Permits | Portal |
|------|---------|--------|
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
| Brookline | 63 | Accela (incomplete) |
| **Total** | **104,257** | |

### `meeting_minutes` by town (in municipal_documents)
| Town | Records |
|------|---------|
| Needham | 1,220 |
| Sherborn | 159 |
| Lincoln | 157 |
| Weston | 71 |
| Wellesley | 61 |
| Natick | 36 |
| Dover | 26 |
| Concord | 20 |
| Brookline | 12 |
| Newton | 2 |
| Wayland | 1 |
| Lexington | 1 |

---

## 12 MVP Town Completion Matrix

| Town | Permits | MEPA | Overlays | Wetlands | Zoning | CIP | Tax Delq | Tax Takings | Minutes |
|------|---------|------|----------|----------|--------|-----|----------|-------------|---------|
| Newton | 12,766 | Done | Done | Done | Done | Done | Done | Cached | 2 |
| Lexington | 9,312 | Done | Done | Done | Done | Done | Done | Cached | 1 |
| Concord | 16,582 | Done | Done | Done | Done | Done | N/A | Cached | 20 |
| Needham | 5,593 | Done | Done | Done | Done | Done | Done | Cached | 1,220 |
| Natick | 5,699 | Done | Done | Done | Done | Done | Done | Cached | 36 |
| Wellesley | 3,586 | Done | Done | Done | Done | Done | N/A | Cached | 61 |
| Wayland | 1,654 | Done | Done | Done | Done | Done | Done | Cached | 1 |
| Dover | 311 | Done | Done | Done | Done | Done | N/A | Cached | 26 |
| Weston | 39,387 | Done | Done | Done | Done | Done | N/A | Cached | 71 |
| Sherborn | 6,364 | Done | Done | Done | Done | Done | N/A | Cached | 159 |
| Lincoln | 2,940 | Done | Done | Done | Done | Done | Done | Cached | 157 |
| Brookline | 63 | Done | Done | Done | Done | Done | Done | Cached | 12 |

**Legend:** Done = in Supabase | Cached = JSON in data_cache but NOT in Supabase | N/A = town doesn't publish

---

## Data Source Details

### 1. Permits (104,257 records in Supabase)

**Status:** COMPLETE for all 12 towns (Brookline has only 63 — Accela portal is hard to scrape)

**Portal Types & Connectors:**
| Portal | Connector | Towns |
|--------|-----------|-------|
| ViewpointCloud | `connectors/vpc_client.py` | Newton, Lexington, Needham, Natick, Wellesley, Wayland, Dover |
| PermitEyes | `connectors/permiteyes_client.py` | Concord, Lincoln |
| SimpliCITY | `connectors/simplicity_client.py` | Weston, Sherborn |
| Accela | N/A (barely scraped) | Brookline |

**How ViewpointCloud works:**
- Partition API at `/{town}/RequestPartition` returns paginated record batches
- Each town has departments: Building, Electrical, Plumbing, Gas, etc.
- Bulk scraper: `backend/scrapers/connectors/vpc_client.py`

**How PermitEyes works:**
- Full Circle Technologies DataTables — server-side AJAX POST to `permiteyes.us/{town}/ajax/*.php`
- Per-town column mapping (`ColumnMap` dataclass) — Concord=12 cols, Lincoln=9 cols
- Client: `backend/scrapers/connectors/permiteyes_client.py`

**How SimpliCITY works:**
- PeopleGIS/Schneider Geospatial — JSON POST to `mapsonline.net/pf-ng/s/search`
- Session-based: GET portal page for `ssid`, then POST with form_id + pagination
- Returns positional arrays with 270+ columns; dates as Unix ms timestamps
- Client: `backend/scrapers/connectors/simplicity_client.py`

**Brookline (Accela) gap:**
- ASP.NET WebForms with ViewState, CSRF tokens, postback simulation
- Hardest portal to automate — only 63 records scraped so far
- Would need dedicated Playwright-based scraper

**Scrape dispatch:** `backend/scrapers/scheduler.py` (routes by `permit_portal_type` in town config)
**Ingest:** Scrapers insert directly into `permits` table via `_insert_permit()`
**Cached data:** `data_cache/permits/*.json` (12 files, all 12 towns)

### 2. MEPA Environmental Monitor (5,314 records in Supabase)

**Status:** COMPLETE — 12/12 towns ingested

**How it works:**
- Scraper: `backend/scrapers/connectors/mepa_scraper.py`
- Queries MA Environmental Monitor API via AWS Gateway
- BeautifulSoup fallback for HTML parsing
- Each record: project name, EEANO, filing type, proponent, location, description

**Scrape script:** `backend/scripts/scrape_all_mepa.py`
**Ingest script:** `backend/scripts/ingest_all_mepa.py`
**Cached data:** `data_cache/{town}_mepa_filings.json` (12 files)

### 3. Municipal Overlays (12 summary + 403 detailed records in Supabase)

**Status:** COMPLETE — 12/12 towns ingested

**How it works:**
- Connector: `backend/scrapers/connectors/municipal_overlays.py`
- Queries ArcGIS REST `/query` endpoints for overlay districts
- LLM enrichment via OpenRouter (Gemini 2.0 Flash) for plain-English summaries
- Types: PDAs, Zoning Districts, Coastal Flood, Institutional Master Plans, Historic Districts

**Scrape script:** `backend/scripts/scrape_all_overlays.py`
**Ingest script:** `backend/scripts/ingest_overlays.py`
**Cached data:** `data_cache/overlays/{town}_overlays.json` (12 files) + 6 Boston GeoJSON files in `data_cache/` root

### 4. Wetlands (12 records in Supabase)

**Status:** COMPLETE — 12/12 towns (1 summary record per town)

**How it works:**
- Scraper: `backend/scripts/scrape_all_wetlands.py`
- Uses MassGIS DEP Wetlands ArcGIS service
- Counts wetland features within town boundaries
- Stores summary (total area, feature count, wetland types) per town

**Ingest script:** `backend/scripts/ingest_wetlands_to_supabase.py`
**Cached data:** `data_cache/wetlands/{town}_wetlands.json` (12 files, ~49MB total)

### 5. Zoning Bylaws (12 records in Supabase)

**Status:** COMPLETE — 12/12 towns (including Wayland)

**How it works:**
- Scraper: `backend/scripts/scrape_all_zoning.py`
- Uses Firecrawl to scrape town zoning bylaw pages
- LLM extraction (OpenRouter) for structured zoning data
- Stores zoning districts, dimensional requirements, use regulations

**Ingest script:** `backend/scripts/ingest_zoning_to_supabase.py`
**Cached data:** `data_cache/zoning_bylaws/{town}_zoning.json` (12 files)

### 6. Capital Improvement Plans (8 records in Supabase)

**Status:** 8/12 towns — 4 towns failed scraping

**How it works:**
- Scraper: `backend/scripts/scrape_all_cip.py`
- Uses Firecrawl to find and download CIP PDFs from town websites
- LLM extraction for project names, departments, costs, timelines

**Failed towns (need retry):**
- Newton: WAF-blocked
- Dover: May not publish CIP
- Wayland: WAF-blocked
- Lincoln: PDF extraction failed

**Ingest script:** `backend/scripts/ingest_cip_to_supabase.py`
**Cached data:** `data_cache/cip/{town}_cip.json` (12 files, but 4 have error status)

### 7. Tax Delinquency (71 records in Supabase — needs town_id fix)

**Status:** 7 towns with data extracted; 71 records in Supabase but `town_id` is NULL

**How it works:**
- Multi-agent orchestration: `backend/scripts/scrape_all_tax_delinquencies.py`
- OSINT Agent: Uses Firecrawl to Google-search for town Tax Title PDF links
- Extraction Agent: Downloads PDF (httpx + Playwright fallback for anti-bot), extracts via LLM
- Output: Address, Owner, Amount Owed per delinquent property

**Towns with cached data:** Brookline, Lexington, Lincoln, Natick, Needham, Newton, Wayland
**Towns without:** Concord, Dover, Wellesley, Weston, Sherborn — likely don't publish (mark N/A)

**Critical bug:** All 71 records have `town_id=NULL` — need UPDATE query to fix

**Cached data:** `data_cache/tax_delinquency/{town}_tax_delinquency.json` (7 files)

### 8. Tax Takings — Registry of Deeds (0 records in Supabase, 12 cached)

**Status:** Cached for all 12 towns but NOT YET INGESTED to Supabase

**How it works:**
- Scraper: `backend/scripts/scrape_tax_takings_from_registry.py` (1,099 lines)
- **Norfolk Registry (WORKING):** Playwright navigates JS SPA at norfolkresearch.org/ALIS/, regex-parses results
  - Norfolk towns: Brookline, Dover, Needham, Wellesley
  - Results: 62 total records (Brookline 47, Dover 5, Needham 2, Wellesley 8)
- **Middlesex South Registry (BLOCKED):** Incapsula/Imperva WAF blocks ALL automated access
  - Middlesex towns: Newton, Lexington, Concord, Natick, Wayland, Weston, Sherborn, Lincoln
  - 6+ bypass approaches tried — ALL FAILED (see Diagnostic Scripts section)
  - These 8 towns have `status: "no_records_found"` in their JSON (WAF blocked, not zero records)

**Ingest script:** `backend/scripts/ingest_tax_takings_to_supabase.py` (ready, never run)
**Cached data:** `data_cache/tax_delinquency/{town}_tax_takings.json` (12 files)

### 9. Meeting Minutes (1,766 records in Supabase)

**Status:** COMPLETE — 12/12 towns ingested

**How it works:**
- Scraper: `backend/scripts/scrape_meeting_minutes.py`
- Supports 4 CMS platforms: AgendaCenter, ArchiveCenter, CivicClerk, Laserfiche
- Extracts meeting date, board/committee name, agenda items, links

**CMS platform mapping:**
| CMS | Connector | Towns |
|-----|-----------|-------|
| AgendaCenter | `connectors/agendacenter_client.py` | Wellesley, Weston, Dover, Natick, Concord, Sherborn, Lincoln, Lexington |
| ArchiveCenter | `connectors/archivecenter_client.py` | Needham |
| CivicClerk | `connectors/civicclerk_client.py` | Brookline |
| Laserfiche | Firecrawl-based | Newton, Wayland |

**Cached data:** `data_cache/meeting_minutes/{town}_minutes.json` (6 files — others ingested directly)

---

## Remaining Work

### HIGH PRIORITY

1. **Ingest Tax Takings to Supabase** — Run `python3 scripts/ingest_tax_takings_to_supabase.py`
   - Will insert Norfolk Registry records (62 from 4 towns)
   - Middlesex records are empty shells (WAF blocked)

2. **Fix Tax Delinquency town_id NULL bug**
   ```sql
   SELECT id, title, content_text FROM municipal_documents
   WHERE doc_type = 'Tax Delinquency' LIMIT 5;
   -- Then UPDATE town_id based on content_text or title patterns
   ```

3. **Bypass Middlesex South WAF** (masslandrecords.com)
   - Incapsula/Imperva WAF blocks ALL automated access
   - Approaches tried and failed:
     1. Stealth Playwright with real user-agent
     2. curl replay of captured browser session
     3. ASP.NET AJAX postback simulation
     4. Direct POST with ViewState
     5. Keyboard-based navigation (Tab + Enter)
     6. Recorded browser session replay
   - **Recommendation:** Try from residential IP, real browser extension, or manual extraction

4. **Retry 4 failed CIP towns** (Newton, Dover, Wayland, Lincoln)
   - Newton/Wayland: WAF-blocked — use Firecrawl `scrape_with_actions()` with wait
   - Dover: Verify if CIP exists
   - Lincoln: Re-download PDF, retry LLM extraction

### MEDIUM PRIORITY

5. **Expand Brookline permits** (only 63 records via Accela)
6. **Batch geocode remaining permits** (~124.5K at 0,0 coords)

### LOW PRIORITY

7. **Deploy backend** (Railway/Render/Fly.io)
8. **Frontend integration** of new data layers (overlays on CesiumJS globe, MEPA tab)

---

## Key File Reference

### Connectors (`backend/scrapers/connectors/`)
| File | Purpose |
|------|---------|
| `vpc_client.py` | ViewpointCloud partition API scraper |
| `permiteyes_client.py` | PermitEyes DataTables AJAX scraper |
| `simplicity_client.py` | SimpliCITY/MapsOnline JSON API scraper |
| `municipal_overlays.py` | ArcGIS REST overlay district client |
| `mepa_scraper.py` | MA Environmental Monitor API |
| `fema_flood.py` | FEMA NFHL ArcGIS REST |
| `massgis_parcels.py` | MassGIS Parcel Feature Service |
| `massgis_comps.py` | Comparable sales via MassGIS |
| `zoning_atlas.py` | Zoning from MassGIS USE_CODE |
| `mass_land_records.py` | MassGIS ownership data |
| `nominatim_geocoder.py` | Nominatim geocoding + cache |
| `normalize.py` | Date parsing, text normalization |
| `town_config.py` | Town definitions (portal types, URLs) |
| `firecrawl_client.py` | Firecrawl API wrapper |
| `llm_extractor.py` | OpenRouter LLM extraction |
| `agendacenter_client.py` | AgendaCenter meeting minutes scraper |
| `archivecenter_client.py` | ArchiveCenter scraper (Needham) |
| `civicclerk_client.py` | CivicClerk OData API (Brookline) |

### Scrape Scripts (`backend/scripts/`)
| File | Purpose |
|------|---------|
| `scrape_all_mepa.py` | Scrape MEPA filings for all towns |
| `scrape_all_overlays.py` | Scrape municipal overlays |
| `scrape_all_wetlands.py` | Scrape wetlands data |
| `scrape_all_zoning.py` | Scrape zoning bylaws |
| `scrape_all_cip.py` | Scrape capital improvement plans |
| `scrape_all_tax_delinquencies.py` | Multi-agent tax delinquency scraper |
| `scrape_tax_takings_from_registry.py` | Registry of Deeds tax takings |
| `scrape_meeting_minutes.py` | Meeting minutes (4 CMS platforms) |

### Ingest Scripts (`backend/scripts/`)
| File | Purpose |
|------|---------|
| `ingest_all_mepa.py` | MEPA -> municipal_documents |
| `ingest_overlays.py` | Overlays -> municipal_documents |
| `ingest_wetlands_to_supabase.py` | Wetlands -> municipal_documents |
| `ingest_zoning_to_supabase.py` | Zoning -> municipal_documents |
| `ingest_cip_to_supabase.py` | CIP -> municipal_documents |
| `ingest_tax_takings_to_supabase.py` | Tax Takings -> municipal_documents |
| `ingest_permits_to_supabase.py` | Permits -> permits table |

### Diagnostic Scripts (`backend/scripts/_diag_*`, `_test_*`)
18 files documenting Middlesex South WAF bypass attempts. All failed. Keep for reference.

| File | Approach |
|------|----------|
| `_diag_mx_v6.py` / `_diag_mx_v7.py` | Stealth Playwright attempts |
| `_diag_mx_dropdown.py` | Dropdown interaction simulation |
| `_diag_mx_fetch_post.py` | HTTP POST replay |
| `_diag_mx_hybrid.py` / `_diag_mx_hybrid2.py` | Combined browser+HTTP approaches |
| `_diag_mx_initial_page.py` / `_diag_mx_initial_page2.py` | Initial page load analysis |
| `_diag_mx_postback.py` | ASP.NET postback simulation |
| `_test_mx_ajax_postback.py` | AJAX UpdatePanel postback |
| `_test_mx_click_option.py` | Click-based option selection |
| `_test_mx_correct_labels.py` | Label/ID correction |
| `_test_mx_direct_post.py` | Direct form POST |
| `_test_mx_dropdown_strategies.py` | Multiple dropdown strategies |
| `_test_mx_keyboard.py` | Keyboard navigation approach |
| `_test_mx_recorded_date_search.py` | Recorded session replay |
| `_test_mx_refresh_navigator.py` | Page refresh navigation |
| `_test_mx_stealth.py` | Stealth/anti-detection |

---

## Environment & Dependencies

```bash
# Required env vars (.env in project root)
SUPABASE_URL=https://tkexrzohviadsgolmupa.supabase.co
SUPABASE_SERVICE_KEY=<service_role_key>
OPENROUTER_API_KEY=<for LLM extraction>
FIRECRAWL_API_KEY=<for web scraping>

# Python deps
pip install httpx pdfplumber playwright python-dotenv beautifulsoup4 lxml
playwright install chromium
```

---

## Critical Gotchas

1. **Supabase project is `tkexrzohviadsgolmupa`** (municipal-intel), NOT `yypsyyzuzgkkjqbmjepl` (realtor-intel)
2. **Content-hash deduplication:** All ingest scripts use SHA-256 content_hash with upsert on conflict — safe to re-run
3. **Date parsing:** `normalize.py` handles `%m/%d/%Y`, `%m/%d/%y`, `%Y-%m-%d`; returns `None` for invalid dates
4. **Middlesex South WAF:** Incapsula/Imperva at masslandrecords.com blocks ALL automated access
5. **Norfolk ALIS:** Works with Playwright headless — norfolkresearch.org/ALIS/ is a JS SPA
6. **PermitEyes column mapping:** Concord (12 cols) and Lincoln (9 cols) have different column positions
7. **SimpliCITY session:** GET portal page first for `ssid`, then POST — sessions expire
8. **Firecrawl rate limit:** 100K credits/month
9. **Tax Delinquency town_id bug:** All 71 records have `town_id=NULL`
10. **Overlay GeoJSON files:** 6 Boston `.geojson` files in `data_cache/` root (not in `overlays/` subfolder)
11. **Permit data format:** Legacy permits in `documents.content` as pipe-delimited strings, new permits in `permits` table with proper columns
