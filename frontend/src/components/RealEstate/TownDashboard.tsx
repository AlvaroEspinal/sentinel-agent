import React, { useState, useEffect } from "react";
import {
  Building2,
  FileText,
  AlertTriangle,
  ScrollText,
  Leaf,
  Landmark,
  Users,
  Loader2,
  MapPin,
} from "lucide-react";
import { getTownDashboardStats } from "../../services/api";
import type { TownDashboardStats } from "../../types";

// ─── Stat Card ──────────────────────────────────────────────────────────────
const StatCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color?: string;
}> = ({ icon, label, value, color = "text-parcl-accent" }) => (
  <div className="p-2.5 rounded-md bg-parcl-surface border border-parcl-border/50">
    <div className="flex items-center gap-2 mb-1">
      {icon}
      <span className="text-[9px] uppercase tracking-wider text-parcl-text-muted">
        {label}
      </span>
    </div>
    <div className={`text-lg font-bold tabular-nums ${color}`}>
      {typeof value === "number" ? value.toLocaleString() : value}
    </div>
  </div>
);

// ─── Town Dashboard ─────────────────────────────────────────────────────────
const TownDashboard: React.FC<{ townId: string }> = ({ townId }) => {
  const [stats, setStats] = useState<TownDashboardStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!townId) return;
    setLoading(true);
    setError(null);
    getTownDashboardStats(townId)
      .then((data) => {
        // API may return an error object instead of stats
        if (data && data.town_id) {
          setStats(data);
        } else {
          setStats(null);
          setError("No dashboard data available for this town");
        }
      })
      .catch(() => {
        setStats(null);
        setError("Failed to load town dashboard");
      })
      .finally(() => setLoading(false));
  }, [townId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-6">
        <Loader2 className="w-4 h-4 text-parcl-accent animate-spin" />
        <span className="text-xs text-parcl-text-muted">Loading dashboard...</span>
      </div>
    );
  }

  if (error || !stats) {
    return (
      <div className="text-xs text-parcl-text-muted text-center py-6">
        {error || "No data available"}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Town header */}
      <div className="flex items-center gap-2 px-1">
        <MapPin className="w-4 h-4 text-parcl-accent flex-shrink-0" />
        <div>
          <div className="text-sm font-semibold text-parcl-text">
            {stats.town_name}
          </div>
          <div className="text-[10px] text-parcl-text-muted">
            {[stats.county, "MA"].filter(Boolean).join(", ")}
          </div>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-2">
        <StatCard
          icon={<Users className="w-3.5 h-3.5 text-blue-400" />}
          label="Population"
          value={stats.population ?? "N/A"}
          color="text-blue-400"
        />
        <StatCard
          icon={<Building2 className="w-3.5 h-3.5 text-emerald-400" />}
          label="Properties"
          value={stats.total_properties}
          color="text-emerald-400"
        />
        <StatCard
          icon={<FileText className="w-3.5 h-3.5 text-sky-400" />}
          label="Permits"
          value={stats.total_permits}
          color="text-sky-400"
        />
        <StatCard
          icon={<AlertTriangle className="w-3.5 h-3.5 text-red-400" />}
          label="Tax Delinquent"
          value={stats.tax_delinquent_count}
          color="text-red-400"
        />
        <StatCard
          icon={<ScrollText className="w-3.5 h-3.5 text-amber-400" />}
          label="Meeting Minutes"
          value={stats.meeting_minutes_count}
          color="text-amber-400"
        />
        <StatCard
          icon={<Landmark className="w-3.5 h-3.5 text-indigo-400" />}
          label="CIP Docs"
          value={stats.cip_count}
          color="text-indigo-400"
        />
        <StatCard
          icon={<Leaf className="w-3.5 h-3.5 text-green-400" />}
          label="MEPA Filings"
          value={stats.mepa_filing_count}
          color="text-green-400"
        />
        {stats.avg_tax_assessment > 0 && (
          <StatCard
            icon={<Building2 className="w-3.5 h-3.5 text-purple-400" />}
            label="Avg Assessment"
            value={`$${Math.round(stats.avg_tax_assessment).toLocaleString()}`}
            color="text-purple-400"
          />
        )}
      </div>

      <div className="text-[8px] text-parcl-text-muted mt-1">
        Source: Municipal Intelligence System &middot; v_town_dashboard
      </div>
    </div>
  );
};

export default TownDashboard;
