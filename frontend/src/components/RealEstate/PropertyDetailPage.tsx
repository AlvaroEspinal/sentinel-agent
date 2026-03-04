import React from "react";
import { useStore } from "../../store/useStore";
import { ArrowLeft, MapPin, DollarSign, Calendar, Home, Ruler } from "lucide-react";
import PropertyDetails from "./PropertyDetails";

const PropertyDetailPage: React.FC = () => {
  const selectedParcel = useStore((s) => s.selectedParcel);
  const navigateToDashboard = useStore((s) => s.navigateToDashboard);
  const setActiveView = useStore((s) => s.setActiveView);

  if (!selectedParcel) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <MapPin size={32} className="mx-auto text-slate-600 mb-3" />
          <p className="text-slate-400 text-sm">No property selected</p>
          <button
            onClick={navigateToDashboard}
            className="mt-3 text-blue-400 text-xs hover:text-blue-300"
          >
            Back to Dashboard
          </button>
        </div>
      </div>
    );
  }

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
            onClick={() => setActiveView("search")}
            className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
          >
            <ArrowLeft size={18} />
          </button>
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-bold text-white truncate">
              {selectedParcel.site_addr || "Unknown Address"}
            </h1>
            <p className="text-slate-400 text-xs">
              {selectedParcel.city || ""}{selectedParcel.city ? ", MA" : "Massachusetts"}
              {selectedParcel.loc_id && (
                <span className="text-slate-500 ml-2 font-mono">
                  {selectedParcel.loc_id}
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Property Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
          <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-4">
            <DollarSign size={14} className="text-emerald-400 mb-1.5" />
            <div className="text-lg font-bold text-white">
              {formatPrice(selectedParcel.total_value)}
            </div>
            <div className="text-slate-500 text-[10px]">Assessment</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-4">
            <DollarSign size={14} className="text-blue-400 mb-1.5" />
            <div className="text-lg font-bold text-white">
              {formatPrice(selectedParcel.last_sale_price)}
            </div>
            <div className="text-slate-500 text-[10px]">Last Sale</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-4">
            <Calendar size={14} className="text-purple-400 mb-1.5" />
            <div className="text-lg font-bold text-white">
              {selectedParcel.last_sale_date || "---"}
            </div>
            <div className="text-slate-500 text-[10px]">Sale Date</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-4">
            <Home size={14} className="text-amber-400 mb-1.5" />
            <div className="text-lg font-bold text-white">
              {selectedParcel.building_area_sqft
                ? `${selectedParcel.building_area_sqft.toLocaleString()}`
                : "---"}
            </div>
            <div className="text-slate-500 text-[10px]">Sqft</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-4">
            <Ruler size={14} className="text-cyan-400 mb-1.5" />
            <div className="text-lg font-bold text-white">
              {selectedParcel.lot_size_acres
                ? `${Number(selectedParcel.lot_size_acres).toFixed(2)} ac`
                : "---"}
            </div>
            <div className="text-slate-500 text-[10px]">Lot Size</div>
          </div>
        </div>

        {/* Owner + Details Row */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-4">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">
              Owner
            </div>
            <div className="text-white text-sm font-medium">
              {selectedParcel.owner || "Unknown"}
            </div>
          </div>
          <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-4 flex gap-6">
            <div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">
                Year Built
              </div>
              <div className="text-white text-sm font-medium">
                {selectedParcel.year_built || "---"}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">
                Use Code
              </div>
              <div className="text-white text-sm font-medium">
                {selectedParcel.use_code || "---"}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">
                Style
              </div>
              <div className="text-white text-sm font-medium">
                {selectedParcel.style || "---"}
              </div>
            </div>
          </div>
        </div>

        {/* Property Details Tabs (Permits, Parcel, Flood, Zoning, Deeds, Comps, Agents) */}
        <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl overflow-hidden">
          <PropertyDetails
            property={{
              address: selectedParcel.site_addr || "",
              city: selectedParcel.city || null,
              latitude: 0,
              longitude: 0,
            }}
          />
        </div>
      </div>
    </div>
  );
};

export default PropertyDetailPage;
