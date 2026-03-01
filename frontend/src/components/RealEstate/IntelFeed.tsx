import React, { useState, useMemo } from "react";
import {
  Activity,
  FileText,
  DollarSign,
  AlertTriangle,
  Hammer,
  Map,
  Home,
  TrendingUp,
  Satellite,
  Camera,
} from "lucide-react";
import { useStore } from "../../store/useStore";
import type { FindingType, AlertSeverity, AgentFinding } from "../../types";

// ─── Finding type -> icon mapping ──────────────────────────────────────────
const FINDING_ICONS: Record<FindingType, React.ElementType> = {
  PERMIT_ACTIVITY: FileText,
  PRICE_CHANGE: DollarSign,
  RISK_UPDATE: AlertTriangle,
  CONSTRUCTION: Hammer,
  ZONING_CHANGE: Map,
  LISTING_CHANGE: Home,
  MARKET_SHIFT: TrendingUp,
  MEETING_MENTION: FileText,
  SATELLITE_CHANGE: Satellite,
  CAMERA_ANOMALY: Camera,
};

// ─── Finding type badge colors ─────────────────────────────────────────────
const FINDING_BADGE_COLORS: Record<string, string> = {
  PERMIT_ACTIVITY: "bg-parcl-blue/10 text-parcl-blue",
  PRICE_CHANGE: "bg-parcl-green/10 text-parcl-green",
  RISK_UPDATE: "bg-parcl-red/10 text-parcl-red",
  CONSTRUCTION: "bg-parcl-amber/10 text-parcl-amber",
};

function getBadgeColor(type: FindingType): string {
  return FINDING_BADGE_COLORS[type] ?? "bg-parcl-accent/10 text-parcl-accent";
}

// ─── Severity colors ───────────────────────────────────────────────────────
const SEVERITY_COLORS: Record<AlertSeverity, { text: string; bg: string }> = {
  CRITICAL: { text: "text-parcl-red", bg: "bg-parcl-red" },
  HIGH: { text: "text-parcl-red", bg: "bg-parcl-red" },
  MEDIUM: { text: "text-parcl-amber", bg: "bg-parcl-amber" },
  LOW: { text: "text-parcl-green", bg: "bg-parcl-green" },
  INFO: { text: "text-parcl-accent", bg: "bg-parcl-accent" },
};

// ─── Filter categories ─────────────────────────────────────────────────────
const FILTER_CHIPS = [
  { label: "All", value: "all" },
  { label: "Permits", value: "permits" },
  { label: "Price", value: "price" },
  { label: "Risk", value: "risk" },
  { label: "Construction", value: "construction" },
] as const;

type FilterValue = (typeof FILTER_CHIPS)[number]["value"];

const FILTER_TYPES: Record<string, FindingType[]> = {
  permits: ["PERMIT_ACTIVITY"],
  price: ["PRICE_CHANGE", "LISTING_CHANGE"],
  risk: ["RISK_UPDATE"],
  construction: ["CONSTRUCTION", "ZONING_CHANGE"],
};

// ─── Relative time helper ──────────────────────────────────────────────────
function relativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

// ─── Component ─────────────────────────────────────────────────────────────
const IntelFeed: React.FC = () => {
  const agentFindings = useStore((s) => s.agentFindings);
  const flyToLocation = useStore((s) => s.flyToLocation);
  const [activeFilter, setActiveFilter] = useState<FilterValue>("all");

  const filteredFindings = useMemo(() => {
    const sorted = [...agentFindings].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
    if (activeFilter === "all") return sorted;
    const allowedTypes = FILTER_TYPES[activeFilter];
    if (!allowedTypes) return sorted;
    return sorted.filter((f) => allowedTypes.includes(f.finding_type));
  }, [agentFindings, activeFilter]);

  const handleFindingClick = (finding: AgentFinding) => {
    if (finding.latitude != null && finding.longitude != null) {
      flyToLocation({
        lat: finding.latitude,
        lon: finding.longitude,
        altitude: 1000,
        heading: 0,
        pitch: -35,
      });
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Filter chips */}
      <div className="flex items-center gap-1.5 px-4 py-2 border-b border-parcl-border/50 flex-shrink-0">
        {FILTER_CHIPS.map((chip) => (
          <button
            key={chip.value}
            onClick={() => setActiveFilter(chip.value)}
            className={`px-2 py-0.5 text-[10px] font-medium rounded-full transition-colors cursor-pointer ${
              activeFilter === chip.value
                ? "bg-parcl-accent text-white"
                : "bg-parcl-surface text-parcl-text-dim hover:bg-parcl-border"
            }`}
          >
            {chip.label}
          </button>
        ))}
      </div>

      {/* Findings list */}
      <div className="flex-1 overflow-y-auto">
        {filteredFindings.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-parcl-text-muted px-6 py-10">
            <Activity className="w-8 h-8 mb-3 opacity-40" />
            <p className="text-xs text-center leading-relaxed">
              No intelligence findings yet. Create agents to start monitoring.
            </p>
          </div>
        ) : (
          filteredFindings.map((finding) => {
            const severity = SEVERITY_COLORS[finding.severity];
            const Icon =
              FINDING_ICONS[finding.finding_type] ?? Activity;
            const badgeColor = getBadgeColor(finding.finding_type);

            return (
              <div
                key={finding.id}
                onClick={() => handleFindingClick(finding)}
                className="px-3 py-2.5 border-b border-parcl-border/50 hover:bg-parcl-surface/50 cursor-pointer transition-colors"
              >
                <div className="flex items-start gap-2">
                  {/* Severity dot */}
                  <div className="flex-shrink-0 mt-1 relative">
                    <div
                      className={`w-2 h-2 rounded-full ${severity.bg} ${
                        finding.severity === "CRITICAL" ? "animate-pulse" : ""
                      }`}
                    />
                  </div>

                  <div className="flex-1 min-w-0">
                    {/* Title */}
                    <p className="text-xs font-bold text-parcl-text truncate">
                      {finding.title}
                    </p>

                    {/* Summary */}
                    <p className="text-[10px] text-parcl-text-dim mt-0.5 line-clamp-2">
                      {finding.summary}
                    </p>

                    {/* Bottom row: badge + timestamp */}
                    <div className="flex items-center gap-2 mt-1.5">
                      <span
                        className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider rounded-full ${badgeColor}`}
                      >
                        <Icon className="w-2.5 h-2.5" />
                        {finding.finding_type.replace(/_/g, " ")}
                      </span>
                      <span className="text-[9px] text-parcl-text-muted">
                        {relativeTime(finding.created_at)}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default IntelFeed;
