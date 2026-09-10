import asyncio
import json
import websockets
import httpx


async def test_live_websocket():
    uri = "ws://127.0.0.1:8001/api/v1/ws/alerts"
    print(f"Connecting to live WebSocket: {uri}...")
    async with websockets.connect(uri) as websocket:
        # Receive welcome message
        welcome = await websocket.recv()
        print("Received initial packet:", welcome)
        welcome_data = json.loads(welcome)
        assert welcome_data["type"] == "SYSTEM_STATUS"

        # In parallel, simulate a threat detection via HTTP POST
        print("Triggering simulated threat detection for GJ05CD5678...")
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
            res = await client.post("/api/v1/watchlist/simulate", json={
                "license_plate": "GJ05CD5678",
                "camera_id": "CAM_SUR_02",
                "confidence": 0.98
            })
            assert res.status_code == 200
            print("Simulation POST succeeded:", res.json()["status"])

        # Wait for WebSocket threat alert
        alert_msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        print("\nWEBSOCKET RECEIVED THREAT ALERT:")
        print(alert_msg)
        alert_data = json.loads(alert_msg)
        assert alert_data["event_type"] == "THREAT_DETECTED"
        assert alert_data["license_plate"] == "GJ05CD5678"
        print("\nLIVE WEBSOCKET STREAM VERIFIED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(test_live_websocket())
