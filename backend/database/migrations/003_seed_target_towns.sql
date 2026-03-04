-- ============================================================================
-- Seed: 12 Target Towns for Parcl Intelligence Realtor MVP
-- ============================================================================
-- Inserts or updates the 12 affluent Massachusetts towns.
-- Uses ON CONFLICT DO UPDATE to be safely re-runnable.
-- ============================================================================

INSERT INTO towns (id, name, state, county, registry_district, center_lat, center_lon, population, median_home_value, permit_portal_url, permit_portal_type, meeting_minutes_url, assessor_url, zoning_bylaw_url, gis_portal_url, active)
VALUES
    ('newton', 'Newton', 'MA', 'Middlesex', 'southern_middlesex', 42.337, -71.209, 88923, 1350000, 'https://newtonma.viewpointcloud.com', 'viewpointcloud', 'https://www.newtonma.gov/government/city-council/agendas-minutes', 'https://www.newtonma.gov/government/assessing', 'https://ecode360.com/NE0839', 'https://www.newtonma.gov/government/information-technology/gis-maps', TRUE),
    ('wellesley', 'Wellesley', 'MA', 'Norfolk', 'norfolk', 42.297, -71.292, 29673, 1600000, 'https://www.wellesleyma.gov/197/Inspectional-Services', 'firecrawl', 'https://www.wellesleyma.gov/AgendaCenter', 'https://www.wellesleyma.gov/200/Board-of-Assessors', 'https://ecode360.com/WE0397', NULL, TRUE),
    ('weston', 'Weston', 'MA', 'Middlesex', 'southern_middlesex', 42.367, -71.303, 12135, 2200000, 'https://www.westonma.gov/298/Building-Department', 'firecrawl', 'https://www.westonma.gov/AgendaCenter', 'https://www.westonma.gov/107/Board-of-Assessors', 'https://ecode360.com/WE0479', NULL, TRUE),
    ('brookline', 'Brookline', 'MA', 'Norfolk', 'norfolk', 42.332, -71.121, 63191, 1200000, 'https://www.brooklinema.gov/168/Building-Department', 'firecrawl', 'https://www.brooklinema.gov/AgendaCenter', 'https://www.brooklinema.gov/180/Board-of-Assessors', 'https://ecode360.com/BR0778', NULL, TRUE),
    ('needham', 'Needham', 'MA', 'Norfolk', 'norfolk', 42.280, -71.233, 31388, 1150000, 'https://www.needhamma.gov/196/Building-Department', 'firecrawl', 'https://www.needhamma.gov/AgendaCenter', 'https://www.needhamma.gov/163/Assessors-Office', 'https://ecode360.com/NE0195', NULL, TRUE),
    ('dover', 'Dover', 'MA', 'Norfolk', 'norfolk', 42.246, -71.282, 6215, 1800000, NULL, 'firecrawl', 'https://www.doverma.gov/AgendaCenter', 'https://www.doverma.gov/137/Board-of-Assessors', NULL, NULL, TRUE),
    ('sherborn', 'Sherborn', 'MA', 'Middlesex', 'southern_middlesex', 42.238, -71.369, 4335, 1100000, NULL, 'firecrawl', 'https://www.sherbornma.org/agendas-minutes', NULL, NULL, NULL, TRUE),
    ('natick', 'Natick', 'MA', 'Middlesex', 'southern_middlesex', 42.283, -71.349, 36050, 850000, 'https://www.natickma.gov/283/Building-Department', 'firecrawl', 'https://www.natickma.gov/AgendaCenter', 'https://www.natickma.gov/277/Board-of-Assessors', NULL, NULL, TRUE),
    ('wayland', 'Wayland', 'MA', 'Middlesex', 'southern_middlesex', 42.363, -71.361, 13835, 1050000, NULL, 'firecrawl', 'https://www.wayland.ma.us/agendas-minutes', NULL, NULL, NULL, TRUE),
    ('lincoln', 'Lincoln', 'MA', 'Middlesex', 'southern_middlesex', 42.426, -71.305, 7012, 1400000, NULL, 'firecrawl', 'https://www.lincolntown.org/AgendaCenter', NULL, NULL, NULL, TRUE),
    ('concord', 'Concord', 'MA', 'Middlesex', 'southern_middlesex', 42.460, -71.349, 19872, 1250000, 'https://concordma.gov/581/Building-Inspections', 'firecrawl', 'https://concordma.gov/AgendaCenter', 'https://concordma.gov/285/Board-of-Assessors', 'https://ecode360.com/CO0735', NULL, TRUE),
    ('lexington', 'Lexington', 'MA', 'Middlesex', 'southern_middlesex', 42.443, -71.226, 34454, 1300000, 'https://www.lexingtonma.gov/building', 'firecrawl', 'https://www.lexingtonma.gov/AgendaCenter', 'https://www.lexingtonma.gov/assessors-office', 'https://ecode360.com/LE0741', NULL, TRUE)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    county = EXCLUDED.county,
    registry_district = EXCLUDED.registry_district,
    center_lat = EXCLUDED.center_lat,
    center_lon = EXCLUDED.center_lon,
    population = EXCLUDED.population,
    median_home_value = EXCLUDED.median_home_value,
    permit_portal_url = EXCLUDED.permit_portal_url,
    permit_portal_type = EXCLUDED.permit_portal_type,
    meeting_minutes_url = EXCLUDED.meeting_minutes_url,
    assessor_url = EXCLUDED.assessor_url,
    zoning_bylaw_url = EXCLUDED.zoning_bylaw_url,
    gis_portal_url = EXCLUDED.gis_portal_url,
    active = EXCLUDED.active,
    updated_at = NOW();
