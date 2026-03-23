import React from "react";
import { useStore } from "../../store/useStore";
import {
  Building2,
  Home,
  Map,
  Search,
  ChevronRight,
  Globe2,
  TrendingUp,
  FileText,
  Eye,
} from "lucide-react";

const Sidebar: React.FC = () => {
  const activeView = useStore((s) => s.activeView);
  const activeTownId = useStore((s) => s.activeTownId);
  const targetTowns = useStore((s) => s.targetTowns);
  const trackedListings = useStore((s) => s.trackedListings);
  const navigateToTown = useStore((s) => s.navigateToTown);
  const navigateToDashboard = useStore((s) => s.navigateToDashboard);
  const setActiveView = useStore((s) => s.setActiveView);
  const setShowMapOverlay = useStore((s) => s.setShowMapOverlay);

  return (
    <aside className="w-60 bg-slate-900/95 border-r border-slate-700/50 flex flex-col h-full overflow-hidden">
      {/* Brand */}
      <div className="px-4 py-4 border-b border-slate-700/50">
        <button
          onClick={navigateToDashboard}
          className="flex items-center gap-2 group"
        >
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center">
            <Building2 size={16} className="text-white" />
          </div>
          <div>
            <div className="text-sm font-semibold text-white tracking-wide group-hover:text-blue-400 transition-colors">
              MIS
            </div>
            <div className="text-[10px] text-slate-400 -mt-0.5 tracking-wider">
              MUNICIPAL INTEL
            </div>
          </div>
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-2 scrollbar-thin">
        {/* Dashboard */}
        <button
          onClick={navigateToDashboard}
          className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
            activeView === "dashboard"
              ? "bg-blue-500/10 text-blue-400 border-r-2 border-blue-500"
              : "text-slate-300 hover:bg-slate-800/60 hover:text-white"
          }`}
        >
          <Home size={16} />
          <span>Dashboard</span>
        </button>

        {/* Search */}
        <button
          onClick={() => setActiveView("search")}
          className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
            activeView === "search"
              ? "bg-blue-500/10 text-blue-400 border-r-2 border-blue-500"
              : "text-slate-300 hover:bg-slate-800/60 hover:text-white"
          }`}
        >
          <Search size={16} />
          <span>Property Search</span>
        </button>

        {/* Towns Section */}
        <div className="mt-4 px-4 mb-2">
          <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
            Towns
          </div>
        </div>

        {targetTowns.length > 0 ? (
          targetTowns.map((town) => (
            <button
              key={town.id}
              onClick={() => navigateToTown(town.id)}
              className={`w-full flex items-center justify-between px-4 py-2 text-sm transition-colors group ${
                activeView === "town" && activeTownId === town.id
                  ? "bg-blue-500/10 text-blue-400 border-r-2 border-blue-500"
                  : "text-slate-400 hover:bg-slate-800/60 hover:text-white"
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div
                  className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                    activeView === "town" && activeTownId === town.id
                      ? "bg-blue-400"
                      : "bg-slate-600 group-hover:bg-slate-400"
                  }`}
                />
                <span className="truncate">{town.name}</span>
              </div>
              <ChevronRight
                size={14}
                className="text-slate-600 group-hover:text-slate-400 flex-shrink-0"
              />
            </button>
          ))
        ) : (
          // Static fallback list of towns
          [
            "Newton", "Wellesley", "Weston", "Brookline", "Needham",
            "Dover", "Sherborn", "Natick", "Wayland", "Lincoln",
            "Concord", "Lexington",
          ].map((name) => {
            const id = name.toLowerCase();
            return (
              <button
                key={id}
                onClick={() => navigateToTown(id)}
                className={`w-full flex items-center justify-between px-4 py-2 text-sm transition-colors group ${
                  activeView === "town" && activeTownId === id
                    ? "bg-blue-500/10 text-blue-400 border-r-2 border-blue-500"
                    : "text-slate-400 hover:bg-slate-800/60 hover:text-white"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <div
                    className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      activeView === "town" && activeTownId === id
                        ? "bg-blue-400"
                        : "bg-slate-600 group-hover:bg-slate-400"
                    }`}
                  />
                  <span className="truncate">{name}</span>
                </div>
                <ChevronRight
                  size={14}
                  className="text-slate-600 group-hover:text-slate-400 flex-shrink-0"
                />
              </button>
            );
          })
        )}

        {/* Watchlist Section */}
        {trackedListings.length > 0 && (
          <>
            <div className="mt-4 px-4 mb-2">
              <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest flex items-center gap-1.5">
                <Eye size={10} />
                Watchlist
                <span className="ml-auto text-slate-600">
                  {trackedListings.length}
                </span>
              </div>
            </div>

            {trackedListings.slice(0, 8).map((listing) => (
              <button
                key={listing.id}
                onClick={() => {
                  // TODO: navigate to property view for this listing
                }}
                className="w-full flex items-center gap-2.5 px-4 py-1.5 text-xs text-slate-400 hover:bg-slate-800/60 hover:text-white transition-colors group"
              >
                <TrendingUp
                  size={12}
                  className="text-emerald-500/70 flex-shrink-0"
                />
                <span className="truncate">{listing.address}</span>
              </button>
            ))}
          </>
        )}
      </nav>

      {/* Map View Button */}
      <div className="px-3 py-3 border-t border-slate-700/50">
        <button
          onClick={() => setShowMapOverlay(true)}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg text-sm font-medium transition-all border border-slate-700/50 hover:border-slate-600"
        >
          <Globe2 size={16} className="text-blue-400" />
          Map View
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
