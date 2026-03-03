import React, { Suspense, lazy } from "react";
import { useStore } from "../../store/useStore";
import { X, Maximize2 } from "lucide-react";

const CesiumGlobe = lazy(() => import("./CesiumGlobe"));

const MapOverlay: React.FC = () => {
  const showMapOverlay = useStore((s) => s.showMapOverlay);
  const setShowMapOverlay = useStore((s) => s.setShowMapOverlay);

  if (!showMapOverlay) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-6">
      <div className="relative w-full h-full max-w-[95vw] max-h-[90vh] bg-slate-900 rounded-2xl border border-slate-700/50 overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-4 py-3 bg-gradient-to-b from-slate-900/95 to-transparent">
          <div className="flex items-center gap-2">
            <Maximize2 size={14} className="text-blue-400" />
            <span className="text-white text-sm font-medium">
              Map View
            </span>
            <span className="text-slate-500 text-xs">
              &middot; 3D Globe with data overlays
            </span>
          </div>
          <button
            onClick={() => setShowMapOverlay(false)}
            className="p-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Globe */}
        <Suspense
          fallback={
            <div className="w-full h-full flex items-center justify-center bg-slate-950">
              <div className="text-center">
                <div className="w-16 h-16 rounded-full border-2 border-blue-500/30 border-t-blue-500 animate-spin mx-auto mb-4" />
                <p className="text-slate-400 text-sm">Loading 3D Globe...</p>
              </div>
            </div>
          }
        >
          <CesiumGlobe />
        </Suspense>
      </div>
    </div>
  );
};

export default MapOverlay;
