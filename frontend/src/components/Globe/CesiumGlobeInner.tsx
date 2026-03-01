import React, { useRef, useEffect, useState } from "react";
import "cesium/Build/Cesium/Widgets/widgets.css";
import {
  Ion,
  Viewer as CesiumViewer,
  Camera,
  Rectangle,
  SceneMode,
  Color,
  Cartesian2,
  Cartesian3,
  Math as CesiumMath,
  NearFarScalar,
  VerticalOrigin,
  HorizontalOrigin,
  LabelStyle,
  DistanceDisplayCondition,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  Cesium3DTileset,
  ArcGisMapServerImageryProvider,
  ImageryLayer,
  ColorMaterialProperty,
  PolygonHierarchy,
  HeightReference,
  ClassificationType,
  CustomDataSource,
} from "cesium";
import { getPermitPins, type PermitPin } from "../../services/api";
import { useStore, MARKET_NAMES } from "../../store/useStore";
import ShaderOverlay from "./ShaderOverlay";

// ─── Set the Ion access token ───────────────────────────────────────────────
const TOKEN = import.meta.env.VITE_CESIUM_ION_ACCESS_TOKEN || "";
if (TOKEN) {
  Ion.defaultAccessToken = TOKEN;
}

// ─── Constants ──────────────────────────────────────────────────────────────
const SPACE_BG = new Color(0.0, 0.0, 0.02, 1.0);
const GLOBE_BASE = new Color(0.04, 0.06, 0.12, 1.0);

// ─── SVG Icon Generators ────────────────────────────────────────────────────

function cameraSvg(status: string): string {
  const colors: Record<string, { f: string; s: string }> = {
    online: { f: "#a78bfa", s: "#5b21b6" },
    offline: { f: "#6b7280", s: "#374151" },
    degraded: { f: "#fbbf24", s: "#92400e" },
  };
  const c = colors[status] || colors.online;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">
    <rect x="3" y="5" width="16" height="10" rx="2" fill="${c.f}" stroke="${c.s}" stroke-width="1.2" opacity="0.9"/>
    <circle cx="11" cy="10" r="3" fill="white" opacity="0.7"/>
    <circle cx="11" cy="10" r="1.2" fill="${c.s}" opacity="0.9"/>
    <rect x="8" y="15" width="6" height="2" rx="0.5" fill="${c.s}" opacity="0.6"/>
  </svg>`;
  return `data:image/svg+xml;base64,${btoa(svg)}`;
}

// Earthquake icon — concentric rings sized by magnitude
function createEarthquakeSvg(magnitude: number): string {
  const size = Math.min(Math.max(magnitude * 4, 12), 40);
  const half = size / 2;
  const colors: Record<string, { f: string; s: string }> = {
    major: { f: "#ef4444", s: "#991b1b" },
    strong: { f: "#f97316", s: "#c2410c" },
    moderate: { f: "#fbbf24", s: "#92400e" },
    light: { f: "#facc15", s: "#a16207" },
    minor: { f: "#a3e635", s: "#4d7c0f" },
    micro: { f: "#6b7280", s: "#374151" },
  };
  const severity = magnitude >= 7 ? "major" : magnitude >= 6 ? "strong" : magnitude >= 5 ? "moderate" : magnitude >= 4 ? "light" : magnitude >= 3 ? "minor" : "micro";
  const c = colors[severity];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <circle cx="${half}" cy="${half}" r="${half - 1}" fill="none" stroke="${c.s}" stroke-width="1" opacity="0.4"/>
    <circle cx="${half}" cy="${half}" r="${half * 0.6}" fill="none" stroke="${c.f}" stroke-width="1" opacity="0.6"/>
    <circle cx="${half}" cy="${half}" r="${half * 0.3}" fill="${c.f}" stroke="${c.s}" stroke-width="0.5" opacity="0.9"/>
  </svg>`;
  return `data:image/svg+xml;base64,${btoa(svg)}`;
}

// Permit icon — document with lines, colored by status
const PERMIT_TYPE_ICON_COLORS: Record<string, { fill: string; stroke: string }> = {
  Building: { fill: "#60a5fa", stroke: "#1d4ed8" },
  Electrical: { fill: "#fbbf24", stroke: "#92400e" },
  Plumbing: { fill: "#4ade80", stroke: "#166534" },
  Gas: { fill: "#f97316", stroke: "#c2410c" },
  Mechanical: { fill: "#a78bfa", stroke: "#5b21b6" },
  Fire: { fill: "#ef4444", stroke: "#991b1b" },
  Demolition: { fill: "#f87171", stroke: "#b91c1c" },
  Certificate: { fill: "#6b7280", stroke: "#374151" },
};

function createPermitSvg(status: string): string {
  const colors = PERMIT_TYPE_ICON_COLORS[status] || { fill: "#6b7280", stroke: "#374151" };
  return `data:image/svg+xml,${encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">
      <rect x="3" y="2" width="14" height="16" rx="2" fill="${colors.fill}" stroke="${colors.stroke}" stroke-width="1.5"/>
      <line x1="6" y1="7" x2="14" y2="7" stroke="${colors.stroke}" stroke-width="1"/>
      <line x1="6" y1="10" x2="14" y2="10" stroke="${colors.stroke}" stroke-width="1"/>
      <line x1="6" y1="13" x2="11" y2="13" stroke="${colors.stroke}" stroke-width="1"/>
    </svg>
  `)}`;
}

// Property icon — house shape, colored by property type
const PROPERTY_TYPE_COLORS: Record<string, string> = {
  SINGLE_FAMILY: "#2563eb",
  MULTI_FAMILY: "#7c3aed",
  CONDO: "#0891b2",
  TOWNHOUSE: "#059669",
  COMMERCIAL: "#d97706",
  LAND: "#65a30d",
  MIXED_USE: "#e11d48",
  OTHER: "#6b7280",
};

function createPropertySvg(propertyType: string): string {
  const color = PROPERTY_TYPE_COLORS[propertyType] || "#6b7280";
  return `data:image/svg+xml,${encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">
      <path d="M11 2 L20 10 L17 10 L17 19 L13 19 L13 14 L9 14 L9 19 L5 19 L5 10 L2 10 Z"
            fill="${color}" stroke="${color === '#2563eb' ? '#1d4ed8' : '#374151'}" stroke-width="1"/>
    </svg>
  `)}`;
}

// Cluster circle — numbered circle for grouped pins
function createClusterSvg(count: number): string {
  const size = count > 50 ? 40 : count > 10 ? 34 : 28;
  const bg = count > 50 ? "#ef4444" : count > 10 ? "#f97316" : "#3b82f6";
  return `data:image/svg+xml,${encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
      <circle cx="${size / 2}" cy="${size / 2}" r="${size / 2 - 1}" fill="${bg}" stroke="white" stroke-width="2"/>
      <text x="${size / 2}" y="${size / 2 + 1}" text-anchor="middle" dominant-baseline="central"
            font-family="monospace" font-size="${size > 34 ? 14 : 12}" font-weight="bold" fill="white">
        ${count > 999 ? `${Math.round(count / 1000)}k` : count}
      </text>
    </svg>
  `)}`;
}

// Grid-based clustering: group pins by grid cell at the current zoom level
interface Cluster {
  lat: number;
  lon: number;
  pins: PermitPin[];
}

function clusterPins(pins: PermitPin[], gridSizeDeg: number): Cluster[] {
  const cells = new Map<string, PermitPin[]>();
  for (const pin of pins) {
    const cx = Math.floor(pin.lon / gridSizeDeg);
    const cy = Math.floor(pin.lat / gridSizeDeg);
    const key = `${cx},${cy}`;
    const arr = cells.get(key);
    if (arr) arr.push(pin);
    else cells.set(key, [pin]);
  }
  const clusters: Cluster[] = [];
  for (const group of cells.values()) {
    const lat = group.reduce((s, p) => s + p.lat, 0) / group.length;
    const lon = group.reduce((s, p) => s + p.lon, 0) / group.length;
    clusters.push({ lat, lon, pins: group });
  }
  return clusters;
}

// ─── Imperative Cesium Globe Component ──────────────────────────────────────
const CesiumGlobeInner: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<CesiumViewer | null>(null);
  const viewMode = useStore((s) => s.viewMode);
  const cameras = useStore((s) => s.cameras);
  const earthquakes = useStore((s) => s.earthquakes);
  const permits = useStore((s) => s.permits);
  const propertySearchResults = useStore((s) => s.propertySearchResults);
  const showCameras = useStore((s) => s.showCameras);
  const showEarthquakes = useStore((s) => s.showEarthquakes);
  const showPermits = useStore((s) => s.showPermits);
  const showProperties = useStore((s) => s.showProperties);
  const showFloodZones = useStore((s) => s.showFloodZones);
  const showParcels = useStore((s) => s.showParcels);
  const selectedProperty = useStore((s) => s.selectedProperty);
  const selectCamera = useStore((s) => s.selectCamera);
  const selectProperty = useStore((s) => s.selectProperty);
  const cameraTarget = useStore((s) => s.cameraTarget);
  const navigateToPOI = useStore((s) => s.navigateToPOI);
  const nextPOI = useStore((s) => s.nextPOI);
  const prevPOI = useStore((s) => s.prevPOI);
  const setActiveCity = useStore((s) => s.setActiveCity);
  const [ready, setReady] = useState(false);
  const floodLayerRef = useRef<ImageryLayer | null>(null);
  const parcelLayerRef = useRef<ImageryLayer | null>(null);
  const parcelEntityIdsRef = useRef<string[]>([]);
  const vpDataSourceRef = useRef<CustomDataSource | null>(null);
  const vpFetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const vpLastBboxRef = useRef<string>("");

  // ── Create Viewer on mount ──────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    if (viewerRef.current) return;

    let resizeObserver: ResizeObserver | null = null;

    // Center the default home view on North America (prevents globe sinking when zoomed out)
    Camera.DEFAULT_VIEW_RECTANGLE = Rectangle.fromDegrees(-130, 20, -60, 55);

    try {
      const viewer = new CesiumViewer(containerRef.current, {
        animation: false,
        baseLayerPicker: false,
        fullscreenButton: false,
        vrButton: false,
        geocoder: false,
        homeButton: false,
        infoBox: false,
        sceneModePicker: false,
        selectionIndicator: false,
        timeline: false,
        navigationHelpButton: false,
        navigationInstructionsInitiallyVisible: false,
        sceneMode: SceneMode.SCENE3D,
        requestRenderMode: false,
        maximumRenderTimeChange: Infinity,
      });

      // Scene config
      const scene = viewer.scene;
      scene.backgroundColor = SPACE_BG;
      scene.screenSpaceCameraController.minimumZoomDistance = 250;
      scene.screenSpaceCameraController.maximumZoomDistance = 25_000_000;
      scene.fog.enabled = true;
      scene.fog.density = 0.0002;

      // Recover from render errors
      scene.renderError.addEventListener((_scene: any, error: any) => {
        console.warn("[CesiumGlobe] Render error caught, recovering:", error?.message);
        try {
          viewer.camera.cancelFlight();
          viewer.camera.setView({
            destination: Cartesian3.fromDegrees(-71.06, 42.36, 15_000_000),
            orientation: { heading: 0, pitch: CesiumMath.toRadians(-89), roll: 0 },
          });
        } catch (e) {
          console.error("[CesiumGlobe] Recovery failed:", e);
        }
      });

      // Globe config
      const globe = scene.globe;
      globe.baseColor = GLOBE_BASE;
      globe.showGroundAtmosphere = true;
      globe.enableLighting = false;

      // ── Google Photorealistic 3D Tiles ──────────────────────────────────
      // Asset ID 2275207 is Google's Photorealistic 3D Tiles on Cesium Ion
      try {
        Cesium3DTileset.fromIonAssetId(2275207).then((tileset) => {
          if (!viewer.isDestroyed()) {
            viewer.scene.primitives.add(tileset);
            console.log("[CesiumGlobe] Google Photorealistic 3D Tiles loaded");
          }
        }).catch((err) => {
          console.warn("[CesiumGlobe] Google 3D Tiles not available:", err?.message);
        });
      } catch (err) {
        console.warn("[CesiumGlobe] Failed to load Google 3D Tiles:", err);
      }

      // Atmosphere
      if (scene.skyAtmosphere) {
        scene.skyAtmosphere.show = true;
        scene.skyAtmosphere.brightnessShift = -0.15;
        scene.skyAtmosphere.saturationShift = -0.1;
        scene.skyAtmosphere.hueShift = 0.0;
      }
      if (scene.skyBox) {
        scene.skyBox.show = false;
      }

      // Initial camera — centered on Boston/New England
      viewer.camera.setView({
        destination: Cartesian3.fromDegrees(-71.06, 42.36, 15_000_000),
        orientation: {
          heading: CesiumMath.toRadians(0),
          pitch: CesiumMath.toRadians(-89),
          roll: 0,
        },
      });

      // Hide credits
      const creditContainer = viewer.cesiumWidget.creditContainer as HTMLElement;
      if (creditContainer) {
        creditContainer.style.display = "none";
      }

      // Handle container resize for contained layout
      resizeObserver = new ResizeObserver(() => {
        if (viewerRef.current && !viewerRef.current.isDestroyed()) {
          viewerRef.current.resize();
        }
      });
      resizeObserver.observe(containerRef.current);

      viewerRef.current = viewer;
      (window as any).__cesiumViewer = viewer;
      setReady(true);
      console.log("[CesiumGlobe] Viewer created successfully");
    } catch (err) {
      console.error("[CesiumGlobe] Failed to create Viewer:", err);
    }

    return () => {
      if (resizeObserver) resizeObserver.disconnect();
      if (viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.destroy();
        viewerRef.current = null;
      }
    };
  }, []);

  // ── Keyboard hotkeys for POI navigation ───────────────────────────────
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if user is typing in an input
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      const POI_KEYS = ["q", "w", "e", "r", "t"];
      const key = e.key.toLowerCase();

      if (POI_KEYS.includes(key)) {
        e.preventDefault();
        navigateToPOI(POI_KEYS.indexOf(key));
      } else if (key === "]" || key === ".") {
        e.preventDefault();
        nextPOI();
      } else if (key === "[" || key === ",") {
        e.preventDefault();
        prevPOI();
      } else if (key >= "1" && key <= "9") {
        // Number keys switch cities / markets
        const idx = parseInt(key) - 1;
        if (idx < MARKET_NAMES.length) {
          e.preventDefault();
          setActiveCity(MARKET_NAMES[idx]);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [navigateToPOI, nextPOI, prevPOI, setActiveCity]);

  // ── Camera fly-to when cameraTarget changes ─────────────────────────────
  useEffect(() => {
    if (!cameraTarget || !viewerRef.current) return;
    const viewer = viewerRef.current;
    if (viewer.isDestroyed()) return;
    viewer.camera.flyTo({
      destination: Cartesian3.fromDegrees(
        cameraTarget.lon,
        cameraTarget.lat,
        cameraTarget.altitude
      ),
      orientation: {
        heading: CesiumMath.toRadians(cameraTarget.heading),
        pitch: CesiumMath.toRadians(cameraTarget.pitch),
        roll: 0,
      },
      duration: 2.0,
    });
  }, [cameraTarget]);

  // ── Entity click handler (cameras, permits, properties) ────────────────
  useEffect(() => {
    if (!viewerRef.current || !ready) return;
    const viewer = viewerRef.current;
    if (viewer.isDestroyed()) return;

    const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((click: any) => {
      const picked = viewer.scene.pick(click.position);
      if (picked && picked.id && typeof picked.id.id === "string") {
        const entityId: string = picked.id.id;

        // Camera click
        if (entityId.startsWith("camera_")) {
          const camId = entityId.replace("camera_", "");
          const cam = cameras?.find((c) => String(c.id) === camId);
          if (cam) {
            selectCamera(cam);
          }
        }

        // Property click
        if (entityId.startsWith("property_")) {
          const propId = entityId.replace("property_", "");
          const prop = propertySearchResults?.find((p) => String(p.id) === propId);
          if (prop) {
            selectProperty(prop);
          }
        }

        // Viewport permit pin click — create virtual property and select it
        if (entityId.startsWith("vpin_")) {
          const entity = vpDataSourceRef.current?.entities.getById(entityId);
          if (entity) {
            const pos = entity.position?.getValue(viewer.clock.currentTime);
            if (pos) {
              const carto = viewer.scene.globe.ellipsoid.cartesianToCartographic(pos);
              const lat = CesiumMath.toDegrees(carto.latitude);
              const lon = CesiumMath.toDegrees(carto.longitude);
              const label = entity.label?.text?.getValue(viewer.clock.currentTime) || "";
              selectProperty({
                id: entityId.replace("vpin_", ""),
                address: label,
                latitude: lat,
                longitude: lon,
                property_type: "OTHER",
              } as any);
            }
          }
        }

        // Cluster click — zoom in
        if (entityId.startsWith("vcluster_")) {
          const entity = vpDataSourceRef.current?.entities.getById(entityId);
          if (entity) {
            const pos = entity.position?.getValue(viewer.clock.currentTime);
            if (pos) {
              const carto = viewer.scene.globe.ellipsoid.cartesianToCartographic(pos);
              const currentHeight = viewer.camera.positionCartographic.height;
              viewer.camera.flyTo({
                destination: Cartesian3.fromDegrees(
                  CesiumMath.toDegrees(carto.longitude),
                  CesiumMath.toDegrees(carto.latitude),
                  currentHeight * 0.4
                ),
                duration: 1.0,
              });
            }
          }
        }
      }
    }, ScreenSpaceEventType.LEFT_CLICK);

    return () => handler.destroy();
  }, [ready, cameras, propertySearchResults, selectCamera, selectProperty]);

  // ── Sync entity data to the viewer ──────────────────────────────────────
  useEffect(() => {
    if (!viewerRef.current || !ready) return;
    const viewer = viewerRef.current;
    if (viewer.isDestroyed()) return;
    const entities = viewer.entities;
    entities.removeAll();
    // Clear parcel IDs since removeAll wiped them — parcel effect will re-add
    parcelEntityIdsRef.current = [];

    // ── Earthquakes (USGS) ───────────────────────────────────────────────
    if (showEarthquakes && earthquakes) {
      earthquakes.forEach((eq) => {
        if (!eq.latitude || !eq.longitude) return;
        entities.add({
          position: Cartesian3.fromDegrees(eq.longitude, eq.latitude, 0),
          billboard: {
            image: createEarthquakeSvg(eq.magnitude || 1),
            scale: 1.0,
            verticalOrigin: VerticalOrigin.CENTER,
            horizontalOrigin: HorizontalOrigin.CENTER,
            distanceDisplayCondition: new DistanceDisplayCondition(0, 2e7),
          },
          label: {
            text: `M${eq.magnitude?.toFixed(1)}`,
            font: "10px monospace",
            fillColor: Color.fromCssColorString(eq.magnitude >= 5 ? "#ef4444" : eq.magnitude >= 3 ? "#fbbf24" : "#a3e635"),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new Cartesian2(14, 0),
            scale: 0.8,
            verticalOrigin: VerticalOrigin.CENTER,
            horizontalOrigin: HorizontalOrigin.LEFT,
            distanceDisplayCondition: new DistanceDisplayCondition(0, 8e6),
            translucencyByDistance: new NearFarScalar(1e5, 1.0, 8e6, 0.0),
          },
          name: `Earthquake M${eq.magnitude}`,
          description: `Magnitude: ${eq.magnitude} ${eq.magnitude_type}<br/>
            Location: ${eq.place}<br/>
            Depth: ${eq.depth_km} km<br/>
            Severity: ${eq.severity}<br/>
            Tsunami: ${eq.tsunami ? "YES" : "No"}<br/>
            Time: ${new Date(eq.time).toUTCString()}`,
        });
      });
    }

    // ── Cameras ──────────────────────────────────────────────────────────
    if (showCameras && cameras) {
      cameras.forEach((cam) => {
        if (!cam.latitude || !cam.longitude) return;
        entities.add({
          id: `camera_${cam.id}`,
          position: Cartesian3.fromDegrees(cam.longitude, cam.latitude, 500),
          billboard: {
            image: cameraSvg(cam.status),
            scale: 1.0,
            verticalOrigin: VerticalOrigin.CENTER,
            horizontalOrigin: HorizontalOrigin.CENTER,
            translucencyByDistance: new NearFarScalar(1e4, 1.0, 8e6, 0.4),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 1e7),
          },
          label: {
            text: cam.name || "",
            font: "9px monospace",
            fillColor: Color.fromCssColorString("#a78bfa"),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new Cartesian2(14, -4),
            scale: 0.8,
            verticalOrigin: VerticalOrigin.CENTER,
            horizontalOrigin: HorizontalOrigin.LEFT,
            distanceDisplayCondition: new DistanceDisplayCondition(0, 2e6),
            translucencyByDistance: new NearFarScalar(5e4, 1.0, 2e6, 0.0),
          },
          name: cam.name,
          description: `Source: ${cam.source}<br/>
            Status: ${cam.status}<br/>
            Category: ${cam.category}<br/>
            Region: ${cam.region}, ${cam.country}`,
        });
      });
    }

    // ── Permits ──────────────────────────────────────────────────────────
    if (showPermits && permits) {
      permits.forEach((permit) => {
        if (!permit.latitude || !permit.longitude) return;
        entities.add({
          id: `permit_${permit.id}`,
          position: Cartesian3.fromDegrees(permit.longitude, permit.latitude, 200),
          billboard: {
            image: createPermitSvg(permit.status),
            scale: 1.0,
            verticalOrigin: VerticalOrigin.CENTER,
            horizontalOrigin: HorizontalOrigin.CENTER,
            translucencyByDistance: new NearFarScalar(1e3, 1.0, 5e6, 0.3),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 8e6),
          },
          label: {
            text: permit.permit_number || permit.permit_type || "Permit",
            font: "9px monospace",
            fillColor: Color.fromCssColorString(
              PERMIT_TYPE_ICON_COLORS[permit.status]?.fill || "#6b7280"
            ),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new Cartesian2(14, -4),
            scale: 0.8,
            verticalOrigin: VerticalOrigin.CENTER,
            horizontalOrigin: HorizontalOrigin.LEFT,
            distanceDisplayCondition: new DistanceDisplayCondition(0, 2e6),
            translucencyByDistance: new NearFarScalar(5e4, 1.0, 2e6, 0.0),
          },
          name: `Permit: ${permit.permit_number || permit.id}`,
          description: `Type: ${permit.permit_type || "N/A"}<br/>
            Status: ${permit.status}<br/>
            Address: ${permit.address || "N/A"}<br/>
            Value: ${permit.estimated_value ? `$${permit.estimated_value.toLocaleString()}` : "N/A"}<br/>
            Filed: ${permit.filed_date || "N/A"}<br/>
            Applicant: ${permit.applicant_name || "N/A"}`,
        });
      });
    }

    // ── Properties ───────────────────────────────────────────────────────
    if (showProperties && propertySearchResults) {
      propertySearchResults.forEach((prop) => {
        if (!prop.latitude || !prop.longitude) return;
        entities.add({
          id: `property_${prop.id}`,
          position: Cartesian3.fromDegrees(prop.longitude, prop.latitude, 100),
          billboard: {
            image: createPropertySvg(prop.property_type),
            scale: 1.0,
            verticalOrigin: VerticalOrigin.CENTER,
            horizontalOrigin: HorizontalOrigin.CENTER,
            translucencyByDistance: new NearFarScalar(1e3, 1.0, 5e6, 0.3),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 8e6),
          },
          label: {
            text: prop.address || "",
            font: "9px monospace",
            fillColor: Color.fromCssColorString(
              PROPERTY_TYPE_COLORS[prop.property_type] || "#6b7280"
            ),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new Cartesian2(14, -4),
            scale: 0.8,
            verticalOrigin: VerticalOrigin.CENTER,
            horizontalOrigin: HorizontalOrigin.LEFT,
            distanceDisplayCondition: new DistanceDisplayCondition(0, 1.5e6),
            translucencyByDistance: new NearFarScalar(3e4, 1.0, 1.5e6, 0.0),
          },
          name: prop.address,
          description: `Address: ${prop.address}<br/>
            Type: ${prop.property_type}<br/>
            ${prop.bedrooms ? `Beds: ${prop.bedrooms}<br/>` : ""}
            ${prop.bathrooms ? `Baths: ${prop.bathrooms}<br/>` : ""}
            ${prop.living_area_sqft ? `Area: ${prop.living_area_sqft.toLocaleString()} sqft<br/>` : ""}
            ${prop.estimated_value ? `Est. Value: $${prop.estimated_value.toLocaleString()}<br/>` : ""}
            ${prop.year_built ? `Built: ${prop.year_built}<br/>` : ""}
            ${prop.zoning ? `Zoning: ${prop.zoning}` : ""}`,
        });
      });
    }

    // ── Parcel boundary for selected property (inline, after removeAll) ────
    if (selectedProperty) {
      const { latitude, longitude } = selectedProperty;
      if (latitude !== 0 || longitude !== 0) {
        const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
        fetch(`${API_BASE}/api/parcels?lat=${latitude}&lon=${longitude}`)
          .then((res) => res.json())
          .then((data) => {
            if (viewer.isDestroyed()) return;
            const geom = data?.geometry;
            if (!geom || !geom.coordinates) return;
            // Remove any existing parcel entities before adding new ones
            for (const id of parcelEntityIdsRef.current) {
              const existing = viewer.entities.getById(id);
              if (existing) viewer.entities.remove(existing);
            }
            parcelEntityIdsRef.current = [];
            const rings = geom.type === "MultiPolygon" ? geom.coordinates.flat() : geom.coordinates;
            rings.forEach((ring: number[][], idx: number) => {
              const positions = ring.map(([lon, lat]: number[]) =>
                Cartesian3.fromDegrees(lon, lat)
              );
              // Close the ring for polyline
              const closedPositions = [...positions];
              if (closedPositions.length > 1) closedPositions.push(closedPositions[0]);

              // Billboard markers at each corner (always visible, ignores depth)
              ring.forEach(([clon, clat]: number[], c: number) => {
                const markerId = `parcel_marker_${idx}_${c}`;
                viewer.entities.add({
                  id: markerId,
                  position: Cartesian3.fromDegrees(clon, clat, 15),
                  point: {
                    pixelSize: 10,
                    color: Color.CYAN,
                    outlineColor: Color.WHITE,
                    outlineWidth: 2,
                    disableDepthTestDistance: Number.POSITIVE_INFINITY,
                    heightReference: HeightReference.RELATIVE_TO_GROUND,
                  },
                });
                parcelEntityIdsRef.current.push(markerId);
              });

              // Polyline with depthFail so it shows through 3D tiles
              const outlineId = `parcel_outline_${idx}`;
              viewer.entities.add({
                id: outlineId,
                polyline: {
                  positions: closedPositions,
                  width: 4,
                  material: Color.CYAN,
                  depthFailMaterial: Color.CYAN.withAlpha(0.5),
                  clampToGround: false,
                },
              });
              parcelEntityIdsRef.current.push(outlineId);
            });
            console.log(`[CesiumGlobe] Parcel boundary rendered (${rings.length} ring(s))`);
          })
          .catch((err) => console.warn("[CesiumGlobe] Parcel fetch failed:", err?.message));
      }
    }
  }, [cameras, earthquakes, permits, propertySearchResults, selectedProperty,
      showCameras, showEarthquakes, showPermits, showProperties, ready]);

  // ── FEMA Flood Zone WMS overlay ──────────────────────────────────────────
  useEffect(() => {
    if (!viewerRef.current || !ready) return;
    const viewer = viewerRef.current;
    if (viewer.isDestroyed()) return;

    if (showFloodZones && !floodLayerRef.current) {
      // Add FEMA NFHL as an ArcGIS Map Server imagery layer
      ArcGisMapServerImageryProvider.fromUrl(
        "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer",
        { enablePickFeatures: false }
      )
        .then((provider) => {
          if (viewer.isDestroyed()) return;
          const layer = viewer.imageryLayers.addImageryProvider(provider);
          layer.alpha = 0.45;
          floodLayerRef.current = layer;
          console.log("[CesiumGlobe] FEMA Flood Zone overlay added");
        })
        .catch((err) => {
          console.warn("[CesiumGlobe] FEMA overlay failed:", err?.message);
        });
    } else if (!showFloodZones && floodLayerRef.current) {
      viewer.imageryLayers.remove(floodLayerRef.current, true);
      floodLayerRef.current = null;
      console.log("[CesiumGlobe] FEMA Flood Zone overlay removed");
    }
  }, [showFloodZones, ready]);

  // ── MassGIS Parcel Boundaries overlay ──────────────────────────────────
  useEffect(() => {
    if (!viewerRef.current || !ready) return;
    const viewer = viewerRef.current;
    if (viewer.isDestroyed()) return;

    if (showParcels && !parcelLayerRef.current) {
      ArcGisMapServerImageryProvider.fromUrl(
        "https://tiles.arcgis.com/tiles/hGdibHYSPO59RG1h/arcgis/rest/services/MassGIS_Level3_Parcels/MapServer",
        { enablePickFeatures: false }
      )
        .then((provider) => {
          if (viewer.isDestroyed()) return;
          const layer = viewer.imageryLayers.addImageryProvider(provider);
          layer.alpha = 0.55;
          parcelLayerRef.current = layer;
          console.log("[CesiumGlobe] MassGIS Parcel Boundaries overlay added");
        })
        .catch((err) => {
          console.warn("[CesiumGlobe] MassGIS parcel overlay failed:", err?.message);
        });
    } else if (!showParcels && parcelLayerRef.current) {
      viewer.imageryLayers.remove(parcelLayerRef.current, true);
      parcelLayerRef.current = null;
      console.log("[CesiumGlobe] MassGIS Parcel Boundaries overlay removed");
    }
  }, [showParcels, ready]);

  // ── Viewport Permit Pins (CustomDataSource — independent of entity sync) ──
  useEffect(() => {
    if (!viewerRef.current || !ready) return;
    const viewer = viewerRef.current;
    if (viewer.isDestroyed()) return;

    // Ensure the data source exists on the current viewer (handles viewer recreation / HMR)
    let dsFound = false;
    if (vpDataSourceRef.current) {
      for (let i = 0; i < viewer.dataSources.length; i++) {
        if (viewer.dataSources.get(i) === vpDataSourceRef.current) {
          dsFound = true;
          break;
        }
      }
    }
    if (!dsFound) {
      const ds = new CustomDataSource("viewportPermits");
      viewer.dataSources.add(ds);
      vpDataSourceRef.current = ds;
    }

    if (!showPermits) {
      // Hide all viewport pins when permits toggle is off
      const ds = vpDataSourceRef.current;
      if (ds) ds.entities.removeAll();
      return;
    }

    // Camera moveEnd listener — fetch permits in viewport when zoomed in
    const fetchViewportPermits = () => {
      if (!viewerRef.current || viewerRef.current.isDestroyed()) return;
      const v = viewerRef.current;
      const ds = vpDataSourceRef.current;
      if (!ds) return;

      const camHeight = v.camera.positionCartographic.height;
      console.log(`[CesiumGlobe] VP check: height=${Math.round(camHeight)}m, showPermits=${showPermits}`);
      if (camHeight > 50_000) {
        ds.entities.removeAll();
        vpLastBboxRef.current = "";
        return;
      }

      // Get viewport rectangle
      const rect = v.camera.computeViewRectangle();
      if (!rect) return;

      const west = CesiumMath.toDegrees(rect.west);
      const south = CesiumMath.toDegrees(rect.south);
      const east = CesiumMath.toDegrees(rect.east);
      const north = CesiumMath.toDegrees(rect.north);

      // Skip if bbox hasn't changed significantly (0.001° ≈ 111m)
      const bboxKey = `${west.toFixed(3)},${south.toFixed(3)},${east.toFixed(3)},${north.toFixed(3)}`;
      if (bboxKey === vpLastBboxRef.current) return;
      vpLastBboxRef.current = bboxKey;

      // Grid size for clustering based on zoom level
      const spanDeg = Math.max(east - west, north - south);
      const gridSize = spanDeg / 20; // ~20 cells across viewport

      getPermitPins(west, south, east, north, 500)
        .then((data) => {
          if (!ds || v.isDestroyed()) return;
          ds.entities.removeAll();

          if (!data.pins || data.pins.length === 0) return;

          const clusters = clusterPins(data.pins, gridSize);

          for (const cluster of clusters) {
            if (cluster.pins.length === 1) {
              // Single pin — show as individual permit icon
              const pin = cluster.pins[0];
              const typeKey = pin.type || "Building";
              ds.entities.add({
                id: `vpin_${pin.id}`,
                position: Cartesian3.fromDegrees(pin.lon, pin.lat, 150),
                billboard: {
                  image: createPermitSvg(typeKey),
                  scale: 1.0,
                  verticalOrigin: VerticalOrigin.CENTER,
                  horizontalOrigin: HorizontalOrigin.CENTER,
                  disableDepthTestDistance: Number.POSITIVE_INFINITY,
                },
                label: {
                  text: pin.addr.split(",")[0] || pin.type || "Permit",
                  font: "9px monospace",
                  fillColor: Color.fromCssColorString(
                    PERMIT_TYPE_ICON_COLORS[typeKey]?.fill || "#6b7280"
                  ),
                  outlineColor: Color.BLACK,
                  outlineWidth: 2,
                  style: LabelStyle.FILL_AND_OUTLINE,
                  pixelOffset: new Cartesian2(14, -4),
                  scale: 0.8,
                  verticalOrigin: VerticalOrigin.CENTER,
                  horizontalOrigin: HorizontalOrigin.LEFT,
                  distanceDisplayCondition: new DistanceDisplayCondition(0, 5000),
                },
              });
            } else {
              // Cluster — show circle with count
              ds.entities.add({
                id: `vcluster_${cluster.lat.toFixed(5)}_${cluster.lon.toFixed(5)}`,
                position: Cartesian3.fromDegrees(cluster.lon, cluster.lat, 200),
                billboard: {
                  image: createClusterSvg(cluster.pins.length),
                  scale: 1.0,
                  verticalOrigin: VerticalOrigin.CENTER,
                  horizontalOrigin: HorizontalOrigin.CENTER,
                  disableDepthTestDistance: Number.POSITIVE_INFINITY,
                },
              });
            }
          }
          console.log(
            `[CesiumGlobe] Viewport permits: ${data.pins.length} pins → ${clusters.length} clusters`
          );
        })
        .catch((err) => {
          console.warn("[CesiumGlobe] Viewport permit fetch failed:", err?.message);
        });
    };

    // Use camera.changed for detecting camera movement (zoom, pan, tilt)
    viewer.camera.percentageChanged = 0.01;
    const onCameraChanged = () => {
      if (vpFetchTimerRef.current) clearTimeout(vpFetchTimerRef.current);
      vpFetchTimerRef.current = setTimeout(fetchViewportPermits, 600);
    };
    viewer.camera.changed.addEventListener(onCameraChanged);

    // Periodic render kick to ensure camera.changed fires even in throttled contexts
    const renderKick = setInterval(() => {
      if (!viewer.isDestroyed()) viewer.scene.requestRender();
    }, 2000);

    console.log("[CesiumGlobe] VP effect mounted, showPermits=", showPermits);

    // Initial fetch for current viewport (delayed to let camera settle)
    setTimeout(fetchViewportPermits, 1500);

    return () => {
      if (vpFetchTimerRef.current) clearTimeout(vpFetchTimerRef.current);
      clearInterval(renderKick);
      if (!viewer.isDestroyed()) {
        viewer.camera.changed.removeEventListener(onCameraChanged);
      }
    };
  }, [showPermits, ready]);

  // ── CSS view mode filter ────────────────────────────────────────────────
  const viewerFilter: React.CSSProperties = (() => {
    switch (viewMode) {
      case "satellite":
        return { filter: "contrast(1.1) saturate(1.2) brightness(1.05)" };
      case "risk":
        return { filter: "sepia(0.3) hue-rotate(-10deg) saturate(1.4) brightness(1.05) contrast(1.1)" };
      default:
        return {};
    }
  })();

  return (
    <div className="w-full h-full relative">
      <div className="absolute inset-0" style={viewerFilter}>
        <div
          ref={containerRef}
          style={{ width: "100%", height: "100%", position: "absolute", inset: 0 }}
        />
      </div>
      <ShaderOverlay />
    </div>
  );
};

export default CesiumGlobeInner;
