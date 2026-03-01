import React, { useState, useEffect } from "react";
import { X, Camera, MapPin, Signal, Clock, Maximize2, Minimize2, Play, Image } from "lucide-react";
import { useStore } from "../../store/useStore";

const PROXY_BASE = "/api/data/cameras/proxy?url=";

function proxyUrl(url: string): string {
  if (!url) return "";
  // Already proxied or data URL — skip
  if (url.startsWith("/api/") || url.startsWith("data:")) return url;
  return `${PROXY_BASE}${encodeURIComponent(url)}`;
}

function isMjpegUrl(url: string): boolean {
  return /mjpe?g/i.test(url);
}

const CameraPreviewPanel: React.FC = () => {
  const selectedCamera = useStore((s) => s.selectedCamera);
  const selectCamera = useStore((s) => s.selectCamera);
  const [viewMode, setViewMode] = useState<"snapshot" | "stream">("snapshot");
  const [cacheBuster, setCacheBuster] = useState(Date.now());
  const [expanded, setExpanded] = useState(false);
  const [imgError, setImgError] = useState(false);

  // Auto-refresh JPEG snapshots
  useEffect(() => {
    if (!selectedCamera || viewMode !== "snapshot") return;
    if (isMjpegUrl(selectedCamera.image_url)) return; // MJPEG self-refreshes
    const interval = selectedCamera.refresh_interval || 10;
    const timer = setInterval(() => {
      setCacheBuster(Date.now());
      setImgError(false);
    }, interval * 1000);
    return () => clearInterval(timer);
  }, [selectedCamera?.id, selectedCamera?.refresh_interval, viewMode]);

  // Reset state when camera changes
  useEffect(() => {
    setViewMode("snapshot");
    setCacheBuster(Date.now());
    setImgError(false);
    setExpanded(false);
  }, [selectedCamera?.id]);

  if (!selectedCamera) return null;

  const hasEmbed = !!selectedCamera.embed_url;
  const isMjpeg = isMjpegUrl(selectedCamera.image_url);

  // Build the image URL with cache busting
  const imageUrl = selectedCamera.image_url
    ? isMjpeg
      ? proxyUrl(selectedCamera.image_url)
      : `${proxyUrl(selectedCamera.image_url)}${proxyUrl(selectedCamera.image_url).includes("?") ? "&" : "?"}_t=${cacheBuster}`
    : "";

  const statusColor: Record<string, string> = {
    online: "text-green-400",
    offline: "text-gray-500",
    degraded: "text-amber-400",
  };

  const statusDot: Record<string, string> = {
    online: "bg-green-400",
    offline: "bg-gray-500",
    degraded: "bg-amber-400",
  };

  return (
    <div className={`absolute bottom-20 left-1/2 -translate-x-1/2 z-50 pointer-events-auto ${expanded ? "w-[700px]" : "w-[400px]"} max-w-[90vw] transition-all duration-300`}>
      <div className="bg-parcl-panel/95 backdrop-blur-xl border border-parcl-border rounded-lg shadow-tactical overflow-hidden">
        {/* Header */}
        <div className="px-4 py-2.5 border-b border-parcl-border/50 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Camera className="w-3.5 h-3.5 text-purple-400" />
            <span className="text-[9px] font-semibold uppercase tracking-[0.2em] text-parcl-text-dim">
              Camera Feed
            </span>
            {/* Live indicator */}
            <div className="flex items-center gap-1 ml-2">
              <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              <span className="text-[8px] text-red-400 font-mono uppercase">
                {isMjpeg ? "STREAM" : "LIVE"}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {/* Snapshot / Stream toggle */}
            {hasEmbed && (
              <div className="flex gap-0.5 mr-2">
                <button
                  onClick={() => setViewMode("snapshot")}
                  className={`p-1 rounded ${viewMode === "snapshot" ? "bg-purple-500/20 text-purple-300" : "text-gray-500 hover:text-gray-300"}`}
                  title="Snapshot"
                >
                  <Image className="w-3 h-3" />
                </button>
                <button
                  onClick={() => setViewMode("stream")}
                  className={`p-1 rounded ${viewMode === "stream" ? "bg-purple-500/20 text-purple-300" : "text-gray-500 hover:text-gray-300"}`}
                  title="Live Stream"
                >
                  <Play className="w-3 h-3" />
                </button>
              </div>
            )}
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-parcl-text-muted hover:text-parcl-text transition-colors p-0.5 rounded hover:bg-parcl-surface/50"
            >
              {expanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
            </button>
            <button
              onClick={() => selectCamera(null)}
              className="text-parcl-text-muted hover:text-parcl-text transition-colors p-0.5 rounded hover:bg-parcl-surface/50"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Camera feed */}
        <div className="relative aspect-video bg-black/50">
          {viewMode === "stream" && selectedCamera.embed_url ? (
            <iframe
              src={selectedCamera.embed_url}
              className="w-full h-full border-0"
              allow="autoplay; fullscreen"
              title={selectedCamera.name}
            />
          ) : imageUrl && !imgError ? (
            <img
              key={`${selectedCamera.id}-${cacheBuster}`}
              src={imageUrl}
              alt={selectedCamera.name}
              className="w-full h-full object-cover opacity-90"
              onError={() => setImgError(true)}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center flex-col gap-2">
              <Camera className="w-8 h-8 text-parcl-text-muted/30" />
              <span className="text-[9px] text-parcl-text-muted/40 font-mono">
                {imgError ? "FEED UNAVAILABLE" : "NO FEED URL"}
              </span>
            </div>
          )}
          {/* Status overlay */}
          <div className="absolute top-2 right-2 flex items-center gap-1.5 bg-black/60 backdrop-blur-sm px-2 py-1 rounded">
            <div className={`w-1.5 h-1.5 rounded-full ${statusDot[selectedCamera.status] || statusDot.online} ${selectedCamera.status === "online" ? "animate-pulse" : ""}`} />
            <span className={`text-[9px] font-semibold uppercase ${statusColor[selectedCamera.status] || statusColor.online}`}>
              {selectedCamera.status}
            </span>
          </div>
          {/* Source badge */}
          <div className="absolute bottom-2 left-2 bg-black/60 backdrop-blur-sm px-2 py-1 rounded">
            <span className="text-[8px] font-mono text-purple-300/80 uppercase tracking-wider">
              {selectedCamera.source}
            </span>
          </div>
          {/* Refresh indicator */}
          {viewMode === "snapshot" && !isMjpeg && (
            <div className="absolute bottom-2 right-2 bg-black/60 backdrop-blur-sm px-2 py-1 rounded flex items-center gap-1">
              <div className="w-1 h-1 rounded-full bg-blue-400 animate-ping" />
              <span className="text-[7px] font-mono text-blue-300/70">
                {selectedCamera.refresh_interval || 10}s
              </span>
            </div>
          )}
        </div>

        {/* Info */}
        <div className="px-4 py-3 space-y-2">
          <h3 className="text-xs font-semibold text-parcl-text truncate">
            {selectedCamera.name}
          </h3>

          <div className="grid grid-cols-2 gap-2">
            <div className="flex items-center gap-1.5">
              <MapPin className="w-3 h-3 text-parcl-text-muted" />
              <span className="text-[10px] text-parcl-text-dim">
                {selectedCamera.region}{selectedCamera.country ? `, ${selectedCamera.country}` : ""}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <Signal className="w-3 h-3 text-parcl-text-muted" />
              <span className="text-[10px] text-parcl-text-dim capitalize">
                {selectedCamera.category}
              </span>
            </div>
            <div className="flex items-center gap-1.5 col-span-2">
              <Clock className="w-3 h-3 text-parcl-text-muted" />
              <span className="text-[10px] text-parcl-text-dim font-mono">
                {selectedCamera.latitude.toFixed(4)}, {selectedCamera.longitude.toFixed(4)}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CameraPreviewPanel;
