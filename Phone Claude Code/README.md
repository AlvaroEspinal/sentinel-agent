# Phone Claude Code Session — Permit Scraping Sprint

## What Was Done

In a single Claude Code session, we scraped **686,242 building permits** across **49 Massachusetts towns** from three different public data platforms. All data is saved as local JSON files ready for Supabase import.

### Data Sources & Scrapers Used

| Platform | Towns | Permits | Notes |
|---|---|---|---|
| **ViewpointCloud** | 37 towns | ~200K | Municipal permit portals (e.g. `newtonma.viewpointcloud.com`) |
| **Socrata** | 2 towns (Cambridge, Somerville) | ~255K | Open data APIs with 10 dataset categories |
| **PermitEyes** | 6 towns | ~233K | Public permit viewer (`permiteyes.us`) |
| **SimpliCITY** | 2 towns (Weston, Sherborn) | ~3K | MapGeo/MapsOnline portals |

### Permits Per Town (Top 15)

| Town | Permits |
|---|---|
| Somerville | 129,042 |
| Cambridge | 125,558 |
| Taunton | 77,320 |
| Chicopee | 61,158 |
| Easthampton | 45,684 |
| Concord | 39,450 |
| Newton | 25,721 |
| Lexington | 18,862 |
| Haverhill | 11,934 |
| Needham | 11,286 |
| Natick | 10,974 |
| Barnstable | 8,073 |
| Wellesley | 8,038 |
| Gloucester | 6,859 |
| Shrewsbury | 6,445 |

*(+ 31 more towns with 600–6,200 permits each)*

### Files Created / Modified

- `backend/data/scraped/permits/*.json` — 46 JSON files, one per town
- `backend/scrapers/connectors/viewpointcloud.py` — ViewpointCloud API scraper
- `backend/scrapers/connectors/simplicity_client.py` — SimpliCITY/MapsOnline scraper
- `backend/scrapers/connectors/permiteyes_client.py` — PermitEyes scraper
- `backend/scrapers/connectors/socrata.py` — Socrata open data scraper
- `backend/scrapers/connectors/town_config.py` — Config registry for all 49 towns
- `backend/scrapers/scheduler.py` — Scraper watchdog with heartbeat/timeout
- `backend/scripts/run_pending_scrapers.py` — Parallel scraper runner
- `backend/scripts/probe_ma_portals.py` — Portal discovery tool
- `backend/scripts/migrate_json_to_supabase.py` — JSON → Supabase migration script

---

## How to Load Data into Supabase

### Prerequisites

1. A Supabase project (free tier works)
2. Your Supabase URL and **service role key** (not the anon key)

### Step 1: Run the Database Migrations

In your Supabase SQL Editor (Dashboard → SQL Editor → New query), run these in order:

```sql
-- 1. Create the base schema (towns, properties, permits, etc.)
-- Copy/paste from: backend/database/schema.sql

-- 2. Create the dedicated permits table with indexes
-- Copy/paste from: backend/database/migrations/002_permits_table.sql

-- 3. Seed the target towns
-- Copy/paste from: backend/database/migrations/003_seed_target_towns.sql
```

**Important:** The `towns` table must exist before inserting permits, because `permits.town_id` has a foreign key reference to `towns(id)`.

For the 37 newer towns (not in the seed migration), you'll need to insert them too. Here's a quick SQL you can run:

```sql
-- Insert all 49 towns (safe to re-run — uses ON CONFLICT)
INSERT INTO towns (id, name, state, active) VALUES
  ('haverhill', 'Haverhill', 'MA', TRUE),
  ('shrewsbury', 'Shrewsbury', 'MA', TRUE),
  ('acton', 'Acton', 'MA', TRUE),
  ('bourne', 'Bourne', 'MA', TRUE),
  ('framingham', 'Framingham', 'MA', TRUE),
  ('salem', 'Salem', 'MA', TRUE),
  ('franklin', 'Franklin', 'MA', TRUE),
  ('walpole', 'Walpole', 'MA', TRUE),
  ('belmont', 'Belmont', 'MA', TRUE),
  ('barnstable', 'Barnstable', 'MA', TRUE),
  ('gloucester', 'Gloucester', 'MA', TRUE),
  ('wrentham', 'Wrentham', 'MA', TRUE),
  ('tewksbury', 'Tewksbury', 'MA', TRUE),
  ('tisbury', 'Tisbury', 'MA', TRUE),
  ('dedham', 'Dedham', 'MA', TRUE),
  ('quincy', 'Quincy', 'MA', TRUE),
  ('gardner', 'Gardner', 'MA', TRUE),
  ('orleans', 'Orleans', 'MA', TRUE),
  ('new_bedford', 'New Bedford', 'MA', TRUE),
  ('hanover', 'Hanover', 'MA', TRUE),
  ('rutland', 'Rutland', 'MA', TRUE),
  ('ashland', 'Ashland', 'MA', TRUE),
  ('brewster', 'Brewster', 'MA', TRUE),
  ('medfield', 'Medfield', 'MA', TRUE),
  ('eastham', 'Eastham', 'MA', TRUE),
  ('marblehead', 'Marblehead', 'MA', TRUE),
  ('manchester', 'Manchester-by-the-Sea', 'MA', TRUE),
  ('peabody', 'Peabody', 'MA', TRUE),
  ('sudbury', 'Sudbury', 'MA', TRUE),
  ('auburn', 'Auburn', 'MA', TRUE),
  ('winchester', 'Winchester', 'MA', TRUE),
  ('chicopee', 'Chicopee', 'MA', TRUE),
  ('easthampton', 'Easthampton', 'MA', TRUE),
  ('taunton', 'Taunton', 'MA', TRUE),
  ('west_bridgewater', 'West Bridgewater', 'MA', TRUE),
  ('somerville', 'Somerville', 'MA', TRUE),
  ('cambridge', 'Cambridge', 'MA', TRUE)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  active = TRUE;
```

### Step 2: Set Environment Variables

Add to your `.env` file:

```bash
SUPABASE_URL=https://YOUR-PROJECT-ID.supabase.co
SUPABASE_SERVICE_KEY=eyJhbG...your-service-role-key
```

### Step 3: Run the Migration Script

```bash
cd backend

# Install dependencies (if not already)
pip install httpx loguru

# Preview what will be migrated (dry run)
python scripts/migrate_json_to_supabase.py --dry-run

# Run the actual migration
python scripts/migrate_json_to_supabase.py --table permits
```

The script:
- Reads each `backend/data/scraped/permits/<town>.json` file
- Checks for existing records by `permit_number + town_id` (deduplication)
- Inserts new records into the `permits` table via Supabase REST API

### Step 4: Verify in Supabase

```sql
-- Check total permit count
SELECT COUNT(*) FROM permits;
-- Expected: ~686,242

-- Check permits per town
SELECT town_id, COUNT(*) as cnt
FROM permits
GROUP BY town_id
ORDER BY cnt DESC;

-- Check a specific town
SELECT * FROM permits WHERE town_id = 'newton' LIMIT 5;
```

---

## Permit Data Schema

Each permit record has these fields:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Auto-generated primary key |
| `town_id` | VARCHAR(50) | Town slug (e.g. `newton`, `cambridge`) |
| `permit_number` | VARCHAR(100) | Original permit number from source |
| `permit_type` | VARCHAR(100) | Building, Electrical, Plumbing, etc. |
| `status` | VARCHAR(50) | FILED, APPROVED, ISSUED, COMPLETED, etc. |
| `address` | TEXT | Street address (when available) |
| `description` | TEXT | Permit description / scope of work |
| `estimated_value` | DECIMAL | Dollar value of permitted work |
| `applicant_name` | TEXT | Person/company who applied |
| `contractor_name` | TEXT | Licensed contractor |
| `filed_date` | DATE | When permit was filed |
| `issued_date` | DATE | When permit was issued |
| `latitude` | DOUBLE | Geocoded latitude |
| `longitude` | DOUBLE | Geocoded longitude |
| `source_system` | VARCHAR(50) | `viewpointcloud`, `socrata`, `permiteyes`, `simplicity` |
| `created_at` | TIMESTAMP | When record was scraped |

---

## Re-running Scrapers

To refresh or expand the data:

```bash
cd backend

# Run all pending scrapers (towns not yet scraped or incomplete)
python scripts/run_pending_scrapers.py --concurrency 8

# Scrape a specific town
python -c "
import asyncio
from scrapers.connectors.viewpointcloud import ViewpointCloudScraper
async def main():
    s = ViewpointCloudScraper('newtonma', 'newton')
    permits = await s.scrape_all()
    print(f'Got {len(permits)} permits')
asyncio.run(main())
"
```

---

## Architecture Notes

- **No API keys required** — All scrapers use public municipal data portals
- **Deduplication** — Migration script checks `permit_number + town_id` before inserting
- **Incremental** — Re-running scrapers overwrites local JSON; migration script skips existing records
- **Parallel** — `run_pending_scrapers.py` runs up to 8 towns concurrently with asyncio semaphore
