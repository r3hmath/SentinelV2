import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
import httpx

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sentinel.test_mock_trap")


async def run_mock_trap_test():
    print("=" * 70)
    print("SENTINEL ADVERSARIAL AUDIT: THE MOCK TRAP TEST")
    print("Verifying Zero Reliance on Static Database Seeds")
    print("=" * 70)

    base_url = "http://127.0.0.1:8001"
    test_plate = f"GJ99ZZ{uuid.uuid4().hex[:4].upper()}"

    print(f"\n[Test Setup] Target Unseeded Vehicle Plate: {test_plate}")

    # Verify plate has 0 historical sightings
    async with httpx.AsyncClient(base_url=base_url) as client:
        route_res = await client.get(f"/api/v1/tracking/route/{test_plate}")
        assert route_res.status_code == 200
        assert route_res.json()["properties"]["total_sightings"] == 0
        print("  [OK] Confirmed zero historical records for plate.")

    # Camera checkpoints across Gujarat
    checkpoints = [
        {
            "camera_id": "CAM_SUR_01",
            "node_id": "NODE_SUR_01",
            "city": "Surat",
            "lat": 21.2678,
            "lon": 72.9644,
            "offset_mins": -120,
        },
        {
            "camera_id": "CAM_VAD_01",
            "node_id": "NODE_VAD_01",
            "city": "Vadodara",
            "lat": 22.3129,
            "lon": 73.1926,
            "offset_mins": -60,
        },
        {
            "camera_id": "CAM_AHM_01",
            "node_id": "NODE_AHM_01",
            "city": "Ahmedabad",
            "lat": 23.0039,
            "lon": 72.5850,
            "offset_mins": 0,
        },
    ]

    print("\n[Simulating Live Highway Traversal] Emitting 3 ALPR sightings across Gujarat corridor...")
    now = datetime.now(timezone.utc)
    event_ids = []

    async with httpx.AsyncClient(base_url=base_url) as client:
        for i, cp in enumerate(checkpoints, start=1):
            event_id = str(uuid.uuid4())
            event_ids.append(event_id)
            event_time = now + timedelta(minutes=cp["offset_mins"])

            payload = {
                "event_id": event_id,
                "node_id": cp["node_id"],
                "camera_id": cp["camera_id"],
                "event_type": "ALPR_DETECTED",
                "timestamp": event_time.isoformat(),
                "confidence": 0.96 + (i * 0.01),
                "latitude": cp["lat"],
                "longitude": cp["lon"],
                "frame_number": 100 * i,
                "inference_latency_ms": 40.0,
                "detections": [
                    {
                        "class_id": 2,
                        "confidence": 0.96,
                        "bbox": [100.0, 150.0, 300.0, 350.0],
                        "track_id": 500 + i,
                        "center": [200.0, 250.0],
                        "object_type": "car",
                    }
                ],
                "metadata": {
                    "city": cp["city"],
                    "source": f"rtsp://mock/{cp['camera_id'].lower()}",
                    "alpr": {
                        "plate": test_plate,
                        "track_id": 500 + i,
                        "plate_confidence": 0.97,
                        "detector_confidence": 0.95,
                        "recognized": True,
                    },
                },
            }

            res = await client.post("/api/events", json=payload)
            assert res.status_code == 200, f"Failed at checkpoint {i}: {res.text}"
            print(f"  Checkpoint #{i} ({cp['city']} - {cp['camera_id']}) accepted into stream.")

    # Allow worker 1.0s to drain stream and persist to PostGIS
    await asyncio.sleep(1.0)

    # -------------------------------------------------------------
    # Verify Dynamic Route Reconstruction via PostGIS ST_MakeLine
    # -------------------------------------------------------------
    print(f"\n[Verifying Dynamic Route Reconstruction] GET /api/v1/tracking/route/{test_plate}...")
    async with httpx.AsyncClient(base_url=base_url) as client:
        route_res = await client.get(f"/api/v1/tracking/route/{test_plate}")
        assert route_res.status_code == 200
        route_geojson = route_res.json()

        props = route_geojson["properties"]
        features = route_geojson["features"]

        print(f"  [OK] GeoJSON FeatureCollection generated!")
        print(f"  Total Sightings:         {props['total_sightings']}")
        print(f"  Unique Cameras:          {props['unique_cameras']}")
        print(f"  Transit Duration:        {props['transit_duration_minutes']} minutes")
        print(f"  Total Highway Distance:  {props['total_distance_km']} km")

        assert props["total_sightings"] == 3
        assert props["unique_cameras"] == 3
        assert props["total_distance_km"] > 200.0, f"Distance too short: {props['total_distance_km']} km"

        # Check Point features
        point_features = [f for f in features if f["geometry"]["type"] == "Point"]
        assert len(point_features) == 3, f"Expected 3 Point checkpoints, got {len(point_features)}"

        # Check LineString feature (PostGIS ST_MakeLine)
        line_features = [f for f in features if f["geometry"]["type"] == "LineString"]
        assert len(line_features) == 1, "LineString feature missing!"
        linestring = line_features[0]
        assert len(linestring["geometry"]["coordinates"]) == 3
        assert linestring["properties"]["checkpoint_count"] == 3
        assert linestring["properties"].get("postgis_generated") is True
        print("  [OK] PostGIS ST_MakeLine LineString Feature verified!")

        # ---------------------------------------------------------
        # Verify Dynamic Appearance in /api/v1/tracking/plates
        # ---------------------------------------------------------
        print("\n[Verifying Dynamic Recents List] GET /api/v1/tracking/plates...")
        plates_res = await client.get("/api/v1/tracking/plates")
        assert plates_res.status_code == 200
        plates_data = plates_res.json()
        matching_plates = [p for p in plates_data["plates"] if p["plate"] == test_plate]
        assert len(matching_plates) == 1, f"Plate {test_plate} missing from recents list!"
        print(f"  [OK] Plate {test_plate} discovered dynamically with {matching_plates[0]['camera_count']} cameras.")

    # Cleanup test events
    conn = await asyncpg.connect("postgresql://postgres:admin@127.0.0.1:5433/sentinel")
    try:
        await conn.execute("DELETE FROM public.events WHERE event_id = ANY($1::uuid[])", [uuid.UUID(eid) for eid in event_ids])
        print("  [Cleanup] Removed test events cleanly.")
    finally:
        await conn.close()

    print("\n" + "=" * 70)
    print("THE MOCK TRAP TEST PASSED 100%! SYSTEM IS PURELY DYNAMIC!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_mock_trap_test())
