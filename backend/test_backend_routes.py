import asyncio
import httpx
from app.database.postgres import postgres
from app.database.redis import redis_client
from app.main import app


async def test_all_routes():
    print("Connecting to DB and Redis...")
    await postgres.connect()
    await redis_client.connect()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health check
        res = await client.get("/api/health")
        print("GET /api/health ->", res.status_code, res.json())
        assert res.status_code == 200

        # 2. Watchlist
        res = await client.get("/api/v1/watchlist")
        print("GET /api/v1/watchlist ->", res.status_code, f"{res.json()['count']} items")
        assert res.status_code == 200
        assert res.json()["count"] >= 5

        # 3. Tracked plates
        res = await client.get("/api/v1/tracking/plates")
        print("GET /api/v1/tracking/plates ->", res.status_code, f"{res.json()['count']} plates found")
        assert res.status_code == 200
        assert res.json()["count"] >= 2

        # 4. Trajectory for GJ01AB1234
        res = await client.get("/api/v1/tracking/route/GJ01AB1234")
        data = res.json()
        print(
            "GET /api/v1/tracking/route/GJ01AB1234 ->",
            res.status_code,
            f"features: {len(data['features'])}, is_watchlist_match: {data['properties']['is_watchlist_match']}",
        )
        assert res.status_code == 200
        assert len(data["features"]) >= 6
        assert data["properties"]["is_watchlist_match"] is True

        # 5. Cameras
        res = await client.get("/api/v1/tracking/cameras")
        cam_data = res.json()
        print("GET /api/v1/tracking/cameras ->", res.status_code, f"{len(cam_data['features'])} cameras")
        assert res.status_code == 200
        assert len(cam_data["features"]) >= 10

        # 6. Simulate Threat Detection
        sim_payload = {
            "license_plate": "GJ01AB1234",
            "camera_id": "CAM_AHM_01",
            "confidence": 0.99
        }
        res = await client.post("/api/v1/watchlist/simulate", json=sim_payload)
        print("POST /api/v1/watchlist/simulate ->", res.status_code, res.json()["status"])
        assert res.status_code == 200
        assert res.json()["is_watchlist_match"] is True

        # 7. Sandbox Ingest Discovery
        ingest_res = await client.get("/api/ingest")
        ingest_data = ingest_res.json()
        print("GET /api/ingest ->", ingest_res.status_code, f"{ingest_data['total_cameras']} cameras discovered")
        assert ingest_res.status_code == 200
        assert ingest_data["total_cameras"] >= 10

    await redis_client.disconnect()
    await postgres.disconnect()
    print("ALL API ROUTES VERIFIED SUCCESSFULLY! [OK]")



if __name__ == "__main__":
    asyncio.run(test_all_routes())
