import { create } from "zustand";
import type {
  ViewMode,
  LeftPanelTab,
  CameraTarget,
  Property,
  Permit,
  Town,
  ChatMessage,
  PropertyMonitorAgent,
  AgentFinding,
  CoverageSummary,
  TownDetail,
  TrackedListing,
  AppView,
  TownConfig,
  TownDashboardData,
  ParcelSearchResult,
} from "../types";

// ─── Market POI Database ───────────────────────────────────────────────────
// Real estate markets with curated neighborhoods.
export const MARKETS: Record<
  string,
  { id: string; name: string; lat: number; lon: number; altitude?: number }[]
> = {
  Boston: [
    { id: "bos1", name: "Back Bay", lat: 42.3503, lon: -71.081 },
    { id: "bos2", name: "Seaport District", lat: 42.3467, lon: -71.041 },
    { id: "bos3", name: "Cambridge", lat: 42.3736, lon: -71.1097 },
    { id: "bos4", name: "Brookline", lat: 42.3318, lon: -71.1212 },
    { id: "bos5", name: "Newton", lat: 42.337, lon: -71.2092 },
  ],
  Miami: [
    { id: "mi1", name: "Brickell", lat: 25.7617, lon: -80.1918 },
    { id: "mi2", name: "Wynwood", lat: 25.805, lon: -80.199 },
    { id: "mi3", name: "Coral Gables", lat: 25.7215, lon: -80.2684 },
    { id: "mi4", name: "Miami Beach", lat: 25.7907, lon: -80.13 },
  ],
  Austin: [
    { id: "au1", name: "Downtown", lat: 30.2672, lon: -97.7431 },
    { id: "au2", name: "East Austin", lat: 30.26, lon: -97.72 },
    { id: "au3", name: "South Congress", lat: 30.246, lon: -97.7494 },
    { id: "au4", name: "Mueller", lat: 30.298, lon: -97.705 },
  ],
  "New York": [
    { id: "ny1", name: "Manhattan", lat: 40.7831, lon: -73.9712 },
    { id: "ny2", name: "Brooklyn Heights", lat: 40.696, lon: -73.9936 },
    { id: "ny3", name: "Long Island City", lat: 40.7425, lon: -73.9235 },
    { id: "ny4", name: "Jersey City", lat: 40.7178, lon: -74.0431 },
  ],
  "Los Angeles": [
    { id: "la1", name: "Beverly Hills", lat: 34.0736, lon: -118.4004 },
    { id: "la2", name: "Santa Monica", lat: 34.0195, lon: -118.4912 },
    { id: "la3", name: "Downtown LA", lat: 34.0407, lon: -118.2468 },
    { id: "la4", name: "Hollywood Hills", lat: 34.1341, lon: -118.3215 },
  ],
};

export const MARKET_NAMES = Object.keys(MARKETS);

// ─── Store State ───────────────────────────────────────────────────────────
interface ParclState {
  // Real estate data
  selectedProperty: Property | null;
  propertySearchResults: Property[];
  permits: Permit[];
  totalPermitsAvailable: number;
  towns: Town[];
  activeTown: string | null; // town id or null for "all"
  coverageSummary: CoverageSummary | null;
  townDetails: TownDetail[];
  chatMessages: ChatMessage[];
  propertyAgents: PropertyMonitorAgent[];
  agentFindings: AgentFinding[];

  // Tracked listings
  trackedListings: TrackedListing[];
  selectedListingId: string | null;

  // Realtor MVP — View management
  activeView: AppView;
  activeTownId: string | null;
  targetTowns: TownConfig[];
  townDashboardData: TownDashboardData | null;
  townDashboardLoading: boolean;
  parcelSearchResults: ParcelSearchResult[];
  parcelSearchLoading: boolean;
  showMapOverlay: boolean;
  selectedParcel: ParcelSearchResult | null;

  // UI state
  viewMode: ViewMode;
  isConnected: boolean;
  leftPanelOpen: boolean;
  rightPanelOpen: boolean;
  leftPanelTab: LeftPanelTab;
  showPermits: boolean;
  showProperties: boolean;
  showFloodZones: boolean;
  showParcels: boolean;
  showWetlands: boolean;
  showConservation: boolean;
  showZoning: boolean;
  showMepa: boolean;
  showTaxDelinquency: boolean;
  searchQuery: string;
  isSearching: boolean;
  isChatLoading: boolean;

  // Navigation
  activeCity: string;
  activePOIIndex: number;
  cameraTarget: CameraTarget | null;

  // ── Actions: Real estate data ────────────────────────────────────────────
  setSelectedProperty: (property: Property | null) => void;
  setPropertySearchResults: (results: Property[]) => void;
  setPermits: (permits: Permit[]) => void;
  setTotalPermitsAvailable: (count: number) => void;
  setTowns: (towns: Town[]) => void;
  setActiveTown: (townId: string | null) => void;
  setCoverageSummary: (summary: CoverageSummary) => void;
  setTownDetails: (towns: TownDetail[]) => void;
  setPropertyAgents: (agents: PropertyMonitorAgent[]) => void;
  addAgentFinding: (finding: AgentFinding) => void;
  setAgentFindings: (findings: AgentFinding[]) => void;

  // ── Actions: Chat ────────────────────────────────────────────────────────
  addChatMessage: (msg: ChatMessage) => void;
  clearChat: () => void;
  setIsChatLoading: (loading: boolean) => void;

  // ── Actions: UI toggles ──────────────────────────────────────────────────
  setViewMode: (mode: ViewMode) => void;
  setConnected: (connected: boolean) => void;
  toggleLeftPanel: () => void;
  toggleRightPanel: () => void;
  setLeftPanelTab: (tab: LeftPanelTab) => void;
  setLeftPanelOpen: (open: boolean) => void;
  setRightPanelOpen: (open: boolean) => void;
  togglePermits: () => void;
  toggleProperties: () => void;
  toggleFloodZones: () => void;
  toggleParcels: () => void;
  toggleWetlands: () => void;
  toggleConservation: () => void;
  toggleZoning: () => void;
  toggleMepa: () => void;
  toggleTaxDelinquency: () => void;
  setSearchQuery: (query: string) => void;
  setIsSearching: (searching: boolean) => void;

  // ── Actions: Navigation ──────────────────────────────────────────────────
  setActiveCity: (city: string) => void;
  navigateToPOI: (index: number) => void;
  nextPOI: () => void;
  prevPOI: () => void;

  // ── Actions: Camera ──────────────────────────────────────────────────────
  flyToLocation: (target: CameraTarget) => void;

  // ── Actions: Tracked Listings ───────────────────────────────────────────
  addTrackedListing: (listing: TrackedListing) => void;
  removeTrackedListing: (id: string) => void;
  updateTrackedListing: (id: string, updates: Partial<TrackedListing>) => void;
  selectListing: (id: string) => void;

  // ── Actions: View management (Realtor MVP) ─────────────────────────────
  setActiveView: (view: AppView) => void;
  setActiveTownId: (townId: string | null) => void;
  setTargetTowns: (towns: TownConfig[]) => void;
  setTownDashboardData: (data: TownDashboardData | null) => void;
  setTownDashboardLoading: (loading: boolean) => void;
  setParcelSearchResults: (results: ParcelSearchResult[]) => void;
  setParcelSearchLoading: (loading: boolean) => void;
  setShowMapOverlay: (show: boolean) => void;
  setSelectedParcel: (parcel: ParcelSearchResult | null) => void;
  navigateToTown: (townId: string) => void;
  navigateToDashboard: () => void;
  navigateToProperty: (parcel: ParcelSearchResult) => void;

  // ── Actions: Compound ────────────────────────────────────────────────────
  selectProperty: (property: Property) => void;
}

// ─── Store Implementation ──────────────────────────────────────────────────
export const useStore = create<ParclState>((set, get) => ({
  // ── Initial real estate data ─────────────────────────────────────────────
  selectedProperty: null,
  propertySearchResults: [],
  permits: [],
  totalPermitsAvailable: 0,
  towns: [],
  activeTown: null,
  coverageSummary: null,
  townDetails: [],
  chatMessages: [],
  propertyAgents: [],
  agentFindings: [],

  // ── Initial tracked listings ────────────────────────────────────────────
  trackedListings: JSON.parse(localStorage.getItem("parcl-tracked-listings") || "[]"),
  selectedListingId: null,

  // ── Realtor MVP — Initial view state ────────────────────────────────────
  activeView: "dashboard" as AppView,
  activeTownId: null,
  targetTowns: [],
  townDashboardData: null,
  townDashboardLoading: false,
  parcelSearchResults: [],
  parcelSearchLoading: false,
  showMapOverlay: false,
  selectedParcel: null,

  // ── Initial UI state ─────────────────────────────────────────────────────
  viewMode: "standard",
  isConnected: false,
  leftPanelOpen: false,
  rightPanelOpen: true,
  leftPanelTab: "summary",
  showPermits: true,
  showProperties: true,
  showFloodZones: false,
  showParcels: false,
  showWetlands: false,
  showConservation: false,
  showZoning: false,
  showMepa: false,
  showTaxDelinquency: false,
  searchQuery: "",
  isSearching: false,
  isChatLoading: false,

  // ── Initial navigation ───────────────────────────────────────────────────
  activeCity: "Boston",
  activePOIIndex: 0,
  cameraTarget: null,

  // ── Real estate data actions ─────────────────────────────────────────────
  setSelectedProperty: (property) => set({ selectedProperty: property }),

  setPropertySearchResults: (results) =>
    set({ propertySearchResults: results }),

  setPermits: (permits) => set({ permits }),

  setTotalPermitsAvailable: (count) => set({ totalPermitsAvailable: count }),

  setTowns: (towns) => set({ towns }),

  setActiveTown: (townId) => set({ activeTown: townId }),

  setCoverageSummary: (summary) => set({ coverageSummary: summary }),
  setTownDetails: (towns) => set({ townDetails: towns }),

  setPropertyAgents: (agents) => set({ propertyAgents: agents }),

  addAgentFinding: (finding) =>
    set((state) => {
      const exists = state.agentFindings.some((f) => f.id === finding.id);
      if (exists) return state;
      return { agentFindings: [finding, ...state.agentFindings].slice(0, 500) };
    }),

  setAgentFindings: (findings) => set({ agentFindings: findings }),

  // ── Chat actions ─────────────────────────────────────────────────────────
  addChatMessage: (msg) =>
    set((state) => ({ chatMessages: [...state.chatMessages, msg] })),

  clearChat: () => set({ chatMessages: [] }),

  setIsChatLoading: (loading) => set({ isChatLoading: loading }),

  // ── UI actions ───────────────────────────────────────────────────────────
  setViewMode: (mode) => set({ viewMode: mode }),

  setConnected: (connected) => set({ isConnected: connected }),

  toggleLeftPanel: () =>
    set((state) => ({ leftPanelOpen: !state.leftPanelOpen })),

  toggleRightPanel: () =>
    set((state) => ({ rightPanelOpen: !state.rightPanelOpen })),

  setLeftPanelTab: (tab) => set({ leftPanelTab: tab }),

  setLeftPanelOpen: (open) => set({ leftPanelOpen: open }),

  setRightPanelOpen: (open) => set({ rightPanelOpen: open }),

  togglePermits: () =>
    set((state) => ({ showPermits: !state.showPermits })),

  toggleProperties: () =>
    set((state) => ({ showProperties: !state.showProperties })),

  toggleFloodZones: () =>
    set((state) => ({ showFloodZones: !state.showFloodZones })),

  toggleParcels: () =>
    set((state) => ({ showParcels: !state.showParcels })),

  toggleWetlands: () =>
    set((state) => ({ showWetlands: !state.showWetlands })),

  toggleConservation: () =>
    set((state) => ({ showConservation: !state.showConservation })),

  toggleZoning: () =>
    set((state) => ({ showZoning: !state.showZoning })),

  toggleMepa: () =>
    set((state) => ({ showMepa: !state.showMepa })),

  toggleTaxDelinquency: () =>
    set((state) => ({ showTaxDelinquency: !state.showTaxDelinquency })),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setIsSearching: (searching) => set({ isSearching: searching }),

  // ── Navigation actions ───────────────────────────────────────────────────
  setActiveCity: (city) => {
    const pois = MARKETS[city];
    if (!pois || pois.length === 0) return;
    set({ activeCity: city, activePOIIndex: 0 });
    const poi = pois[0];
    get().flyToLocation({
      lat: poi.lat,
      lon: poi.lon,
      altitude: poi.altitude ?? 2000,
      heading: 0,
      pitch: -35,
    });
  },

  navigateToPOI: (index) => {
    const { activeCity } = get();
    const pois = MARKETS[activeCity];
    if (!pois || index < 0 || index >= pois.length) return;
    set({ activePOIIndex: index });
    const poi = pois[index];
    get().flyToLocation({
      lat: poi.lat,
      lon: poi.lon,
      altitude: poi.altitude ?? 2000,
      heading: 0,
      pitch: -35,
    });
  },

  nextPOI: () => {
    const { activeCity, activePOIIndex } = get();
    const pois = MARKETS[activeCity];
    if (!pois) return;
    const next = (activePOIIndex + 1) % pois.length;
    get().navigateToPOI(next);
  },

  prevPOI: () => {
    const { activeCity, activePOIIndex } = get();
    const pois = MARKETS[activeCity];
    if (!pois) return;
    const prev = (activePOIIndex - 1 + pois.length) % pois.length;
    get().navigateToPOI(prev);
  },

  // ── Camera actions ───────────────────────────────────────────────────────
  flyToLocation: (target) => set({ cameraTarget: target }),

  // ── Tracked listing actions ──────────────────────────────────────────────
  addTrackedListing: (listing) => {
    set((state) => {
      const updated = [...state.trackedListings, listing];
      localStorage.setItem("parcl-tracked-listings", JSON.stringify(updated));
      // Only fly to location if coordinates are valid (not 0,0 / Null Island)
      const hasValidCoords = listing.latitude !== 0 || listing.longitude !== 0;
      return {
        trackedListings: updated,
        selectedListingId: listing.id,
        ...(hasValidCoords
          ? {
            cameraTarget: {
              lat: listing.latitude,
              lon: listing.longitude,
              altitude: 1000,
              heading: 0,
              pitch: -35,
            },
          }
          : {}),
      };
    });
  },
  removeTrackedListing: (id) => {
    set((state) => {
      const updated = state.trackedListings.filter((l) => l.id !== id);
      localStorage.setItem("parcl-tracked-listings", JSON.stringify(updated));
      return {
        trackedListings: updated,
        selectedListingId: state.selectedListingId === id ? null : state.selectedListingId,
      };
    });
  },
  updateTrackedListing: (id, updates) => {
    set((state) => {
      const updated = state.trackedListings.map((l) =>
        l.id === id ? { ...l, ...updates } : l
      );
      localStorage.setItem("parcl-tracked-listings", JSON.stringify(updated));
      return { trackedListings: updated };
    });
  },
  selectListing: (id) => {
    if (!id) {
      set({ selectedListingId: null });
      return;
    }
    const listing = get().trackedListings.find((l) => l.id === id);
    if (listing) {
      const hasValidCoords = listing.latitude !== 0 || listing.longitude !== 0;
      set({
        selectedListingId: id,
        ...(hasValidCoords
          ? {
            cameraTarget: {
              lat: listing.latitude,
              lon: listing.longitude,
              altitude: 1000,
              heading: 0,
              pitch: -35,
            },
          }
          : {}),
      });
    }
  },

  // ── View management actions (Realtor MVP) ──────────────────────────────
  setActiveView: (view) => set({ activeView: view }),
  setActiveTownId: (townId) => set({ activeTownId: townId }),
  setTargetTowns: (towns) => set({ targetTowns: towns }),
  setTownDashboardData: (data) => set({ townDashboardData: data }),
  setTownDashboardLoading: (loading) => set({ townDashboardLoading: loading }),
  setParcelSearchResults: (results) => set({ parcelSearchResults: results }),
  setParcelSearchLoading: (loading) => set({ parcelSearchLoading: loading }),
  setShowMapOverlay: (show) => set({ showMapOverlay: show }),
  setSelectedParcel: (parcel) => set({ selectedParcel: parcel }),

  navigateToTown: (townId) => {
    set({ activeView: "town" as AppView, activeTownId: townId, townDashboardData: null, townDashboardLoading: true });
  },

  navigateToDashboard: () => {
    set({ activeView: "dashboard" as AppView, activeTownId: null, townDashboardData: null });
  },

  navigateToProperty: (parcel) => {
    set({ activeView: "property" as AppView, selectedParcel: parcel });
  },

  // ── Compound actions ─────────────────────────────────────────────────────
  selectProperty: (property) => {
    const hasValidCoords = property.latitude !== 0 || property.longitude !== 0;
    set({
      selectedProperty: property,
      leftPanelOpen: true,
      leftPanelTab: "summary",
      ...(hasValidCoords
        ? {
          cameraTarget: {
            lat: property.latitude,
            lon: property.longitude,
            altitude: 1000,
            heading: 0,
            pitch: -35,
          },
        }
        : {}),
    });
  },
}));

// Expose store for debugging / programmatic access
if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).__parclStore = useStore;
}
