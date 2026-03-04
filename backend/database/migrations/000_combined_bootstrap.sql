-- ============================================================================
-- Parcl Intelligence — Combined Bootstrap Migration
-- ============================================================================
-- Run this ONCE in Supabase SQL Editor to create all tables.
-- Safe to re-run (uses IF NOT EXISTS / IF NOT EXISTS throughout).
--
-- Order: base tables → extensions → migration 001 → migration 002 → indexes
-- ============================================================================

-- ── Extensions ──
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. Base Tables (from schema.sql)
-- ============================================================================

CREATE TABLE IF NOT EXISTS towns (
    id              VARCHAR(50) PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    state           VARCHAR(2)  DEFAULT 'MA',
    scraper_config  JSONB       DEFAULT '{}',
    active          BOOLEAN     DEFAULT TRUE,
    last_scraped    TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS properties (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address             TEXT NOT NULL,
    normalized_address  TEXT,
    city                VARCHAR(100),
    state               VARCHAR(2),
    zip                 VARCHAR(10),
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,
    parcel_id           VARCHAR(50),
    attom_id            VARCHAR(50),
    year_built          INTEGER,
    lot_size_sqft       DOUBLE PRECISION,
    living_area_sqft    DOUBLE PRECISION,
    bedrooms            INTEGER,
    bathrooms           DOUBLE PRECISION,
    property_type       VARCHAR(50),
    zoning              VARCHAR(50),
    tax_assessment      DECIMAL(12,2),
    last_sale_price     DECIMAL(12,2),
    last_sale_date      DATE,
    estimated_value     DECIMAL(12,2),
    flood_risk_score    INTEGER,
    fire_risk_score     INTEGER,
    heat_risk_score     INTEGER,
    wind_risk_score     INTEGER,
    walk_score          INTEGER,
    transit_score       INTEGER,
    bike_score          INTEGER,
    data_sources        JSONB DEFAULT '[]',
    raw_data            JSONB DEFAULT '{}',
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS permits (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id         UUID REFERENCES properties(id),
    town_id             VARCHAR(50) REFERENCES towns(id),
    permit_number       VARCHAR(100),
    permit_type         VARCHAR(100) DEFAULT 'Building',
    permit_status       VARCHAR(50),
    status              VARCHAR(50) DEFAULT 'FILED',
    permit_value        DECIMAL(12,2),
    estimated_value     DECIMAL(12,2),
    description         TEXT,
    applicant_name      TEXT,
    contractor_name     TEXT,
    address             TEXT,
    latitude            DOUBLE PRECISION DEFAULT 0,
    longitude           DOUBLE PRECISION DEFAULT 0,
    filed_date          DATE,
    issued_date         DATE,
    completed_date      DATE,
    source_system       VARCHAR(50),
    source_id           VARCHAR(200),
    raw_data            JSONB DEFAULT '{}',
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS listings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id         UUID REFERENCES properties(id),
    source              VARCHAR(50),
    mls_id              VARCHAR(50),
    list_price          DECIMAL(12,2),
    status              VARCHAR(50),
    days_on_market      INTEGER,
    price_per_sqft      DECIMAL(10,2),
    listing_url         TEXT,
    agent_name          VARCHAR(200),
    brokerage           VARCHAR(200),
    raw_data            JSONB DEFAULT '{}',
    listed_at           TIMESTAMP WITH TIME ZONE,
    sold_at             TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS property_agents (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id             UUID REFERENCES properties(id),
    agent_type              VARCHAR(50) NOT NULL,
    config                  JSONB DEFAULT '{}',
    status                  VARCHAR(20) DEFAULT 'active',
    last_run                TIMESTAMP WITH TIME ZONE,
    next_run                TIMESTAMP WITH TIME ZONE,
    run_interval_seconds    INTEGER DEFAULT 300,
    findings_count          INTEGER DEFAULT 0,
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_findings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID REFERENCES property_agents(id),
    property_id         UUID REFERENCES properties(id),
    finding_type        VARCHAR(50),
    severity            VARCHAR(20) DEFAULT 'INFO',
    title               TEXT NOT NULL,
    summary             TEXT,
    data                JSONB DEFAULT '{}',
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,
    acknowledged        BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type         VARCHAR(50) NOT NULL,
    source_id           VARCHAR(200),
    town_id             VARCHAR(50) REFERENCES towns(id),
    property_id         UUID REFERENCES properties(id),
    content             TEXT NOT NULL,
    content_summary     TEXT,
    embedding           vector(1536),
    chunk_index         INTEGER DEFAULT 0,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS portfolios (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                VARCHAR(200) NOT NULL,
    description         TEXT,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS portfolio_properties (
    portfolio_id        UUID REFERENCES portfolios(id),
    property_id         UUID REFERENCES properties(id),
    added_at            TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes               TEXT,
    PRIMARY KEY (portfolio_id, property_id)
);


-- ============================================================================
-- 2. Migration 001 — Realtor MVP tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS municipal_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    town_id         VARCHAR(50) REFERENCES towns(id),
    doc_type        VARCHAR(50) NOT NULL,
    board           VARCHAR(100),
    title           TEXT NOT NULL,
    meeting_date    DATE,
    source_url      TEXT,
    file_url        TEXT,
    content_text    TEXT,
    content_summary TEXT,
    keywords        TEXT[] DEFAULT '{}',
    mentions        JSONB DEFAULT '[]',
    page_count      INTEGER,
    file_size_bytes INTEGER,
    content_hash    VARCHAR(64),
    scraped_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at    TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS property_transfers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    town_id         VARCHAR(50) REFERENCES towns(id),
    loc_id          VARCHAR(50),
    map_par_id      VARCHAR(50),
    site_addr       TEXT,
    city            VARCHAR(100),
    owner           TEXT,
    use_code        VARCHAR(10),
    use_description VARCHAR(200),
    grantor         TEXT,
    grantee         TEXT,
    sale_date       DATE,
    sale_price      DECIMAL(12,2),
    book_page       VARCHAR(50),
    doc_type        VARCHAR(50) DEFAULT 'deed',
    assessed_value  DECIMAL(12,2),
    building_value  DECIMAL(12,2),
    land_value      DECIMAL(12,2),
    price_per_sqft  DECIMAL(10,2),
    building_area   INTEGER,
    lot_size_acres  DECIMAL(10,4),
    year_built      INTEGER,
    style           VARCHAR(100),
    fiscal_year     VARCHAR(4),
    scraped_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scrape_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    town_id         VARCHAR(50) REFERENCES towns(id),
    source_type     VARCHAR(50) NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',
    started_at      TIMESTAMP WITH TIME ZONE,
    completed_at    TIMESTAMP WITH TIME ZONE,
    records_found   INTEGER DEFAULT 0,
    records_new     INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    error_message   TEXT,
    error_count     INTEGER DEFAULT 0,
    config          JSONB DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ============================================================================
-- 3. Extend towns table (Migration 001)
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
-- 4. All Indexes
-- ============================================================================

-- pgvector HNSW index for cosine similarity search
CREATE INDEX IF NOT EXISTS idx_documents_embedding
    ON documents USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Permits
CREATE INDEX IF NOT EXISTS idx_permits_town_id     ON permits (town_id);
CREATE INDEX IF NOT EXISTS idx_permits_address      ON permits (address);
CREATE INDEX IF NOT EXISTS idx_permits_permit_type  ON permits (permit_type);
CREATE INDEX IF NOT EXISTS idx_permits_filed_date   ON permits (filed_date);
CREATE INDEX IF NOT EXISTS idx_permits_number       ON permits (permit_number);
CREATE INDEX IF NOT EXISTS idx_permits_town_number  ON permits (town_id, permit_number);
CREATE INDEX IF NOT EXISTS idx_permits_type         ON permits (permit_type);
CREATE INDEX IF NOT EXISTS idx_permits_status       ON permits (status);
CREATE INDEX IF NOT EXISTS idx_permits_location
    ON permits (latitude, longitude)
    WHERE latitude != 0 AND longitude != 0;

-- Properties
CREATE INDEX IF NOT EXISTS idx_properties_city_state ON properties (city, state);
CREATE INDEX IF NOT EXISTS idx_properties_zip        ON properties (zip);
CREATE INDEX IF NOT EXISTS idx_properties_parcel_id  ON properties (parcel_id);

-- Listings
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings (status);
CREATE INDEX IF NOT EXISTS idx_listings_source ON listings (source);

-- Property agents & findings
CREATE INDEX IF NOT EXISTS idx_property_agents_status             ON property_agents (status);
CREATE INDEX IF NOT EXISTS idx_agent_findings_agent_id_created_at ON agent_findings (agent_id, created_at);

-- Municipal documents
CREATE INDEX IF NOT EXISTS idx_municipal_docs_town_type ON municipal_documents (town_id, doc_type);
CREATE INDEX IF NOT EXISTS idx_municipal_docs_board     ON municipal_documents (board);
CREATE INDEX IF NOT EXISTS idx_municipal_docs_date      ON municipal_documents (meeting_date DESC);
CREATE INDEX IF NOT EXISTS idx_municipal_docs_hash      ON municipal_documents (content_hash);
CREATE INDEX IF NOT EXISTS idx_municipal_docs_mentions  ON municipal_documents USING GIN (mentions);
CREATE INDEX IF NOT EXISTS idx_municipal_docs_keywords  ON municipal_documents USING GIN (keywords);

-- Property transfers
CREATE INDEX IF NOT EXISTS idx_property_transfers_town_date  ON property_transfers (town_id, sale_date DESC);
CREATE INDEX IF NOT EXISTS idx_property_transfers_loc_id     ON property_transfers (loc_id);
CREATE INDEX IF NOT EXISTS idx_property_transfers_city       ON property_transfers (city);
CREATE INDEX IF NOT EXISTS idx_property_transfers_sale_price ON property_transfers (sale_price);

-- Scrape jobs
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_town_type ON scrape_jobs (town_id, source_type);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_status    ON scrape_jobs (status);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_created   ON scrape_jobs (created_at DESC);
