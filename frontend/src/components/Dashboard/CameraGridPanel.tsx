import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { X, Camera, ChevronLeft, ChevronRight, LayoutGrid, MapPin, Crosshair, Satellite, Globe, Radio, ScanLine } from "lucide-react";
import { useStore } from "../../store/useStore";
import type { TrafficCameraData } from "../../types";

/** Local type for LPR plate detection results */
interface PlateDetection {
  plate_text: string;
  confidence: number;
  vehicle?: {
    make?: string;
    model?: string;
    year?: string;
    color?: string;
  };
}

// ─── Satellite Recon Sites ───────────────────────────────────────────────────
// Key real estate development zones for satellite monitoring
interface SatFacility {
  label: string;
  name: string;
  lat: number;
  lon: number;
  zoom: number; // higher = more zoomed in
}

const SAT_FACILITIES: SatFacility[] = [
  { label: "BOS-1", name: "Seaport District, Boston", lat: 42.3480, lon: -71.0405, zoom: 16 },
  { label: "MIA-1", name: "Brickell Ave, Miami", lat: 25.7617, lon: -80.1918, zoom: 16 },
  { label: "AUS-1", name: "Downtown Austin", lat: 30.2672, lon: -97.7431, zoom: 16 },
  { label: "NYC-1", name: "Hudson Yards, NYC", lat: 40.7536, lon: -74.0004, zoom: 16 },
  { label: "LA-1", name: "DTLA Arts District", lat: 34.0407, lon: -118.2346, zoom: 16 },
  { label: "SF-1", name: "Mission Bay, SF", lat: 37.7706, lon: -122.3892, zoom: 16 },
  { label: "DEN-1", name: "RiNo District, Denver", lat: 39.7684, lon: -104.9812, zoom: 15 },
];

// ─── Satellite Source Types ─────────────────────────────────────────────────
type SatSource = "ESRI" | "GOES" | "GIBS";

const SAT_SOURCE_META: Record<SatSource, { label: string; color: string; refresh: string; resolution: string }> = {
  ESRI: { label: "ESRI Archival", color: "text-blue-400", refresh: "10s cache-bust", resolution: "~1m" },
  GOES: { label: "GOES-16 Live", color: "text-amber-400", refresh: "~60s", resolution: "500m" },
  GIBS: { label: "NASA GIBS", color: "text-emerald-400", refresh: "~4hr", resolution: "250m" },
};

/** Build ESRI World Imagery URL for a lat/lon at a given zoom level */
function esriSatelliteUrl(lat: number, lon: number, zoom: number, cacheBust: number): string {
  const scale = 360 / Math.pow(2, zoom);
  const aspect = 1.3;
  const halfW = (scale * aspect) / 2;
  const halfH = scale / 2;
  const bbox = `${lon - halfW},${lat - halfH},${lon + halfW},${lat + halfH}`;
  return (
    `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export` +
    `?bbox=${bbox}&bboxSR=4326&size=480,360&f=image&format=jpg&_t=${cacheBust}`
  );
}

/** Map lat/lon to nearest GOES-16 sector */
function goesUrl(lat: number, lon: number): string {
  const sectors: { id: string; lat: number; lon: number }[] = [
    { id: "ne", lat: 42, lon: -72 },
    { id: "se", lat: 30, lon: -82 },
    { id: "umv", lat: 44, lon: -92 },
    { id: "smv", lat: 33, lon: -90 },
    { id: "gm", lat: 26, lon: -90 },
    { id: "nrp", lat: 44, lon: -108 },
    { id: "srp", lat: 36, lon: -108 },
    { id: "pnw", lat: 46, lon: -122 },
    { id: "psw", lat: 36, lon: -120 },
  ];
  let closest = sectors[0];
  let minDist = Infinity;
  for (const s of sectors) {
    const d = Math.hypot(lat - s.lat, lon - s.lon);
    if (d < minDist) { minDist = d; closest = s; }
  }
  return `https://cdn.star.nesdis.noaa.gov/GOES16/ABI/SECTOR/${closest.id}/GEOCOLOR/latest.jpg`;
}

/** Build NASA GIBS WMTS tile URL */
function gibsTileUrl(lat: number, lon: number, zoom: number = 6): string {
  const n = Math.pow(2, zoom);
  const x = Math.floor(((lon + 180) / 360) * n);
  const latRad = (lat * Math.PI) / 180;
  const y = Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n);
  const today = new Date().toISOString().slice(0, 10);
  return `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/${today}/GoogleMapsCompatible_Level9/${zoom}/${y}/${x}.jpg`;
}

// ─── Satellite Recon Cell ────────────────────────────────────────────────────

const SatelliteReconCell: React.FC<{
  facility: SatFacility;
  cacheBust: number;
  scanProgress: number;
  source: SatSource;
}> = React.memo(({ facility, cacheBust, scanProgress, source }) => {
  const [imgError, setImgError] = useState(false);

  const imgUrl = useMemo(() => {
    switch (source) {
      case "GOES": return goesUrl(facility.lat, facility.lon);
      case "GIBS": return gibsTileUrl(facility.lat, facility.lon, 6);
      default: return esriSatelliteUrl(facility.lat, facility.lon, facility.zoom, cacheBust);
    }
  }, [facility, cacheBust, source]);

  useEffect(() => { setImgError(false); }, [cacheBust, source]);

  const meta = SAT_SOURCE_META[source];

  return (
    <div className="relative bg-black/80 rounded overflow-hidden flex-shrink-0 w-[180px] h-[130px] group border border-parcl-border/30 hover:border-blue-500/40 transition-all">
      {!imgError ? (
        <img
          key={`sat-${facility.label}-${cacheBust}-${source}`}
          src={imgUrl}
          alt={facility.name}
          className="w-full h-full object-cover"
          onError={() => setImgError(true)}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center">
          <Satellite className="w-6 h-6 text-parcl-text-muted/20" />
        </div>
      )}

      {/* Scan-line overlay */}
      <div
        className="absolute inset-x-0 h-[2px] bg-gradient-to-r from-transparent via-blue-400/60 to-transparent pointer-events-none transition-all duration-300"
        style={{ top: `${scanProgress}%` }}
      />

      {/* Vignette */}
      <div className="absolute inset-0 pointer-events-none"
        style={{ background: "radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.5) 100%)" }}
      />

      {/* Site label badge */}
      <div className="absolute top-1 left-1 bg-black/70 px-1.5 py-0.5 rounded flex items-center gap-1">
        <span className="text-[8px] font-bold text-blue-300 font-mono">{facility.label}</span>
      </div>

      {/* Source indicator */}
      <div className="absolute top-1 right-1 flex items-center gap-0.5 bg-black/70 px-1 py-0.5 rounded">
        {source === "GOES" ? <Radio className="w-2 h-2 text-amber-400" /> :
         source === "GIBS" ? <Globe className="w-2 h-2 text-emerald-400" /> :
         <Satellite className="w-2 h-2 text-blue-400" />}
        <span className={`text-[6px] font-mono ${meta.color}`}>{source}</span>
      </div>

      {/* Bottom info */}
      <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/90 to-transparent p-1.5 pt-4">
        <div className="text-[7px] font-mono text-white/80 truncate leading-tight">{facility.name}</div>
        <div className="flex items-center justify-between">
          <span className="text-[6px] text-gray-400 font-mono">
            {facility.lat.toFixed(3)}°N {Math.abs(facility.lon).toFixed(3)}°W
          </span>
          <span className={`text-[6px] font-mono ${meta.color}`}>{meta.resolution}</span>
        </div>
      </div>
    </div>
  );
});

SatelliteReconCell.displayName = "SatelliteReconCell";

// ─── Satellite Recon Strip ───────────────────────────────────────────────────

const SAT_SOURCES: SatSource[] = ["ESRI", "GOES", "GIBS"];

const SatelliteReconStrip: React.FC = () => {
  const [cacheBust, setCacheBust] = useState(Date.now());
  const [scanProgress, setScanProgress] = useState(0);
  const [countdown, setCountdown] = useState(10);
  const [satSource, setSatSource] = useState<SatSource>("ESRI");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-refresh every 10 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      setCacheBust(Date.now());
      setCountdown(10);
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  // Countdown timer
  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown((c) => Math.max(0, c - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Scan-line animation
  useEffect(() => {
    const animInterval = setInterval(() => {
      setScanProgress((p) => (p >= 100 ? 0 : p + 2));
    }, 200);
    return () => clearInterval(animInterval);
  }, []);

  useEffect(() => { setScanProgress(0); }, [cacheBust]);

  const meta = SAT_SOURCE_META[satSource];

  return (
    <div className="flex-shrink-0 border-b border-parcl-border/50">
      {/* Strip header */}
      <div className="px-3 py-1.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Satellite className="w-3 h-3 text-emerald-400" />
          <span className="text-[8px] font-semibold uppercase tracking-[0.2em] text-emerald-400/80">
            Satellite Recon
          </span>
          <span className="text-[8px] text-parcl-text-muted font-mono">
            {SAT_FACILITIES.length} facilities
          </span>
          {/* Source toggle buttons */}
          <div className="flex items-center gap-0.5 ml-2 bg-parcl-surface/50 rounded px-1 py-0.5">
            {SAT_SOURCES.map((src) => (
              <button
                key={src}
                onClick={() => setSatSource(src)}
                className={`text-[7px] font-mono px-1.5 py-0.5 rounded transition-all ${
                  satSource === src
                    ? `${SAT_SOURCE_META[src].color} bg-white/10`
                    : "text-parcl-text-muted hover:text-white/60"
                }`}
              >
                {src}
              </button>
            ))}
          </div>
          <span className={`text-[7px] font-mono ${meta.color}`}>
            {meta.resolution} / {meta.refresh}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[7px] text-parcl-text-muted font-mono">
            refresh in {countdown}s
          </span>
          <div className="w-12 h-1 bg-parcl-surface rounded-full overflow-hidden">
            <div
              className="h-full bg-emerald-500/60 transition-all duration-1000 ease-linear rounded-full"
              style={{ width: `${(countdown / 10) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Scrollable satellite image strip */}
      <div
        ref={scrollRef}
        className="flex gap-1.5 px-3 pb-2 overflow-x-auto scrollbar-thin scrollbar-track-transparent scrollbar-thumb-parcl-border/30"
      >
        {SAT_FACILITIES.map((fac) => (
          <SatelliteReconCell
            key={`${fac.label}-${satSource}`}
            facility={fac}
            cacheBust={cacheBust}
            scanProgress={scanProgress}
            source={satSource}
          />
        ))}
      </div>
    </div>
  );
};

const PROXY_BASE = "/api/data/cameras/proxy?url=";

function proxyUrl(url: string): string {
  if (!url) return "";
  if (url.startsWith("/api/") || url.startsWith("data:")) return url;
  return `${PROXY_BASE}${encodeURIComponent(url)}`;
}

function isMjpegUrl(url: string): boolean {
  return /mjpe?g/i.test(url);
}

/** Haversine distance in miles */
function haversineDistance(
  lat1: number, lon1: number,
  lat2: number, lon2: number
): number {
  const R = 3958.8; // Earth radius in miles
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// ─── Single Camera Cell ─────────────────────────────────────────────────────

const CameraGridCell: React.FC<{
  camera: TrafficCameraData;
  onClick: () => void;
  distanceMi?: number;
}> = React.memo(({ camera, onClick, distanceMi }) => {
  const [cacheBuster, setCacheBuster] = useState(Date.now());
  const [imgError, setImgError] = useState(false);
  const isMjpeg = isMjpegUrl(camera.image_url);

  useEffect(() => {
    if (isMjpeg) return;
    const interval = camera.refresh_interval || 10;
    const timer = setInterval(() => {
      setCacheBuster(Date.now());
      setImgError(false);
    }, interval * 1000);
    return () => clearInterval(timer);
  }, [camera.id, camera.refresh_interval, isMjpeg]);

  const imageUrl = camera.image_url
    ? isMjpeg
      ? proxyUrl(camera.image_url)
      : `${proxyUrl(camera.image_url)}${proxyUrl(camera.image_url).includes("?") ? "&" : "?"}_t=${cacheBuster}`
    : "";

  return (
    <div
      onClick={onClick}
      className="relative bg-black/60 rounded overflow-hidden cursor-pointer hover:ring-1 hover:ring-purple-400/50 transition-all group"
    >
      {imageUrl && !imgError ? (
        <img
          key={`${camera.id}-${cacheBuster}`}
          src={imageUrl}
          alt={camera.name}
          className="w-full h-full object-cover"
          loading="lazy"
          onError={() => setImgError(true)}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center min-h-[80px]">
          <Camera className="w-6 h-6 text-parcl-text-muted/20" />
        </div>
      )}

      {/* Overlay: camera name + status */}
      <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent p-1.5 pt-4">
        <div className="flex items-center gap-1">
          <div
            className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
              camera.status === "online"
                ? "bg-green-400 animate-pulse"
                : camera.status === "degraded"
                ? "bg-amber-400"
                : "bg-gray-500"
            }`}
          />
          <span className="text-[8px] font-mono text-white/80 truncate leading-tight">
            {camera.name}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[7px] text-gray-400 uppercase font-mono">
            {camera.source} / {camera.category}
          </span>
          {distanceMi !== undefined && (
            <span className="text-[7px] text-blue-400 font-mono">
              {distanceMi < 1 ? `${(distanceMi * 5280).toFixed(0)} ft` : `${distanceMi.toFixed(1)} mi`}
            </span>
          )}
        </div>
      </div>

      {/* Live indicator */}
      <div className="absolute top-1 right-1 flex items-center gap-0.5 bg-black/60 px-1 py-0.5 rounded">
        <div className="w-1 h-1 rounded-full bg-red-500 animate-pulse" />
        <span className="text-[6px] text-red-400 font-mono">LIVE</span>
      </div>

      {/* Distance badge (nearby mode) */}
      {distanceMi !== undefined && (
        <div className="absolute top-1 left-1 flex items-center gap-0.5 bg-blue-900/80 px-1.5 py-0.5 rounded">
          <MapPin className="w-2 h-2 text-blue-400" />
          <span className="text-[7px] text-blue-300 font-mono">
            {distanceMi < 1 ? `${(distanceMi * 5280).toFixed(0)}ft` : `${distanceMi.toFixed(1)}mi`}
          </span>
        </div>
      )}
    </div>
  );
});

CameraGridCell.displayName = "CameraGridCell";

// ─── Swarm Monitor Grid ─────────────────────────────────────────────────────

const GRID_SIZES = [4, 8, 9, 16] as const;
type GridSize = (typeof GRID_SIZES)[number];

const GRID_COLS: Record<GridSize, number> = { 4: 2, 8: 4, 9: 3, 16: 4 };
const GRID_LABELS: Record<GridSize, string> = { 4: "2x2", 8: "4x2", 9: "3x3", 16: "4x4" };

const CATEGORIES = ["all", "traffic", "port", "industrial", "webcam", "shipping", "logistics", "mining"] as const;

const NEARBY_COUNT = 50;

const CameraGridPanel: React.FC = () => {
  const cameras = useStore((s) => s.cameras);
  const showCameraGrid = useStore((s) => s.showCameraGrid);
  const toggleCameraGrid = useStore((s) => s.toggleCameraGrid);
  const selectCamera = useStore((s) => s.selectCamera);

  // Nearby mode state (local — no store field for this yet)
  const [nearbyCameraLocation, setNearbyCameraLocation] = useState<{
    lat: number;
    lon: number;
    label?: string;
  } | null>(null);

  const isNearbyMode = nearbyCameraLocation !== null;

  const [gridSize, setGridSize] = useState<GridSize>(isNearbyMode ? 8 : 9);
  const [page, setPage] = useState(0);
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [lprMode, setLprMode] = useState(false);
  const [plateResults, setPlateResults] = useState<Map<string, PlateDetection[]>>(new Map());
  const [analyzingCameras, setAnalyzingCameras] = useState<Set<string>>(new Set());

  // When nearby mode activates, switch to 4x2 grid
  useEffect(() => {
    if (isNearbyMode) {
      setGridSize(8);
      setPage(0);
    }
  }, [isNearbyMode]);

  const analyzeFrameForPlates = async (camera: TrafficCameraData) => {
    if (!camera.image_url || analyzingCameras.has(camera.id)) return;
    setAnalyzingCameras(prev => new Set(prev).add(camera.id));
    try {
      const resp = await fetch("/api/vision/analyze-frame", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_url: camera.image_url,
          camera_id: camera.id,
          camera_name: camera.name,
          latitude: camera.latitude,
          longitude: camera.longitude,
          run_lpr: true,
        }),
      });
      if (resp.ok) {
        const result = await resp.json();
        if (result.plates?.length > 0) {
          setPlateResults(prev => new Map(prev).set(camera.id, result.plates));
        }
      }
    } catch {}
    finally {
      setAnalyzingCameras(prev => { const s = new Set(prev); s.delete(camera.id); return s; });
    }
  };

  // Compute distances + sort if nearby mode
  const { displayCameras, distances } = useMemo(() => {
    // Base filter: online cameras with images
    const filtered = cameras.filter((cam) => {
      if (filterCategory !== "all" && cam.category !== filterCategory) return false;
      return cam.image_url && cam.status !== "offline";
    });

    if (!nearbyCameraLocation) {
      return { displayCameras: filtered, distances: new Map<string, number>() };
    }

    // Compute distance for every camera
    const withDist = filtered.map((cam) => ({
      cam,
      dist: haversineDistance(
        nearbyCameraLocation.lat,
        nearbyCameraLocation.lon,
        cam.latitude,
        cam.longitude
      ),
    }));

    // Sort by distance, take closest NEARBY_COUNT
    withDist.sort((a, b) => a.dist - b.dist);
    const closest = withDist.slice(0, NEARBY_COUNT);

    const distMap = new Map<string, number>();
    closest.forEach(({ cam, dist }) => distMap.set(cam.id, dist));

    return {
      displayCameras: closest.map((c) => c.cam),
      distances: distMap,
    };
  }, [cameras, filterCategory, nearbyCameraLocation]);

  const totalPages = Math.max(1, Math.ceil(displayCameras.length / gridSize));
  const pageCameras = displayCameras.slice(page * gridSize, (page + 1) * gridSize);
  const cols = GRID_COLS[gridSize];

  // Reset page when filter or grid size changes
  useEffect(() => {
    setPage(0);
  }, [filterCategory, gridSize]);

  // Auto-scan visible cameras when LPR mode is toggled on
  useEffect(() => {
    if (!lprMode) return;
    const visible = displayCameras.slice(page * gridSize, (page + 1) * gridSize);
    visible.forEach((cam) => analyzeFrameForPlates(cam));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lprMode, page, gridSize]);

  const handleCameraClick = useCallback(
    (cam: TrafficCameraData) => {
      toggleCameraGrid();
      if (isNearbyMode) setNearbyCameraLocation(null);
      selectCamera(cam);
    },
    [toggleCameraGrid, selectCamera, isNearbyMode, setNearbyCameraLocation]
  );

  const handleClose = useCallback(() => {
    toggleCameraGrid();
    if (isNearbyMode) setNearbyCameraLocation(null);
  }, [toggleCameraGrid, isNearbyMode, setNearbyCameraLocation]);

  if (!showCameraGrid) return null;

  return (
    <div className="absolute inset-4 z-[60] pointer-events-auto">
      <div className="w-full h-full bg-parcl-panel/97 backdrop-blur-xl border border-parcl-border rounded-lg shadow-tactical flex flex-col overflow-hidden">
        {/* Header toolbar */}
        <div className="px-4 py-2.5 border-b border-parcl-border/50 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-3">
            {isNearbyMode ? (
              <Crosshair className="w-4 h-4 text-blue-400" />
            ) : (
              <LayoutGrid className="w-4 h-4 text-purple-400" />
            )}
            <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-parcl-text-dim">
              {isNearbyMode ? "Nearby Cameras" : "Swarm Monitor"}
            </span>
            {isNearbyMode && nearbyCameraLocation && (
              <span className="text-[9px] font-mono text-blue-400/80 max-w-[200px] truncate">
                {nearbyCameraLocation.label}
              </span>
            )}
            <span className="text-[9px] font-mono text-purple-400/80">
              {displayCameras.length} feeds
            </span>
            <div className="flex items-center gap-1 ml-2">
              <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              <span className="text-[8px] text-red-400 font-mono uppercase">live</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Category filter (hidden in nearby mode) */}
            {!isNearbyMode && (
              <select
                value={filterCategory}
                onChange={(e) => setFilterCategory(e.target.value)}
                className="bg-parcl-surface/50 border border-parcl-border/50 rounded px-2 py-1 text-[9px] text-parcl-text-dim font-mono uppercase focus:outline-none focus:border-purple-400/50"
              >
                {CATEGORIES.map((cat) => (
                  <option key={cat} value={cat}>
                    {cat === "all" ? "All Categories" : cat}
                  </option>
                ))}
              </select>
            )}

            {/* Grid size selector */}
            <div className="flex gap-0.5">
              {GRID_SIZES.map((size) => (
                <button
                  key={size}
                  onClick={() => setGridSize(size)}
                  className={`px-2 py-1 text-[9px] font-mono rounded transition-colors ${
                    gridSize === size
                      ? "bg-purple-500/20 text-purple-300 border border-purple-400/30"
                      : "text-gray-500 hover:text-gray-300 border border-transparent"
                  }`}
                >
                  {GRID_LABELS[size]}
                </button>
              ))}
            </div>

            {/* LPR Mode Toggle */}
            <button
              onClick={() => setLprMode(v => !v)}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-mono border transition-colors ${
                lprMode
                  ? "bg-yellow-500/20 border-yellow-500/60 text-yellow-400"
                  : "bg-gray-800 border-gray-700 text-gray-400 hover:text-yellow-400"
              }`}
              title="Toggle LPR Mode"
            >
              <ScanLine size={12} />
              <span>LPR</span>
            </button>

            {/* Close */}
            <button
              onClick={handleClose}
              className="text-parcl-text-muted hover:text-parcl-text transition-colors p-1 rounded hover:bg-parcl-surface/50"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Satellite Recon Strip (nearby mode only) */}
        {isNearbyMode && <SatelliteReconStrip />}

        {/* Camera grid */}
        <div
          className="flex-1 grid gap-1.5 p-2 overflow-hidden"
          style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
        >
          {pageCameras.map((cam) => (
            <div key={cam.id} className="relative">
              <CameraGridCell
                camera={cam}
                onClick={() => handleCameraClick(cam)}
                distanceMi={distances.get(cam.id)}
              />
              {lprMode && plateResults.get(cam.id)?.map((plate, i) => (
                <div key={i} className="absolute bottom-0 left-0 right-0 bg-black/80 px-1 py-0.5 flex items-center gap-1 text-xs font-mono">
                  <span className="text-yellow-400 font-bold">{plate.plate_text}</span>
                  {plate.vehicle?.make && (
                    <span className="text-gray-300">{plate.vehicle.color} {plate.vehicle.year} {plate.vehicle.make}</span>
                  )}
                  <span className="ml-auto text-gray-500">{Math.round(plate.confidence * 100)}%</span>
                </div>
              ))}
              {lprMode && analyzingCameras.has(cam.id) && (
                <div className="absolute top-1 right-1 bg-yellow-500/20 border border-yellow-500/40 rounded px-1 text-yellow-400 text-xs font-mono animate-pulse">
                  SCAN
                </div>
              )}
            </div>
          ))}
          {/* Empty cells if not enough cameras to fill grid */}
          {pageCameras.length < gridSize &&
            Array.from({ length: gridSize - pageCameras.length }).map((_, i) => (
              <div
                key={`empty-${i}`}
                className="bg-black/30 rounded flex items-center justify-center"
              >
                <Camera className="w-5 h-5 text-parcl-text-muted/10" />
              </div>
            ))}
        </div>

        {/* Footer with pagination */}
        <div className="px-4 py-2 border-t border-parcl-border/50 flex items-center justify-between flex-shrink-0">
          <span className="text-[9px] text-gray-500 font-mono">
            {isNearbyMode
              ? `${displayCameras.length} closest cameras — page ${page + 1}/${totalPages}`
              : `Page ${page + 1} of ${totalPages} (${displayCameras.length} cameras)`}
          </span>
          {totalPages > 1 && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="flex items-center gap-1 px-2 py-1 text-[9px] font-mono rounded transition-colors disabled:opacity-30 text-parcl-text-dim hover:text-parcl-text hover:bg-parcl-surface/50"
              >
                <ChevronLeft className="w-3 h-3" />
                Prev
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="flex items-center gap-1 px-2 py-1 text-[9px] font-mono rounded transition-colors disabled:opacity-30 text-parcl-text-dim hover:text-parcl-text hover:bg-parcl-surface/50"
              >
                Next
                <ChevronRight className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CameraGridPanel;
