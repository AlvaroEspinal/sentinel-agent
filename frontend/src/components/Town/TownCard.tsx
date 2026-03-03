import React from "react";
import { useStore } from "../../store/useStore";
import {
  Building2,
  Users,
  DollarSign,
  ChevronRight,
  MapPin,
} from "lucide-react";

interface TownCardProps {
  town: {
    id: string;
    name: string;
    county?: string;
    population?: number;
    median_home_value?: number;
    center?: { lat: number; lon: number };
    permit_portal_type?: string;
    boards?: string[];
  };
}

const TownCard: React.FC<TownCardProps> = ({ town }) => {
  const navigateToTown = useStore((s) => s.navigateToTown);

  const formatPrice = (value: number | undefined) => {
    if (!value) return "N/A";
    if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
    return `$${value.toLocaleString()}`;
  };

  const formatPop = (value: number | undefined) => {
    if (!value) return "N/A";
    return value.toLocaleString();
  };

  return (
    <button
      onClick={() => navigateToTown(town.id)}
      className="group flex flex-col bg-slate-800/60 hover:bg-slate-800/90 border border-slate-700/50 hover:border-blue-500/30 rounded-xl p-4 transition-all text-left"
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-white font-semibold text-sm group-hover:text-blue-400 transition-colors">
            {town.name}
          </h3>
          {town.county && (
            <p className="text-slate-500 text-xs mt-0.5">
              {town.county} County
            </p>
          )}
        </div>
        <ChevronRight
          size={16}
          className="text-slate-600 group-hover:text-blue-400 transition-colors mt-0.5"
        />
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-3 mt-auto">
        <div className="flex items-center gap-2">
          <DollarSign size={13} className="text-emerald-500/70 flex-shrink-0" />
          <div>
            <div className="text-white text-xs font-medium">
              {formatPrice(town.median_home_value)}
            </div>
            <div className="text-slate-500 text-[10px]">Median Value</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Users size={13} className="text-blue-400/70 flex-shrink-0" />
          <div>
            <div className="text-white text-xs font-medium">
              {formatPop(town.population)}
            </div>
            <div className="text-slate-500 text-[10px]">Population</div>
          </div>
        </div>
      </div>

      {/* Boards Preview */}
      {town.boards && town.boards.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-3 pt-3 border-t border-slate-700/30">
          {town.boards.slice(0, 3).map((board, i) => (
            <span
              key={i}
              className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400"
            >
              {board}
            </span>
          ))}
          {town.boards.length > 3 && (
            <span className="text-[10px] text-slate-500">
              +{town.boards.length - 3}
            </span>
          )}
        </div>
      )}
    </button>
  );
};

export default TownCard;
