import React from "react";
import { useStore } from "../../store/useStore";
import type { ViewMode } from "../../types";

// ─── SVG Filters ────────────────────────────────────────────────────────────

const SVGFilters: React.FC = () => (
  <svg
    style={{
      position: "absolute",
      width: 0,
      height: 0,
      overflow: "hidden",
    }}
    xmlns="http://www.w3.org/2000/svg"
  >
    <defs>
      {/* Satellite enhanced contrast / saturation filter */}
      <filter id="filter-satellite" colorInterpolationFilters="sRGB">
        <feComponentTransfer>
          <feFuncR type="linear" slope="1.15" intercept="0" />
          <feFuncG type="linear" slope="1.15" intercept="0" />
          <feFuncB type="linear" slope="1.1" intercept="0" />
        </feComponentTransfer>
        <feColorMatrix
          type="saturate"
          values="1.3"
        />
      </filter>

      {/* Risk heat overlay — warm red/amber tint */}
      <filter id="filter-risk" colorInterpolationFilters="sRGB">
        <feColorMatrix
          type="matrix"
          values="
            1.2   0.1   0.0   0  0.02
            0.05  0.9   0.0   0  0
            0.0   0.0   0.7   0  0
            0     0     0     1  0
          "
        />
        <feComponentTransfer>
          <feFuncR type="linear" slope="1.2" intercept="0.02" />
          <feFuncG type="linear" slope="0.95" intercept="0" />
          <feFuncB type="linear" slope="0.7" intercept="0" />
        </feComponentTransfer>
      </filter>
    </defs>
  </svg>
);

// ─── Mode label ─────────────────────────────────────────────────────────────

const MODE_LABELS: Record<ViewMode, string> = {
  standard: "",
  satellite: "SATELLITE VIEW",
  risk: "RISK OVERLAY",
};

const MODE_LABEL_COLORS: Record<ViewMode, string> = {
  standard: "",
  satellite: "text-blue-400",
  risk: "text-amber-400",
};

// ─── ShaderOverlay Component ────────────────────────────────────────────────

const ShaderOverlay: React.FC = () => {
  const viewMode = useStore((s) => s.viewMode);

  // CSS filter styles for each mode
  const filterStyle: React.CSSProperties = (() => {
    switch (viewMode) {
      case "satellite":
        return {
          filter: "url(#filter-satellite) contrast(1.1) brightness(1.05)",
        };
      case "risk":
        return {
          filter: "url(#filter-risk) contrast(1.15) brightness(1.05)",
        };
      default:
        return {};
    }
  })();

  return (
    <>
      {/* SVG filter definitions (always present, zero-size) */}
      <SVGFilters />

      {/* Filter overlay: sits on top of globe, applies CSS filter to content below via mix-blend */}
      {viewMode !== "standard" && (
        <div
          className="absolute inset-0 pointer-events-none z-20"
          style={filterStyle}
        >
          {/* This div captures the visual appearance via the filter */}
          <div className="absolute inset-0" />
        </div>
      )}

      {/* Mode indicator label */}
      {viewMode !== "standard" && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-40 pointer-events-none">
          <div
            className={`flex items-center gap-2 px-3 py-1 rounded border
            border-parcl-border bg-parcl-bg/80 backdrop-blur-sm
            text-[10px] font-bold uppercase tracking-[0.3em] ${MODE_LABEL_COLORS[viewMode]}`}
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-current" />
            </span>
            {MODE_LABELS[viewMode]}
          </div>
        </div>
      )}

      {/* Risk mode warm vignette */}
      {viewMode === "risk" && (
        <div
          className="absolute inset-0 pointer-events-none z-25"
          style={{
            background: `radial-gradient(
              ellipse at center,
              transparent 50%,
              rgba(180, 80, 20, 0.08) 70%,
              rgba(120, 40, 10, 0.15) 90%,
              rgba(80, 20, 5, 0.25) 100%
            )`,
          }}
        />
      )}

      {/* Risk mode legend */}
      {viewMode === "risk" && (
        <div className="absolute bottom-20 right-4 z-40 pointer-events-none">
          <div className="flex flex-col items-center gap-1">
            <span className="text-[9px] text-red-400 font-mono">HIGH</span>
            <div
              className="w-3 h-32 rounded-full border border-parcl-border"
              style={{
                background:
                  "linear-gradient(to bottom, #ef4444, #f97316, #fbbf24, #4ade80, #3b82f6)",
              }}
            />
            <span className="text-[9px] text-blue-400 font-mono">LOW</span>
          </div>
        </div>
      )}
    </>
  );
};

export default ShaderOverlay;
