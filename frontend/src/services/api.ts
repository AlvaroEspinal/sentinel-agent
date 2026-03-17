import type {
  Property,
  Permit,
  Town,
  ChatResponse,
  PropertyMonitorAgent,
  AgentFinding,
  CoverageSummary,
  MunicipalityCoverage,
  TownDetail,
  MepaFiling,
  CipDocument,
  TownDashboardStats,
} from "../types";

// ─── Base configuration ─────────────────────────────────────────────────────
const API_BASE =
  import.meta.env.VITE_API_URL ||
  `http://${window.location.hostname}:8000`;

// ─── Property API ───────────────────────────────────────────────────────────

export async function searchProperties(params: {
  q?: string;
  address?: string;
  city?: string;
  lat?: number;
  lon?: number;
  radius_km?: number;
  limit?: number;
}): Promise<{ properties: Property[]; total: number }> {
  const searchParams = new URLSearchParams();
  if (params.q) searchParams.set("q", params.q);
  if (params.address) searchParams.set("address", params.address);
  if (params.city) searchParams.set("city", params.city);
  if (params.lat !== undefined) searchParams.set("lat", String(params.lat));
  if (params.lon !== undefined) searchParams.set("lon", String(params.lon));
  if (params.radius_km !== undefined)
    searchParams.set("radius_km", String(params.radius_km));
  if (params.limit !== undefined)
    searchParams.set("limit", String(params.limit));
  const res = await fetch(`${API_BASE}/api/properties/search?${searchParams}`);
  return res.json();
}

export async function getProperty(propertyId: string): Promise<Property> {
  const res = await fetch(`${API_BASE}/api/properties/${propertyId}`);
  return res.json();
}

// ─── Permit API ─────────────────────────────────────────────────────────────

export async function searchPermits(params: {
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
}): Promise<{ permits: Permit[]; total: number }> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, val]) => {
    if (val !== undefined && val !== null) searchParams.set(key, String(val));
  });
  const res = await fetch(`${API_BASE}/api/permits/search?${searchParams}`);
  return res.json();
}

export async function getPermitsNear(
  lat: number,
  lon: number,
  radius_km = 1.0,
  limit = 20
): Promise<{ permits: Permit[]; total: number }> {
  const res = await fetch(
    `${API_BASE}/api/permits/near/${lat}/${lon}?radius_km=${radius_km}&limit=${limit}`
  );
  return res.json();
}

export async function getPermitTowns(): Promise<{
  towns: Town[];
}> {
  const res = await fetch(`${API_BASE}/api/permits/towns`);
  return res.json();
}

// ─── Coverage API ──────────────────────────────────────────────────────────

export async function getCoverageSummary(): Promise<CoverageSummary> {
  const res = await fetch(`${API_BASE}/api/coverage/summary`);
  return res.json();
}

export async function getMunicipalityCoverage(
  municipalityId: string
): Promise<{ municipality_id: string; sources: MunicipalityCoverage[]; total: number }> {
  const res = await fetch(`${API_BASE}/api/coverage/municipality/${municipalityId}`);
  return res.json();
}

export async function listTowns(params?: {
  q?: string;
  limit?: number;
}): Promise<{ towns: TownDetail[]; total: number }> {
  const searchParams = new URLSearchParams();
  if (params?.q) searchParams.set("q", params.q);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  const qs = searchParams.toString();
  const res = await fetch(`${API_BASE}/api/towns${qs ? `?${qs}` : ""}`);
  return res.json();
}

// ─── Chat API ───────────────────────────────────────────────────────────────

export async function sendChatMessage(
  message: string,
  propertyId?: string,
  context?: string
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, property_id: propertyId, context }),
  });
  return res.json();
}

// ─── Listing Enrichment API ──────────────────────────────────────────────────

export async function enrichListing(params: {
  address: string;
  latitude?: number;
  longitude?: number;
}): Promise<{ permits: Permit[]; total: number }> {
  const res = await fetch(`${API_BASE}/api/listings/enrich`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    return { permits: [], total: 0 };
  }
  return res.json();
}

// ─── Geocoding API ─────────────────────────────────────────────────────────

export async function geocodeAddress(address: string): Promise<{
  lat: number | null;
  lon: number | null;
  display_name: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
}> {
  const res = await fetch(
    `${API_BASE}/api/geocode?address=${encodeURIComponent(address)}`
  );
  return res.json();
}

// ─── Flood Zone API ────────────────────────────────────────────────────────

export interface FloodZoneInfo {
  flood_zone: string | null;
  zone_subtype: string | null;
  in_sfha: boolean;
  base_flood_elevation: number | null;
  risk_level: string;
  description: string;
}

export async function getFloodZone(
  lat: number,
  lon: number
): Promise<FloodZoneInfo> {
  const res = await fetch(
    `${API_BASE}/api/flood-zone?lat=${lat}&lon=${lon}`
  );
  return res.json();
}

// ─── Parcel API ────────────────────────────────────────────────────────────

export interface ParcelInfo {
  loc_id: string | null;
  site_addr: string | null;
  city: string | null;
  owner: string | null;
  last_sale_date: string | null;
  last_sale_price: number | null;
  building_value: number | null;
  land_value: number | null;
  total_value: number | null;
  use_code: string | null;
  lot_size: number | null;
  lot_size_acres: number | null;
  year_built: number | null;
  building_area_sqft: number | null;
  fiscal_year: string | null;
  geometry: unknown | null;
}

export async function getParcelInfo(
  lat: number,
  lon: number
): Promise<ParcelInfo> {
  const res = await fetch(
    `${API_BASE}/api/parcels?lat=${lat}&lon=${lon}`
  );
  return res.json();
}

// ─── Zoning API ────────────────────────────────────────────────────────────

export interface ZoningInfo {
  zone_code: string | null;
  zone_name: string | null;
  allowed_uses: string[];
  description: string | null;
  min_lot_size: number | null;
  min_lot_size_sqft: number | null;
  max_height_ft: number | null;
  max_density: string | null;
  jurisdiction: string | null;
}

export async function getZoning(
  lat: number,
  lon: number
): Promise<ZoningInfo> {
  const res = await fetch(
    `${API_BASE}/api/zoning?lat=${lat}&lon=${lon}`
  );
  return res.json();
}

// ─── Land Records / Ownership API ──────────────────────────────────────────

export interface LandRecord {
  doc_type: string;
  grantor: string | null;
  grantee: string | null;
  recording_date: string | null;
  book_page: string | null;
  consideration: number | null;
  description: string | null;
}

export interface OwnershipInfo {
  owner: string;
  mailing_address: string;
  mailing_city: string;
  mailing_state: string;
  mailing_zip: string;
  site_address: string;
  city: string;
  total_assessed_value: number | null;
  building_value: number | null;
  land_value: number | null;
}

export interface OwnershipResponse {
  ownership: OwnershipInfo | null;
  records: LandRecord[];
  total: number;
  source: string;
}

export async function getLandRecords(
  lat: number,
  lon: number
): Promise<OwnershipResponse> {
  const res = await fetch(
    `${API_BASE}/api/land-records?lat=${lat}&lon=${lon}`
  );
  return res.json();
}

// ─── Comparable Sales API ────────────────────────────────────────────────────

export interface CompSale {
  loc_id: string | null;
  site_addr: string | null;
  city: string | null;
  sale_date: string | null;
  sale_price: number | null;
  price_per_sqft: number | null;
  building_area_sqft: number | null;
  lot_size_acres: number | null;
  year_built: number | null;
  style: string | null;
  use_code: string | null;
  total_assessed_value: number | null;
  distance_m: number | null;
}

export interface CompsSummary {
  comp_count: number;
  median_price_per_sqft: number | null;
  avg_sale_price: number | null;
  min_sale_price: number | null;
  max_sale_price: number | null;
  date_range_start: string | null;
  date_range_end: string | null;
}

export interface CompsResponse {
  comps: CompSale[];
  summary: CompsSummary;
  subject_loc_id: string | null;
  radius_m: number;
  source: string;
}

export async function getComps(
  lat: number,
  lon: number,
  radiusM: number = 500,
): Promise<CompsResponse> {
  const res = await fetch(
    `${API_BASE}/api/comps?lat=${lat}&lon=${lon}&radius_m=${radiusM}`
  );
  return res.json();
}

// ─── Permit Map Pins API ─────────────────────────────────────────────────────

export interface PermitPin {
  id: string;
  lat: number;
  lon: number;
  addr: string;
  type: string;
  status: string;
  value: number | null;
  date: string | null;
}

export interface PermitPinsResponse {
  pins: PermitPin[];
  total: number;
  truncated: boolean;
}

export async function getPermitPins(
  west: number,
  south: number,
  east: number,
  north: number,
  limit: number = 500,
): Promise<PermitPinsResponse> {
  const res = await fetch(
    `${API_BASE}/api/permits/viewport?west=${west}&south=${south}&east=${east}&north=${north}&limit=${limit}`
  );
  return res.json();
}

// ─── Town Intelligence API ──────────────────────────────────────────────────

export async function getTargetTowns(): Promise<{
  towns: Array<{
    id: string;
    name: string;
    county: string;
    population: number;
    median_home_value: number;
    center: { lat: number; lon: number };
    permit_portal_type: string;
    boards: string[];
  }>;
  total: number;
}> {
  const res = await fetch(`${API_BASE}/api/target-towns`);
  return res.json();
}

export async function getTownDashboard(townId: string): Promise<{
  town: { id: string; name: string; county: string; median_home_value: number; population: number };
  stats: Record<string, unknown>;
  recent_sales: Array<Record<string, unknown>>;
  recent_documents: Array<Record<string, unknown>>;
  scrape_jobs: Array<Record<string, unknown>>;
}> {
  const res = await fetch(`${API_BASE}/api/towns/${townId}/dashboard`);
  return res.json();
}

export async function getTownActivity(townId: string, limit = 50): Promise<{
  town_id: string;
  activities: Array<{
    type: string;
    date: string;
    title: string;
    detail: string;
    data: Record<string, unknown>;
  }>;
  total: number;
}> {
  const res = await fetch(`${API_BASE}/api/towns/${townId}/activity?limit=${limit}`);
  return res.json();
}

export async function getTownDocuments(
  townId: string,
  params?: { doc_type?: string; board?: string; limit?: number; offset?: number }
): Promise<{
  documents: Array<Record<string, unknown>>;
  total: number;
}> {
  const searchParams = new URLSearchParams();
  if (params?.doc_type) searchParams.set("doc_type", params.doc_type);
  if (params?.board) searchParams.set("board", params.board);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  const res = await fetch(`${API_BASE}/api/towns/${townId}/documents${qs ? `?${qs}` : ""}`);
  return res.json();
}

export async function getTownTransfers(
  townId: string,
  params?: { min_price?: number; limit?: number; offset?: number }
): Promise<{
  transfers: Array<Record<string, unknown>>;
  total: number;
}> {
  const searchParams = new URLSearchParams();
  if (params?.min_price) searchParams.set("min_price", String(params.min_price));
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  const res = await fetch(`${API_BASE}/api/towns/${townId}/transfers${qs ? `?${qs}` : ""}`);
  return res.json();
}

// ─── Parcel Search API ─────────────────────────────────────────────────────

export async function searchParcels(params: {
  town?: string;
  owner?: string;
  loc_id?: string;
  limit?: number;
}): Promise<{
  parcels: Array<Record<string, unknown>>;
  total: number;
  query: Record<string, string>;
}> {
  const searchParams = new URLSearchParams();
  if (params.town) searchParams.set("town", params.town);
  if (params.owner) searchParams.set("owner", params.owner);
  if (params.loc_id) searchParams.set("loc_id", params.loc_id);
  if (params.limit) searchParams.set("limit", String(params.limit));
  const res = await fetch(`${API_BASE}/api/parcels/search?${searchParams}`);
  return res.json();
}

export async function getParcelMentions(locId: string): Promise<{
  parcel: { loc_id: string; address: string } | null;
  mentions: Array<Record<string, unknown>>;
  total: number;
}> {
  const res = await fetch(`${API_BASE}/api/parcels/${locId}/mentions`);
  return res.json();
}

// ─── Scrape Management API ─────────────────────────────────────────────────

export async function triggerScrape(
  townId: string,
  sourceType?: string
): Promise<{ status: string; town_id: string; results: Record<string, unknown> }> {
  const qs = sourceType ? `?source_type=${sourceType}` : "";
  const res = await fetch(`${API_BASE}/api/scrape/trigger/${townId}${qs}`, { method: "POST" });
  return res.json();
}

export async function getScrapeStatus(townId?: string): Promise<{
  jobs: Array<Record<string, unknown>>;
  total: number;
}> {
  const qs = townId ? `?town_id=${townId}` : "";
  const res = await fetch(`${API_BASE}/api/scrape/status${qs}`);
  return res.json();
}

export async function getScrapeStats(): Promise<{
  stats: {
    total_documents: number;
    total_transfers: number;
    total_jobs: number;
    completed_jobs: number;
    failed_jobs: number;
  };
}> {
  const res = await fetch(`${API_BASE}/api/scrape/stats`);
  return res.json();
}

// ─── Scraped Permits API ─────────────────────────────────────────────────────

export async function getScrapedPermits(params?: {
  town_id?: string;
  permit_type?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<{
  permits: Array<Record<string, unknown>>;
  total: number;
}> {
  const searchParams = new URLSearchParams();
  if (params?.town_id) searchParams.set("town_id", params.town_id);
  if (params?.permit_type) searchParams.set("permit_type", params.permit_type);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  const res = await fetch(`${API_BASE}/api/scraped-permits${qs ? `?${qs}` : ""}`);
  return res.json();
}

export async function getScrapedPermitsByTown(townId: string, params?: {
  limit?: number;
  offset?: number;
}): Promise<{
  permits: Array<Record<string, unknown>>;
  total: number;
  town_id: string;
}> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  const res = await fetch(`${API_BASE}/api/scraped-permits/by-town/${townId}${qs ? `?${qs}` : ""}`);
  return res.json();
}

// ─── Agent API ──────────────────────────────────────────────────────────────

export async function listPropertyAgents(): Promise<{
  agents: PropertyMonitorAgent[];
  total: number;
}> {
  const res = await fetch(`${API_BASE}/api/agents`);
  return res.json();
}

export async function createPropertyAgent(params: {
  entity_type: string;
  entity_id: string;
  agent_type: string;
  name?: string;
  config?: Record<string, unknown>;
  run_interval_seconds?: number;
}): Promise<{ status: string; agent: PropertyMonitorAgent }> {
  const res = await fetch(`${API_BASE}/api/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function deletePropertyAgent(
  agentId: string
): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/api/agents/${agentId}`, {
    method: "DELETE",
  });
  return res.json();
}

// ─── Notifications API ──────────────────────────────────────────────────────

export async function getNotifications(params?: {
  limit?: number;
  acknowledged?: boolean;
}): Promise<{
  notifications: AgentFinding[];
  total: number;
}> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.acknowledged !== undefined)
    searchParams.set("acknowledged", String(params.acknowledged));
  const qs = searchParams.toString();
  const res = await fetch(`${API_BASE}/api/notifications${qs ? `?${qs}` : ""}`);
  return res.json();
}

// ─── MEPA Filings API ──────────────────────────────────────────────────────

export async function getMepaFilings(
  townId: string,
  limit = 50
): Promise<{ filings: MepaFiling[]; total: number; town_id: string }> {
  const res = await fetch(
    `${API_BASE}/api/mepa?town_id=${encodeURIComponent(townId)}&limit=${limit}`
  );
  return res.json();
}

// ─── CIP Documents API ─────────────────────────────────────────────────────

export async function getCipDocuments(
  townId: string,
  limit = 50
): Promise<{ documents: CipDocument[]; total: number; town_id: string }> {
  const res = await fetch(
    `${API_BASE}/api/cip?town_id=${encodeURIComponent(townId)}&limit=${limit}`
  );
  return res.json();
}

// ─── Town Dashboard Stats API ──────────────────────────────────────────────

export async function getTownDashboardStats(
  townId: string
): Promise<TownDashboardStats> {
  const res = await fetch(
    `${API_BASE}/api/town-dashboard?town_id=${encodeURIComponent(townId)}`
  );
  return res.json();
}

export interface PlatformStats {
  total_permits: number;
  total_properties: number;
  total_towns: number;
  total_mepa: number;
  total_documents: number;
  total_tax_delinquent: number;
}

export async function getPlatformStats(): Promise<PlatformStats> {
  const res = await fetch(`${API_BASE}/api/platform-stats`);
  return res.json();
}
