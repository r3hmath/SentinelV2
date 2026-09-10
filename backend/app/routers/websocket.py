import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.database.redis import redis_client

logger = logging.getLogger("sentinel.api.websocket")

router = APIRouter(tags=["WebSockets & Live Alerting"])


class AlertConnectionManager:
    """
    Manages active WebSocket connections from command center dashboards
    and broadcasts threat alerts received from Redis Pub/Sub.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._listener_task: asyncio.Task | None = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(
            "WebSocket client connected | active_clients=%d",
            len(self.active_connections),
        )

        # Send initial status
        await websocket.send_text(
            json.dumps(
                {
                    "type": "SYSTEM_STATUS",
                    "status": "CONNECTED",
                    "channel": "sentinel:alerts",
                    "message": "Connected to Sentinel Live Threat Alert Feed",
                }
            )
        )

        # Ensure Redis Pub/Sub listener is running
        self._ensure_listener()

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(
            "WebSocket client disconnected | active_clients=%d",
            len(self.active_connections),
        )

    async def broadcast(self, message: str):
        if not self.active_connections:
            return

        dead_connections = set()
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                dead_connections.add(connection)

        for dead in dead_connections:
            self.active_connections.discard(dead)

    def _ensure_listener(self):
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._redis_alert_listener())

    async def _redis_alert_listener(self):
        """
        Continuously listen to Redis pub/sub channel 'sentinel:alerts'
        and forward every message to all active WebSocket clients.
        """
        logger.info("Starting Redis pub/sub alert listener for 'sentinel:alerts'...")
        while True:
            try:
                if redis_client.client is None:
                    await asyncio.sleep(2)
                    continue

                pubsub = redis_client.client.pubsub()
                await pubsub.subscribe("sentinel:alerts")

                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        logger.info("Broadcasting threat alert to clients: %s", data)
                        await self.broadcast(data)

            except asyncio.CancelledError:
                logger.info("Redis alert listener cancelled.")
                break
            except Exception as e:
                logger.warning("Redis alert listener error: %s. Reconnecting in 3s...", e)
                await asyncio.sleep(3)


manager = AlertConnectionManager()


@router.websocket("/ws/alerts")
@router.websocket("/api/v1/ws/alerts")
async def websocket_alerts_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep-alive receive loop
            data = await websocket.receive_text()
            try:
                parsed = json.loads(data)
                # Handle client ping
                if parsed.get("action") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
        manager.disconnect(websocket)
