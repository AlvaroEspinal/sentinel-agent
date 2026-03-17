import React, { useEffect, useState } from "react";
import { useStore } from "../../store/useStore";
import { getTownDashboard, getScrapedPermitsByTown, getTownPermitBreakdown } from "../../services/api";
import type { PermitBreakdownResponse } from "../../services/api";
import {
  ArrowLeft,
  Building2,
  DollarSign,
  Users,
  FileText,
  TrendingDown,
  TrendingUp,
  Clock,
  Home,
  Loader2,
  MapPin,
  Calendar,
  ExternalLink,
  Hammer,
} from "lucide-react";

// Cached stats from v_town_dashboard (March 2026) — shown when API is unavailable
const CACHED_STATS: Record<string, {
  total_properties: number; total_permits: number; avg_tax_assessment: number;
  mepa_filing_count: number; meeting_minutes_count: number; cip_count: number;
  tax_delinquent_count: number; median_home_value: number;
}> = {
  newton: { total_properties: 23000, total_permits: 12766, avg_tax_assessment: 1830114, mepa_filing_count: 13, meeting_minutes_count: 2, cip_count: 1, tax_delinquent_count: 0, median_home_value: 1350000 },
  wellesley: { total_properties: 8000, total_permits: 3586, avg_tax_assessment: 2363620, mepa_filing_count: 5, meeting_minutes_count: 61, cip_count: 1, tax_delinquent_count: 0, median_home_value: 1600000 },
  weston: { total_properties: 4062, total_permits: 39387, avg_tax_assessment: 2492961, mepa_filing_count: 5, meeting_minutes_count: 71, cip_count: 1, tax_delinquent_count: 0, median_home_value: 2200000 },
  brookline: { total_properties: 8439, total_permits: 314, avg_tax_assessment: 3232420, mepa_filing_count: 16, meeting_minutes_count: 12, cip_count: 1, tax_delinquent_count: 69, median_home_value: 1100000 },
  needham: { total_properties: 9770, total_permits: 5593, avg_tax_assessment: 1637287, mepa_filing_count: 10, meeting_minutes_count: 1220, cip_count: 1, tax_delinquent_count: 0, median_home_value: 1050000 },
  concord: { total_properties: 5102, total_permits: 16582, avg_tax_assessment: 1613735, mepa_filing_count: 17, meeting_minutes_count: 21, cip_count: 1, tax_delinquent_count: 0, median_home_value: 1200000 },
  lexington: { total_properties: 11331, total_permits: 9312, avg_tax_assessment: 1579565, mepa_filing_count: 11, meeting_minutes_count: 17, cip_count: 1, tax_delinquent_count: 2, median_home_value: 1150000 },
  dover: { total_properties: 2503, total_permits: 311, avg_tax_assessment: 1536930, mepa_filing_count: 13, meeting_minutes_count: 26, cip_count: 1, tax_delinquent_count: 0, median_home_value: 1600000 },
  sherborn: { total_properties: 1878, total_permits: 6364, avg_tax_assessment: 1078957, mepa_filing_count: 0, meeting_minutes_count: 159, cip_count: 1, tax_delinquent_count: 0, median_home_value: 1500000 },
  natick: { total_properties: 11061, total_permits: 5699, avg_tax_assessment: 1002577, mepa_filing_count: 3, meeting_minutes_count: 36, cip_count: 1, tax_delinquent_count: 0, median_home_value: 800000 },
  wayland: { total_properties: 5049, total_permits: 1654, avg_tax_assessment: 1052222, mepa_filing_count: 3, meeting_minutes_count: 81, cip_count: 1, tax_delinquent_count: 0, median_home_value: 950000 },
  lincoln: { total_properties: 1788, total_permits: 2940, avg_tax_assessment: 1536728, mepa_filing_count: 21, meeting_minutes_count: 157, cip_count: 1, tax_delinquent_count: 0, median_home_value: 1200000 },
};

const TownDashboard: React.FC = () => {
  const activeTownId = useStore((s) => s.activeTownId);
  const townDashboardData = useStore((s) => s.townDashboardData);
  const townDashboardLoading = useStore((s) => s.townDashboardLoading);
  const setTownDashboardData = useStore((s) => s.setTownDashboardData);
  const setTownDashboardLoading = useStore((s) => s.setTownDashboardLoading);
  const navigateToDashboard = useStore((s) => s.navigateToDashboard);
  const targetTowns = useStore((s) => s.targetTowns);

  // Fetch dashboard data when town changes
  useEffect(() => {
    if (!activeTownId) return;

    let cancelled = false;

    const fetchData = async () => {
      setTownDashboardLoading(true);
      try {
        const data = await getTownDashboard(activeTownId);
        if (!cancelled) {
          setTownDashboardData(data as any);
        }
      } catch (err) {
        console.warn("[TownDashboard] Fetch error:", err);
        if (!cancelled) {
          // Use cached stats as fallback
          const cached = CACHED_STATS[activeTownId];
          const townConfig = targetTowns.find((t) => t.id === activeTownId);
          setTownDashboardData({
            town: {
              id: activeTownId,
              name: townConfig?.name || activeTownId.charAt(0).toUpperCase() + activeTownId.slice(1),
              county: townConfig?.county || "",
              median_home_value: cached?.median_home_value || townConfig?.median_home_value || 0,
              population: townConfig?.population || 0,
            },
            stats: cached ? {
              total_properties: cached.total_properties,
              total_permits: cached.total_permits,
              avg_tax_assessment: cached.avg_tax_assessment,
              mepa_filing_count: cached.mepa_filing_count,
              meeting_minutes_count: cached.meeting_minutes_count,
              cip_count: cached.cip_count,
              tax_delinquent_count: cached.tax_delinquent_count,
            } : {},
            recent_sales: [],
            recent_documents: [],
            scrape_jobs: [],
          });
        }
      } finally {
        if (!cancelled) setTownDashboardLoading(false);
      }
    };

    fetchData();
    return () => { cancelled = true; };
  }, [activeTownId, setTownDashboardData, setTownDashboardLoading]);

  // Fetch scraped permits
  const [scrapedPermits, setScrapedPermits] = useState<any[]>([]);
  const [permitsLoading, setPermitsLoading] = useState(false);

  useEffect(() => {
    if (!activeTownId) return;
    let cancelled = false;
    setPermitsLoading(true);
    getScrapedPermitsByTown(activeTownId, { limit: 15 })
      .then((result) => {
        if (!cancelled) setScrapedPermits(result.permits || []);
      })
      .catch(() => {
        if (!cancelled) setScrapedPermits([]);
      })
      .finally(() => {
        if (!cancelled) setPermitsLoading(false);
      });
    return () => { cancelled = true; };
  }, [activeTownId]);

  // Fetch permit breakdown
  const [permitBreakdown, setPermitBreakdown] = useState<PermitBreakdownResponse | null>(null);

  useEffect(() => {
    if (!activeTownId) return;
    let cancelled = false;
    getTownPermitBreakdown(activeTownId)
      .then((result) => {
        if (!cancelled) setPermitBreakdown(result);
      })
      .catch(() => {
        if (!cancelled) setPermitBreakdown(null);
      });
    return () => { cancelled = true; };
  }, [activeTownId]);

  // Find town config for extra info
  const townConfig = targetTowns.find((t) => t.id === activeTownId);
  const townName = townDashboardData?.town?.name || townConfig?.name || activeTownId || "Town";

  const formatPrice = (v: number | null | undefined) => {
    if (!v) return "N/A";
    if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
    if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
    return `$${v.toLocaleString()}`;
  };

  if (townDashboardLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <Loader2 size={32} className="mx-auto text-blue-400 animate-spin mb-3" />
          <p className="text-slate-400 text-sm">Loading {townName} data...</p>
        </div>
      </div>
    );
  }

  const data = townDashboardData;

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={navigateToDashboard}
            className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
          >
            <ArrowLeft size={18} />
          </button>
          <div>
            <h1 className="text-xl font-bold text-white">{townName}</h1>
            <p className="text-slate-400 text-xs">
              {data?.town?.county ? `${data.town.county} County` : ""}{" "}
              {data?.town?.population ? `\u00B7 Pop. ${data.town.population.toLocaleString()}` : ""}
            </p>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
          <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-4">
            <DollarSign size={16} className="text-emerald-400 mb-2" />
            <div className="text-lg font-bold text-white">
              {formatPrice(data?.town?.median_home_value)}
            </div>
            <div className="text-slate-500 text-xs">Median Home Value</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-4">
            <Home size={16} className="text-blue-400 mb-2" />
            <div className="text-lg font-bold text-white">
              {data?.stats && typeof data.stats === "object" && "total_properties" in data.stats
                ? (data.stats.total_properties as number).toLocaleString()
                : data?.stats && "parcel_count" in (data.stats as Record<string, unknown>)
                  ? ((data.stats as Record<string, unknown>).parcel_count as number).toLocaleString()
                  : "---"}
            </div>
            <div className="text-slate-500 text-xs">Properties</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-4">
            <Hammer size={16} className="text-amber-400 mb-2" />
            <div className="text-lg font-bold text-white">
              {data?.stats && typeof data.stats === "object" && "total_permits" in data.stats
                ? (data.stats.total_permits as number).toLocaleString()
                : "---"}
            </div>
            <div className="text-slate-500 text-xs">Total Permits</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-4">
            <TrendingUp size={16} className="text-emerald-400 mb-2" />
            <div className="text-lg font-bold text-white">
              {data?.recent_sales?.length || 0}
            </div>
            <div className="text-slate-500 text-xs">Recent Sales (90d)</div>
          </div>
        </div>

        {/* Secondary Stats Row */}
        {data?.stats && typeof data.stats === "object" && "mepa_filing_count" in data.stats && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-8">
            <div className="bg-slate-800/40 border border-slate-700/30 rounded-lg p-3">
              <div className="text-sm font-semibold text-white">
                {((data.stats as Record<string, unknown>).mepa_filing_count as number || 0).toLocaleString()}
              </div>
              <div className="text-slate-500 text-[11px]">MEPA Filings</div>
            </div>
            <div className="bg-slate-800/40 border border-slate-700/30 rounded-lg p-3">
              <div className="text-sm font-semibold text-white">
                {((data.stats as Record<string, unknown>).meeting_minutes_count as number || 0).toLocaleString()}
              </div>
              <div className="text-slate-500 text-[11px]">Meeting Minutes</div>
            </div>
            <div className="bg-slate-800/40 border border-slate-700/30 rounded-lg p-3">
              <div className="text-sm font-semibold text-white">
                {((data.stats as Record<string, unknown>).cip_count as number || 0).toLocaleString()}
              </div>
              <div className="text-slate-500 text-[11px]">CIP Documents</div>
            </div>
            <div className="bg-slate-800/40 border border-slate-700/30 rounded-lg p-3">
              <div className="text-sm font-semibold text-white">
                {((data.stats as Record<string, unknown>).tax_delinquent_count as number || 0).toLocaleString()}
              </div>
              <div className="text-slate-500 text-[11px]">Tax Delinquent</div>
            </div>
            <div className="bg-slate-800/40 border border-slate-700/30 rounded-lg p-3">
              <div className="text-sm font-semibold text-white">
                {formatPrice((data.stats as Record<string, unknown>).avg_tax_assessment as number)}
              </div>
              <div className="text-slate-500 text-[11px]">Avg Assessment</div>
            </div>
          </div>
        )}

        {/* Permit Type Breakdown & Data Quality */}
        {permitBreakdown && permitBreakdown.permit_types.length > 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            {/* Permit Types */}
            <div>
              <h2 className="text-sm font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                <Building2 size={14} className="text-blue-400" />
                Permit Types
              </h2>
              <div className="bg-slate-800/30 border border-slate-700/20 rounded-xl p-4 space-y-2">
                {permitBreakdown.permit_types.slice(0, 8).map((pt) => (
                  <div key={pt.type} className="flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-slate-300 truncate">{pt.type}</span>
                        <span className="text-xs text-slate-500 ml-2">{pt.count.toLocaleString()}</span>
                      </div>
                      <div className="h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-blue-500/60 rounded-full"
                          style={{ width: `${Math.min(pt.pct, 100)}%` }}
                        />
                      </div>
                    </div>
                    <span className="text-[10px] text-slate-500 w-10 text-right">{pt.pct}%</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Data Quality */}
            <div>
              <h2 className="text-sm font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                <MapPin size={14} className="text-emerald-400" />
                Data Quality
              </h2>
              <div className="bg-slate-800/30 border border-slate-700/20 rounded-xl p-4 space-y-4">
                {[
                  { label: "Has Address", value: permitBreakdown.data_quality.has_address, pct: permitBreakdown.data_quality.address_pct, color: "bg-emerald-500/60" },
                  { label: "Geocoded", value: permitBreakdown.data_quality.has_geocode, pct: permitBreakdown.data_quality.geocode_pct, color: "bg-blue-500/60" },
                  { label: "Has Date", value: permitBreakdown.data_quality.has_date, pct: permitBreakdown.data_quality.date_pct, color: "bg-purple-500/60" },
                ].map((metric) => (
                  <div key={metric.label}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-slate-300">{metric.label}</span>
                      <span className="text-xs text-slate-500">
                        {metric.value.toLocaleString()} / {permitBreakdown.data_quality.total_permits.toLocaleString()} ({metric.pct}%)
                      </span>
                    </div>
                    <div className="h-2 bg-slate-700/50 rounded-full overflow-hidden">
                      <div
                        className={`h-full ${metric.color} rounded-full transition-all`}
                        style={{ width: `${Math.min(metric.pct, 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
                <div className="pt-2 border-t border-slate-700/30">
                  <div className="text-xs text-slate-500">
                    Total: <span className="text-white font-medium">{permitBreakdown.data_quality.total_permits.toLocaleString()}</span> permits tracked
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Scraped Permits */}
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
            <Hammer size={14} className="text-amber-400" />
            Recent Permits
            {scrapedPermits.length > 0 && (
              <span className="text-xs text-slate-500 font-normal normal-case ml-1">
                ({scrapedPermits.length})
              </span>
            )}
          </h2>

          {permitsLoading ? (
            <div className="text-center py-6">
              <Loader2 size={20} className="mx-auto text-blue-400 animate-spin mb-2" />
              <p className="text-slate-500 text-xs">Loading permits...</p>
            </div>
          ) : scrapedPermits.length > 0 ? (
            <div className="bg-slate-800/30 border border-slate-700/20 rounded-xl overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-700/30">
                    <th className="text-left text-slate-500 font-medium px-4 py-2">Permit #</th>
                    <th className="text-left text-slate-500 font-medium px-4 py-2">Type</th>
                    <th className="text-left text-slate-500 font-medium px-4 py-2">Address</th>
                    <th className="text-left text-slate-500 font-medium px-4 py-2">Status</th>
                    <th className="text-right text-slate-500 font-medium px-4 py-2">Value</th>
                    <th className="text-right text-slate-500 font-medium px-4 py-2">Filed</th>
                  </tr>
                </thead>
                <tbody>
                  {scrapedPermits.map((p: any, i: number) => (
                    <tr key={p.id || i} className="border-b border-slate-700/10 hover:bg-slate-800/40">
                      <td className="px-4 py-2 font-mono text-blue-400 text-[10px]">
                        {p.permit_number || "---"}
                      </td>
                      <td className="px-4 py-2 text-white">
                        {p.permit_type || "---"}
                      </td>
                      <td className="px-4 py-2 text-slate-300 truncate max-w-[200px]">
                        {p.address || "---"}
                      </td>
                      <td className="px-4 py-2">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          p.status === "APPROVED" || p.status === "ISSUED" || p.status === "COMPLETED"
                            ? "bg-emerald-500/10 text-emerald-400"
                            : p.status === "DENIED"
                            ? "bg-red-500/10 text-red-400"
                            : p.status === "FILED" || p.status === "UNDER_REVIEW"
                            ? "bg-blue-500/10 text-blue-400"
                            : "bg-slate-500/10 text-slate-400"
                        }`}>
                          {p.status || "---"}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right text-slate-300">
                        {p.estimated_value
                          ? `$${Number(p.estimated_value).toLocaleString()}`
                          : "---"}
                      </td>
                      <td className="px-4 py-2 text-right text-slate-500">
                        {p.filed_date || "---"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="bg-slate-800/20 border border-slate-700/20 rounded-xl p-6 text-center">
              <Hammer size={20} className="mx-auto text-slate-600 mb-2" />
              <p className="text-slate-500 text-sm">No scraped permits yet</p>
              <p className="text-slate-600 text-xs mt-1">
                Run the scraper to populate permit data for this town
              </p>
            </div>
          )}
        </div>

        {/* Two Column: Recent Sales + Documents */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Recent Sales */}
          <div>
            <h2 className="text-sm font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
              <DollarSign size={14} className="text-emerald-400" />
              Recent Sales
            </h2>

            {data?.recent_sales && data.recent_sales.length > 0 ? (
              <div className="space-y-2">
                {data.recent_sales.slice(0, 10).map((sale: any, i: number) => (
                  <div
                    key={sale.loc_id || i}
                    className="bg-slate-800/40 border border-slate-700/30 rounded-lg px-4 py-3"
                  >
                    <div className="flex items-start justify-between">
                      <div className="min-w-0">
                        <div className="text-white text-sm font-medium truncate">
                          {sale.site_addr || "Unknown Address"}
                        </div>
                        <div className="text-slate-500 text-xs mt-0.5">
                          {sale.owner || "Owner unknown"}
                        </div>
                      </div>
                      <div className="text-right flex-shrink-0 ml-3">
                        <div className="text-emerald-400 text-sm font-semibold">
                          {sale.last_sale_price
                            ? formatPrice(sale.last_sale_price)
                            : "N/A"}
                        </div>
                        <div className="text-slate-500 text-[10px]">
                          {sale.last_sale_date || ""}
                        </div>
                      </div>
                    </div>
                    {(sale.building_area_sqft || sale.lot_size_acres) && (
                      <div className="flex gap-3 mt-2 text-[10px] text-slate-500">
                        {sale.building_area_sqft && (
                          <span>{sale.building_area_sqft.toLocaleString()} sqft</span>
                        )}
                        {sale.lot_size_acres && (
                          <span>{sale.lot_size_acres} acres</span>
                        )}
                        {sale.year_built && <span>Built {sale.year_built}</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-slate-800/20 border border-slate-700/20 rounded-xl p-6 text-center">
                <TrendingDown size={20} className="mx-auto text-slate-600 mb-2" />
                <p className="text-slate-500 text-sm">No recent sales data</p>
                <p className="text-slate-600 text-xs mt-1">
                  Sales data is scraped from MassGIS daily
                </p>
              </div>
            )}
          </div>

          {/* Recent Documents */}
          <div>
            <h2 className="text-sm font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
              <FileText size={14} className="text-purple-400" />
              Municipal Documents
            </h2>

            {data?.recent_documents && data.recent_documents.length > 0 ? (
              <div className="space-y-2">
                {data.recent_documents.slice(0, 10).map((doc: any, i: number) => (
                  <div
                    key={doc.id || i}
                    className="bg-slate-800/40 border border-slate-700/30 rounded-lg px-4 py-3"
                  >
                    <div className="flex items-start gap-2">
                      <Calendar size={12} className="text-slate-500 mt-0.5 flex-shrink-0" />
                      <div className="min-w-0">
                        <div className="text-white text-sm font-medium">
                          {doc.title || "Untitled Document"}
                        </div>
                        <div className="text-slate-500 text-xs mt-0.5">
                          {doc.board && <span className="text-purple-400/80">{doc.board}</span>}
                          {doc.meeting_date && <span> &middot; {doc.meeting_date}</span>}
                        </div>
                        {doc.content_summary && (
                          <p className="text-slate-400 text-xs mt-1.5 line-clamp-2">
                            {doc.content_summary}
                          </p>
                        )}
                        {doc.keywords && Array.isArray(doc.keywords) && doc.keywords.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {doc.keywords.slice(0, 4).map((kw: string, ki: number) => (
                              <span
                                key={ki}
                                className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400"
                              >
                                {kw}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-slate-800/20 border border-slate-700/20 rounded-xl p-6 text-center">
                <FileText size={20} className="mx-auto text-slate-600 mb-2" />
                <p className="text-slate-500 text-sm">No documents scraped yet</p>
                <p className="text-slate-600 text-xs mt-1">
                  Meeting minutes are scraped weekly from town websites
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Scrape Jobs */}
        {data?.scrape_jobs && data.scrape_jobs.length > 0 && (
          <div className="mt-8">
            <h2 className="text-sm font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
              <Clock size={14} className="text-slate-400" />
              Recent Scrape Activity
            </h2>
            <div className="bg-slate-800/30 border border-slate-700/20 rounded-xl overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-700/30">
                    <th className="text-left text-slate-500 font-medium px-4 py-2">Source</th>
                    <th className="text-left text-slate-500 font-medium px-4 py-2">Status</th>
                    <th className="text-right text-slate-500 font-medium px-4 py-2">Found</th>
                    <th className="text-right text-slate-500 font-medium px-4 py-2">New</th>
                    <th className="text-right text-slate-500 font-medium px-4 py-2">When</th>
                  </tr>
                </thead>
                <tbody>
                  {data.scrape_jobs.map((job: any, i: number) => (
                    <tr key={job.id || i} className="border-b border-slate-700/10">
                      <td className="px-4 py-2 text-white">{job.source_type}</td>
                      <td className="px-4 py-2">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                            job.status === "completed"
                              ? "bg-emerald-500/10 text-emerald-400"
                              : job.status === "failed"
                              ? "bg-red-500/10 text-red-400"
                              : job.status === "running"
                              ? "bg-blue-500/10 text-blue-400"
                              : "bg-slate-500/10 text-slate-400"
                          }`}
                        >
                          {job.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right text-slate-300">{job.records_found || 0}</td>
                      <td className="px-4 py-2 text-right text-emerald-400">{job.records_new || 0}</td>
                      <td className="px-4 py-2 text-right text-slate-500">
                        {job.completed_at
                          ? new Date(job.completed_at).toLocaleDateString()
                          : "---"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default TownDashboard;
