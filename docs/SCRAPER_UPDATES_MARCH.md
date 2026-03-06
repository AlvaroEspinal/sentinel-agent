# Municipal Document Scrapers Update (March 2026)

## Overview
During these sessions, we shifted focus from pure permitting data to extracting rich municipal intelligence documents across our 12 affluent target towns.

### Scrapers Built & Tools Used
1. **Zoning Bylaw Scraper** (`backend/scrapers/connectors/zoning_bylaw_scraper.py`)
   - **Target:** "Table of Uses" and dimensional requirements.
   - **Tech:** Firecrawl (to bypass Cloudflare on eCode360/General Code portals) + Anthropic/OpenRouter LLM for structured JSON extraction.
   - **Status:** Built, tested, and actively used for batch extraction.

2. **MEPA Environmental Monitor Scraper** (`backend/scrapers/connectors/mepa_scraper.py`)
   - **Target:** Massachusetts Environmental Policy Act (MEPA) filings (EIRs, ENFs, NPCs).
   - **Tech:** Hits the AWS API Gateway backing the state's Angular SPA. Includes a beautifulsoup HTML fallback just in case.
   - **Status:** Built, tested, and actively used for batch extraction.

3. **Tax Delinquency Scraper** (`backend/scrapers/connectors/tax_delinquency_scraper.py`)
   - **Target:** "Tax Title" and "Tax Delinquency" PDFs published by town treasurers.
   - **Tech:** Multi-agent search via Firecrawl to locate the PDFs dynamically -> `pdfplumber` to extract tables/text -> LLM for structured extraction (Address, Owner, Amount Owed).
   - **Status:** Built and verified for specific towns; ready to be integrated into the batch pipeline.

4. **Capital Improvement Plan (CIP) Extractor** (`backend/scrapers/connectors/cip_extractor.py`)
   - **Target:** Future infrastructure projects, budgets, and proposed years from municipal CIPs and Town Meeting Warrants.
   - **Tech:** Employs our LLM extraction patterns (via Anthropic/OpenRouter fallback architectures) to parse massive text blocks into structured `project_name`, `budget`, and `location` arrays.
   - **Status:** Built and verified working via CLI scripts; ready to be hooked up to PDF ingestion.

5. **Municipal Overlays Connector** (`backend/scrapers/connectors/municipal_overlays.py`)
   - **Target:** ArcGIS FeatureServers for Historic Districts, Institutional Overlays, and Planned Development Areas.
   - **Status:** Built and verified for Boston and Cambridge geometries.

### Batch Processing & Supabase Migration
We created a new bulk extraction runner (`scripts/run_extractors.py`) that successfully ran both the **MEPA** and **Zoning** scrapers concurrently across all 12 target towns. 

We then updated the Supabase migration script (`scripts/migrate_json_to_supabase.py`) to parse this extracted data, compute SHA-256 idempotency hashes, and upsert the records into the `municipal_documents` table in our PostgreSQL database.

**What Has Been Scraped and Pushed to Supabase:**
- **MEPA Filings:** 240 recent filings (20 per town across 12 towns) fully pushed to the `municipal_documents` table (`doc_type = 'mepa_filing'`).
- **Zoning Bylaws:** Tables of Uses extracted and pushed for towns utilizing eCode360 (placeholder cleanups successfully skipped empty responses).

**What Is Left to Do (Next Steps):**
1. **Hook CIP & Tax Delinquency into Bulk Pipeline:** The extractors are built, but we need to automate downloading their respective PDFs/warrants at scale and piping them into `tax_delinquency_scraper.py` and `cip_extractor.py`.
2. **Push Remaining Data:** After batching Tax/CIP, run standard migrations to push the rest to Supabase.
3. **Frontend Integration:** Build map toggles and dashboard views to expose this new data (MEPA, Tax Delinquencies, Overlays) directly to the end-users on the Alpha Data Platform.
