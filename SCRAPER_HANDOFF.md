# Meeting Minutes Scraper — Handoff Guide

> Last updated: 2026-03-05
> For transitioning to Google Antigravity / Kimi K2.5 agent swarms

---

## 1. What We Have: Data Inventory

### Permits (in Supabase `documents` table)
- **129,947 permits** across 46 Massachusetts towns
- Stored as pipe-delimited strings in `documents.content`
- Format: `"Type: Building | Address: 123 Main St | Cost: $627.00"`
- ~124.5K still need geocoding (lat/lon = 0,0)

### Meeting Minutes (in Supabase `municipal_documents` table)
- **214 documents** across 5 towns (of 12 target MVP towns)
- Also saved locally as JSON in `backend/data/scraped/minutes/{town_id}.json`

**Current status by town:**

| Town | Docs | Boards Scraped | Status |
|------|------|----------------|--------|
| Wellesley | 61 | conservation (8), zba (53) | Done |
| Weston | 71 | conservation (28), planning (23), zba (20) | Done |
| Natick | 36 | conservation (35), planning (1) | Done |
| Dover | 26 | conservation (16), zba (10) | Done |
| Concord | 20 | planning (20) | Done |
| Sherborn | ? | Running... | Agent may still be running |
| Lincoln | ? | Running... | Agent may still be running |
| Needham | ? | Re-running with fixed parser | Agent may still be running |
| Brookline | 0 | — | CivicClerk PDF auth blocks downloads |
| Lexington | 0 | — | Minutes on external Laserfiche system |
| Newton | 0 | — | Firecrawl API returning 400 errors |
| Wayland | 0 | — | Firecrawl API returning 400 errors |

### Local JSON Format

Files at `backend/data/scraped/minutes/{town_id}.json` — array of objects:

```json
{
  "town_id": "wellesley",
  "doc_type": "meeting_minutes",
  "board": "zba",
  "title": "Zoning Board of Appeals Minutes — Meeting Minutes",
  "meeting_date": "2024-12-19",
  "source_url": "https://www.wellesleyma.gov/AgendaCenter/Zoning-Board-of-Appeals-14",
  "file_url": "https://www.wellesleyma.gov/AgendaCenter/ViewFile/Minutes/_12192024-8068",
  "content_text": "Full extracted PDF text (up to 50KB)...",
  "page_count": null,
  "file_size_bytes": 203653,
  "content_hash": "5744dfc7c351c4bcada0d75d2bb41c00b6c8ff7f99f4bbdf7e3d3104ebb551ab",
  "content_summary": "",
  "keywords": [],
  "mentions": []
}
```

**Note:** Most documents have empty `content_summary`, `keywords`, and `mentions` because the LLM extraction hit Anthropic API rate limits (30K input tokens/min). The raw `content_text` is always present.

---

## 2. How the Scrapers Work

### Architecture Overview

```
scrape_meeting_minutes.py (CLI entrypoint)
    ├── Detects CMS type per town
    ├── Routes to correct scraper:
    │   ├── AgendaCenterClient  → 8 towns (free, no API keys)
    │   ├── ArchiveCenterClient → 1 town: Needham (free)
    │   ├── CivicClerkClient    → 1 town: Brookline (free, but PDF download blocked)
    │   └── Firecrawl           → 2 towns: Newton, Wayland (needs API key)
    ├── Downloads PDFs → extracts text via pdfplumber
    ├── (Optional) LLM extraction via Claude API
    ├── Saves to local JSON
    └── Upserts to Supabase (dedup by content_hash)
```

### Key Files

| File | Purpose |
|------|---------|
| `backend/scripts/scrape_meeting_minutes.py` | **Main CLI script** — run per town |
| `backend/scrapers/connectors/agendacenter_client.py` | AgendaCenter scraper (10 towns) |
| `backend/scrapers/connectors/archivecenter_client.py` | ArchiveCenter scraper (Needham) |
| `backend/scrapers/connectors/civicclerk_client.py` | CivicClerk OData API (Brookline) |
| `backend/scrapers/connectors/town_config.py` | Town/board URL registry |
| `backend/scrapers/connectors/llm_extractor.py` | Claude-based structured extraction |
| `backend/scrapers/connectors/firecrawl_client.py` | Firecrawl wrapper (Newton/Wayland) |
| `backend/scrapers/connectors/meeting_minutes.py` | Original Firecrawl-based scraper |
| `backend/database/supabase_client.py` | Supabase REST client |
| `backend/config.py` | Environment variable loader |

### Running a Scraper

```bash
cd backend

# Scrape one town (all boards, years 2024-2026)
python scripts/scrape_meeting_minutes.py --town wellesley

# Specific boards only
python scripts/scrape_meeting_minutes.py --town dover --boards zba,conservation_commission

# Specific years
python scripts/scrape_meeting_minutes.py --town concord --years 2024,2025

# Preview mode (no downloads)
python scripts/scrape_meeting_minutes.py --town sherborn --dry-run

# Skip LLM extraction (faster, no Anthropic API cost)
python scripts/scrape_meeting_minutes.py --town natick --skip-llm
```

### Environment Variables Needed

```bash
# Required for Supabase storage
SUPABASE_URL=https://kqxobtacjhrqqxniridj.supabase.co
SUPABASE_SERVICE_KEY=<service_role_key>

# Optional: for LLM extraction (adds summary, keywords, mentions)
ANTHROPIC_API_KEY=<key>

# Optional: only for Newton/Wayland
FIRECRAWL_API_KEY=<key>
```

---

## 3. How Each Scraper Works

### A. AgendaCenter (8 towns: Wellesley, Weston, Dover, Natick, Concord, Sherborn, Lincoln, Lexington)

**How it works:**
1. POST to `{baseURL}/AgendaCenter/UpdateCategoryList` with `year=YYYY&catID=NN`
2. Returns HTML fragment with meeting rows
3. Parse with regex for `/AgendaCenter/ViewFile/Minutes/_MMDDYYYY-NNNN` links
4. Download each PDF, extract text with pdfplumber

**Key details:**
- `cat_id` is extracted from the board URL slug (e.g., `Planning-Board-12` → `cat_id=12`)
- Date is encoded in URL: `_01152025` = January 15, 2025 (MMDDYYYY)
- Free, no API keys, no auth needed
- Rate: ~1-2 requests/second is fine

**Board URLs configured in `town_config.py`:**
```
wellesley: Select Board-25, Planning-Board-12, ZBA-14, Conservation-15
weston:    Planning-Board-9, ZBA-10, Conservation-11
dover:     Select-Board-1, Planning-Board-3, ZBA-4, Conservation-5
natick:    Select-Board-1, Planning-Board-3, Conservation-7
concord:   Select-Board-1, Planning-Board-4, Natural-Resources-12
sherborn:  Select-Board-5, Planning-Board-6, ZBA-28, Conservation-16
lincoln:   Select-Board-1, Planning-Board-22, ZBA-3, Conservation-13
lexington: Select-Board-54, Planning-Board-4, ZBA-7, Conservation-5
```

### B. ArchiveCenter (Needham)

**How it works:**
1. GET `{baseURL}/Archive.aspx?AMID={amid}` — returns HTML page with archive links
2. Parse for `<a href="Archive.aspx?ADID=NNNNN">Title</a>` or `<a href="ArchiveCenter/ViewFile/Item/NNNNN">`
3. Download PDFs from `/ArchiveCenter/ViewFile/Item/{adid}`
4. Extract text with pdfplumber

**AMID mappings (configured in `scrape_meeting_minutes.py`):**
```python
"needham": {
    "base_url": "https://www.needhamma.gov",
    "boards": {
        "select_board": 31,
        "planning_board": 33,
        "conservation_commission": 39,
        "zba": 65,
    },
}
```

### C. CivicClerk OData API (Brookline)

**How it works:**
1. GET `https://BrooklineMA.api.civicclerk.com/v1/EventCategories` — lists all boards
2. Match board name via `categoryDesc` field (fuzzy match)
3. GET `/Events?$filter=eventCategoryId eq {id}&$orderby=eventDate desc`
4. Extract meeting info from events, look for `publishedFiles` with minutes

**PROBLEM:** PDF download URLs require SPA authentication tokens. The portal at `brooklinema.portal.civicclerk.com` is a React SPA that generates auth tokens dynamically. Direct HTTP downloads return 404.

**To fix Brookline:** Either use a headless browser (Playwright) to get auth tokens, or find an alternative minutes source.

### D. Firecrawl (Newton, Wayland)

**How it works:**
1. Uses Firecrawl API to crawl the town's meeting minutes pages
2. Extracts PDF links from crawled pages
3. Downloads and processes PDFs

**PROBLEM:** Firecrawl API is returning HTTP 400 for all crawl requests. This is an API-side issue, not a code issue.

**To fix Newton/Wayland:** Either fix Firecrawl API key/config, use a different crawling approach, or build custom scrapers for these towns' CMS platforms.

---

## 4. What's Still Missing

### Towns with 0 Documents — Action Needed

| Town | Issue | Fix Needed |
|------|-------|------------|
| **Sherborn** | Agent may still be running | Check `sherborn.json` — if empty, re-run scraper |
| **Lincoln** | Agent may still be running | Check `lincoln.json` — if empty, re-run scraper |
| **Needham** | Re-running with fixed ArchiveCenter parser | Check `needham.json` — should have data now |
| **Brookline** | CivicClerk portal requires SPA auth for PDF downloads | Need Playwright or alternative source |
| **Lexington** | Minutes hosted on external Laserfiche WebLink system, not AgendaCenter | Need custom Laserfiche scraper |
| **Newton** | Firecrawl API 400 errors | Custom scraper for Newton's gov site |
| **Wayland** | Firecrawl API 400 errors | Custom scraper for Wayland's Drupal site |

### Missing Boards for Towns That Have Data

Most towns only have 2-3 boards scraped (of 4 configured). Common missing boards:
- **Select Board** — many towns return HTTP 404 for this category
- Some boards have agendas but no minutes PDFs uploaded

### LLM Extraction Not Done

Most of the 214 documents have empty `content_summary`, `keywords`, and `mentions` fields. The raw `content_text` is there — just needs LLM processing. You can re-process with:

```bash
# Would need a script that reads existing docs and runs LLM extraction
# The LLMExtractor class in llm_extractor.py handles this
```

### Geocoding Gap

~124.5K permits still have lat/lon = 0,0. Batch geocoder script exists at `backend/scripts/batch_geocode_permits.py`.

---

## 5. What to Do with the Data

### Option A: Save Locally Only (simplest)

Data is already saved at `backend/data/scraped/minutes/{town_id}.json`. Each file is a JSON array of document objects with full text.

### Option B: Supabase (current approach)

Data upserts into `municipal_documents` table, deduped by `content_hash` (SHA-256 of extracted text).

**Supabase table schema:**
```sql
municipal_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  town_id text NOT NULL,
  doc_type text DEFAULT 'meeting_minutes',
  board text,
  title text,
  meeting_date date,
  source_url text,
  file_url text,
  content_text text,        -- full PDF text (up to 50KB)
  content_summary text,     -- LLM-generated summary
  keywords jsonb DEFAULT '[]',
  mentions jsonb DEFAULT '[]',
  page_count integer,
  file_size_bytes integer,
  content_hash text UNIQUE, -- SHA-256 for dedup
  scraped_at timestamptz DEFAULT now(),
  processed_at timestamptz,
  created_at timestamptz DEFAULT now()
)
```

### Option C: Post-Processing Pipeline

After scraping, the intended pipeline is:
1. **LLM Extraction** — Run `LLMExtractor.extract_from_minutes()` on each doc's `content_text`
2. **This produces:** summary, keywords, mentions (addresses + decisions), decisions (votes)
3. **Cross-reference** mentions with permit data to link meeting decisions to specific properties
4. **Feed into** the property detail view in the frontend (PropertyDetails.tsx, "Agents" tab or new "Minutes" tab)

---

## 6. Quick Start for Agent Swarm

To parallelize across towns with Kimi K2.5 agent swarm:

```bash
# Each agent runs one town independently:
cd /Users/alvaroespinal/sentinel-agent/backend

# Agent 1
python scripts/scrape_meeting_minutes.py --town wellesley --skip-llm

# Agent 2
python scripts/scrape_meeting_minutes.py --town weston --skip-llm

# ... etc for each town
```

**Dependencies:** `pip install httpx pdfplumber anthropic supabase`

**No API keys needed** for AgendaCenter/ArchiveCenter towns (8 of 12). Only need `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` for database storage, and `ANTHROPIC_API_KEY` for LLM extraction.

---

## 7. Supabase Credentials

Stored in the environment (not in files). Project ID: `kqxobtacjhrqqxniridj`

The `backend/config.py` file loads from environment variables:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `ANTHROPIC_API_KEY`
- `FIRECRAWL_API_KEY`

---

## 8. File Tree (Relevant Files Only)

```
backend/
├── config.py                                    # Env var loader
├── scripts/
│   ├── scrape_meeting_minutes.py                # Main CLI scraper
│   └── batch_geocode_permits.py                 # Permit geocoding
├── scrapers/connectors/
│   ├── agendacenter_client.py                   # AgendaCenter scraper
│   ├── archivecenter_client.py                  # ArchiveCenter scraper (Needham)
│   ├── civicclerk_client.py                     # CivicClerk OData (Brookline)
│   ├── firecrawl_client.py                      # Firecrawl wrapper
│   ├── meeting_minutes.py                       # Original Firecrawl scraper
│   ├── llm_extractor.py                         # Claude LLM extraction
│   └── town_config.py                           # Town/board URL registry
├── database/
│   └── supabase_client.py                       # Supabase REST client
└── data/scraped/minutes/
    ├── wellesley.json    (61 docs)
    ├── weston.json       (71 docs)
    ├── natick.json       (36 docs)
    ├── dover.json        (16 docs)
    ├── concord.json      (20 docs)
    ├── brookline.json    (empty)
    ├── lexington.json    (empty)
    ├── needham.json      (empty — re-run may populate)
    ├── newton.json       (empty)
    └── wayland.json      (empty)
```
