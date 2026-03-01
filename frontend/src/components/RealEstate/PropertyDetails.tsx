import React, { useState, useEffect } from "react";
import {
  X,
  FileText,
  Bot,
  MapPin,
  Droplets,
  Map,
  ScrollText,
  Building2,
  TrendingUp,
  Loader2,
} from "lucide-react";
import { useStore } from "../../store/useStore";
import {
  enrichListing,
  getFloodZone,
  getParcelInfo,
  getZoning,
  getLandRecords,
  getComps,
} from "../../services/api";
import type {
  FloodZoneInfo,
  ParcelInfo,
  ZoningInfo,
  LandRecord,
  OwnershipInfo,
  OwnershipResponse,
  CompSale,
  CompsSummary,
  CompsResponse,
} from "../../services/api";
import type { Permit } from "../../types";

type TabId = "permits" | "parcel" | "flood" | "zoning" | "deeds" | "comps" | "agents";

const TABS: { id: TabId; label: string; icon: React.FC<{ className?: string }> }[] = [
  { id: "permits", label: "Permits", icon: FileText },
  { id: "parcel", label: "Parcel", icon: Building2 },
  { id: "flood", label: "Flood", icon: Droplets },
  { id: "zoning", label: "Zoning", icon: Map },
  { id: "deeds", label: "Deeds", icon: ScrollText },
  { id: "comps", label: "Comps", icon: TrendingUp },
  { id: "agents", label: "Agents", icon: Bot },
];

interface PropertySource {
  address: string;
  city: string;
  state?: string;
  latitude: number;
  longitude: number;
}

const PropertyDetails: React.FC<{
  listingId?: string;
  property?: PropertySource;
}> = ({ listingId, property: propProp }) => {
  const listing = useStore((s) =>
    listingId ? s.trackedListings.find((l) => l.id === listingId) : undefined
  );
  const selectedProperty = useStore((s) => s.selectedProperty);

  // Derive a unified source: listing > explicit prop > selectedProperty
  const source: PropertySource | undefined =
    listing ?? propProp ?? (selectedProperty ? {
      address: selectedProperty.address,
      city: selectedProperty.city,
      state: selectedProperty.state,
      latitude: selectedProperty.latitude,
      longitude: selectedProperty.longitude,
    } : undefined);

  const sourceKey = source ? `${source.address}|${source.latitude}` : "";

  const [tab, setTab] = useState<TabId>("permits");

  // Data states
  const [permits, setPermits] = useState<Permit[]>([]);
  const [parcel, setParcel] = useState<ParcelInfo | null>(null);
  const [flood, setFlood] = useState<FloodZoneInfo | null>(null);
  const [zoning, setZoningData] = useState<ZoningInfo | null>(null);
  const [deeds, setDeeds] = useState<LandRecord[]>([]);
  const [ownership, setOwnership] = useState<OwnershipInfo | null>(null);
  const [comps, setComps] = useState<CompSale[]>([]);
  const [compsSummary, setCompsSummary] = useState<CompsSummary | null>(null);

  // Loading states
  const [loadingPermits, setLoadingPermits] = useState(false);
  const [loadingParcel, setLoadingParcel] = useState(false);
  const [loadingFlood, setLoadingFlood] = useState(false);
  const [loadingZoning, setLoadingZoning] = useState(false);
  const [loadingDeeds, setLoadingDeeds] = useState(false);
  const [loadingComps, setLoadingComps] = useState(false);

  const hasCoords =
    source && (source.latitude !== 0 || source.longitude !== 0);

  // Reset data when source changes
  useEffect(() => {
    setPermits([]);
    setParcel(null);
    setFlood(null);
    setZoningData(null);
    setDeeds([]);
    setOwnership(null);
    setComps([]);
    setCompsSummary(null);
    setTab("permits");
  }, [sourceKey]);

  // Fetch permits on mount / source change
  useEffect(() => {
    if (!source) return;
    setLoadingPermits(true);
    enrichListing({
      address: source.address,
      latitude: source.latitude,
      longitude: source.longitude,
    })
      .then((data) => setPermits(data.permits || []))
      .catch(() => setPermits([]))
      .finally(() => setLoadingPermits(false));
  }, [sourceKey]);

  // Fetch parcel data when tab selected and we have coords
  useEffect(() => {
    if (tab !== "parcel" || !hasCoords || parcel) return;
    setLoadingParcel(true);
    getParcelInfo(source!.latitude, source!.longitude)
      .then((data) => setParcel(data))
      .catch(() => setParcel(null))
      .finally(() => setLoadingParcel(false));
  }, [tab, hasCoords, parcel, sourceKey]);

  // Fetch flood zone when tab selected
  useEffect(() => {
    if (tab !== "flood" || !hasCoords || flood) return;
    setLoadingFlood(true);
    getFloodZone(source!.latitude, source!.longitude)
      .then((data) => setFlood(data))
      .catch(() => setFlood(null))
      .finally(() => setLoadingFlood(false));
  }, [tab, hasCoords, flood, sourceKey]);

  // Fetch zoning when tab selected
  useEffect(() => {
    if (tab !== "zoning" || !hasCoords || zoning) return;
    setLoadingZoning(true);
    getZoning(source!.latitude, source!.longitude)
      .then((data) => setZoningData(data))
      .catch(() => setZoningData(null))
      .finally(() => setLoadingZoning(false));
  }, [tab, hasCoords, zoning, sourceKey]);

  // Fetch deed/ownership records when tab selected
  useEffect(() => {
    if (tab !== "deeds" || !hasCoords || (deeds.length > 0 || ownership)) return;
    setLoadingDeeds(true);
    getLandRecords(source!.latitude, source!.longitude)
      .then((data: OwnershipResponse) => {
        setDeeds(data.records || []);
        setOwnership(data.ownership || null);
      })
      .catch(() => { setDeeds([]); setOwnership(null); })
      .finally(() => setLoadingDeeds(false));
  }, [tab, hasCoords, sourceKey]);

  // Fetch comparable sales when tab selected
  useEffect(() => {
    if (tab !== "comps" || !hasCoords || comps.length > 0) return;
    setLoadingComps(true);
    getComps(source!.latitude, source!.longitude)
      .then((data: CompsResponse) => {
        setComps(data.comps || []);
        setCompsSummary(data.summary || null);
      })
      .catch(() => { setComps([]); setCompsSummary(null); })
      .finally(() => setLoadingComps(false));
  }, [tab, hasCoords, sourceKey]);

  if (!source) return null;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-parcl-border flex items-start gap-2">
        <MapPin className="w-4 h-4 text-parcl-accent mt-0.5 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-parcl-text truncate">
            {source.address}
          </div>
          <div className="text-[10px] text-parcl-text-muted">
            {[source.city, source.state].filter(Boolean).join(", ")}
          </div>
        </div>
        <button
          onClick={() => {
            useStore.getState().selectListing("");
            useStore.getState().setSelectedProperty(null);
          }}
          className="p-1 rounded hover:bg-parcl-border text-parcl-text-muted hover:text-parcl-text transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Tabs — scrollable row of small tabs */}
      <div className="flex border-b border-parcl-border overflow-x-auto scrollbar-none">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1 px-2.5 py-2 text-[9px] font-semibold uppercase tracking-wider whitespace-nowrap transition-colors ${
                tab === t.id
                  ? "text-parcl-accent border-b-2 border-parcl-accent"
                  : "text-parcl-text-muted hover:text-parcl-text"
              }`}
            >
              <Icon className="w-3 h-3" />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {/* ── PERMITS TAB ─────────────────────────────────────────── */}
        {tab === "permits" && (
          <>
            {loadingPermits ? (
              <LoadingState text="Loading nearby permits..." />
            ) : permits.length === 0 ? (
              <EmptyState text="No permits found near this address" />
            ) : (
              permits.map((p, i) => (
                <div
                  key={p.id || i}
                  className="p-2.5 rounded-md bg-parcl-surface border border-parcl-border/50 space-y-1"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[10px] font-mono text-parcl-accent">
                      {p.permit_number || `#${i + 1}`}
                    </span>
                    {p.permit_type && (
                      <span className="badge badge-blue">{p.permit_type}</span>
                    )}
                    {p.status && (
                      <span
                        className={`badge ${
                          p.status === "APPROVED" || p.status === "ISSUED"
                            ? "badge-green"
                            : p.status === "DENIED"
                              ? "badge-red"
                              : "badge-amber"
                        }`}
                      >
                        {p.status}
                      </span>
                    )}
                  </div>
                  {p.description && (
                    <p className="text-[11px] text-parcl-text-dim line-clamp-2">
                      {p.description}
                    </p>
                  )}
                  <div className="flex items-center gap-3 text-[9px] text-parcl-text-muted">
                    {p.filed_date && <span>Filed: {p.filed_date}</span>}
                    {p.estimated_value != null && (
                      <span>
                        Value: ${Number(p.estimated_value).toLocaleString()}
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </>
        )}

        {/* ── PARCEL TAB ──────────────────────────────────────────── */}
        {tab === "parcel" && (
          <>
            {loadingParcel ? (
              <LoadingState text="Loading parcel data..." />
            ) : !parcel || !parcel.loc_id ? (
              <EmptyState text={!hasCoords ? "Geocode this address to see parcel data" : "No parcel data found"} />
            ) : (
              <div className="space-y-2">
                <DataCard label="Owner" value={parcel.owner} />
                <DataCard label="Address" value={parcel.site_addr} />
                <DataCard label="City" value={parcel.city} />
                <DataCard
                  label="Total Assessment"
                  value={
                    parcel.total_value
                      ? `$${Number(parcel.total_value).toLocaleString()}`
                      : null
                  }
                />
                <div className="grid grid-cols-2 gap-2">
                  <DataCard
                    label="Building Value"
                    value={
                      parcel.building_value
                        ? `$${Number(parcel.building_value).toLocaleString()}`
                        : null
                    }
                    compact
                  />
                  <DataCard
                    label="Land Value"
                    value={
                      parcel.land_value
                        ? `$${Number(parcel.land_value).toLocaleString()}`
                        : null
                    }
                    compact
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <DataCard
                    label="Lot Size"
                    value={
                      parcel.lot_size_acres
                        ? `${Number(parcel.lot_size_acres).toFixed(2)} acres`
                        : null
                    }
                    compact
                  />
                  <DataCard
                    label="Year Built"
                    value={parcel.year_built ? String(parcel.year_built) : null}
                    compact
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <DataCard
                    label="Building Area"
                    value={
                      parcel.building_area_sqft
                        ? `${Number(parcel.building_area_sqft).toLocaleString()} sqft`
                        : null
                    }
                    compact
                  />
                  <DataCard
                    label="Use Code"
                    value={parcel.use_code}
                    compact
                  />
                </div>
                {parcel.last_sale_price && (
                  <DataCard
                    label="Last Sale"
                    value={`$${Number(parcel.last_sale_price).toLocaleString()} (${parcel.last_sale_date || "N/A"})`}
                  />
                )}
                <div className="text-[8px] text-parcl-text-muted mt-2">
                  Source: MassGIS Property Tax Parcels | FY {parcel.fiscal_year || "N/A"}
                </div>
              </div>
            )}
          </>
        )}

        {/* ── FLOOD TAB ───────────────────────────────────────────── */}
        {tab === "flood" && (
          <>
            {loadingFlood ? (
              <LoadingState text="Querying FEMA flood zones..." />
            ) : !flood ? (
              <EmptyState text={!hasCoords ? "Geocode this address to see flood data" : "No flood data available"} />
            ) : (
              <div className="space-y-2">
                <div className="p-3 rounded-md bg-parcl-surface border border-parcl-border/50">
                  <div className="flex items-center gap-2 mb-2">
                    <Droplets className={`w-5 h-5 ${
                      flood.risk_level === "minimal"
                        ? "text-green-400"
                        : flood.risk_level === "high"
                          ? "text-red-400"
                          : flood.risk_level === "very_high"
                            ? "text-red-600"
                            : "text-yellow-400"
                    }`} />
                    <div>
                      <div className="text-sm font-semibold text-parcl-text">
                        Zone {flood.flood_zone || "Unknown"}
                      </div>
                      <div className="text-[10px] text-parcl-text-muted capitalize">
                        {flood.risk_level?.replace("_", " ")} Risk
                      </div>
                    </div>
                  </div>
                  <p className="text-[11px] text-parcl-text-dim">
                    {flood.description}
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <DataCard
                    label="In SFHA"
                    value={flood.in_sfha ? "Yes" : "No"}
                    compact
                  />
                  <DataCard
                    label="Base Flood Elev."
                    value={
                      flood.base_flood_elevation
                        ? `${flood.base_flood_elevation} ft`
                        : "N/A"
                    }
                    compact
                  />
                </div>
                {flood.zone_subtype && (
                  <DataCard label="Zone Subtype" value={flood.zone_subtype} />
                )}
                <div className="text-[8px] text-parcl-text-muted mt-2">
                  Source: FEMA National Flood Hazard Layer
                </div>
              </div>
            )}
          </>
        )}

        {/* ── ZONING TAB ──────────────────────────────────────────── */}
        {tab === "zoning" && (
          <>
            {loadingZoning ? (
              <LoadingState text="Querying zoning data..." />
            ) : !zoning || !zoning.zone_code ? (
              <EmptyState text={!hasCoords ? "Geocode this address to see zoning data" : "No zoning data available for this location"} />
            ) : (
              <div className="space-y-2">
                <div className="p-3 rounded-md bg-parcl-surface border border-parcl-border/50">
                  <div className="flex items-center gap-2 mb-2">
                    <Map className="w-5 h-5 text-blue-400" />
                    <div>
                      <div className="text-sm font-semibold text-parcl-text">
                        {zoning.zone_code}
                      </div>
                      {zoning.zone_name && (
                        <div className="text-[10px] text-parcl-text-muted">
                          {zoning.zone_name}
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {zoning.allowed_uses.length > 0 && (
                  <div className="p-3 rounded-md bg-parcl-surface border border-parcl-border/50">
                    <div className="text-[10px] uppercase tracking-wider text-parcl-text-muted mb-2">
                      Allowed Uses
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {zoning.allowed_uses.map((use, i) => (
                        <span key={i} className="badge badge-blue">
                          {use}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-2">
                  <DataCard
                    label="Min Lot Size"
                    value={
                      zoning.min_lot_size_sqft
                        ? `${Number(zoning.min_lot_size_sqft).toLocaleString()} sqft`
                        : "N/A"
                    }
                    compact
                  />
                  <DataCard
                    label="Max Height"
                    value={
                      zoning.max_height_ft
                        ? `${zoning.max_height_ft} ft`
                        : "N/A"
                    }
                    compact
                  />
                </div>
                {zoning.jurisdiction && (
                  <DataCard label="Jurisdiction" value={zoning.jurisdiction} />
                )}
                <div className="text-[8px] text-parcl-text-muted mt-2">
                  Source: National Zoning Atlas
                </div>
              </div>
            )}
          </>
        )}

        {/* ── DEEDS TAB ───────────────────────────────────────────── */}
        {tab === "deeds" && (
          <>
            {loadingDeeds ? (
              <LoadingState text="Looking up ownership records..." />
            ) : !ownership && deeds.length === 0 ? (
              <EmptyState text="No ownership records found. Data is available for Massachusetts properties." />
            ) : (
              <div className="space-y-3">
                {/* Ownership section */}
                {ownership && (
                  <div className="space-y-1">
                    <div className="text-[10px] uppercase tracking-wider text-parcl-text-muted mb-1.5">
                      Current Owner
                    </div>
                    <div className="p-3 rounded-md bg-parcl-surface border border-parcl-border/50 space-y-2">
                      <div className="text-[13px] font-semibold text-parcl-text">
                        {ownership.owner}
                      </div>
                      {ownership.mailing_address && (
                        <div className="text-[10px] text-parcl-text-muted">
                          <span className="text-parcl-text-dim">Mailing:</span>{" "}
                          {ownership.mailing_address}
                          {ownership.mailing_city && `, ${ownership.mailing_city}`}
                          {ownership.mailing_state && ` ${ownership.mailing_state}`}
                          {ownership.mailing_zip && ` ${ownership.mailing_zip}`}
                        </div>
                      )}
                      {ownership.total_assessed_value != null && (
                        <div className="flex items-center gap-4 text-[10px]">
                          <div>
                            <span className="text-parcl-text-muted">Total Assessed: </span>
                            <span className="font-semibold text-parcl-text">
                              ${Number(ownership.total_assessed_value).toLocaleString()}
                            </span>
                          </div>
                          {ownership.building_value != null && (
                            <div>
                              <span className="text-parcl-text-muted">Bldg: </span>
                              <span className="text-parcl-text-dim">
                                ${Number(ownership.building_value).toLocaleString()}
                              </span>
                            </div>
                          )}
                          {ownership.land_value != null && (
                            <div>
                              <span className="text-parcl-text-muted">Land: </span>
                              <span className="text-parcl-text-dim">
                                ${Number(ownership.land_value).toLocaleString()}
                              </span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Last sale / deed records */}
                {deeds.length > 0 && (
                  <div className="space-y-1">
                    <div className="text-[10px] uppercase tracking-wider text-parcl-text-muted mb-1.5">
                      Last Recorded Sale
                    </div>
                    {deeds.map((d, i) => (
                      <div
                        key={i}
                        className="p-2.5 rounded-md bg-parcl-surface border border-parcl-border/50 flex items-start gap-2"
                      >
                        <div className="w-1 h-full bg-parcl-accent/30 rounded-full flex-shrink-0 self-stretch" />
                        <div className="flex-1 min-w-0 space-y-0.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[10px] font-semibold text-parcl-accent">
                              {d.doc_type || "Record"}
                            </span>
                            {d.recording_date && (
                              <span className="text-[9px] text-parcl-text-muted">
                                {d.recording_date}
                              </span>
                            )}
                          </div>
                          {d.grantee && (
                            <div className="text-[11px] text-parcl-text">
                              Transferred to: {d.grantee}
                            </div>
                          )}
                          <div className="flex items-center gap-3 text-[9px] text-parcl-text-muted">
                            {d.consideration != null && d.consideration > 0 && (
                              <span className="font-semibold text-parcl-text-dim">
                                ${Number(d.consideration).toLocaleString()}
                              </span>
                            )}
                            {d.book_page && <span>B/P: {d.book_page}</span>}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <div className="text-[8px] text-parcl-text-muted mt-1">
                  Source: MassGIS Property Tax Parcels
                </div>
              </div>
            )}
          </>
        )}

        {/* ── COMPS TAB ───────────────────────────────────────────── */}
        {tab === "comps" && (
          <>
            {loadingComps ? (
              <LoadingState text="Finding comparable sales..." />
            ) : comps.length === 0 ? (
              <EmptyState text={!hasCoords ? "Geocode this address to see comps" : "No comparable sales found nearby"} />
            ) : (
              <div className="space-y-3">
                {/* Summary Stats Card */}
                {compsSummary && (
                  <div className="p-3 rounded-md bg-parcl-surface border border-parcl-border/50">
                    <div className="text-[10px] uppercase tracking-wider text-parcl-text-muted mb-2">
                      Comp Summary &middot; {compsSummary.comp_count} sales
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <div className="text-[9px] text-parcl-text-muted">Median $/sqft</div>
                        <div className="text-sm font-semibold text-parcl-accent">
                          {compsSummary.median_price_per_sqft
                            ? `$${Math.round(compsSummary.median_price_per_sqft).toLocaleString()}`
                            : "N/A"}
                        </div>
                      </div>
                      <div>
                        <div className="text-[9px] text-parcl-text-muted">Avg Sale Price</div>
                        <div className="text-sm font-semibold text-parcl-text">
                          {compsSummary.avg_sale_price
                            ? `$${Math.round(compsSummary.avg_sale_price).toLocaleString()}`
                            : "N/A"}
                        </div>
                      </div>
                      <div>
                        <div className="text-[9px] text-parcl-text-muted">Price Range</div>
                        <div className="text-[11px] text-parcl-text">
                          {compsSummary.min_sale_price && compsSummary.max_sale_price
                            ? `$${Math.round(compsSummary.min_sale_price).toLocaleString()} – $${Math.round(compsSummary.max_sale_price).toLocaleString()}`
                            : "N/A"}
                        </div>
                      </div>
                      <div>
                        <div className="text-[9px] text-parcl-text-muted">Date Range</div>
                        <div className="text-[11px] text-parcl-text">
                          {compsSummary.date_range_start && compsSummary.date_range_end
                            ? `${compsSummary.date_range_start} – ${compsSummary.date_range_end}`
                            : "N/A"}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Individual Comp List */}
                <div className="text-[10px] uppercase tracking-wider text-parcl-text-muted mb-1">
                  Comparable Sales
                </div>
                {comps.map((c, i) => (
                  <div
                    key={c.loc_id ? `${c.loc_id}-${i}` : i}
                    className="p-2.5 rounded-md bg-parcl-surface border border-parcl-border/50 space-y-1"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-semibold text-parcl-text truncate">
                        {c.site_addr || "Unknown Address"}
                      </span>
                      {c.distance_m != null && (
                        <span className="text-[9px] text-parcl-text-muted whitespace-nowrap ml-2">
                          {c.distance_m < 1000
                            ? `${Math.round(c.distance_m)}m`
                            : `${(c.distance_m / 1000).toFixed(1)}km`}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-[10px]">
                      {c.sale_price != null && (
                        <span className="font-semibold text-parcl-accent">
                          ${Number(c.sale_price).toLocaleString()}
                        </span>
                      )}
                      {c.sale_date && (
                        <span className="text-parcl-text-muted">{c.sale_date}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-[9px] text-parcl-text-muted flex-wrap">
                      {c.price_per_sqft != null && (
                        <span>${Math.round(c.price_per_sqft)}/sqft</span>
                      )}
                      {c.building_area_sqft != null && c.building_area_sqft > 0 && (
                        <span>{Number(c.building_area_sqft).toLocaleString()} sqft</span>
                      )}
                      {c.lot_size_acres != null && (
                        <span>{Number(c.lot_size_acres).toFixed(2)} ac</span>
                      )}
                      {c.year_built != null && c.year_built > 0 && (
                        <span>Built {c.year_built}</span>
                      )}
                      {c.style && <span>{c.style}</span>}
                    </div>
                  </div>
                ))}
                <div className="text-[8px] text-parcl-text-muted mt-2">
                  Source: MassGIS Property Tax Parcels &middot; 500m radius
                </div>
              </div>
            )}
          </>
        )}

        {/* ── AGENTS TAB ──────────────────────────────────────────── */}
        {tab === "agents" && (
          <div className="space-y-3">
            {listing?.agentId ? (
              <div className="p-3 rounded-md bg-parcl-surface border border-parcl-border/50">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-2 h-2 rounded-full bg-parcl-green" />
                  <span className="text-xs font-semibold text-parcl-text">
                    Monitoring Active
                  </span>
                </div>
                <div className="text-[10px] text-parcl-text-muted">
                  Agent is monitoring for new permits, zoning changes, and
                  construction activity near this address.
                </div>
                <div className="text-[9px] font-mono text-parcl-text-muted mt-2">
                  ID: {listing?.agentId}
                </div>
              </div>
            ) : (
              <div className="text-xs text-parcl-text-muted text-center py-8">
                <Bot className="w-8 h-8 mx-auto mb-2 opacity-30" />
                No agent assigned yet.
                <br />
                <span className="text-[10px]">
                  Re-add this listing to auto-assign an agent.
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

// ── Reusable Components ─────────────────────────────────────────────────────

const DataCard: React.FC<{
  label: string;
  value: string | number | null | undefined;
  compact?: boolean;
}> = ({ label, value, compact }) => (
  <div
    className={`${compact ? "p-2" : "p-3"} rounded-md bg-parcl-surface border border-parcl-border/50`}
  >
    <div className="text-[10px] uppercase tracking-wider text-parcl-text-muted mb-0.5">
      {label}
    </div>
    <div className={`${compact ? "text-xs" : "text-sm"} text-parcl-text`}>
      {value ?? "N/A"}
    </div>
  </div>
);

const LoadingState: React.FC<{ text: string }> = ({ text }) => (
  <div className="flex items-center justify-center gap-2 py-8">
    <Loader2 className="w-4 h-4 text-parcl-accent animate-spin" />
    <span className="text-xs text-parcl-text-muted">{text}</span>
  </div>
);

const EmptyState: React.FC<{ text: string }> = ({ text }) => (
  <div className="text-xs text-parcl-text-muted text-center py-8">{text}</div>
);

export default PropertyDetails;
