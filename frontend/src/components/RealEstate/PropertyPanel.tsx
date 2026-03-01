import React, { useState, useEffect, useCallback } from "react";
import {
  MapPin,
  X,
  ChevronLeft,
  ChevronRight,
  Bed,
  Bath,
  Ruler,
  Calendar,
  DollarSign,
  FileText,
  Shield,
  Bot,
  Plus,
  Trash2,
  AlertTriangle,
  Loader2,
  Home,
} from "lucide-react";
import { useStore } from "../../store/useStore";
import {
  getPermitsNear,
  createPropertyAgent,
  deletePropertyAgent,
  listPropertyAgents,
} from "../../services/api";
import type { Permit, PropertyMonitorAgent } from "../../types";

// ─── Formatters ──────────────────────────────────────────────────────────────

const fmtCurrency = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);

const fmtNumber = (value: number) =>
  new Intl.NumberFormat("en-US").format(value);

const fmtDate = (date: string) => new Date(date).toLocaleDateString();

const fmtRelativeTime = (date: string) => {
  const diff = Date.now() - new Date(date).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
};

// ─── Badge helpers ───────────────────────────────────────────────────────────

const propertyTypeBadgeClass = (type: string): string => {
  switch (type) {
    case "SINGLE_FAMILY":
    case "TOWNHOUSE":
      return "badge-blue";
    case "MULTI_FAMILY":
    case "CONDO":
      return "badge-green";
    case "COMMERCIAL":
    case "MIXED_USE":
      return "badge-amber";
    case "LAND":
      return "badge-red";
    default:
      return "badge-blue";
  }
};

const permitTypeBadgeClass = (type: string | null): string => {
  if (!type) return "badge-blue";
  const t = type.toUpperCase();
  if (t.includes("DEMOLITION")) return "badge-red";
  if (t.includes("COMMERCIAL")) return "badge-amber";
  if (t.includes("RESIDENTIAL")) return "badge-blue";
  if (t.includes("ELECTRICAL") || t.includes("PLUMBING")) return "badge-green";
  return "badge-blue";
};

const permitStatusBadgeClass = (status: string): string => {
  switch (status) {
    case "FILED":
    case "UNDER_REVIEW":
      return "badge-blue";
    case "APPROVED":
    case "ISSUED":
    case "COMPLETED":
      return "badge-green";
    case "IN_PROGRESS":
      return "badge-amber";
    case "DENIED":
    case "EXPIRED":
    case "WITHDRAWN":
      return "badge-red";
    default:
      return "badge-blue";
  }
};

const agentTypeBadgeClass = (type: string): string => {
  switch (type) {
    case "listing":
      return "badge-blue";
    case "neighborhood":
    case "community_intel":
      return "badge-green";
    case "climate_risk":
      return "badge-red";
    case "development_scout":
    case "market_pulse":
      return "badge-amber";
    default:
      return "badge-blue";
  }
};

const agentStatusDot = (status: string): string => {
  switch (status) {
    case "active":
      return "bg-parcl-green";
    case "paused":
      return "bg-parcl-amber";
    case "error":
      return "bg-parcl-red";
    default:
      return "bg-parcl-text-muted";
  }
};

const riskBarColor = (score: number): string => {
  if (score <= 30) return "bg-parcl-green";
  if (score <= 60) return "bg-parcl-amber";
  return "bg-parcl-red";
};

const riskLabelColor = (score: number): string => {
  if (score <= 30) return "text-parcl-green";
  if (score <= 60) return "text-parcl-amber";
  return "text-parcl-red";
};

// ─── Tab definitions ─────────────────────────────────────────────────────────

const TABS = [
  { key: "summary" as const, label: "Summary", icon: Home },
  { key: "permits" as const, label: "Permits", icon: FileText },
  { key: "risk" as const, label: "Risk", icon: Shield },
  { key: "agents" as const, label: "Agents", icon: Bot },
];

// ─── PropertyPanel Component ─────────────────────────────────────────────────

const PropertyPanel: React.FC = () => {
  const leftPanelOpen = useStore((s) => s.leftPanelOpen);
  const leftPanelTab = useStore((s) => s.leftPanelTab);
  const selectedProperty = useStore((s) => s.selectedProperty);
  const propertyAgents = useStore((s) => s.propertyAgents);
  const toggleLeftPanel = useStore((s) => s.toggleLeftPanel);
  const setLeftPanelTab = useStore((s) => s.setLeftPanelTab);
  const setSelectedProperty = useStore((s) => s.setSelectedProperty);
  const setPropertyAgents = useStore((s) => s.setPropertyAgents);

  // ── Local state ──────────────────────────────────────────────────────────
  const [nearbyPermits, setNearbyPermits] = useState<Permit[]>([]);
  const [permitsLoading, setPermitsLoading] = useState(false);
  const [agentsLoading, setAgentsLoading] = useState(false);
  const [creatingAgent, setCreatingAgent] = useState(false);

  // ── Fetch permits when property changes and permits tab is active ───────
  const fetchPermits = useCallback(async () => {
    if (!selectedProperty) return;
    setPermitsLoading(true);
    try {
      const result = await getPermitsNear(
        selectedProperty.latitude,
        selectedProperty.longitude,
        1.0,
        20
      );
      setNearbyPermits(result.permits || []);
    } catch (err) {
      console.error("[PropertyPanel] Failed to fetch permits:", err);
      setNearbyPermits([]);
    } finally {
      setPermitsLoading(false);
    }
  }, [selectedProperty]);

  useEffect(() => {
    if (leftPanelTab === "permits" && selectedProperty) {
      fetchPermits();
    }
  }, [leftPanelTab, selectedProperty, fetchPermits]);

  // ── Fetch agents when agents tab is active ──────────────────────────────
  const fetchAgents = useCallback(async () => {
    setAgentsLoading(true);
    try {
      const result = await listPropertyAgents();
      setPropertyAgents(result.agents || []);
    } catch (err) {
      console.error("[PropertyPanel] Failed to fetch agents:", err);
    } finally {
      setAgentsLoading(false);
    }
  }, [setPropertyAgents]);

  useEffect(() => {
    if (leftPanelTab === "agents" && selectedProperty) {
      fetchAgents();
    }
  }, [leftPanelTab, selectedProperty, fetchAgents]);

  // ── Filter agents for current property ──────────────────────────────────
  const filteredAgents = propertyAgents.filter((agent) => {
    if (!selectedProperty) return false;
    if (agent.entity_id === selectedProperty.id) return true;
    return false;
  });

  // ── Create agent handler ────────────────────────────────────────────────
  const handleCreateAgent = async () => {
    if (!selectedProperty || creatingAgent) return;
    setCreatingAgent(true);
    try {
      await createPropertyAgent({
        entity_type: "property",
        entity_id: selectedProperty.id,
        agent_type: "listing",
        name: `Listing Monitor - ${selectedProperty.address}`,
        config: {
          latitude: selectedProperty.latitude,
          longitude: selectedProperty.longitude,
        },
        run_interval_seconds: 3600,
      });
      await fetchAgents();
    } catch (err) {
      console.error("[PropertyPanel] Failed to create agent:", err);
    } finally {
      setCreatingAgent(false);
    }
  };

  // ── Delete agent handler ────────────────────────────────────────────────
  const handleDeleteAgent = async (agentId: string) => {
    try {
      await deletePropertyAgent(agentId);
      await fetchAgents();
    } catch (err) {
      console.error("[PropertyPanel] Failed to delete agent:", err);
    }
  };

  // ── Close property ──────────────────────────────────────────────────────
  const handleClose = () => {
    setSelectedProperty(null);
  };

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div
      className={`fixed top-14 left-0 bottom-0 w-[340px] z-30
        bg-parcl-panel/95 backdrop-blur-lg border-r border-parcl-border
        transition-transform duration-300 ease-out
        ${leftPanelOpen ? "translate-x-0" : "-translate-x-full"}`}
    >
      {/* Collapse toggle button */}
      <button
        onClick={toggleLeftPanel}
        className="absolute -right-8 top-4 w-8 h-8 flex items-center justify-center
          bg-parcl-panel/95 backdrop-blur-lg border border-parcl-border border-l-0
          rounded-r-md text-parcl-text-dim hover:text-parcl-text
          transition-colors duration-200 cursor-pointer"
        aria-label={leftPanelOpen ? "Collapse panel" : "Expand panel"}
      >
        {leftPanelOpen ? (
          <ChevronLeft className="w-4 h-4" />
        ) : (
          <ChevronRight className="w-4 h-4" />
        )}
      </button>

      {/* Panel content */}
      <div className="h-full flex flex-col overflow-hidden">
        {!selectedProperty ? (
          /* ── Empty state ─────────────────────────────────────────────── */
          <div className="flex-1 flex flex-col items-center justify-center px-8 text-center">
            <MapPin className="w-12 h-12 text-parcl-text-muted mb-4 opacity-40" />
            <p className="text-sm text-parcl-text-muted leading-relaxed">
              Search for a property or click on the map to begin
            </p>
          </div>
        ) : (
          <>
            {/* ── Header ──────────────────────────────────────────────── */}
            <div className="px-4 py-3 border-b border-parcl-border flex-shrink-0">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-bold text-parcl-text truncate">
                    {selectedProperty.address}
                  </h2>
                  <p className="text-xs text-parcl-text-dim mt-0.5">
                    {[
                      selectedProperty.city,
                      selectedProperty.state,
                      selectedProperty.zip_code,
                    ]
                      .filter(Boolean)
                      .join(", ")}
                  </p>
                </div>
                <button
                  onClick={handleClose}
                  className="flex-shrink-0 w-6 h-6 flex items-center justify-center
                    rounded text-parcl-text-dim hover:text-parcl-text
                    hover:bg-parcl-border transition-colors cursor-pointer"
                  aria-label="Close property"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="mt-2">
                <span className={propertyTypeBadgeClass(selectedProperty.property_type)}>
                  {selectedProperty.property_type.replace(/_/g, " ")}
                </span>
              </div>
            </div>

            {/* ── Tab Bar ─────────────────────────────────────────────── */}
            <div className="flex border-b border-parcl-border flex-shrink-0">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setLeftPanelTab(tab.key)}
                  className={`flex-1 px-2 py-2.5 text-[11px] font-medium tracking-wide
                    transition-colors duration-200 cursor-pointer border-b-2
                    ${
                      leftPanelTab === tab.key
                        ? "border-parcl-accent text-parcl-accent"
                        : "border-transparent text-parcl-text-dim hover:text-parcl-text"
                    }`}
                >
                  <tab.icon className="w-3.5 h-3.5 mx-auto mb-1" />
                  {tab.label}
                </button>
              ))}
            </div>

            {/* ── Tab Content ─────────────────────────────────────────── */}
            <div className="flex-1 overflow-y-auto">
              {leftPanelTab === "summary" && (
                <SummaryTab
                  property={selectedProperty}
                  onSwitchToPermits={() => setLeftPanelTab("permits")}
                />
              )}
              {leftPanelTab === "permits" && (
                <PermitsTab
                  permits={nearbyPermits}
                  loading={permitsLoading}
                />
              )}
              {leftPanelTab === "risk" && (
                <RiskTab property={selectedProperty} />
              )}
              {leftPanelTab === "agents" && (
                <AgentsTab
                  agents={filteredAgents}
                  loading={agentsLoading}
                  creating={creatingAgent}
                  onCreateAgent={handleCreateAgent}
                  onDeleteAgent={handleDeleteAgent}
                />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

// ─── Summary Tab ─────────────────────────────────────────────────────────────

interface SummaryTabProps {
  property: NonNullable<ReturnType<typeof useStore.getState>["selectedProperty"]>;
  onSwitchToPermits: () => void;
}

const SummaryTab: React.FC<SummaryTabProps> = ({ property, onSwitchToPermits }) => (
  <div className="p-4 space-y-4">
    {/* 2x2 stat grid */}
    <div className="grid grid-cols-2 gap-2">
      <StatCard
        icon={<Bed className="w-3.5 h-3.5" />}
        label="Beds"
        value={property.bedrooms != null ? String(property.bedrooms) : "--"}
      />
      <StatCard
        icon={<Bath className="w-3.5 h-3.5" />}
        label="Baths"
        value={property.bathrooms != null ? String(property.bathrooms) : "--"}
      />
      <StatCard
        icon={<Ruler className="w-3.5 h-3.5" />}
        label="Sqft"
        value={
          property.living_area_sqft != null
            ? fmtNumber(property.living_area_sqft)
            : "--"
        }
      />
      <StatCard
        icon={<Calendar className="w-3.5 h-3.5" />}
        label="Year Built"
        value={property.year_built != null ? String(property.year_built) : "--"}
      />
    </div>

    {/* Estimated value */}
    {property.estimated_value != null && (
      <div className="bg-parcl-surface/60 border border-parcl-border rounded-lg p-3">
        <p className="text-[10px] uppercase tracking-wider text-parcl-text-dim mb-1">
          Estimated Value
        </p>
        <p className="text-lg font-bold text-parcl-accent">
          {fmtCurrency(property.estimated_value)}
        </p>
      </div>
    )}

    {/* Last sale */}
    {(property.last_sale_price != null || property.last_sale_date != null) && (
      <div className="bg-parcl-surface/60 border border-parcl-border rounded-lg p-3">
        <p className="text-[10px] uppercase tracking-wider text-parcl-text-dim mb-1">
          Last Sale
        </p>
        <div className="flex items-baseline gap-2">
          {property.last_sale_price != null && (
            <span className="text-sm font-semibold text-parcl-text">
              {fmtCurrency(property.last_sale_price)}
            </span>
          )}
          {property.last_sale_date != null && (
            <span className="text-xs text-parcl-text-dim">
              {fmtDate(property.last_sale_date)}
            </span>
          )}
        </div>
      </div>
    )}

    {/* Details list */}
    <div className="space-y-2">
      {property.zoning && (
        <DetailRow label="Zoning">
          <span className="badge-blue">{property.zoning}</span>
        </DetailRow>
      )}
      {property.tax_assessment != null && (
        <DetailRow label="Tax Assessment">
          <span className="text-sm text-parcl-text">
            {fmtCurrency(property.tax_assessment)}
          </span>
        </DetailRow>
      )}
      {property.lot_size_sqft != null && (
        <DetailRow label="Lot Size">
          <span className="text-sm text-parcl-text">
            {fmtNumber(property.lot_size_sqft)} sqft
          </span>
        </DetailRow>
      )}
    </div>

    {/* Nearby counts */}
    <div className="border-t border-parcl-border pt-3 space-y-1.5">
      <button
        onClick={onSwitchToPermits}
        className="text-xs text-parcl-accent hover:text-parcl-accent-light
          transition-colors cursor-pointer"
      >
        {property.nearby_permits_count} permits nearby
      </button>
      <p className="text-xs text-parcl-text-dim">
        {property.nearby_cameras_count} cameras nearby
      </p>
    </div>
  </div>
);

// ─── Stat Card ───────────────────────────────────────────────────────────────

const StatCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string;
}> = ({ icon, label, value }) => (
  <div className="bg-parcl-surface/60 border border-parcl-border rounded-lg p-2.5">
    <div className="flex items-center gap-1.5 text-parcl-text-dim mb-1">
      {icon}
      <span className="text-[10px] uppercase tracking-wider">{label}</span>
    </div>
    <p className="text-sm font-semibold text-parcl-text">{value}</p>
  </div>
);

// ─── Detail Row ──────────────────────────────────────────────────────────────

const DetailRow: React.FC<{
  label: string;
  children: React.ReactNode;
}> = ({ label, children }) => (
  <div className="flex items-center justify-between">
    <span className="text-xs text-parcl-text-dim">{label}</span>
    {children}
  </div>
);

// ─── Permits Tab ─────────────────────────────────────────────────────────────

interface PermitsTabProps {
  permits: Permit[];
  loading: boolean;
}

const PermitsTab: React.FC<PermitsTabProps> = ({ permits, loading }) => {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-5 h-5 text-parcl-accent animate-spin" />
        <span className="ml-2 text-xs text-parcl-text-dim">Loading permits...</span>
      </div>
    );
  }

  if (permits.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
        <FileText className="w-8 h-8 text-parcl-text-muted mb-3 opacity-40" />
        <p className="text-sm text-parcl-text-muted">No permits found nearby</p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-2">
      {permits.map((permit) => (
        <div
          key={permit.id}
          className="bg-parcl-surface/60 border border-parcl-border rounded-lg p-3
            hover:border-parcl-border-bright transition-colors duration-200"
        >
          {/* Permit number */}
          {permit.permit_number && (
            <p className="font-mono text-[10px] text-parcl-text-muted mb-1.5">
              {permit.permit_number}
            </p>
          )}

          {/* Type + status badges */}
          <div className="flex items-center gap-1.5 mb-2 flex-wrap">
            {permit.permit_type && (
              <span className={permitTypeBadgeClass(permit.permit_type)}>
                {permit.permit_type}
              </span>
            )}
            <span className={permitStatusBadgeClass(permit.status)}>
              {permit.status}
            </span>
          </div>

          {/* Description */}
          {permit.description && (
            <p className="text-xs text-parcl-text leading-relaxed line-clamp-2 mb-2">
              {permit.description}
            </p>
          )}

          {/* Meta row */}
          <div className="flex items-center justify-between text-[10px] text-parcl-text-dim">
            <div className="flex items-center gap-3">
              {permit.filed_date && (
                <span>Filed {fmtDate(permit.filed_date)}</span>
              )}
              {permit.estimated_value != null && (
                <span>{fmtCurrency(permit.estimated_value)}</span>
              )}
            </div>
            {permit.distance_km != null && (
              <span>{permit.distance_km.toFixed(2)} km</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};

// ─── Risk Tab ────────────────────────────────────────────────────────────────

interface RiskTabProps {
  property: NonNullable<ReturnType<typeof useStore.getState>["selectedProperty"]>;
}

const RISK_TYPES: { key: keyof NonNullable<RiskTabProps["property"]["risk_scores"]>; label: string }[] = [
  { key: "flood_risk", label: "Flood" },
  { key: "fire_risk", label: "Fire" },
  { key: "heat_risk", label: "Heat" },
  { key: "wind_risk", label: "Wind" },
  { key: "environmental_risk", label: "Environmental" },
];

const RiskTab: React.FC<RiskTabProps> = ({ property }) => {
  const scores = property.risk_scores;

  if (!scores) {
    return (
      <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
        <Shield className="w-8 h-8 text-parcl-text-muted mb-3 opacity-40" />
        <p className="text-sm text-parcl-text-muted">
          Risk assessment not available
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      {/* Overall risk score */}
      {scores.overall_risk != null && (
        <div className="bg-parcl-surface/60 border border-parcl-border rounded-lg p-4 text-center">
          <p className="text-[10px] uppercase tracking-wider text-parcl-text-dim mb-2">
            Overall Risk Score
          </p>
          <p className={`text-3xl font-bold ${riskLabelColor(scores.overall_risk)}`}>
            {scores.overall_risk}
          </p>
          <div className="mt-2 w-full bg-parcl-border rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all duration-500 ${riskBarColor(scores.overall_risk)}`}
              style={{ width: `${Math.min(scores.overall_risk, 100)}%` }}
            />
          </div>
          {scores.assessed_at && (
            <p className="text-[10px] text-parcl-text-muted mt-2">
              Assessed {fmtDate(scores.assessed_at)}
            </p>
          )}
        </div>
      )}

      {/* Individual risk scores */}
      <div className="space-y-3">
        {RISK_TYPES.map(({ key, label }) => {
          const score = scores[key];
          if (score == null) return null;
          return (
            <div key={key}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-parcl-text-dim">{label}</span>
                <span className={`text-xs font-semibold ${riskLabelColor(score as number)}`}>
                  {score}
                </span>
              </div>
              <div className="w-full bg-parcl-border rounded-full h-2">
                <div
                  className={`h-2 rounded-full transition-all duration-500 ${riskBarColor(score as number)}`}
                  style={{ width: `${Math.min(score as number, 100)}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Source */}
      {scores.source && (
        <p className="text-[10px] text-parcl-text-muted pt-2 border-t border-parcl-border">
          Source: {scores.source}
        </p>
      )}
    </div>
  );
};

// ─── Agents Tab ──────────────────────────────────────────────────────────────

interface AgentsTabProps {
  agents: PropertyMonitorAgent[];
  loading: boolean;
  creating: boolean;
  onCreateAgent: () => void;
  onDeleteAgent: (agentId: string) => void;
}

const AgentsTab: React.FC<AgentsTabProps> = ({
  agents,
  loading,
  creating,
  onCreateAgent,
  onDeleteAgent,
}) => {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-5 h-5 text-parcl-accent animate-spin" />
        <span className="ml-2 text-xs text-parcl-text-dim">Loading agents...</span>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-2">
      {agents.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 px-4 text-center">
          <Bot className="w-8 h-8 text-parcl-text-muted mb-3 opacity-40" />
          <p className="text-sm text-parcl-text-muted mb-4">
            No agents monitoring this property
          </p>
          <button
            onClick={onCreateAgent}
            disabled={creating}
            className="btn-tactical-blue flex items-center gap-1.5"
          >
            {creating ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Plus className="w-3.5 h-3.5" />
            )}
            Create Listing Agent
          </button>
        </div>
      ) : (
        <>
          {agents.map((agent) => (
            <div
              key={agent.id}
              className="bg-parcl-surface/60 border border-parcl-border rounded-lg p-3
                hover:border-parcl-border-bright transition-colors duration-200"
            >
              {/* Header row */}
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${agentStatusDot(agent.status)}`} />
                  <span className={agentTypeBadgeClass(agent.agent_type)}>
                    {agent.agent_type.replace(/_/g, " ")}
                  </span>
                </div>
                <button
                  onClick={() => onDeleteAgent(agent.id)}
                  className="flex-shrink-0 w-6 h-6 flex items-center justify-center
                    rounded text-parcl-text-muted hover:text-parcl-red
                    hover:bg-parcl-red/10 transition-colors cursor-pointer"
                  aria-label="Delete agent"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* Agent name */}
              <p className="text-xs text-parcl-text font-medium truncate mb-2">
                {agent.name}
              </p>

              {/* Meta row */}
              <div className="flex items-center justify-between text-[10px] text-parcl-text-dim">
                <span>{agent.findings_count} findings</span>
                {agent.last_run && (
                  <span>Last run {fmtRelativeTime(agent.last_run)}</span>
                )}
              </div>
            </div>
          ))}

          {/* Create agent button at bottom */}
          <button
            onClick={onCreateAgent}
            disabled={creating}
            className="w-full btn-tactical-blue flex items-center justify-center gap-1.5 mt-2"
          >
            {creating ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Plus className="w-3.5 h-3.5" />
            )}
            Create Agent
          </button>
        </>
      )}
    </div>
  );
};

export default PropertyPanel;
