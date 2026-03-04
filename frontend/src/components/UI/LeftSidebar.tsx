import React, { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Plus,
  MapPin,
  Layers,
  FileText,
  Camera,
  Waves,
  Activity,
} from "lucide-react";
import { useStore, MARKETS, MARKET_NAMES } from "../../store/useStore";

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

// ─── Format large numbers ────────────────────────────────────────────────────
function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

// ─── Section Header ──────────────────────────────────────────────────────────
const SectionHeader: React.FC<{
  title: string;
  badge?: number;
  action?: React.ReactNode;
  collapsible?: boolean;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}> = ({ title, badge, action, collapsible, collapsed, onToggleCollapse }) => (
  <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-parcl-text-dim border-b border-parcl-border flex items-center gap-2">
    {collapsible && (
      <button
        onClick={onToggleCollapse}
        className="text-parcl-text-dim hover:text-parcl-text"
      >
        {collapsed ? (
          <ChevronRight className="w-3 h-3" />
        ) : (
          <ChevronDown className="w-3 h-3" />
        )}
      </button>
    )}
    <span className="flex-1">{title}</span>
    {badge !== undefined && badge > 0 && (
      <span className="text-[9px] font-mono tabular-nums bg-parcl-accent/10 text-parcl-accent px-1.5 py-0.5 rounded-full">
        {badge}
      </span>
    )}
    {action}
  </div>
);

// ─── Left Sidebar ────────────────────────────────────────────────────────────
const LeftSidebar: React.FC = () => {
  // Tracked listings state
  const trackedListings = useStore((s) => s.trackedListings);
  const selectedListingId = useStore((s) => s.selectedListingId);
  const selectListing = useStore((s) => s.selectListing);

  // Markets state
  const activeCity = useStore((s) => s.activeCity);
  const setActiveCity = useStore((s) => s.setActiveCity);
  const activePOIIndex = useStore((s) => s.activePOIIndex);
  const navigateToPOI = useStore((s) => s.navigateToPOI);

  // Data layer state
  const permits = useStore((s) => s.permits);
  const totalPermitsAvailable = useStore((s) => s.totalPermitsAvailable);
  const showPermits = useStore((s) => s.showPermits);
  const showFloodZones = useStore((s) => s.showFloodZones);
  const showParcels = useStore((s) => s.showParcels);
  const togglePermits = useStore((s) => s.togglePermits);
  const toggleFloodZones = useStore((s) => s.toggleFloodZones);
  const toggleParcels = useStore((s) => s.toggleParcels);

  // Local UI state
  const [dataLayersOpen, setDataLayersOpen] = useState(true);
  const [showAddInput, setShowAddInput] = useState(false);

  const pois = MARKETS[activeCity] ?? [];
  const permitsDisplayCount = totalPermitsAvailable || permits.length;

  const layers = [
    {
      icon: <FileText className="w-3.5 h-3.5 text-blue-400" />,
      label: "Permits",
      count: permitsDisplayCount,
      isOn: showPermits,
      onToggle: togglePermits,
    },
    {
      icon: <Waves className="w-3.5 h-3.5 text-sky-400" />,
      label: "Flood Zones",
      count: null,
      isOn: showFloodZones,
      onToggle: toggleFloodZones,
    },
    {
      icon: <Layers className="w-3.5 h-3.5 text-amber-400" />,
      label: "Parcels (MA)",
      count: null,
      isOn: showParcels,
      onToggle: toggleParcels,
    },
  ];

  return (
    <div className="w-[280px] flex-shrink-0 bg-parcl-panel/95 border-r border-parcl-border flex flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {/* ── Section 1: MY LISTINGS ─────────────────────────────────────── */}
        <SectionHeader
          title="MY LISTINGS"
          badge={trackedListings.length}
          action={
            <button
              onClick={() => setShowAddInput(!showAddInput)}
              className="text-parcl-text-dim hover:text-parcl-accent transition-colors"
              title="Add listing"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          }
        />
        <div className="border-b border-parcl-border">
          {showAddInput && (
            <div className="px-3 py-2">
              <input
                type="text"
                placeholder="Search address to track..."
                autoFocus
                className="w-full bg-parcl-surface border border-parcl-border rounded px-2 py-1.5 text-[11px] text-parcl-text placeholder-parcl-text-dim focus:outline-none focus:border-parcl-accent transition-colors"
                onKeyDown={(e) => {
                  if (e.key === "Escape") setShowAddInput(false);
                }}
              />
            </div>
          )}

          {trackedListings.length === 0 ? (
            <div className="px-3 py-4 text-[10px] text-parcl-text-dim text-center">
              Search for properties to start tracking
            </div>
          ) : (
            <div className="py-1">
              {trackedListings.map((listing) => (
                <button
                  key={listing.id}
                  onClick={() => selectListing(listing.id)}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-left transition-colors ${
                    selectedListingId === listing.id
                      ? "bg-parcl-accent/10 text-parcl-accent"
                      : "text-parcl-text-dim hover:text-parcl-text hover:bg-parcl-surface"
                  }`}
                >
                  {/* Agent indicator */}
                  <div className="flex-shrink-0">
                    {listing.agentId ? (
                      <div className="w-2 h-2 rounded-full bg-parcl-green" />
                    ) : (
                      <div className="w-2 h-2 rounded-full border border-parcl-text-dim" />
                    )}
                  </div>
                  {/* Address */}
                  <span className="flex-1 text-[11px] truncate">
                    {listing.address}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* ── Section 2: MARKETS ─────────────────────────────────────────── */}
        <SectionHeader title="MARKETS" />
        <div className="px-3 py-2 space-y-2 border-b border-parcl-border">
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
          <div className="space-y-0.5">
            {pois.map((poi, index) => (
              <button
                key={poi.id}
                onClick={() => navigateToPOI(index)}
                className={`flex items-center gap-2 px-2 py-1.5 text-[10px] rounded cursor-pointer transition-colors w-full text-left ${
                  activePOIIndex === index
                    ? "bg-parcl-accent/10 text-parcl-accent"
                    : "text-parcl-text-dim hover:text-parcl-text hover:bg-parcl-surface"
                }`}
              >
                <MapPin className="w-3 h-3 flex-shrink-0" />
                {poi.name}
              </button>
            ))}
          </div>
        </div>

        {/* ── Section 3: DATA LAYERS (collapsible) ───────────────────────── */}
        <SectionHeader
          title="DATA LAYERS"
          collapsible
          collapsed={!dataLayersOpen}
          onToggleCollapse={() => setDataLayersOpen(!dataLayersOpen)}
        />
        {dataLayersOpen && (
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
        )}
      </div>
    </div>
  );
};

export default LeftSidebar;
