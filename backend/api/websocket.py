"""WebSocket manager for real-time data streaming to the dashboard."""
from __future__ import annotations

import json
import asyncio
from typing import Optional
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger


class ConnectionManager:
    """Manages WebSocket connections for real-time dashboard updates.

    Supports broadcasting to all connected clients:
    - Flight position updates (ADSB)
    - Ship position updates (AIS)
    - Alert notifications
    - Portfolio sync events
    - Sensor status changes
    """

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._broadcast_lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Active: {len(self.active_connections)}")

        # Send initial connection confirmation
        await self._send_to(websocket, {
            "type": "connection_established",
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Sentinel Agent connected",
        })

    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected client."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Active: {len(self.active_connections)}")

    async def broadcast(self, message_type: str, data: dict):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return

        payload = {
            "type": message_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data,
        }

        async with self._broadcast_lock:
            disconnected = []
            for ws in self.active_connections:
                try:
                    await ws.send_json(payload)
                except Exception:
                    disconnected.append(ws)

            for ws in disconnected:
                self.disconnect(ws)

    async def broadcast_alert(self, alert_data: dict):
        """Broadcast a new alert to all clients."""
        await self.broadcast("alert", alert_data)

    async def broadcast_flights(self, flights: list[dict]):
        """Broadcast updated flight positions."""
        await self.broadcast("flights_update", {"flights": flights, "count": len(flights)})

    async def broadcast_ships(self, ships: list[dict]):
        """Broadcast updated ship positions."""
        await self.broadcast("ships_update", {"ships": ships, "count": len(ships)})

    async def broadcast_portfolio(self, portfolio_data: dict):
        """Broadcast portfolio sync event."""
        await self.broadcast("portfolio_sync", portfolio_data)

    async def broadcast_cameras(self, cameras: list[dict]):
        """Broadcast updated camera feeds."""
        await self.broadcast("cameras_update", {"cameras": cameras, "count": len(cameras)})

    async def broadcast_sensor_status(self, status: dict):
        """Broadcast sensor status update."""
        await self.broadcast("sensor_status", status)

    async def _send_to(self, websocket: WebSocket, data: dict):
        """Send data to a specific client."""
        try:
            await websocket.send_json(data)
        except Exception as e:
            logger.error(f"WebSocket send error: {e}")
            self.disconnect(websocket)

    @property
    def client_count(self) -> int:
        return len(self.active_connections)
