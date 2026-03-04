-- ============================================================================
-- Migration 002: Permits Table
-- ============================================================================
-- Dedicated permits table for structured permit records from all sources
-- (Socrata, ViewpointCloud, Firecrawl). Replaces the documents/metadata/locations
-- structure for new ingested permits.
-- ============================================================================

CREATE TABLE IF NOT EXISTS permits (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    town_id         VARCHAR(50) REFERENCES towns(id),

    -- Permit identifiers
    permit_number   VARCHAR(100) NOT NULL,
    permit_type     VARCHAR(100) DEFAULT 'Building',
        -- 'Building', 'Electrical', 'Plumbing', 'Gas', 'Mechanical',
        -- 'Demolition', 'Solar', 'Roofing', 'Siding', 'New Construction',
        -- 'Addition/Alteration', 'Certificate of Inspection', etc.

    status          VARCHAR(50) DEFAULT 'FILED',
        -- 'FILED', 'UNDER_REVIEW', 'APPROVED', 'ISSUED',
        -- 'IN_PROGRESS', 'COMPLETED', 'DENIED', 'WITHDRAWN', 'EXPIRED'

    -- Location
    address         TEXT,
    latitude        DOUBLE PRECISION DEFAULT 0,
    longitude       DOUBLE PRECISION DEFAULT 0,

    -- Details
    description     TEXT,
    estimated_value DECIMAL(12,2),
    applicant_name  TEXT,
    contractor_name TEXT,

    -- Dates
    filed_date      DATE,
    issued_date     DATE,
    completed_date  DATE,

    -- Source tracking
    source_system   VARCHAR(50),
        -- 'socrata', 'viewpointcloud', 'firecrawl', 'ckan'

    -- Metadata
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_permits_town
    ON permits(town_id);
CREATE INDEX IF NOT EXISTS idx_permits_number
    ON permits(permit_number);
CREATE INDEX IF NOT EXISTS idx_permits_town_number
    ON permits(town_id, permit_number);
CREATE INDEX IF NOT EXISTS idx_permits_address
    ON permits(address);
CREATE INDEX IF NOT EXISTS idx_permits_type
    ON permits(permit_type);
CREATE INDEX IF NOT EXISTS idx_permits_status
    ON permits(status);
CREATE INDEX IF NOT EXISTS idx_permits_filed_date
    ON permits(filed_date DESC);
CREATE INDEX IF NOT EXISTS idx_permits_location
    ON permits(latitude, longitude)
    WHERE latitude != 0 AND longitude != 0;
