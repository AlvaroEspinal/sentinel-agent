import React, { useEffect, useCallback, Component, ErrorInfo, ReactNode, Suspense, lazy } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import { api, listPropertyAgents, searchPermits, getPermitTowns, getCoverageSummary, listTowns } from "./services/api";
import { useStore } from "./store/useStore";

// ── Lazy load heavy components ──
const CesiumGlobe = lazy(() => import("./components/Globe/CesiumGlobe"));

// Parcl Intelligence UI components
const TopBar = lazy(() => import("./components/UI/TopBar"));
const LeftSidebar = lazy(() => import("./components/UI/LeftSidebar"));
const RightPanel = lazy(() => import("./components/RealEstate/RightPanel"));
const CameraPreviewPanel = lazy(() => import("./components/Dashboard/CameraPreviewPanel"));

// ── Generic Error Boundary ──
interface EBProps { children: ReactNode; fallback?: ReactNode; name?: string }
interface EBState { hasError: boolean; error: string }

class SafeBoundary extends Component<EBProps, EBState> {
  constructor(props: EBProps) {
    super(props);
    this.state = { hasError: false, error: "" };
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error: error.message };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn(`[SafeBoundary:${this.props.name || "unknown"}]`, error.message);
  }
  render() {
    if (this.state.hasError) {
      return this.props.fallback || null;
    }
    return this.props.children;
  }
}

// ── Safe wrapper for lazy + boundary ──
const Safe: React.FC<{ name: string; fallback?: ReactNode; children: ReactNode }> = ({ name, fallback, children }) => (
  <SafeBoundary name={name} fallback={fallback}>
    <Suspense fallback={null}>
      {children}
    </Suspense>
  </SafeBoundary>
);

// ── Globe fallback when Cesium fails ──
const GlobeFallback: React.FC = () => (
  <div className="w-full h-full relative bg-slate-950 flex items-center justify-center overflow-hidden">
    {/* Animated grid background */}
    <div className="absolute inset-0 opacity-10"
      style={{
        backgroundImage: `
          linear-gradient(rgba(37,99,235,0.3) 1px, transparent 1px),
          linear-gradient(90deg, rgba(37,99,235,0.3) 1px, transparent 1px)
        `,
        backgroundSize: "60px 60px",
        animation: "grid-drift 20s linear infinite",
      }}
    />
    {/* Glowing orb */}
    <div className="relative">
      <div className="w-64 h-64 rounded-full bg-gradient-to-br from-blue-900/40 via-slate-800/60 to-blue-900/40 border border-parcl-accent/20 shadow-[0_0_60px_rgba(37,99,235,0.15)]"
        style={{ animation: "pulse-glow 4s ease-in-out infinite" }}
      />
      <div className="absolute inset-0 flex items-center justify-center flex-col">
        <div className="text-parcl-accent/80 font-mono text-xs tracking-[0.3em] uppercase">Parcl Intelligence</div>
        <div className="text-parcl-accent/50 font-mono text-[10px] mt-2 tracking-wider">REAL ESTATE INTEL ONLINE</div>
        <div className="text-slate-500 font-mono text-[9px] mt-4 max-w-[200px] text-center">
          Set CESIUM_ION_ACCESS_TOKEN for 3D globe
        </div>
      </div>
    </div>
    <style>{`
      @keyframes grid-drift {
        0% { transform: translate(0,0); }
        100% { transform: translate(60px,60px); }
      }
      @keyframes pulse-glow {
        0%,100% { box-shadow: 0 0 40px rgba(37,99,235,0.1); }
        50% { box-shadow: 0 0 80px rgba(37,99,235,0.25); }
      }
    `}</style>
  </div>
);

const App: React.FC = () => {
  // Initialize WebSocket connection
  useWebSocket();

  const setCameras = useStore((s) => s.setCameras);
  const setEarthquakes = useStore((s) => s.setEarthquakes);
  const setPropertyAgents = useStore((s) => s.setPropertyAgents);
  const setPermits = useStore((s) => s.setPermits);
  const setTotalPermitsAvailable = useStore((s) => s.setTotalPermitsAvailable);
  const setTowns = useStore((s) => s.setTowns);
  const setCoverageSummary = useStore((s) => s.setCoverageSummary);
  const setTownDetails = useStore((s) => s.setTownDetails);

  // Fetch initial data on mount
  const fetchInitialData = useCallback(async () => {
    try {
      const cameras = await api.fetchCameras();
      setCameras(cameras);
    } catch (err) {
      console.warn("[Parcl] Failed to fetch cameras:", err);
    }

    try {
      const earthquakes = await api.fetchEarthquakes();
      setEarthquakes(earthquakes);
    } catch (err) {
      console.warn("[Parcl] Failed to fetch earthquakes:", err);
    }

    try {
      const { agents } = await listPropertyAgents();
      setPropertyAgents(agents);
    } catch (err) {
      console.warn("[Parcl] Failed to fetch agents:", err);
    }

    try {
      const response = await searchPermits({ limit: 500 });
      setPermits(response.permits);
      if ((response as any).total_available) {
        setTotalPermitsAvailable((response as any).total_available);
      }
    } catch (err) {
      console.warn("[Parcl] Failed to fetch permits:", err);
    }

    try {
      const { towns } = await getPermitTowns();
      setTowns(towns);
    } catch (err) {
      console.warn("[Parcl] Failed to fetch towns:", err);
    }

    try {
      const coverage = await getCoverageSummary();
      setCoverageSummary(coverage);
    } catch (err) {
      console.warn("[Parcl] Failed to fetch coverage summary:", err);
    }

    try {
      const { towns: townDetails } = await listTowns({ limit: 400 });
      setTownDetails(townDetails);
    } catch (err) {
      console.warn("[Parcl] Failed to fetch town details:", err);
    }
  }, [setCameras, setEarthquakes, setPropertyAgents, setPermits, setTotalPermitsAvailable, setTowns, setCoverageSummary, setTownDetails]);

  useEffect(() => {
    fetchInitialData();
  }, [fetchInitialData]);

  // Periodic data refresh for cameras + earthquakes (every 30s)
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const [cameras, earthquakes] = await Promise.all([
          api.fetchCameras().catch(() => null),
          api.fetchEarthquakes().catch(() => null),
        ]);
        if (cameras) setCameras(cameras);
        if (earthquakes) setEarthquakes(earthquakes);
      } catch {
        // Silent fail
      }
    }, 30000);
    return () => clearInterval(interval);
  }, [setCameras, setEarthquakes]);

  return (
    <div className="w-full h-full overflow-hidden bg-parcl-bg flex flex-col">
      {/* Top: Navigation bar with branding + search + stats */}
      <Safe name="TopBar">
        <TopBar />
      </Safe>

      {/* Main content: Left sidebar + Globe + Right panel */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Listings + Markets + Data Layers */}
        <Safe name="LeftSidebar">
          <LeftSidebar />
        </Safe>

        {/* Center: 3D Globe in contained area */}
        <div className="flex-1 relative overflow-hidden m-1 rounded-lg border border-parcl-border/30">
          <Safe name="Globe" fallback={<GlobeFallback />}>
            <CesiumGlobe />
          </Safe>
          {/* Camera feed overlay — floats above globe when a camera is selected */}
          <Safe name="CameraPreview">
            <CameraPreviewPanel />
          </Safe>
        </div>

        {/* Right: Intel Feed + AI Chat */}
        <Safe name="RightPanel">
          <RightPanel />
        </Safe>
      </div>
    </div>
  );
};

export default App;
