import React, { useState, useEffect } from "react";
import { Building2, Bot, Wifi, WifiOff, Sun, Moon } from "lucide-react";
import { useStore } from "../../store/useStore";
import SearchBar from "../RealEstate/SearchBar";
import { useTheme } from "../../hooks/useTheme";

// ─── UTC Clock Hook ──────────────────────────────────────────────────────────
function useUTCClock(): string {
  const [time, setTime] = useState(
    () => new Date().toISOString().slice(11, 19) + "Z"
  );

  useEffect(() => {
    const interval = setInterval(() => {
      setTime(new Date().toISOString().slice(11, 19) + "Z");
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return time;
}

// ─── Divider ─────────────────────────────────────────────────────────────────
const Divider: React.FC = () => (
  <div className="w-px h-5 bg-parcl-border/50" />
);

// ─── TopBar ──────────────────────────────────────────────────────────────────
const TopBar: React.FC = () => {
  const isConnected = useStore((s) => s.isConnected);
  const permits = useStore((s) => s.permits);
  const totalPermitsAvailable = useStore((s) => s.totalPermitsAvailable);
  const propertyAgents = useStore((s) => s.propertyAgents);
  const utcClock = useUTCClock();
  const { isDark, toggle: toggleTheme } = useTheme();

  // Derive stat counts — show total available from DB, fallback to loaded count
  const permitsCount = totalPermitsAvailable || permits.length;
  const activeAgentsCount = propertyAgents.filter(
    (a) => a.status === "active"
  ).length;
  return (
    <div className="h-14 flex-shrink-0 bg-parcl-panel/95 backdrop-blur-lg border-b border-parcl-border relative z-[100]">
      <div className="h-full flex items-center justify-between px-4">
        {/* ── Left: Brand + Connection ────────────────────────────────────── */}
        <div className="flex items-center gap-3 min-w-[200px]">
          <div className="flex items-center gap-1.5 select-none">
            <span className="text-sm font-bold tracking-wider uppercase text-parcl-accent text-glow-blue">
              MUNICIPAL
            </span>
            <span className="text-xs tracking-wider uppercase text-parcl-text-muted">
              INTELLIGENCE SYSTEM
            </span>
          </div>

          {/* Connection indicator */}
          <div className="flex items-center gap-1.5">
            {isConnected ? (
              <>
                <div className="relative">
                  <div className="w-2 h-2 rounded-full bg-parcl-green" />
                  <div className="absolute inset-0 w-2 h-2 rounded-full bg-parcl-green animate-ping opacity-50" />
                </div>
                <Wifi className="w-3 h-3 text-parcl-green" />
              </>
            ) : (
              <>
                <div className="w-2 h-2 rounded-full bg-parcl-red" />
                <WifiOff className="w-3 h-3 text-parcl-red" />
              </>
            )}
          </div>
        </div>

        {/* ── Center: Search ──────────────────────────────────────────────── */}
        <div className="flex-1 flex justify-center px-4">
          <SearchBar />
        </div>

        {/* ── Right: Stats + Clock + Theme Toggle ─────────────────────────── */}
        <div className="flex items-center gap-3 min-w-[280px] justify-end">
          {/* Permits count */}
          <div className="flex items-center gap-1.5 text-parcl-text-muted" title={`${permitsCount.toLocaleString()} permits tracked`}>
            <Building2 className="w-3.5 h-3.5" />
            <span className="text-xs font-mono tabular-nums">
              {permitsCount >= 1000
                ? `${(permitsCount / 1000).toFixed(1)}K`
                : permitsCount}
            </span>
          </div>

          <Divider />

          {/* Active agents */}
          <div className="flex items-center gap-1.5 text-parcl-text-muted" title="Active agents">
            <Bot className="w-3.5 h-3.5" />
            <span className="text-xs font-mono tabular-nums">
              {activeAgentsCount}
            </span>
          </div>

          <Divider />

          {/* UTC clock */}
          <div className="text-xs font-mono tabular-nums text-parcl-accent text-glow-blue tracking-wide">
            {utcClock}
          </div>

          <Divider />

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            className="btn-tactical p-1.5"
            title={isDark ? "Switch to light mode" : "Switch to dark mode"}
            aria-label="Toggle theme"
          >
            {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </div>
  );
};

export default TopBar;
