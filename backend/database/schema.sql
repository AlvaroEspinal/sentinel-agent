-- ============================================================================
-- Parcl Intelligence -- Merged PostgreSQL Schema
-- ============================================================================
-- Combines municipal-intel permit/document tables with new property-centric
-- tables for the Sentinel Agent real estate platform.
--
-- Requires:  PostgreSQL 14+
-- Optional:  pgvector extension (for document embeddings)
-- ============================================================================

-- Enable pgvector if available (ignore error if not installed)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Towns (adapted from municipal-intel)
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

-- ============================================================================
-- Properties
-- ============================================================================
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

    -- ATTOM data (Phase 3)
    attom_id            VARCHAR(50),
    year_built          INTEGER,
    lot_size_sqft       DOUBLE PRECISION,
    living_area_sqft    DOUBLE PRECISION,
    bedrooms            INTEGER,
    bathrooms           DOUBLE PRECISION,
    property_type       VARCHAR(50),
    zoning              VARCHAR(50),

    -- Valuation
    tax_assessment      DECIMAL(12,2),
    last_sale_price     DECIMAL(12,2),
    last_sale_date      DATE,
    estimated_value     DECIMAL(12,2),

    -- Risk scores (Phase 3)
    flood_risk_score    INTEGER,
    fire_risk_score     INTEGER,
    heat_risk_score     INTEGER,
    wind_risk_score     INTEGER,

    -- Walk / transit / bike scores
    walk_score          INTEGER,
    transit_score       INTEGER,
    bike_score          INTEGER,

    -- Metadata
    data_sources        JSONB DEFAULT '[]',
    raw_data            JSONB DEFAULT '{}',
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Permits
-- ============================================================================
CREATE TABLE IF NOT EXISTS permits (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id         UUID REFERENCES properties(id),
    town_id             VARCHAR(50) REFERENCES towns(id),
    permit_number       VARCHAR(100),
    permit_type         VARCHAR(100),
    permit_status       VARCHAR(50),
    permit_value        DECIMAL(12,2),
    description         TEXT,
    applicant_name      VARCHAR(200),
    contractor_name     VARCHAR(200),
    address             TEXT,
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,
    filed_date          DATE,
    issued_date         DATE,
    completed_date      DATE,
    source_system       VARCHAR(50),        -- 'accela', 'opengov', 'boston'
    source_id           VARCHAR(200),
    raw_data            JSONB DEFAULT '{}',
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Listings
-- ============================================================================
CREATE TABLE IF NOT EXISTS listings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id         UUID REFERENCES properties(id),
    source              VARCHAR(50),        -- 'realtor', 'zillow', 'mls'
    mls_id              VARCHAR(50),
    list_price          DECIMAL(12,2),
    status              VARCHAR(50),        -- 'active', 'pending', 'sold', 'withdrawn'
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

-- ============================================================================
-- Property Agents (sentinel agents assigned to properties)
-- ============================================================================
CREATE TABLE IF NOT EXISTS property_agents (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id             UUID REFERENCES properties(id),
    agent_type              VARCHAR(50) NOT NULL,
        -- 'listing', 'neighborhood', 'portfolio', 'development_scout',
        -- 'climate_risk', 'market_pulse', 'community_intel'
    config                  JSONB DEFAULT '{}',
    status                  VARCHAR(20) DEFAULT 'active',
        -- 'active', 'paused', 'stopped'
    last_run                TIMESTAMP WITH TIME ZONE,
    next_run                TIMESTAMP WITH TIME ZONE,
    run_interval_seconds    INTEGER DEFAULT 300,
    findings_count          INTEGER DEFAULT 0,
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Agent Findings
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_findings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID REFERENCES property_agents(id),
    property_id         UUID REFERENCES properties(id),
    finding_type        VARCHAR(50),
        -- 'permit_activity', 'price_change', 'risk_update',
        -- 'construction', 'zoning_change'
    severity            VARCHAR(20) DEFAULT 'INFO',
        -- 'INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    title               TEXT NOT NULL,
    summary             TEXT,
    data                JSONB DEFAULT '{}',
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,
    acknowledged        BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Documents (with optional pgvector embedding)
-- ============================================================================
CREATE TABLE IF NOT EXISTS documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type         VARCHAR(50) NOT NULL,
        -- 'permit', 'listing', 'meeting_transcript', 'sec_filing'
    source_id           VARCHAR(200),
    town_id             VARCHAR(50) REFERENCES towns(id),
    property_id         UUID REFERENCES properties(id),
    content             TEXT NOT NULL,
    content_summary     TEXT,
    embedding           vector(1536),
    chunk_index         INTEGER DEFAULT 0,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- Portfolios
-- ============================================================================
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
-- Indexes
-- ============================================================================

-- pgvector HNSW index for cosine similarity search on document embeddings
-- This will only succeed if the pgvector extension is installed.
CREATE INDEX IF NOT EXISTS idx_documents_embedding
    ON documents USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Permits
CREATE INDEX IF NOT EXISTS idx_permits_town_id     ON permits (town_id);
CREATE INDEX IF NOT EXISTS idx_permits_address      ON permits (address);
CREATE INDEX IF NOT EXISTS idx_permits_permit_type  ON permits (permit_type);
CREATE INDEX IF NOT EXISTS idx_permits_filed_date   ON permits (filed_date);

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
