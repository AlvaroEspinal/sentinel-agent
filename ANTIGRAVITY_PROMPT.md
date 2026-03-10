# Antigravity Sprint Prompt — Parcl Intelligence Data Pipeline

**Date:** March 10, 2026
**Goal:** Complete all HIGH and MEDIUM priority data pipeline tasks for the 12-town MA MVP. You should spawn sub-agents to parallelize independent work streams.

---

## Environment & Credentials

```bash
cd /Users/alvaroespinal/sentinel-agent/backend
source ../.env  # Loads: SUPABASE_URL, SUPABASE_SERVICE_KEY, OPENROUTER_API_KEY, FIRECRAWL_API_KEY
```

- **Supabase Project ID:** `tkexrzohviadsgolmupa`
- **Supabase URL:** read from `.env` (`SUPABASE_URL`)
- **12 MVP Towns:** newton, wellesley, weston, brookline, needham, dover, sherborn, natick, wayland, lincoln, concord, lexington
- **Repo root:** `/Users/alvaroespinal/sentinel-agent`
- **All scripts:** `backend/scripts/`
- **Data cache:** `backend/data_cache/`

---

## Current Database State (Baseline — verify these first)

| Table | Count | Notes |
|-------|-------|-------|
| `permits` | 439,175 | 49 towns (12 MVP + 37 expanded) |
| `permits` geocoded (lat≠0) | 125,250 | Only Somerville + Cambridge have coords |
| `permits` NOT geocoded | 313,925 | Need batch geocoder for these |
| `municipal_documents` | 7,900 | MEPA, overlays, wetlands, zoning, CIP, meetings, tax delin |
| `mepa_filings` | 5,554 | Complete for 12 towns |
| `tax_delinquent_parcels` | 71 | Has town_id bug — 69 say "boston", 2 say "lexington" |

---

## TASK 1 (HIGH): Run Brookline Playwright Permit Scraper

**Status:** Script exists at `backend/scripts/scrape_brookline_playwright.py` but was NEVER RUN. Brookline has only 63 permits in Supabase (from legacy ViewpointCloud scrape). The Playwright scraper was built to bypass Accela's 100-record cap using prefix-based recursive splitting.

**Steps:**
1. Navigate to `backend/` directory
2. Run for multiple years to get comprehensive data:
   ```bash
   python3 scripts/scrape_brookline_playwright.py --year 2024
   python3 scripts/scrape_brookline_playwright.py --year 2023
   python3 scripts/scrape_brookline_playwright.py --year 2022
   ```
3. Each run produces `brookline_permits_{year}.json` in the script directory
4. After scraping, ingest ALL output files to Supabase's `permits` table
5. Write a quick ingest script if needed — the JSON structure has `permits[]` array with fields mapping to the permits table columns: `permit_number, permit_type, address, description, filed_date, issued_date, applicant_name, status`
6. **Verification:** Brookline permit count should go from 63 to several thousand

**Important:** The Playwright scraper requires a browser. Make sure `playwright install chromium` has been run. The script uses prefix search — it types permit prefixes like "BP", "EP", "GP" into the Accela search form and recursively splits if results hit the 100-record cap.

---

## TASK 2 (HIGH): Fix Tax Delinquency town_id Bug

**Status:** 71 records in `tax_delinquent_parcels` have wrong `town_id` values. 69 show "boston" and 2 show "lexington" — but these records are from various MVP towns. The bug is in `repair_tax_delinquency.py` which defaults to "boston" when it can't parse the town from content.

**Steps:**
1. Read the existing script: `backend/scripts/repair_tax_delinquency.py`
2. The bug: it falls back to `town_id = "boston"` when town detection fails. The actual towns can be determined from the `content_text` field which contains pipe-delimited address data.
3. Fix approach:
   - Query all 71 records from `tax_delinquent_parcels` (NOT `municipal_documents` — the repair script targets the wrong table)
   - Parse the address field from `content_text` (format: "Address: 123 Main St, Needham")
   - Extract the town name from the address
   - UPDATE each record with the correct `town_id`
4. If addresses don't contain town names, check the `source_url` or `raw_data` fields for town indicators
5. **Verification:** Run `SELECT town_id, COUNT(*) FROM tax_delinquent_parcels GROUP BY town_id` — should show proper distribution across MVP towns, zero "boston" entries

---

## TASK 3 (HIGH): Resolve 4 Failed CIP Towns

**Status:** 8/12 towns have CIP data (565 total projects extracted). 4 towns failed:

| Town | Status | Problem | Stale URLs Tried |
|------|--------|---------|-----------------|
| Newton | `not_found` | All 3 URLs returned no CIP content | newtonma.gov/city-hall/finance/... |
| Dover | `timeout` | Direct PDF link timed out, .org URLs may be wrong domain | doverma.gov + doverma.org mix |
| Wayland | `not_found` | CivicPlus site restructured, all 3 URLs stale | wayland.ma.us/finance/... |
| Lincoln | `not_found` | Page numbers likely changed | lincolntown.org/259/... |

**Resolution Strategy (per town):**

### Newton
1. The current URLs (`newtonma.gov/city-hall/finance/capital-improvement-program`) are stale — Newton likely restructured their site
2. Use Firecrawl to Google search: `site:newtonma.gov "capital improvement" filetype:pdf`
3. Also try: `site:newtonma.gov CIP budget` and `site:newtonma.gov capital plan`
4. Newton has a WAF — use `scrape_with_actions()` with a 5s wait, NOT plain `scrape()`
5. If you find the CIP page/PDF, update the URLs in `scrape_all_cip.py` and re-run for newton

### Dover
1. Domain confusion: Dover uses BOTH `doverma.gov` (CivicPlus) and `doverma.org`
2. The direct PDF link `doverma.gov/documentcenter/view/4554` timed out — it might still be valid, just slow
3. Try scraping `doverma.gov/documentcenter/view/4554` with a 60s timeout and `scrape_with_actions()` with a long wait
4. Also try the document center index: `https://www.doverma.gov/documentcenter`
5. Search: `site:doverma.gov "capital improvement"` OR `site:doverma.gov CIP`
6. Dover is a small town — they may genuinely not publish CIP docs. If nothing found after thorough search, mark as `not_available`

### Wayland
1. Wayland uses CivicPlus CMS — page numbers change when sites are updated
2. Google: `site:wayland.ma.us "capital improvement"` and `site:wayland.ma.us CIP budget`
3. Try the document center: `https://www.wayland.ma.us/documentcenter`
4. Wayland has a WAF — use `scrape_with_actions()` with a 5s wait
5. Try alternate URL patterns: `wayland.ma.us/*/capital-improvement*`

### Lincoln
1. Lincoln's CivicPlus page numbers shifted — `/259/Capital-Improvement-Plan` is stale
2. Google: `site:lincolntown.org "capital improvement"` and `site:lincolntown.org CIP`
3. Try document center: `https://www.lincolntown.org/documentcenter`
4. Lincoln is also small — may use town meeting warrant articles instead of formal CIP docs
5. If a PDF is found, download and re-run CIPExtractor on it

**For all 4 towns:**
- Use the existing `scrape_all_cip.py` pipeline — just update the URLs in the `TOWNS` config (lines 52-162) and re-run
- The script already handles: Firecrawl scraping → PDF detection → LLM extraction via CIPExtractor
- To run only failed towns: the script already filters to `("newton", "wayland", "dover", "lincoln")` on line 437
- After fixing URLs, run: `python3 -m backend.scripts.scrape_all_cip`
- **Verification:** Check `backend/data_cache/cip/{town}_cip.json` — status should be `extracted` or `found_no_projects`, NOT `not_found`

---

## TASK 4 (HIGH): Manage Batch Geocoder

**Status:** Geocoder is running as PID 78739, scanning 125,795 permits (stale scope — DB now has 439K). Currently at ~900/30,797 unique addresses (2.9%), running at 0.5 addr/sec. ETA ~17 hours for this batch.

**Steps:**
1. **DO NOT KILL** the current geocoder process — let it finish its current batch
2. Monitor progress: `tail -5 backend/batch_geocode.log`
3. Check if done: `ps aux | grep batch_geocode`
4. After current batch completes, the 313K new permits (from the 37 expanded towns) still need geocoding
5. Re-run the geocoder with `--resume` flag to pick up remaining un-geocoded permits:
   ```bash
   cd backend && nohup python3 -u scripts/batch_geocode_permits.py --resume > batch_geocode_round2.log 2>&1 &
   ```
6. The geocoder uses Nominatim (1 req/sec rate limit). Cache is at `backend/data_cache/geocode_cache.json` (13K+ entries)
7. **Verification:** After both rounds, run: `SELECT COUNT(*) FROM permits WHERE latitude != 0 AND longitude != 0` — should be significantly more than 125,250

---

## TASK 5 (MEDIUM): Commit All Uncommitted Files to GitHub

**Status:** 8 files on disk not in git:

```
M  backend/scripts/ingest_tax_takings_to_supabase.py
M  backend/scripts/scrape_all_cip.py
?? backend/batch_geocode.log
?? backend/scripts/_test_400.py
?? backend/scripts/_test_brookline_inputs.py
?? backend/scripts/_test_fc_massland.py
?? backend/scripts/repair_tax_delinquency.py
?? backend/scripts/scrape_brookline_playwright.py
```

**Steps:**
1. Stage the meaningful files (skip test/debug files):
   ```bash
   git add backend/scripts/scrape_brookline_playwright.py
   git add backend/scripts/repair_tax_delinquency.py
   git add backend/scripts/ingest_tax_takings_to_supabase.py
   git add backend/scripts/scrape_all_cip.py
   ```
2. Add `batch_geocode.log` to `.gitignore` (log files shouldn't be tracked)
3. Commit with message: `"Add Brookline Playwright scraper, tax repair script, update CIP + tax takings ingest"`
4. Push to `main` branch
5. **Verification:** `git status` should show clean working tree (except ignored files)

---

## TASK 6 (MEDIUM): Run Existing Ingest Scripts for Cached Data

**Status:** Several data sources have been scraped to `data_cache/` but NOT yet ingested to Supabase. The plan file at `/Users/alvaroespinal/.claude/plans/unified-dazzling-snowglobe.md` details ingest scripts that exist but haven't been run.

**Check and run these:**

### 6a. CIP Ingest (8 successful towns)
- Script: `backend/scripts/ingest_cip_to_supabase.py` (exists, 5,623 bytes)
- Data: `backend/data_cache/cip/{town}_cip.json` — 8 files with projects
- Inserts into `municipal_documents` with `doc_type="capital_improvement"`
- Run: `python3 scripts/ingest_cip_to_supabase.py`

### 6b. Overlays Ingest (has known bugs)
- Script: `backend/scripts/ingest_overlays.py` (exists, 5,212 bytes)
- **Known bug on line 39:** Hardcodes `"eq.Boston"` — needs to parse `town_id` from filename
- **Known bug on line 45:** Glob `*.geojson` is wrong — should be `*_overlays.json`
- Fix both bugs, then run

### 6c. Zoning Ingest (11 towns, Wayland missing)
- Script: `backend/scripts/ingest_zoning_to_supabase.py` (exists, 4,826 bytes)
- Data: `backend/data_cache/zoning_bylaws/*_zoning.json`
- Run: `python3 scripts/ingest_zoning_to_supabase.py`

### 6d. Wetlands Ingest (12 towns)
- Script: `backend/scripts/ingest_wetlands_to_supabase.py` (exists, 5,758 bytes)
- Data: `backend/data_cache/wetlands/{town}_wetlands.json`
- Run: `python3 scripts/ingest_wetlands_to_supabase.py`

**Verification after all ingests:**
```sql
SELECT doc_type, COUNT(*) FROM municipal_documents GROUP BY doc_type ORDER BY count DESC;
```
Expected: `capital_improvement` should have 8+ entries, `overlay_district` 12+, `zoning_bylaw` 11+, `wetland_area` 12+.

---

## SUB-AGENT ARCHITECTURE

**You MUST spawn parallel sub-agents for independent work streams.** Here is the recommended breakdown:

### Sub-Agent 1: "Brookline Scraper"
- Handles: TASK 1 (run Playwright scraper for 2022-2024, ingest results)
- Independent — no dependencies on other tasks
- Estimated time: 30-60 min (scraping) + 5 min (ingest)

### Sub-Agent 2: "CIP Resolution"
- Handles: TASK 3 (all 4 failed towns)
- Can run 4 sub-sub-agents (one per town) for maximum parallelism
- Each sub-sub-agent: Google OSINT → find current URL → update config → re-run scraper → verify
- Estimated time: 1-2 hours

### Sub-Agent 3: "Data Ingest & Fixes"
- Handles: TASK 2 (tax delinquency fix), TASK 6 (all ingest scripts)
- Run sequentially: fix tax → ingest CIP → fix+ingest overlays → ingest zoning → ingest wetlands
- Estimated time: 30-45 min

### Sub-Agent 4: "Git & Geocoder Management"
- Handles: TASK 4 (monitor geocoder), TASK 5 (git commits)
- Git commit first (quick), then monitor geocoder until current batch completes
- Launch round 2 geocoder when round 1 finishes
- Estimated time: monitoring (passive, check every 30 min)

**Spawning pattern:**
```
Main Agent
├── spawn Sub-Agent 1 (Brookline)     ← can start immediately
├── spawn Sub-Agent 2 (CIP)           ← can start immediately
├── spawn Sub-Agent 3 (Ingest+Fix)    ← can start immediately
└── spawn Sub-Agent 4 (Git+Geocoder)  ← can start immediately
         └── Sub-Agent 2 spawns:
             ├── Sub-Agent 2a (Newton CIP)
             ├── Sub-Agent 2b (Dover CIP)
             ├── Sub-Agent 2c (Wayland CIP)
             └── Sub-Agent 2d (Lincoln CIP)
```

All 4 top-level sub-agents can start simultaneously — they operate on different data and different Supabase tables with no conflicts.

---

## WHAT NOT TO DO (Low Priority — Alvaro will handle)

Do NOT work on any of these:
- Backend deployment (Railway/Render/Fly.io)
- Frontend UI polish or design changes
- Property valuation features
- Middlesex South Registry of Deeds WAF bypass
- Expanding to towns beyond the 12 MVP
- ViewpointCloud SPA scraper for 8 towns (already have permit data from other sources)

---

## Success Criteria

When all tasks complete, the following should be true:

1. **Brookline permits:** 1,000+ permits in Supabase (up from 63)
2. **Tax delinquency:** Zero records with `town_id = 'boston'` — all correctly assigned
3. **CIP towns:** 10-12 out of 12 towns have CIP data (up from 8). Any remaining gaps documented as `not_available`
4. **Municipal documents:** `capital_improvement` count > 8 in Supabase, overlays/zoning/wetlands all ingested
5. **Geocoder:** Current batch completed, round 2 launched for expanded towns
6. **Git:** All new scripts committed and pushed to `main`

Report back with a summary of what was accomplished, what failed, and any remaining gaps.
