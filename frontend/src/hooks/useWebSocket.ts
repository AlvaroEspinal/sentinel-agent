import { useEffect, useRef } from "react";
import { wsService } from "../services/api";

/**
 * React hook that manages WebSocket connection lifecycle.
 * Connects on mount, disconnects on unmount.
 * Reconnection logic is handled internally by wsService.
 *
 * Dispatches the following events to the store:
 *   - cameras_update
 *   - earthquakes_update
 *   - sensor_status
 *   - connection_established
 *   - permits_update
 *   - property_update
 *   - agent_finding
 *   - property_agent_status
 */
export function useWebSocket(): void {
  const isConnected = useRef(false);

  useEffect(() => {
    if (!isConnected.current) {
      isConnected.current = true;
      wsService.connect();
    }

    return () => {
      isConnected.current = false;
      wsService.disconnect();
    };
  }, []);
}
