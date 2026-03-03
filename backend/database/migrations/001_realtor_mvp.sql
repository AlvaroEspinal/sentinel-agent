-- ============================================================================
-- Migration 001: Realtor MVP — New tables for municipal intelligence
-- ============================================================================
-- Adds:
--   1. municipal_documents — meeting minutes, bylaws, filings
--   2. property_transfers — historical sales tracking from MassGIS
--   3. scrape_jobs — scraper run tracking
--   4. Extends towns table with new columns
-- ============================================================================

-- ============================================================================
-- 1. Municipal Documents
-- ============================================================================
-- Stores scraped town documents: meeting minutes, zoning bylaws,
-- capital plans, MEPA filings, tax delinquency lists, etc.
-- Content is extracted via Firecrawl + LLM summarization.
-- ============================================================================

CREATE TABLE IF NOT EXISTS municipal_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    town_id         VARCHAR(50) REFERENCES towns(id),

    -- Document classification
    doc_type        VARCHAR(50) NOT NULL,
        -- 'meeting_minutes', 'zoning_bylaw', 'capital_plan',
        -- 'tax_delinquency', 'conservation_restriction',
        -- 'mepa_filing', 'subdivision_plan', 'site_plan_approval',
        -- 'zoning_map', 'overlay_district', 'foreclosure_notice'

    board           VARCHAR(100),
        -- 'select_board', 'planning_board', 'zba',
        -- 'conservation_commission', 'school_committee', 'finance_committee'

    -- Content
    title           TEXT NOT NULL,
    meeting_date    DATE,
    source_url      TEXT,              -- Original page URL
    file_url        TEXT,              -- Direct link to PDF/document
    content_text    TEXT,              -- Full extracted text (from HTML or PDF)
    content_summary TEXT,              -- LLM-generated summary

    -- Structured extraction (from LLM)
    keywords        TEXT[] DEFAULT '{}',
    mentions        JSONB DEFAULT '[]',
        -- Array of: {address, parcel_id, loc_id, topic, decision, context_snippet}
        -- e.g. [{"address": "123 Main St", "topic": "demolition", "decision": "approved"}]

    -- Metadata
    page_count      INTEGER,           -- For PDFs
    file_size_bytes INTEGER,
    content_hash    VARCHAR(64),       -- SHA-256 for dedup
    scraped_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at    TIMESTAMP WITH TIME ZONE, -- When LLM extraction completed
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ============================================================================
-- 2. Property Transfers
-- ============================================================================
-- Historical property sales from MassGIS assessor data.
-- Tracked over time to detect trends, flag flips, monitor neighborhoods.
-- ============================================================================

CREATE TABLE IF NOT EXISTS property_transfers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    town_id         VARCHAR(50) REFERENCES towns(id),

    -- MassGIS identifiers
    loc_id          VARCHAR(50),       -- MassGIS LOC_ID (unique parcel identifier)
    map_par_id      VARCHAR(50),       -- MAP_PAR_ID

    -- Property details
    site_addr       TEXT,
    city            VARCHAR(100),
    owner           TEXT,              -- Current owner (OWNER1)
    use_code        VARCHAR(10),       -- MA DOR use code
    use_description VARCHAR(200),

    -- Transfer details
    grantor         TEXT,              -- Previous owner (if available)
    grantee         TEXT,              -- New owner
    sale_date       DATE,
    sale_price      DECIMAL(12,2),
    book_page       VARCHAR(50),       -- Registry book/page reference
    doc_type        VARCHAR(50) DEFAULT 'deed',
        -- 'deed', 'mortgage', 'lien', 'foreclosure'

    -- Valuation
    assessed_value  DECIMAL(12,2),     -- Total assessed value
    building_value  DECIMAL(12,2),
    land_value      DECIMAL(12,2),

    -- Computed fields
    price_per_sqft  DECIMAL(10,2),
    building_area   INTEGER,           -- sqft
    lot_size_acres  DECIMAL(10,4),
    year_built      INTEGER,
    style           VARCHAR(100),

    -- Metadata
    fiscal_year     VARCHAR(4),
    scraped_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ============================================================================
-- 3. Scrape Jobs
-- ============================================================================
-- Tracks each scraper run for monitoring, debugging, and scheduling.
-- ============================================================================

CREATE TABLE IF NOT EXISTS scrape_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    town_id         VARCHAR(50) REFERENCES towns(id),

    source_type     VARCHAR(50) NOT NULL,
        -- 'permits', 'meeting_minutes', 'property_transfers',
        -- 'zoning_bylaws', 'mepa_filings', 'tax_delinquency'

    status          VARCHAR(20) DEFAULT 'pending',
        -- 'pending', 'running', 'completed', 'failed', 'cancelled'

    -- Timing
    started_at      TIMESTAMP WITH TIME ZONE,
    completed_at    TIMESTAMP WITH TIME ZONE,

    -- Results
    records_found   INTEGER DEFAULT 0,  -- Total records discovered
    records_new     INTEGER DEFAULT 0,  -- New records (not previously seen)
    records_updated INTEGER DEFAULT 0,  -- Updated existing records

    -- Error tracking
    error_message   TEXT,
    error_count     INTEGER DEFAULT 0,

    -- Configuration snapshot (what settings were used)
    config          JSONB DEFAULT '{}',

    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ============================================================================
-- 4. Extend Towns Table
-- ============================================================================
-- Add columns for richer town profiles and scraping configuration.
-- ============================================================================

ALTER TABLE towns ADD COLUMN IF NOT EXISTS county VARCHAR(100);
ALTER TABLE towns ADD COLUMN IF NOT EXISTS population INTEGER;
ALTER TABLE towns ADD COLUMN IF NOT EXISTS median_home_value DECIMAL(12,2);
ALTER TABLE towns ADD COLUMN IF NOT EXISTS center_lat DOUBLE PRECISION;
ALTER TABLE towns ADD COLUMN IF NOT EXISTS center_lon DOUBLE PRECISION;
ALTER TABLE towns ADD COLUMN IF NOT EXISTS permit_portal_url TEXT;
ALTER TABLE towns ADD COLUMN IF NOT EXISTS permit_portal_type VARCHAR(50);
ALTER TABLE towns ADD COLUMN IF NOT EXISTS meeting_minutes_url TEXT;
ALTER TABLE towns ADD COLUMN IF NOT EXISTS assessor_url TEXT;
ALTER TABLE towns ADD COLUMN IF NOT EXISTS zoning_bylaw_url TEXT;
ALTER TABLE towns ADD COLUMN IF NOT EXISTS gis_portal_url TEXT;
ALTER TABLE towns ADD COLUMN IF NOT EXISTS registry_district VARCHAR(100);
ALTER TABLE towns ADD COLUMN IF NOT EXISTS scrape_schedule JSONB DEFAULT '{}';
ALTER TABLE towns ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();


-- ============================================================================
-- 5. Indexes
-- ============================================================================

-- Municipal documents
CREATE INDEX IF NOT EXISTS idx_municipal_docs_town_type
    ON municipal_documents(town_id, doc_type);
CREATE INDEX IF NOT EXISTS idx_municipal_docs_board
    ON municipal_documents(board);
CREATE INDEX IF NOT EXISTS idx_municipal_docs_date
    ON municipal_documents(meeting_date DESC);
CREATE INDEX IF NOT EXISTS idx_municipal_docs_hash
    ON municipal_documents(content_hash);

-- Property transfers
CREATE INDEX IF NOT EXISTS idx_property_transfers_town_date
    ON property_transfers(town_id, sale_date DESC);
CREATE INDEX IF NOT EXISTS idx_property_transfers_loc_id
    ON property_transfers(loc_id);
CREATE INDEX IF NOT EXISTS idx_property_transfers_city
    ON property_transfers(city);
CREATE INDEX IF NOT EXISTS idx_property_transfers_sale_price
    ON property_transfers(sale_price);

-- Scrape jobs
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_town_type
    ON scrape_jobs(town_id, source_type);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_status
    ON scrape_jobs(status);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_created
    ON scrape_jobs(created_at DESC);


-- ============================================================================
-- 6. GIN index on municipal_documents.mentions for JSONB queries
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_municipal_docs_mentions
    ON municipal_documents USING GIN (mentions);

CREATE INDEX IF NOT EXISTS idx_municipal_docs_keywords
    ON municipal_documents USING GIN (keywords);
