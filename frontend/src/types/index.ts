// ─── Parcl Intelligence — Type Definitions ─────────────────────────────────
// Clean real-estate + geospatial types. Hedge fund types removed.

// ─── Alert / Finding Severity ──────────────────────────────────────────────
export type AlertSeverity = "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

// ─── Finding Type ──────────────────────────────────────────────────────────
export type FindingType =
  | "PERMIT_ACTIVITY"
  | "PRICE_CHANGE"
  | "RISK_UPDATE"
  | "CONSTRUCTION"
  | "ZONING_CHANGE"
  | "LISTING_CHANGE"
  | "MARKET_SHIFT"
  | "MEETING_MENTION";

export type FindingSeverity = AlertSeverity;

// ─── Property Type ─────────────────────────────────────────────────────────
export type PropertyType =
  | "SINGLE_FAMILY"
  | "MULTI_FAMILY"
  | "CONDO"
  | "TOWNHOUSE"
  | "LAND"
  | "COMMERCIAL"
  | "MIXED_USE"
  | "OTHER";

// ─── Agent Type ────────────────────────────────────────────────────────────
export type AgentType =
  | "listing"
  | "neighborhood"
  | "portfolio"
  | "development_scout"
  | "climate_risk"
  | "market_pulse"
  | "community_intel";

// ─── Visualization Mode ────────────────────────────────────────────────────
export type ViewMode = "standard" | "satellite" | "risk";

// ─── Left Panel Tab ────────────────────────────────────────────────────────
export type LeftPanelTab = "summary" | "permits" | "risk" | "agents";

// ─── Permit Status ─────────────────────────────────────────────────────────
export type PermitStatus =
  | "FILED"
  | "UNDER_REVIEW"
  | "APPROVED"
  | "ISSUED"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "DENIED"
  | "WITHDRAWN"
  | "EXPIRED";

// ─── Listing Status ────────────────────────────────────────────────────────
export type ListingStatus =
  | "ACTIVE"
  | "PENDING"
  | "SOLD"
  | "WITHDRAWN"
  | "EXPIRED"
  | "COMING_SOON";

// ─── Property Agent Status ─────────────────────────────────────────────────
export type PropertyAgentStatus = "active" | "paused" | "stopped" | "error";

// ─── Camera Target ─────────────────────────────────────────────────────────
export interface CameraTarget {
  lat: number;
  lon: number;
  altitude: number;
  heading: number;
  pitch: number;
}

// ─── WebSocket Message Types ───────────────────────────────────────────────
export type WSMessageType =
  | "connection_established"
  | "permits_update"
  | "property_update"
  | "agent_finding"
  | "property_agent_status";

export interface WSMessage {
  type: WSMessageType;
  data: unknown;
  timestamp?: string;
}

// ─── Risk & Neighborhood Scores ────────────────────────────────────────────

export interface RiskScores {
  flood_risk: number | null;
  fire_risk: number | null;
  heat_risk: number | null;
  wind_risk: number | null;
  environmental_risk: number | null;
  overall_risk: number | null;
  source: string | null;
  assessed_at: string | null;
}

export interface NeighborhoodScores {
  walk_score: number | null;
  transit_score: number | null;
  bike_score: number | null;
  school_rating: number | null;
  median_income: number | null;
  population_growth_pct: number | null;
  source: string | null;
}

// ─── Property ──────────────────────────────────────────────────────────────

export interface Property {
  id: string;
  address: string;
  normalized_address: string | null;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  latitude: number;
  longitude: number;
  parcel_id: string | null;
  property_type: PropertyType;
  year_built: number | null;
  lot_size_sqft: number | null;
  living_area_sqft: number | null;
  bedrooms: number | null;
  bathrooms: number | null;
  zoning: string | null;
  tax_assessment: number | null;
  last_sale_price: number | null;
  last_sale_date: string | null;
  estimated_value: number | null;
  risk_scores: RiskScores | null;
  neighborhood_scores: NeighborhoodScores | null;
  data_sources: string[];
  created_at: string;
  updated_at: string;
  active_agents_count: number;
  nearby_permits_count: number;
}

// ─── Permit ────────────────────────────────────────────────────────────────

export interface Permit {
  id: string;
  property_id: string | null;
  town_id: string | null;
  permit_number: string | null;
  permit_type: string | null;
  status: PermitStatus;
  estimated_value: number | null;
  description: string | null;
  applicant_name: string | null;
  contractor_name: string | null;
  address: string | null;
  latitude: number;
  longitude: number;
  filed_date: string | null;
  issued_date: string | null;
  completed_date: string | null;
  source_system: string | null;
  distance_km?: number;
  relevance_score?: number;
  created_at: string;
}

// ─── Town (Municipality) ──────────────────────────────────────────────────

export interface Town {
  id: string;
  name: string;
  state: string;
  county: string | null;
  permit_count: number;
  active: boolean;
}

// ─── Listing ───────────────────────────────────────────────────────────────

export interface Listing {
  id: string;
  property_id: string | null;
  source: string | null;
  mls_id: string | null;
  list_price: number | null;
  status: ListingStatus;
  days_on_market: number | null;
  price_per_sqft: number | null;
  listing_url: string | null;
  agent_name: string | null;
  brokerage: string | null;
  listed_at: string | null;
  sold_at: string | null;
  sold_price: number | null;
  created_at: string;
}

// ─── Property Monitor Agent ────────────────────────────────────────────────

export interface PropertyMonitorAgent {
  id: string;
  entity_type: string;
  entity_id: string | null;
  agent_type: AgentType;
  name: string;
  config: Record<string, unknown>;
  status: PropertyAgentStatus;
  last_run: string | null;
  next_run: string | null;
  run_interval_seconds: number;
  findings_count: number;
  created_at: string;
}

/** Convenience alias */
export type PropertyAgent = PropertyMonitorAgent;

// ─── Agent Finding ─────────────────────────────────────────────────────────

export interface AgentFinding {
  id: string;
  agent_id: string;
  property_id: string | null;
  finding_type: FindingType;
  severity: AlertSeverity;
  title: string;
  summary: string;
  data: Record<string, unknown>;
  latitude: number | null;
  longitude: number | null;
  acknowledged: boolean;
  created_at: string;
}

// ─── Property Portfolio ────────────────────────────────────────────────────

export interface PropertyPortfolio {
  id: string;
  name: string;
  description: string | null;
  properties: Property[];
  total_estimated_value: number | null;
  average_risk_score: number | null;
  active_agents_count: number;
  created_at: string;
}

// ─── Chat ──────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  sources?: { permit_number: string; address: string; relevance: number }[];
  suggested_questions?: string[];
}

export interface ChatResponse {
  content: string;
  sources: { permit_number: string; address: string; relevance: number }[];
  permits_found: number;
  suggested_questions: string[];
  confidence: number;
}

// ─── Search Request Types ──────────────────────────────────────────────────

export interface PropertySearchRequest {
  q?: string;
  address?: string;
  city?: string;
  lat?: number;
  lon?: number;
  radius_km?: number;
  limit?: number;
}

export interface PermitSearchRequest {
  q?: string;
  address?: string;
  town?: string;
  permit_type?: string;
  status?: string;
  lat?: number;
  lon?: number;
  radius_km?: number;
  filed_after?: string;
  min_value?: number;
  limit?: number;
}

// ─── Coverage & Source Requirements ─────────────────────────────────────────

export interface SourceRequirement {
  id: string;
  label: string;
  category: string;
  active: boolean;
  total_municipalities: number;
  ready: number;
  pending: number;
  status_breakdown: Record<string, number>;
}

export interface CoverageSummary {
  sources: SourceRequirement[];
  total_source_types: number;
  total_municipalities: number;
  total_coverage_rows: number;
}

export interface MunicipalityCoverage {
  source_id: string;
  source_label: string;
  category: string;
  status: string;
  ingestion_method: string | null;
  source_url: string | null;
  source_system: string | null;
  priority: number;
  last_checked_at: string | null;
  last_ingested_at: string | null;
  notes: string;
}

export interface TownDetail {
  id: string;
  name: string;
  state: string;
  county: string | null;
  population: number | null;
  permit_count: number;
  permit_portal_url: string | null;
  coverage_total: number;
  coverage_ready: number;
  coverage_pct: number;
}

// ─── App View ─────────────────────────────────────────────────────────────
export type AppView = "dashboard" | "search" | "property" | "town" | "map";

// ─── Municipal Document (meeting minutes, filings) ──────────────────────
export interface MunicipalDocument {
  id: string;
  town_id: string;
  doc_type: string;
  board: string | null;
  title: string;
  meeting_date: string | null;
  source_url: string | null;
  file_url: string | null;
  content_summary: string | null;
  keywords: string[];
  mentions: Record<string, unknown> | null;
  scraped_at: string | null;
}

// ─── Property Transfer ──────────────────────────────────────────────────
export interface PropertyTransfer {
  id: string;
  town_id: string;
  loc_id: string | null;
  site_addr: string | null;
  owner: string | null;
  sale_date: string | null;
  sale_price: number | null;
  book_page: string | null;
  assessed_value: number | null;
  price_per_sqft: number | null;
  building_area: number | null;
  lot_size_acres: number | null;
  year_built: number | null;
  style: string | null;
  use_code: string | null;
}

// ─── Town Config (from backend registry) ────────────────────────────────
export interface TownConfig {
  id: string;
  name: string;
  county: string;
  population: number;
  median_home_value: number;
  center: { lat: number; lon: number };
  permit_portal_type: string;
  boards: string[];
}

// ─── Town Dashboard Data ────────────────────────────────────────────────
export interface TownDashboardData {
  town: {
    id: string;
    name: string;
    county: string;
    median_home_value: number;
    population: number;
  };
  stats: Record<string, unknown>;
  recent_sales: PropertyTransfer[];
  recent_documents: MunicipalDocument[];
  scrape_jobs: Array<Record<string, unknown>>;
}

// ─── Activity Feed Item ─────────────────────────────────────────────────
export interface ActivityItem {
  type: "sale" | "document" | "permit";
  date: string;
  title: string;
  detail: string;
  data: Record<string, unknown>;
}

// ─── Parcel Search Result ───────────────────────────────────────────────
export interface ParcelSearchResult {
  loc_id: string | null;
  site_addr: string | null;
  city: string | null;
  owner: string | null;
  last_sale_date: string | null;
  last_sale_price: number | null;
  total_value: number | null;
  building_area_sqft: number | null;
  lot_size_acres: number | null;
  year_built: number | null;
  use_code: string | null;
  style: string | null;
}

// ── Listing Tracking ──
export type ListingTrackingStatus = "active" | "potential" | "archived";

export interface TrackedListing {
  id: string;
  address: string;
  city: string | null;
  state: string | null;
  latitude: number;
  longitude: number;
  trackingStatus: ListingTrackingStatus;
  agentId?: string;
  addedAt: string;
  notes?: string;
}
