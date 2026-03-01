import { useEffect, useRef } from "react";
import {
  Cartesian3,
  Math as CesiumMath,
  type Viewer as CesiumViewerType,
} from "cesium";
import { useStore } from "../store/useStore";
import type { CameraTarget } from "../types";

/**
 * React hook that watches store.cameraTarget and smoothly
 * flies the Cesium camera to the target coordinates.
 *
 * @param viewerRef - React ref to the Cesium Viewer instance
 */
export function useGlobeCamera(
  viewerRef: React.MutableRefObject<CesiumViewerType | null>
): void {
  const cameraTarget = useStore((s) => s.cameraTarget);
  const lastTarget = useRef<CameraTarget | null>(null);

  useEffect(() => {
    if (!cameraTarget) return;
    if (!viewerRef.current) return;

    // Avoid flying to the same target twice
    if (
      lastTarget.current &&
      lastTarget.current.lat === cameraTarget.lat &&
      lastTarget.current.lon === cameraTarget.lon &&
      lastTarget.current.altitude === cameraTarget.altitude
    ) {
      return;
    }

    lastTarget.current = cameraTarget;

    const viewer = viewerRef.current;
    const camera = viewer.camera;

    camera.flyTo({
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
      easingFunction: (time: number) => {
        // Smooth ease-in-out cubic
        return time < 0.5
          ? 4 * time * time * time
          : 1 - Math.pow(-2 * time + 2, 3) / 2;
      },
    });
  }, [cameraTarget, viewerRef]);
}
