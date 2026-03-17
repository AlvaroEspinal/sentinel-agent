import React, { useState, useCallback, useEffect } from "react";
import { useStore } from "../../store/useStore";
import { searchParcels, geocodeAddress, getParcelInfo, getPlatformStats, type PlatformStats } from "../../services/api";
import TownCard from "../Town/TownCard";
import {
  Search,
  MapPin,
  FileText,
  TrendingUp,
  Eye,
  ArrowRight,
  Building2,
  Clock,
  DollarSign,
  Globe2,
  Database,
  Leaf,
  AlertTriangle,
  Home,
} from "lucide-react";

const LandingPage: React.FC = () => {
  const targetTowns = useStore((s) => s.targetTowns);
  const trackedListings = useStore((s) => s.trackedListings);
  const agentFindings = useStore((s) => s.agentFindings);
  const setActiveView = useStore((s) => s.setActiveView);
  const setParcelSearchResults = useStore((s) => s.setParcelSearchResults);
  const setParcelSearchLoading = useStore((s) => s.setParcelSearchLoading);
  const setShowMapOverlay = useStore((s) => s.setShowMapOverlay);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchType, setSearchType] = useState<"address" | "owner">("address");
  const [searchTown, setSearchTown] = useState("newton");
  const [isSearching, setIsSearching] = useState(false);
  const [platformStats, setPlatformStats] = useState<PlatformStats | null>(null);

  // Fetch platform stats
  useEffect(() => {
    getPlatformStats().then(setPlatformStats).catch(() => {});
  }, []);

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setIsSearching(true);
    setParcelSearchLoading(true);

    try {
      if (searchType === "owner") {
        const result = await searchParcels({
          owner: searchQuery.trim(),
          town: searchTown,
          limit: 25,
        });
        setParcelSearchResults(result.parcels as any);
      } else {
        // Address search — geocode first, then parcel lookup
        const geo = await geocodeAddress(searchQuery.trim());
        if (geo.lat && geo.lon) {
          const parcelData = await getParcelInfo(geo.lat, geo.lon);
          if (parcelData && parcelData.loc_id) {
            setParcelSearchResults([{
              loc_id: parcelData.loc_id,
              site_addr: parcelData.site_addr || searchQuery.trim(),
              city: parcelData.city || geo.display_name?.split(",")[1]?.trim() || null,
              owner: parcelData.owner || null,
              last_sale_date: parcelData.last_sale_date || null,
              last_sale_price: parcelData.last_sale_price || null,
              total_value: parcelData.total_value || null,
              building_area_sqft: parcelData.building_area_sqft || null,
              lot_size_acres: parcelData.lot_size_acres || null,
              year_built: parcelData.year_built || null,
              use_code: parcelData.use_code || null,
              style: (parcelData as any).style || null,
            }] as any);
          } else {
            setParcelSearchResults([]);
          }
        } else {
          setParcelSearchResults([]);
        }
      }
      setActiveView("search");
    } catch (err) {
      console.warn("[Search] Error:", err);
    } finally {
      setIsSearching(false);
      setParcelSearchLoading(false);
    }
  }, [searchQuery, searchType, searchTown, setActiveView, setParcelSearchResults, setParcelSearchLoading]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  };

  const fmtNum = (n: number | undefined) => {
    if (!n) return "0";
    return n.toLocaleString();
  };

  // Static town list fallback
  const towns = targetTowns.length > 0
    ? targetTowns
    : [
        { id: "newton", name: "Newton", county: "Middlesex", population: 88923, median_home_value: 1250000, boards: ["Select Board", "Planning Board", "ZBA", "Conservation"] },
        { id: "wellesley", name: "Wellesley", county: "Norfolk", population: 28747, median_home_value: 1450000, boards: ["Select Board", "Planning Board", "ZBA"] },
        { id: "weston", name: "Weston", county: "Middlesex", population: 12135, median_home_value: 1850000, boards: ["Select Board", "Planning Board"] },
        { id: "brookline", name: "Brookline", county: "Norfolk", population: 63191, median_home_value: 1100000, boards: ["Select Board", "Planning Board", "ZBA"] },
        { id: "needham", name: "Needham", county: "Norfolk", population: 31388, median_home_value: 1050000, boards: ["Select Board", "Planning Board"] },
        { id: "concord", name: "Concord", county: "Middlesex", population: 19259, median_home_value: 1200000, boards: ["Select Board", "Planning Board"] },
        { id: "lexington", name: "Lexington", county: "Middlesex", population: 34454, median_home_value: 1150000, boards: ["Select Board", "Planning Board"] },
        { id: "dover", name: "Dover", county: "Norfolk", population: 6215, median_home_value: 1600000, boards: ["Select Board", "Planning Board"] },
      ].map(t => ({ ...t, center: { lat: 0, lon: 0 }, permit_portal_type: "" }));

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Hero Search Section */}
        <div className="mb-10">
          <h1 className="text-2xl font-bold text-white mb-1">
            Parcl Intelligence
          </h1>
          <p className="text-slate-400 text-sm mb-6">
            Real estate data intelligence for affluent Massachusetts communities
          </p>

          {/* Search Bar */}
          <div className="bg-slate-800/70 border border-slate-700/50 rounded-xl p-4">
            <div className="flex gap-2 mb-3">
              <button
                onClick={() => setSearchType("address")}
                className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                  searchType === "address"
                    ? "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                    : "text-slate-400 hover:text-white border border-transparent"
                }`}
              >
                <MapPin size={12} className="inline mr-1" />
                Address
              </button>
              <button
                onClick={() => setSearchType("owner")}
                className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                  searchType === "owner"
                    ? "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                    : "text-slate-400 hover:text-white border border-transparent"
                }`}
              >
                <Building2 size={12} className="inline mr-1" />
                Owner Name
              </button>
            </div>

            <div className="flex gap-2">
              {searchType === "owner" && (
                <select
                  value={searchTown}
                  onChange={(e) => setSearchTown(e.target.value)}
                  className="bg-slate-700/80 border border-slate-600/50 rounded-lg px-3 py-2.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500/50"
                >
                  {towns.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              )}
              <div className="flex-1 relative">
                <Search
                  size={16}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
                />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={
                    searchType === "address"
                      ? "Search by address, parcel ID, or location..."
                      : "Search by owner name (e.g., Smith, Johnson)..."
                  }
                  className="w-full bg-slate-700/80 border border-slate-600/50 rounded-lg pl-10 pr-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/30"
                />
              </div>
              <button
                onClick={handleSearch}
                disabled={isSearching || !searchQuery.trim()}
                className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                {isSearching ? "Searching..." : "Search"}
              </button>
            </div>
          </div>
        </div>

        {/* Platform Data Stats */}
        <div className="mb-10">
          <div className="flex items-center gap-2 mb-4">
            <Database size={16} className="text-blue-400" />
            <h2 className="text-sm font-semibold text-white uppercase tracking-wider">
              Platform Data
            </h2>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <div className="bg-gradient-to-br from-blue-500/10 to-blue-600/5 border border-blue-500/20 rounded-xl p-4">
              <FileText size={16} className="text-blue-400 mb-2" />
              <div className="text-xl font-bold text-white">
                {platformStats ? fmtNum(platformStats.total_permits) : "104,508"}
              </div>
              <div className="text-slate-400 text-[11px]">Permits Tracked</div>
            </div>
            <div className="bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 border border-emerald-500/20 rounded-xl p-4">
              <Home size={16} className="text-emerald-400 mb-2" />
              <div className="text-xl font-bold text-white">
                {platformStats ? fmtNum(platformStats.total_properties) : "91,983"}
              </div>
              <div className="text-slate-400 text-[11px]">Properties</div>
            </div>
            <div className="bg-gradient-to-br from-purple-500/10 to-purple-600/5 border border-purple-500/20 rounded-xl p-4">
              <MapPin size={16} className="text-purple-400 mb-2" />
              <div className="text-xl font-bold text-white">
                {platformStats ? fmtNum(platformStats.total_towns) : "12"}
              </div>
              <div className="text-slate-400 text-[11px]">Towns Monitored</div>
            </div>
            <div className="bg-gradient-to-br from-orange-500/10 to-orange-600/5 border border-orange-500/20 rounded-xl p-4">
              <Leaf size={16} className="text-orange-400 mb-2" />
              <div className="text-xl font-bold text-white">
                {platformStats ? fmtNum(platformStats.total_mepa) : "5,554"}
              </div>
              <div className="text-slate-400 text-[11px]">MEPA Filings</div>
            </div>
            <div className="bg-gradient-to-br from-amber-500/10 to-amber-600/5 border border-amber-500/20 rounded-xl p-4">
              <Clock size={16} className="text-amber-400 mb-2" />
              <div className="text-xl font-bold text-white">
                {platformStats ? fmtNum(platformStats.total_documents) : "8,024"}
              </div>
              <div className="text-slate-400 text-[11px]">Municipal Docs</div>
            </div>
            <button
              onClick={() => setShowMapOverlay(true)}
              className="bg-gradient-to-br from-cyan-500/10 to-cyan-600/5 border border-cyan-500/20 hover:border-cyan-400/40 rounded-xl p-4 text-left transition-colors group"
            >
              <Globe2 size={16} className="text-cyan-400 mb-2 group-hover:scale-110 transition-transform" />
              <div className="text-sm font-bold text-white group-hover:text-cyan-300">
                Open Map
              </div>
              <div className="text-slate-400 text-[11px]">Interactive Globe</div>
            </button>
          </div>
        </div>

        {/* Two Column Layout: Watchlist + Stats */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-10">
          {/* Watchlist Feed */}
          <div className="lg:col-span-2">
            <div className="flex items-center gap-2 mb-4">
              <Eye size={16} className="text-blue-400" />
              <h2 className="text-sm font-semibold text-white uppercase tracking-wider">
                Recent Activity
              </h2>
            </div>

            {agentFindings.length > 0 ? (
              <div className="space-y-2">
                {agentFindings.slice(0, 5).map((finding) => (
                  <div
                    key={finding.id}
                    className="bg-slate-800/50 border border-slate-700/30 rounded-lg px-4 py-3 hover:border-slate-600/50 transition-colors"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-2">
                        <div
                          className={`w-2 h-2 rounded-full flex-shrink-0 ${
                            finding.severity === "HIGH"
                              ? "bg-red-500"
                              : finding.severity === "MEDIUM"
                              ? "bg-amber-500"
                              : "bg-blue-500"
                          }`}
                        />
                        <span className="text-white text-sm font-medium">
                          {finding.title}
                        </span>
                      </div>
                      <span className="text-slate-500 text-xs whitespace-nowrap ml-3">
                        {new Date(finding.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    {finding.summary && (
                      <p className="text-slate-400 text-xs mt-1.5 ml-4">
                        {finding.summary.slice(0, 120)}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            ) : trackedListings.length > 0 ? (
              <div className="space-y-2">
                {trackedListings.slice(0, 5).map((listing) => (
                  <div
                    key={listing.id}
                    className="bg-slate-800/50 border border-slate-700/30 rounded-lg px-4 py-3 flex items-center gap-3"
                  >
                    <TrendingUp size={14} className="text-emerald-500/70 flex-shrink-0" />
                    <div className="min-w-0">
                      <div className="text-white text-sm truncate">
                        {listing.address}
                      </div>
                      <div className="text-slate-500 text-xs">
                        {listing.city || "Massachusetts"} &middot; Tracked since{" "}
                        {new Date(listing.addedAt).toLocaleDateString()}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-slate-800/30 border border-slate-700/20 rounded-xl p-8 text-center">
                <Eye size={24} className="mx-auto text-slate-600 mb-3" />
                <p className="text-slate-400 text-sm">No activity yet</p>
                <p className="text-slate-500 text-xs mt-1">
                  Track properties and monitor towns to see updates here
                </p>
              </div>
            )}
          </div>

          {/* Quick Stats */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <TrendingUp size={16} className="text-emerald-400" />
              <h2 className="text-sm font-semibold text-white uppercase tracking-wider">
                Overview
              </h2>
            </div>

            <div className="space-y-3">
              <div className="bg-slate-800/50 border border-slate-700/30 rounded-lg p-4">
                <div className="text-2xl font-bold text-white">
                  {towns.length}
                </div>
                <div className="text-slate-400 text-xs mt-0.5">
                  Target Towns Monitored
                </div>
              </div>
              <div className="bg-slate-800/50 border border-slate-700/30 rounded-lg p-4">
                <div className="text-2xl font-bold text-white">
                  {trackedListings.length}
                </div>
                <div className="text-slate-400 text-xs mt-0.5">
                  Properties on Watchlist
                </div>
              </div>
              <div className="bg-slate-800/50 border border-slate-700/30 rounded-lg p-4">
                <div className="text-2xl font-bold text-white">
                  {agentFindings.length}
                </div>
                <div className="text-slate-400 text-xs mt-0.5">
                  Agent Findings
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Town Cards Grid */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <MapPin size={16} className="text-blue-400" />
              <h2 className="text-sm font-semibold text-white uppercase tracking-wider">
                Target Communities
              </h2>
            </div>
            <span className="text-xs text-slate-500">
              {towns.length} municipalities
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {towns.map((town) => (
              <TownCard key={town.id} town={town} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default LandingPage;
