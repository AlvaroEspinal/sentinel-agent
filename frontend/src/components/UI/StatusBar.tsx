import React, { useState, useEffect } from "react";
import {
  Wifi,
  WifiOff,
  Server,
  Database,
  Building2,
  Camera,
  Activity,
  Bot,
  Monitor,
} from "lucide-react";
import { useStore } from "../../store/useStore";

// ── Uptime counter ─────────────────────────────────────────────────────────
function useUptime(): string {
  const [startTime] = useState(Date.now());
  const [elapsed, setElapsed] = useState("00:00:00");

  useEffect(() => {
    const update = () => {
      const diff = Date.now() - startTime;
      const hours = Math.floor(diff / 3600000);
      const minutes = Math.floor((diff % 3600000) / 60000);
      const seconds = Math.floor((diff % 60000) / 1000);
      setElapsed(
        `${hours.toString().padStart(2, "0")}:${minutes
          .toString()
          .padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`
      );
    };
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  return elapsed;
}

const StatusBar: React.FC = () => {
  const isConnected = useStore((s) => s.isConnected);
  const viewMode = useStore((s) => s.viewMode);
  const permits = useStore((s) => s.permits);
  const totalPermitsAvailable = useStore((s) => s.totalPermitsAvailable);
  const activeTown = useStore((s) => s.activeTown);
  const cameras = useStore((s) => s.cameras);
  const earthquakes = useStore((s) => s.earthquakes);
  const propertyAgents = useStore((s) => s.propertyAgents);
  const leftPanelOpen = useStore((s) => s.leftPanelOpen);

  const uptime = useUptime();

  // Simulated data throughput
  const [throughput, setThroughput] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => {
      setThroughput(
        Math.round(
          (permits.length * 0.4 +
            cameras.length * 0.3 +
            earthquakes.length * 0.2 +
            Math.random() * 10) *
            100
        ) / 100
      );
    }, 2000);
    return () => clearInterval(interval);
  }, [permits.length, cameras.length, earthquakes.length]);

  return (
    <div
      className={`absolute bottom-16 z-30 pointer-events-none transition-all duration-300 ${
        leftPanelOpen ? "left-[356px]" : "left-4"
      }`}
    >
      <div className="pointer-events-auto">
        <div className="bg-parcl-panel/80 backdrop-blur-md border border-parcl-border/50 rounded-md px-3 py-1.5 flex items-center gap-4">
          {/* Connection status */}
          <div
            className={`flex items-center gap-1.5 ${
              isConnected ? "text-parcl-green" : "text-parcl-red"
            }`}
          >
            {isConnected ? (
              <Wifi className="w-3 h-3" />
            ) : (
              <WifiOff className="w-3 h-3" />
            )}
            <span className="text-[9px] font-mono uppercase">
              {isConnected ? "Connected" : "Disconnected"}
            </span>
          </div>

          <Divider />

          {/* Uptime */}
          <div className="flex items-center gap-1.5 text-parcl-text-muted">
            <Server className="w-3 h-3" />
            <span className="text-[9px] font-mono tabular-nums">{uptime}</span>
          </div>

          <Divider />

          {/* View mode */}
          <div className="flex items-center gap-1.5 text-parcl-text-muted">
            <Monitor className="w-3 h-3" />
            <span className="text-[9px] font-mono uppercase text-parcl-accent">
              {viewMode === "standard" ? "STD" : viewMode.toUpperCase()}
            </span>
          </div>

          <Divider />

          {/* Permits */}
          <div className="flex items-center gap-1.5 text-parcl-text-muted" title={`${(totalPermitsAvailable || permits.length).toLocaleString()} total permits`}>
            <Building2 className="w-3 h-3" />
            <span className="text-[9px] font-mono">
              {(totalPermitsAvailable || permits.length).toLocaleString()} permits{activeTown ? ` (${activeTown})` : ""}
            </span>
          </div>

          <Divider />

          {/* Cameras online */}
          <div className="flex items-center gap-1.5 text-parcl-text-muted">
            <Camera className="w-3 h-3" />
            <span className="text-[9px] font-mono">
              {cameras.length} cameras
            </span>
          </div>

          <Divider />

          {/* Earthquakes tracked */}
          <div className="flex items-center gap-1.5 text-parcl-text-muted">
            <Activity className="w-3 h-3" />
            <span className="text-[9px] font-mono">
              {earthquakes.length} quakes
            </span>
          </div>

          <Divider />

          {/* Active agents */}
          <div className="flex items-center gap-1.5 text-parcl-text-muted">
            <Bot className="w-3 h-3" />
            <span className="text-[9px] font-mono">
              {propertyAgents.length} agents
            </span>
          </div>

          <Divider />

          {/* Data throughput */}
          <div className="flex items-center gap-1.5 text-parcl-text-muted">
            <Database className="w-3 h-3" />
            <span className="text-[9px] font-mono tabular-nums">
              {throughput.toFixed(1)} KB/s
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

const Divider: React.FC = () => (
  <div className="w-px h-3 bg-parcl-border/50" />
);

export default StatusBar;
