-- ============================================================================
-- Migration 004: Property-Centric SQL Views
-- ============================================================================
-- Applied via Supabase MCP apply_migration (2026-03-11)
-- Drops and recreates all four views with correct column definitions.
--
-- Views:
--   1. v_property_360      — Single-row-per-property with aggregated permit + tax data
--   2. v_town_dashboard    — Town-level aggregates for dashboard display
--   3. v_property_timeline — Chronological events per property
--   4. v_coverage_matrix   — Data completeness tracking per town
-- ============================================================================

-- Drop existing views (they may have stale column definitions)
DROP VIEW IF EXISTS v_property_360 CASCADE;
DROP VIEW IF EXISTS v_town_dashboard CASCADE;
DROP VIEW IF EXISTS v_property_timeline CASCADE;
DROP VIEW IF EXISTS v_coverage_matrix CASCADE;

-- ============================================================================
-- View 1: v_property_360
-- ============================================================================
-- Full 360-degree view of each property with permit aggregates and tax
-- delinquency flag. One row per property. Uses LATERAL joins for efficiency.
-- ============================================================================

CREATE VIEW v_property_360 AS
SELECT
    p.id,
    p.address,
    p.normalized_address,
    p.city,
    p.state,
    p.zip,
    p.latitude,
    p.longitude,
    p.parcel_id,
    p.attom_id,
    p.year_built,
    p.lot_size_sqft,
    p.living_area_sqft,
    p.bedrooms,
    p.bathrooms,
    p.property_type,
    p.zoning,
    p.tax_assessment,
    p.last_sale_price,
    p.last_sale_date,
    p.estimated_value,
    p.flood_risk_score,
    p.fire_risk_score,
    p.heat_risk_score,
    p.wind_risk_score,
    p.walk_score,
    p.transit_score,
    p.bike_score,
    p.data_sources,
    p.raw_data,
    p.created_at,
    p.updated_at,
    COALESCE(pm.permit_count, 0)         AS permit_count,
    pm.latest_permit_date,
    pm.permit_types,
    COALESCE(pm.total_permit_value, 0)   AS total_permit_value,
    (td.id IS NOT NULL)                  AS tax_delinquent
FROM properties p
LEFT JOIN LATERAL (
    SELECT
        COUNT(*)::int                                        AS permit_count,
        MAX(GREATEST(per.filed_date, per.issued_date))       AS latest_permit_date,
        ARRAY_AGG(DISTINCT per.permit_type)
            FILTER (WHERE per.permit_type IS NOT NULL)       AS permit_types,
        SUM(COALESCE(per.permit_value, per.estimated_value, 0)) AS total_permit_value
    FROM permits per
    WHERE per.property_id = p.id
) pm ON true
LEFT JOIN LATERAL (
    SELECT tdp.id
    FROM tax_delinquent_parcels tdp
    WHERE (
        (tdp.parcel_id IS NOT NULL AND p.parcel_id IS NOT NULL
         AND LOWER(TRIM(tdp.parcel_id)) = LOWER(TRIM(p.parcel_id)))
        OR
        (tdp.address IS NOT NULL AND p.address IS NOT NULL
         AND LOWER(TRIM(tdp.address)) = LOWER(TRIM(p.address)))
    )
    LIMIT 1
) td ON true;

COMMENT ON VIEW v_property_360 IS 'Single-row-per-property view with aggregated permit counts, types, values, and tax delinquency flag';


-- ============================================================================
-- View 2: v_town_dashboard
-- ============================================================================
-- Town-level aggregates across all data sources.
-- Joins towns -> properties (via LOWER(city) = town_id), permits,
-- tax_delinquent_parcels, municipal_documents, and mepa_filings.
-- ============================================================================

CREATE VIEW v_town_dashboard AS
SELECT
    t.id                    AS town_id,
    t.name                  AS town_name,
    t.county,
    t.population,
    t.center_lat,
    t.center_lon,
    COALESCE(prop.total_properties, 0)       AS total_properties,
    COALESCE(prop.avg_tax_assessment, 0)     AS avg_tax_assessment,
    COALESCE(perm.permit_count, 0)           AS total_permits,
    COALESCE(tdp.tax_delinquent_count, 0)    AS tax_delinquent_count,
    COALESCE(mm.meeting_minutes_count, 0)    AS meeting_minutes_count,
    COALESCE(cip.cip_count, 0)               AS cip_count,
    COALESCE(mepa.mepa_filing_count, 0)      AS mepa_filing_count
FROM towns t
LEFT JOIN (
    SELECT
        LOWER(city) AS town_key,
        COUNT(*)::int AS total_properties,
        ROUND(AVG(tax_assessment), 2) AS avg_tax_assessment
    FROM properties
    WHERE city IS NOT NULL
    GROUP BY LOWER(city)
) prop ON prop.town_key = t.id
LEFT JOIN (
    SELECT
        town_id,
        COUNT(*)::int AS permit_count
    FROM permits
    WHERE town_id IS NOT NULL
    GROUP BY town_id
) perm ON perm.town_id = t.id
LEFT JOIN (
    SELECT
        town_id,
        COUNT(*)::int AS tax_delinquent_count
    FROM tax_delinquent_parcels
    WHERE town_id IS NOT NULL
    GROUP BY town_id
) tdp ON tdp.town_id = t.id
LEFT JOIN (
    SELECT
        town_id,
        COUNT(*)::int AS meeting_minutes_count
    FROM municipal_documents
    WHERE doc_type = 'meeting_minutes'
      AND town_id IS NOT NULL
    GROUP BY town_id
) mm ON mm.town_id = t.id
LEFT JOIN (
    SELECT
        town_id,
        COUNT(*)::int AS cip_count
    FROM municipal_documents
    WHERE doc_type = 'capital_improvement'
      AND town_id IS NOT NULL
    GROUP BY town_id
) cip ON cip.town_id = t.id
LEFT JOIN (
    SELECT
        town_id,
        COUNT(*)::int AS mepa_filing_count
    FROM mepa_filings
    WHERE town_id IS NOT NULL
    GROUP BY town_id
) mepa ON mepa.town_id = t.id;

COMMENT ON VIEW v_town_dashboard IS 'Town-level dashboard aggregates: properties, permits, tax delinquency, meeting minutes, CIP, MEPA filings';


-- ============================================================================
-- View 3: v_property_timeline
-- ============================================================================
-- Chronological event feed per property.
-- UNIONs permit filed/issued/completed events with property sale events.
-- ============================================================================

CREATE VIEW v_property_timeline AS
-- Permit filed events
SELECT
    per.property_id,
    p.address,
    p.city,
    'permit_filed'::text        AS event_type,
    per.filed_date              AS event_date,
    per.permit_type             AS event_subtype,
    per.description             AS event_description,
    per.permit_value            AS event_value,
    per.id                      AS source_id
FROM permits per
JOIN properties p ON p.id = per.property_id
WHERE per.filed_date IS NOT NULL
  AND per.property_id IS NOT NULL

UNION ALL

-- Permit issued events
SELECT
    per.property_id,
    p.address,
    p.city,
    'permit_issued'::text       AS event_type,
    per.issued_date             AS event_date,
    per.permit_type             AS event_subtype,
    per.description             AS event_description,
    per.permit_value            AS event_value,
    per.id                      AS source_id
FROM permits per
JOIN properties p ON p.id = per.property_id
WHERE per.issued_date IS NOT NULL
  AND per.property_id IS NOT NULL

UNION ALL

-- Permit completed events
SELECT
    per.property_id,
    p.address,
    p.city,
    'permit_completed'::text    AS event_type,
    per.completed_date          AS event_date,
    per.permit_type             AS event_subtype,
    per.description             AS event_description,
    per.permit_value            AS event_value,
    per.id                      AS source_id
FROM permits per
JOIN properties p ON p.id = per.property_id
WHERE per.completed_date IS NOT NULL
  AND per.property_id IS NOT NULL

UNION ALL

-- Property sale events
SELECT
    p.id                        AS property_id,
    p.address,
    p.city,
    'sale'::text                AS event_type,
    p.last_sale_date            AS event_date,
    p.property_type             AS event_subtype,
    ('Sale at ' || COALESCE(p.last_sale_price::text, 'unknown price'))::text
                                AS event_description,
    p.last_sale_price           AS event_value,
    p.id                        AS source_id
FROM properties p
WHERE p.last_sale_date IS NOT NULL;

COMMENT ON VIEW v_property_timeline IS 'Chronological event feed per property: permit filed/issued/completed + sales';


-- ============================================================================
-- View 4: v_coverage_matrix
-- ============================================================================
-- Data completeness matrix per town.
-- Shows property/permit/geocoded counts, linked permits, MEPA,
-- tax delinquency, meeting minutes, and CIP counts.
-- ============================================================================

CREATE VIEW v_coverage_matrix AS
SELECT
    t.id                    AS town_id,
    t.name                  AS town_name,
    COALESCE(prop.property_count, 0)         AS property_count,
    COALESCE(perm.permit_count, 0)           AS permit_count,
    COALESCE(perm.linked_permit_count, 0)    AS linked_permit_count,
    CASE
        WHEN COALESCE(perm.permit_count, 0) = 0 THEN 0
        ELSE ROUND(
            100.0 * COALESCE(perm.geocoded_count, 0) / perm.permit_count, 1
        )
    END                                       AS pct_geocoded,
    COALESCE(mepa.mepa_count, 0)             AS mepa_count,
    COALESCE(tdp.tax_delinquent_count, 0)    AS tax_delinquent_count,
    COALESCE(mm.meeting_minutes_count, 0)    AS meeting_minutes_count,
    COALESCE(cip.cip_count, 0)               AS cip_count
FROM towns t
LEFT JOIN (
    SELECT
        LOWER(city) AS town_key,
        COUNT(*)::int AS property_count
    FROM properties
    WHERE city IS NOT NULL
    GROUP BY LOWER(city)
) prop ON prop.town_key = t.id
LEFT JOIN (
    SELECT
        town_id,
        COUNT(*)::int AS permit_count,
        COUNT(*) FILTER (WHERE property_id IS NOT NULL)::int AS linked_permit_count,
        COUNT(*) FILTER (WHERE latitude IS NOT NULL
                         AND longitude IS NOT NULL
                         AND latitude != 0
                         AND longitude != 0)::int AS geocoded_count
    FROM permits
    WHERE town_id IS NOT NULL
    GROUP BY town_id
) perm ON perm.town_id = t.id
LEFT JOIN (
    SELECT
        town_id,
        COUNT(*)::int AS mepa_count
    FROM mepa_filings
    WHERE town_id IS NOT NULL
    GROUP BY town_id
) mepa ON mepa.town_id = t.id
LEFT JOIN (
    SELECT
        town_id,
        COUNT(*)::int AS tax_delinquent_count
    FROM tax_delinquent_parcels
    WHERE town_id IS NOT NULL
    GROUP BY town_id
) tdp ON tdp.town_id = t.id
LEFT JOIN (
    SELECT
        town_id,
        COUNT(*)::int AS meeting_minutes_count
    FROM municipal_documents
    WHERE doc_type = 'meeting_minutes'
      AND town_id IS NOT NULL
    GROUP BY town_id
) mm ON mm.town_id = t.id
LEFT JOIN (
    SELECT
        town_id,
        COUNT(*)::int AS cip_count
    FROM municipal_documents
    WHERE doc_type = 'capital_improvement'
      AND town_id IS NOT NULL
    GROUP BY town_id
) cip ON cip.town_id = t.id;

COMMENT ON VIEW v_coverage_matrix IS 'Data completeness matrix per town: property/permit/geocoded counts, MEPA, tax delinquency, meeting minutes, CIP';
