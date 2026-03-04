import React, { useState, useMemo, useCallback } from "react";
import {
  Eye,
  Satellite,
  ShieldAlert,
  FileText,
  Home,
  Camera,
  Waves,
  Activity,
  ChevronDown,
  MapPin,
  Search,
  X,
  BarChart3,
} from "lucide-react";
import { useStore, MARKETS, MARKET_NAMES } from "../../store/useStore";
import { searchPermits } from "../../services/api";
import type { ViewMode } from "../../types";

// ─── Toggle Switch ───────────────────────────────────────────────────────────
const Toggle: React.FC<{ isOn: boolean; onToggle: () => void }> = ({
  isOn,
  onToggle,
}) => (
  <button
    onClick={onToggle}
    className={`relative w-8 h-4 rounded-full transition-colors ${
      isOn ? "bg-parcl-accent" : "bg-parcl-border"
    }`}
  >
    <div
      className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${
        isOn ? "translate-x-4" : "translate-x-0.5"
      }`}
    />
  </button>
);

// ─── View Mode Config ────────────────────────────────────────────────────────
const VIEW_MODES: { key: ViewMode; label: string; icon: React.ReactNode }[] = [
  { key: "standard", label: "STD", icon: <Eye className="w-3 h-3" /> },
  {
    key: "satellite",
    label: "SAT",
    icon: <Satellite className="w-3 h-3" />,
  },
  {
    key: "risk",
    label: "RISK",
    icon: <ShieldAlert className="w-3 h-3" />,
  },
];

// ─── Format large numbers ────────────────────────────────────────────────────
function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

// ─── Data Layer Panel ────────────────────────────────────────────────────────
const DataLayerPanel: React.FC = () => {
  const viewMode = useStore((s) => s.viewMode);
  const setViewMode = useStore((s) => s.setViewMode);

  const permits = useStore((s) => s.permits);
  const totalPermitsAvailable = useStore((s) => s.totalPermitsAvailable);
  const propertySearchResults = useStore((s) => s.propertySearchResults);
  const showPermits = useStore((s) => s.showPermits);
  const showProperties = useStore((s) => s.showProperties);
  const showFloodZones = useStore((s) => s.showFloodZones);

  const togglePermits = useStore((s) => s.togglePermits);
  const toggleProperties = useStore((s) => s.toggleProperties);
  const toggleFloodZones = useStore((s) => s.toggleFloodZones);

  const activeCity = useStore((s) => s.activeCity);
  const setActiveCity = useStore((s) => s.setActiveCity);
  const activePOIIndex = useStore((s) => s.activePOIIndex);
  const navigateToPOI = useStore((s) => s.navigateToPOI);

  // Town state
  const towns = useStore((s) => s.towns);
  const activeTown = useStore((s) => s.activeTown);
  const setActiveTown = useStore((s) => s.setActiveTown);
  const setPermits = useStore((s) => s.setPermits);
  const setTotalPermitsAvailable = useStore((s) => s.setTotalPermitsAvailable);

  // Coverage state
  const coverageSummary = useStore((s) => s.coverageSummary);
  const townDetails = useStore((s) => s.townDetails);

  const [townSearch, setTownSearch] = useState("");
  const [isLoadingTown, setIsLoadingTown] = useState(false);

  const pois = MARKETS[activeCity] ?? [];

  // Permit count: show total available from Supabase, fallback to loaded count
  const permitsDisplayCount = totalPermitsAvailable || permits.length;

  // Towns with permits, sorted by count (already sorted by backend)
  const townsWithPermits = useMemo(
    () => towns.filter((t) => t.permit_count > 0),
    [towns],
  );

  // Filter towns by search query
  const filteredTowns = useMemo(() => {
    if (!townSearch.trim()) return townsWithPermits;
    const q = townSearch.toLowerCase();
    return towns.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.id.toLowerCase().includes(q) ||
        (t.county && t.county.toLowerCase().includes(q)),
    );
  }, [towns, townsWithPermits, townSearch]);

  // Handle town selection — fetch permits filtered by town
  const handleTownSelect = useCallback(
    async (townId: string | null) => {
      setActiveTown(townId);
      setIsLoadingTown(true);
      try {
        const params: { limit: number; town?: string } = { limit: 500 };
        if (townId) params.town = townId;
        const response = await searchPermits(params);
        setPermits(response.permits);
        if ((response as any).total_available) {
          setTotalPermitsAvailable((response as any).total_available);
        }
      } catch (err) {
        console.warn("[Parcl] Failed to fetch permits for town:", err);
      } finally {
        setIsLoadingTown(false);
      }
    },
    [setActiveTown, setPermits, setTotalPermitsAvailable],
  );

  // Layer definitions
  const layers = [
    {
      icon: <FileText className="w-3.5 h-3.5 text-blue-400" />,
      label: "Permits",
      count: permitsDisplayCount,
      isOn: showPermits,
      onToggle: togglePermits,
    },
    {
      icon: <Home className="w-3.5 h-3.5 text-emerald-400" />,
      label: "Properties",
      count: propertySearchResults.length,
      isOn: showProperties,
      onToggle: toggleProperties,
    },
    {
      icon: <Waves className="w-3.5 h-3.5 text-sky-400" />,
      label: "Flood Zones",
      count: null,
      isOn: showFloodZones,
      onToggle: toggleFloodZones,
    },
  ];

  return (
    <div className="fixed top-16 right-[396px] z-40 w-56 bg-parcl-panel/95 backdrop-blur-lg border border-parcl-border rounded-lg shadow-tactical">
      {/* ── Section 1: VIEW MODE ─────────────────────────────────────────── */}
      <div className="text-[10px] font-semibold uppercase tracking-widest text-parcl-text-dim px-3 py-2 border-b border-parcl-border">
        View Mode
      </div>
      <div className="flex gap-1 px-3 py-2 border-b border-parcl-border">
        {VIEW_MODES.map((mode) => (
          <button
            key={mode.key}
            onClick={() => setViewMode(mode.key)}
            className={`flex items-center gap-1 px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider rounded transition-all ${
              viewMode === mode.key
                ? "bg-parcl-accent text-white"
                : "bg-parcl-surface text-parcl-text-dim hover:text-parcl-text hover:bg-parcl-border"
            }`}
          >
            {mode.icon}
            {mode.label}
          </button>
        ))}
      </div>

      {/* ── Section 2: DATA LAYERS ───────────────────────────────────────── */}
      <div className="text-[10px] font-semibold uppercase tracking-widest text-parcl-text-dim px-3 py-2 border-b border-parcl-border">
        Data Layers
      </div>
      <div className="px-3 py-2 space-y-1.5 border-b border-parcl-border">
        {layers.map((layer) => (
          <div
            key={layer.label}
            className="flex items-center gap-2 text-[11px]"
          >
            {layer.icon}
            <span className="flex-1 text-parcl-text text-[11px]">
              {layer.label}
            </span>
            {layer.count !== null && (
              <span className="text-[10px] text-parcl-text-dim tabular-nums">
                {formatCount(layer.count)}
              </span>
            )}
            <Toggle isOn={layer.isOn} onToggle={layer.onToggle} />
          </div>
        ))}
      </div>

      {/* ── Section 3: MUNICIPALITIES (MA Towns) ─────────────────────────── */}
      {towns.length > 0 && (
        <>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-parcl-text-dim px-3 py-2 border-b border-parcl-border flex items-center justify-between">
            <span className="flex items-center gap-1">
              <MapPin className="w-3 h-3" />
              Municipalities
            </span>
            <span className="text-[9px] font-normal text-parcl-text-dim tabular-nums">
              {townsWithPermits.length} active
            </span>
          </div>
          <div className="px-3 py-2 space-y-2 border-b border-parcl-border">
            {/* Search input */}
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-parcl-text-dim" />
              <input
                type="text"
                value={townSearch}
                onChange={(e) => setTownSearch(e.target.value)}
                placeholder="Search 351 MA towns..."
                className="w-full bg-parcl-surface border border-parcl-border rounded pl-7 pr-7 py-1.5 text-[10px] text-parcl-text placeholder-parcl-text-dim focus:outline-none focus:border-parcl-accent transition-colors"
              />
              {townSearch && (
                <button
                  onClick={() => setTownSearch("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-parcl-text-dim hover:text-parcl-text"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>

            {/* Active town indicator */}
            {activeTown && (
              <div className="flex items-center gap-1.5 text-[10px]">
                <span className="text-parcl-accent font-medium truncate flex-1">
                  {towns.find((t) => t.id === activeTown)?.name ?? activeTown}
                </span>
                <button
                  onClick={() => handleTownSelect(null)}
                  className="text-parcl-text-dim hover:text-parcl-text text-[9px] px-1.5 py-0.5 rounded bg-parcl-surface"
                >
                  Clear
                </button>
              </div>
            )}

            {/* Town list */}
            <div className="space-y-0.5 max-h-32 overflow-y-auto scrollbar-thin">
              {filteredTowns.slice(0, 50).map((town) => {
                const detail = townDetails.find((td) => td.id === town.id);
                const covPct = detail?.coverage_pct ?? 0;
                return (
                  <button
                    key={town.id}
                    onClick={() => handleTownSelect(town.id)}
                    disabled={isLoadingTown}
                    className={`flex items-center gap-1.5 px-2 py-1 text-[10px] rounded cursor-pointer transition-colors w-full text-left ${
                      activeTown === town.id
                        ? "bg-parcl-accent/10 text-parcl-accent"
                        : "text-parcl-text-dim hover:text-parcl-text hover:bg-parcl-surface"
                    }`}
                    title={detail ? `${detail.coverage_ready}/${detail.coverage_total} sources (${covPct}%) | ${formatCount(town.permit_count)} permits` : undefined}
                  >
                    <span className="flex-1 truncate">{town.name}</span>
                    {covPct > 0 && (
                      <div className="w-8 h-1.5 bg-parcl-border/50 rounded-full overflow-hidden" title={`${covPct}% coverage`}>
                        <div
                          className="h-full bg-emerald-500/70 rounded-full"
                          style={{ width: `${covPct}%` }}
                        />
                      </div>
                    )}
                    {town.permit_count > 0 && (
                      <span className="text-[9px] tabular-nums opacity-60">
                        {formatCount(town.permit_count)}
                      </span>
                    )}
                  </button>
                );
              })}
              {filteredTowns.length === 0 && (
                <div className="text-[10px] text-parcl-text-dim text-center py-2">
                  No towns found
                </div>
              )}
              {filteredTowns.length > 50 && (
                <div className="text-[9px] text-parcl-text-dim text-center py-1">
                  +{filteredTowns.length - 50} more — refine search
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ── Section 4: STATEWIDE COVERAGE ──────────────────────────────── */}
      {coverageSummary && coverageSummary.sources.length > 0 && (
        <>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-parcl-text-dim px-3 py-2 border-b border-parcl-border flex items-center justify-between">
            <span className="flex items-center gap-1">
              <BarChart3 className="w-3 h-3" />
              Statewide Coverage
            </span>
            <span className="text-[9px] font-normal text-parcl-text-dim tabular-nums">
              {coverageSummary.total_source_types} sources
            </span>
          </div>
          <div className="px-3 py-2 space-y-1 border-b border-parcl-border max-h-36 overflow-y-auto scrollbar-thin">
            {/* Group by category */}
            {(() => {
              const categories: Record<string, typeof coverageSummary.sources> = {};
              for (const src of coverageSummary.sources) {
                const cat = src.category || "other";
                if (!categories[cat]) categories[cat] = [];
                categories[cat].push(src);
              }
              return Object.entries(categories).map(([cat, sources]) => {
                const totalReady = sources.reduce((s, src) => s + src.ready, 0);
                const totalAll = sources.reduce((s, src) => s + src.total_municipalities, 0);
                const pct = totalAll > 0 ? Math.round((totalReady / totalAll) * 100) : 0;
                return (
                  <div key={cat} className="flex items-center gap-1.5 text-[10px]">
                    <span className="flex-1 text-parcl-text capitalize truncate">{cat.replace(/_/g, " ")}</span>
                    <div className="w-12 h-1.5 bg-parcl-border/50 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${pct > 20 ? "bg-emerald-500/70" : pct > 0 ? "bg-amber-500/70" : "bg-parcl-border"}`}
                        style={{ width: `${Math.max(pct, 2)}%` }}
                      />
                    </div>
                    <span className="text-[9px] tabular-nums text-parcl-text-dim w-7 text-right">{pct}%</span>
                  </div>
                );
              });
            })()}
            {/* Overall stats */}
            <div className="pt-1 mt-1 border-t border-parcl-border/30 flex items-center gap-2 text-[9px] text-parcl-text-dim">
              <span className="tabular-nums">
                {coverageSummary.sources.reduce((s, src) => s + src.ready, 0).toLocaleString()} ready
              </span>
              <span>/</span>
              <span className="tabular-nums">
                {coverageSummary.total_coverage_rows.toLocaleString()} total
              </span>
            </div>
          </div>
        </>
      )}

      {/* ── Section 5: MARKETS (Globe Navigation) ────────────────────────── */}
      <div className="text-[10px] font-semibold uppercase tracking-widest text-parcl-text-dim px-3 py-2 border-b border-parcl-border">
        Markets
      </div>
      <div className="px-3 py-2 space-y-2">
        {/* Market dropdown */}
        <div className="relative">
          <select
            value={activeCity}
            onChange={(e) => setActiveCity(e.target.value)}
            className="w-full appearance-none bg-parcl-surface border border-parcl-border rounded px-2 py-1.5 text-[11px] text-parcl-text pr-7 focus:outline-none focus:border-parcl-accent transition-colors"
          >
            {MARKET_NAMES.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-parcl-text-dim pointer-events-none" />
        </div>

        {/* POI list */}
        <div className="space-y-0.5 max-h-40 overflow-y-auto">
          {pois.map((poi, index) => (
            <button
              key={poi.id}
              onClick={() => navigateToPOI(index)}
              className={`px-3 py-1.5 text-[10px] rounded cursor-pointer transition-colors w-full text-left ${
                activePOIIndex === index
                  ? "bg-parcl-accent/10 text-parcl-accent"
                  : "text-parcl-text-dim hover:text-parcl-text hover:bg-parcl-surface"
              }`}
            >
              {poi.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default DataLayerPanel;
