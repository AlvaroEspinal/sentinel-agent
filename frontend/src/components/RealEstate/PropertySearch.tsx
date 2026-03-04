import React, { useState, useCallback } from "react";
import { useStore } from "../../store/useStore";
import { searchParcels, geocodeAddress } from "../../services/api";
import {
  Search,
  ArrowLeft,
  Building2,
  MapPin,
  DollarSign,
  Calendar,
  Ruler,
  Home,
  Loader2,
} from "lucide-react";

const PropertySearch: React.FC = () => {
  const parcelSearchResults = useStore((s) => s.parcelSearchResults);
  const parcelSearchLoading = useStore((s) => s.parcelSearchLoading);
  const setParcelSearchResults = useStore((s) => s.setParcelSearchResults);
  const setParcelSearchLoading = useStore((s) => s.setParcelSearchLoading);
  const navigateToDashboard = useStore((s) => s.navigateToDashboard);
  const navigateToProperty = useStore((s) => s.navigateToProperty);
  const targetTowns = useStore((s) => s.targetTowns);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchType, setSearchType] = useState<"owner" | "loc_id">("owner");
  const [searchTown, setSearchTown] = useState("newton");

  const towns = targetTowns.length > 0
    ? targetTowns
    : [
        { id: "newton", name: "Newton" },
        { id: "wellesley", name: "Wellesley" },
        { id: "weston", name: "Weston" },
        { id: "brookline", name: "Brookline" },
        { id: "needham", name: "Needham" },
        { id: "concord", name: "Concord" },
        { id: "lexington", name: "Lexington" },
        { id: "dover", name: "Dover" },
        { id: "natick", name: "Natick" },
        { id: "wayland", name: "Wayland" },
        { id: "lincoln", name: "Lincoln" },
        { id: "sherborn", name: "Sherborn" },
      ];

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setParcelSearchLoading(true);

    try {
      const result = await searchParcels(
        searchType === "loc_id"
          ? { loc_id: searchQuery.trim() }
          : { owner: searchQuery.trim(), town: searchTown, limit: 25 }
      );
      setParcelSearchResults(result.parcels as any);
    } catch (err) {
      console.warn("[Search] Error:", err);
    } finally {
      setParcelSearchLoading(false);
    }
  }, [searchQuery, searchType, searchTown, setParcelSearchResults, setParcelSearchLoading]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  };

  const formatPrice = (v: number | null | undefined) => {
    if (!v) return "---";
    if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
    if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
    return `$${v.toLocaleString()}`;
  };

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
          <h1 className="text-xl font-bold text-white">Property Search</h1>
        </div>

        {/* Search Controls */}
        <div className="bg-slate-800/70 border border-slate-700/50 rounded-xl p-4 mb-6">
          <div className="flex gap-2 mb-3">
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
            <button
              onClick={() => setSearchType("loc_id")}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                searchType === "loc_id"
                  ? "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                  : "text-slate-400 hover:text-white border border-transparent"
              }`}
            >
              <MapPin size={12} className="inline mr-1" />
              Parcel ID (LOC_ID)
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
                  searchType === "owner"
                    ? "Enter owner name (e.g., Smith, Johnson Trust)..."
                    : "Enter LOC_ID (e.g., M_123456_789)..."
                }
                className="w-full bg-slate-700/80 border border-slate-600/50 rounded-lg pl-10 pr-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500/50"
              />
            </div>
            <button
              onClick={handleSearch}
              disabled={parcelSearchLoading || !searchQuery.trim()}
              className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {parcelSearchLoading ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                "Search"
              )}
            </button>
          </div>
        </div>

        {/* Results */}
        {parcelSearchLoading ? (
          <div className="text-center py-12">
            <Loader2 size={32} className="mx-auto text-blue-400 animate-spin mb-3" />
            <p className="text-slate-400 text-sm">Searching MassGIS...</p>
          </div>
        ) : parcelSearchResults.length > 0 ? (
          <div className="space-y-2">
            <div className="text-xs text-slate-500 mb-3">
              {parcelSearchResults.length} result{parcelSearchResults.length !== 1 ? "s" : ""} found
            </div>

            {/* Table Header */}
            <div className="grid grid-cols-12 gap-2 px-4 py-2 text-[10px] font-medium text-slate-500 uppercase tracking-wider">
              <div className="col-span-3">Address</div>
              <div className="col-span-2">Owner</div>
              <div className="col-span-1 text-right">Value</div>
              <div className="col-span-1 text-right">Sale Price</div>
              <div className="col-span-1 text-right">Sale Date</div>
              <div className="col-span-1 text-right">Sqft</div>
              <div className="col-span-1 text-right">Lot</div>
              <div className="col-span-1 text-right">Year</div>
              <div className="col-span-1">Use</div>
            </div>

            {/* Table Body */}
            {parcelSearchResults.map((parcel: any, i: number) => (
              <div
                key={parcel.loc_id || i}
                onClick={() => navigateToProperty(parcel)}
                className="grid grid-cols-12 gap-2 px-4 py-3 bg-slate-800/40 border border-slate-700/20 rounded-lg hover:border-blue-500/30 hover:bg-slate-800/60 transition-colors text-sm cursor-pointer"
              >
                <div className="col-span-3 text-white font-medium truncate">
                  {parcel.site_addr || "Unknown"}
                </div>
                <div className="col-span-2 text-slate-400 truncate">
                  {parcel.owner || "---"}
                </div>
                <div className="col-span-1 text-right text-slate-300">
                  {formatPrice(parcel.total_value)}
                </div>
                <div className="col-span-1 text-right text-emerald-400">
                  {formatPrice(parcel.last_sale_price)}
                </div>
                <div className="col-span-1 text-right text-slate-500 text-xs">
                  {parcel.last_sale_date || "---"}
                </div>
                <div className="col-span-1 text-right text-slate-400 text-xs">
                  {parcel.building_area_sqft
                    ? parcel.building_area_sqft.toLocaleString()
                    : "---"}
                </div>
                <div className="col-span-1 text-right text-slate-400 text-xs">
                  {parcel.lot_size_acres ? `${Number(parcel.lot_size_acres).toFixed(2)}ac` : "---"}
                </div>
                <div className="col-span-1 text-right text-slate-400 text-xs">
                  {parcel.year_built || "---"}
                </div>
                <div className="col-span-1 text-slate-500 text-xs">
                  {parcel.use_code || "---"}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-16">
            <Search size={32} className="mx-auto text-slate-600 mb-3" />
            <p className="text-slate-400 text-sm">Search for properties</p>
            <p className="text-slate-500 text-xs mt-1">
              Search by owner name across all 12 target towns, or by parcel ID
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default PropertySearch;
