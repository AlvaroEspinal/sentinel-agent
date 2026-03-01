import React from "react";

// ─── Check if Cesium Ion token is available ─────────────────────────────────
const CESIUM_TOKEN = import.meta.env.VITE_CESIUM_ION_ACCESS_TOKEN || "";
const HAS_VALID_TOKEN =
  CESIUM_TOKEN.length > 50 && !CESIUM_TOKEN.includes("demo_token");

// ─── No-Token Fallback ──────────────────────────────────────────────────────
const NoTokenFallback: React.FC = () => (
  <div className="w-full h-full relative bg-slate-950 flex items-center justify-center overflow-hidden">
    <div
      className="absolute inset-0 opacity-10"
      style={{
        backgroundImage: `
          linear-gradient(rgba(59,130,246,0.3) 1px, transparent 1px),
          linear-gradient(90deg, rgba(59,130,246,0.3) 1px, transparent 1px)
        `,
        backgroundSize: "60px 60px",
        animation: "grid-drift 20s linear infinite",
      }}
    />
    <div className="relative">
      <div
        className="w-64 h-64 rounded-full bg-gradient-to-br from-blue-900/40 via-slate-800/60 to-indigo-900/40 border border-blue-500/20 shadow-[0_0_60px_rgba(59,130,246,0.15)]"
        style={{ animation: "pulse-glow 4s ease-in-out infinite" }}
      />
      <div className="absolute inset-0 flex items-center justify-center flex-col">
        <div className="text-blue-400/80 font-mono text-xs tracking-[0.3em] uppercase">
          Parcl Intelligence
        </div>
        <div className="text-blue-300/50 font-mono text-[10px] mt-2 tracking-wider">
          REAL ESTATE INTELLIGENCE
        </div>
        <div className="text-slate-500 font-mono text-[9px] mt-4 max-w-[200px] text-center">
          Set VITE_CESIUM_ION_ACCESS_TOKEN for 3D globe
        </div>
      </div>
    </div>
    <style>{`
      @keyframes grid-drift {
        0% { transform: translate(0,0); }
        100% { transform: translate(60px,60px); }
      }
      @keyframes pulse-glow {
        0%,100% { box-shadow: 0 0 40px rgba(59,130,246,0.1); }
        50% { box-shadow: 0 0 80px rgba(59,130,246,0.25); }
      }
    `}</style>
  </div>
);

// ─── Loading State ──────────────────────────────────────────────────────────
const GlobeLoading: React.FC = () => (
  <div className="w-full h-full relative bg-slate-950 flex items-center justify-center">
    <span className="text-blue-400/50 font-mono text-xs animate-pulse">
      Initializing globe...
    </span>
  </div>
);

// ─── Lazy-loaded Globe Inner (uses React.lazy for proper code-splitting) ────
const CesiumGlobeInner = React.lazy(() => import("./CesiumGlobeInner"));

const CesiumGlobe: React.FC = () => {
  if (!HAS_VALID_TOKEN) {
    return <NoTokenFallback />;
  }

  return (
    <React.Suspense fallback={<GlobeLoading />}>
      <CesiumGlobeInner />
    </React.Suspense>
  );
};

export default CesiumGlobe;
