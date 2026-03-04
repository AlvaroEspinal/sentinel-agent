import React, { useEffect, useCallback, Component, ErrorInfo, ReactNode, Suspense, lazy } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import { listPropertyAgents, searchPermits, getPermitTowns, getCoverageSummary, listTowns, getTargetTowns } from "./services/api";
import { useStore } from "./store/useStore";

// ── Lazy load components ──
const Sidebar = lazy(() => import("./components/Layout/Sidebar"));
const LandingPage = lazy(() => import("./components/Dashboard/LandingPage"));
const TownDashboard = lazy(() => import("./components/Town/TownDashboard"));
const PropertySearch = lazy(() => import("./components/RealEstate/PropertySearch"));
const MapOverlay = lazy(() => import("./components/Globe/MapOverlay"));

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

// ── Loading spinner ──
const PageLoader: React.FC = () => (
  <div className="flex-1 flex items-center justify-center bg-slate-950/50">
    <div className="text-center">
      <div className="w-10 h-10 rounded-full border-2 border-blue-500/30 border-t-blue-500 animate-spin mx-auto mb-3" />
      <p className="text-slate-500 text-xs">Loading...</p>
    </div>
  </div>
);

// ── Main Content Router ──
const MainContent: React.FC = () => {
  const activeView = useStore((s) => s.activeView);

  switch (activeView) {
    case "dashboard":
      return (
        <Safe name="LandingPage" fallback={<PageLoader />}>
          <LandingPage />
        </Safe>
      );
    case "town":
      return (
        <Safe name="TownDashboard" fallback={<PageLoader />}>
          <TownDashboard />
        </Safe>
      );
    case "search":
      return (
        <Safe name="PropertySearch" fallback={<PageLoader />}>
          <PropertySearch />
        </Safe>
      );
    default:
      return (
        <Safe name="LandingPage" fallback={<PageLoader />}>
          <LandingPage />
        </Safe>
      );
  }
};

const App: React.FC = () => {
  // Initialize WebSocket connection
  useWebSocket();

  const setPropertyAgents = useStore((s) => s.setPropertyAgents);
  const setPermits = useStore((s) => s.setPermits);
  const setTotalPermitsAvailable = useStore((s) => s.setTotalPermitsAvailable);
  const setTowns = useStore((s) => s.setTowns);
  const setCoverageSummary = useStore((s) => s.setCoverageSummary);
  const setTownDetails = useStore((s) => s.setTownDetails);
  const setTargetTowns = useStore((s) => s.setTargetTowns);

  // Fetch initial data on mount
  const fetchInitialData = useCallback(async () => {
    // Fetch target towns (Realtor MVP — priority)
    try {
      const { towns: targetTowns } = await getTargetTowns();
      setTargetTowns(targetTowns as any);
    } catch (err) {
      console.warn("[Parcl] Failed to fetch target towns:", err);
    }

    // Fetch other data in parallel (non-blocking)
    Promise.all([
      listPropertyAgents().then(({ agents }) => setPropertyAgents(agents)).catch(() => {}),
      searchPermits({ limit: 500 }).then((r) => {
        setPermits(r.permits);
        if ((r as any).total_available) setTotalPermitsAvailable((r as any).total_available);
      }).catch(() => {}),
      getPermitTowns().then(({ towns }) => setTowns(towns)).catch(() => {}),
      getCoverageSummary().then(setCoverageSummary).catch(() => {}),
      listTowns({ limit: 400 }).then(({ towns }) => setTownDetails(towns)).catch(() => {}),
    ]);
  }, [setPropertyAgents, setPermits, setTotalPermitsAvailable, setTowns, setCoverageSummary, setTownDetails, setTargetTowns]);

  useEffect(() => {
    fetchInitialData();
  }, [fetchInitialData]);

  // Handle ESC key to close map overlay
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        const store = useStore.getState();
        if (store.showMapOverlay) {
          store.setShowMapOverlay(false);
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="w-full h-full overflow-hidden bg-slate-950 flex">
      {/* Sidebar */}
      <Safe name="Sidebar">
        <Sidebar />
      </Safe>

      {/* Main Content Area */}
      <main className="flex-1 overflow-hidden bg-slate-950">
        <MainContent />
      </main>

      {/* Map Overlay (Globe as modal) */}
      <Safe name="MapOverlay">
        <MapOverlay />
      </Safe>
    </div>
  );
};

export default App;
