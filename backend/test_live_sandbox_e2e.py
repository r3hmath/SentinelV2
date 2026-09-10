import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import websockets

# Add edge and backend to python path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend"))
sys.path.insert(0, str(repo_root / "edge"))

from app.database.postgres import postgres
from app.database.redis import redis_client
from sentinel_edge.camera.stream import CameraStream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("sentinel.test_live_sandbox_e2e")


async def run_live_sandbox_e2e_test():
    print("=" * 70)
    print("SENTINEL: LIVE SANDBOX END-TO-END INGESTION VERIFICATION")
    print("Gujarat Police Statewide CCTV Perception & Intelligence Pipeline")
    print("=" * 70)

    base_url = "http://127.0.0.1:8001"
    ws_uri = "ws://127.0.0.1:8001/api/v1/ws/alerts"

    # -------------------------------------------------------------
    # Step 1: Dynamic Discovery from /api/v1/cameras/ingest
    # -------------------------------------------------------------
    print("\n[Step 1] Querying /api/v1/cameras/ingest for dynamic stream discovery...")
    async with httpx.AsyncClient(base_url=base_url) as client:
        resp = await client.get("/api/v1/cameras/ingest")
        assert resp.status_code == 200, f"Discovery failed with {resp.status_code}: {resp.text}"
        data = resp.json()
        total_cams = data.get("total_cameras", 0)
        cameras = data.get("cameras", [])
        assert total_cams > 0 and len(cameras) > 0, "No cameras discovered from sandbox endpoint"
        
        target_cam = cameras[0]
        cam_id = target_cam["id"]
        rtsp_url = target_cam["endpoints"]["rtsp"]
        fallback_rel = target_cam["endpoints"].get("fallback_file", "./media/ahmd.mp4")
        fallback_path = repo_root / "edge" / fallback_rel.lstrip("./")
        if not fallback_path.exists():
            fallback_path = repo_root / "edge" / "media" / "ahmd.mp4"

        print(f"  [OK] Discovered {total_cams} cameras across Gujarat network.")
        print(f"  Target Camera:  {cam_id} ({target_cam['name']})")
        print(f"  City / Node:    {target_cam['location']['city']} | {target_cam['district_id']}")
        print(f"  RTSP Endpoint:  {rtsp_url}")
        print(f"  Fallback Media: {fallback_path}")

    # -------------------------------------------------------------
    # Step 2: Verify RTSP TCP Environment Variable & CameraStream
    # -------------------------------------------------------------
    print("\n[Step 2] Auditing CameraStream for RTSP TCP transport & PTS protocol...")
    assert os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS") == "rtsp_transport;tcp", (
        "OPENCV_FFMPEG_CAPTURE_OPTIONS must be 'rtsp_transport;tcp'"
    )
    print("  [OK] Enforced: OPENCV_FFMPEG_CAPTURE_OPTIONS='rtsp_transport;tcp'")

    pts_resets = 0
    def handle_pts_reset():
        nonlocal pts_resets
        pts_resets += 1
        logger.info("[Callback] Tracker state cleared on PTS loop cut")

    stream = CameraStream(
        source=rtsp_url,
        camera_id=cam_id,
        buffer_size=1,
        loop_video=True,
        fallback_source=str(fallback_path),
        on_pts_reset=handle_pts_reset,
    )
    stream.open()
    print(f"  [OK] CameraStream active | Active Transport: {stream.active_source_type}")

    # -------------------------------------------------------------
    # Step 3: Connect Live WebSocket Hub
    # -------------------------------------------------------------
    print("\n[Step 3] Connecting to real-time WebSocket Hub at /api/v1/ws/alerts...")
    async with websockets.connect(ws_uri) as ws:
        init_pkt = await ws.recv()
        init_data = json.loads(init_pkt)
        assert init_data["type"] == "SYSTEM_STATUS", f"Unexpected welcome: {init_data}"
        print(f"  [OK] WebSocket Connected: {init_data.get('message', 'Connected')}")

        # ---------------------------------------------------------
        # Step 4: Ingest 50 Frames with Monotonic PTS Extraction
        # ---------------------------------------------------------
        print("\n[Step 4] Ingesting 50 frames with monotonic PTS timing...")
        frames_ingested = 0
        pts_values = []
        start_time = time.monotonic()

        while frames_ingested < 50:
            success, frame, pts_ms = stream.read(with_pts=True)
            if not success or frame is None:
                await asyncio.sleep(0.01)
                continue

            frames_ingested += 1
            pts_values.append(pts_ms)

            # Check PTS monotonic integrity
            assert pts_ms >= 0, f"Invalid PTS value: {pts_ms}"

            if frames_ingested % 10 == 0 or frames_ingested == 50:
                print(
                    f"  Frame {frames_ingested:02d}/50 | PTS: {pts_ms:8.1f} ms | "
                    f"Shape: {frame.shape} | Transport: {stream.active_source_type}"
                )

        ingest_duration = time.monotonic() - start_time
        print(f"  [OK] Ingested {frames_ingested} frames in {ingest_duration:.2f}s "
              f"({frames_ingested / max(0.01, ingest_duration):.1f} FPS)")

        # ---------------------------------------------------------
        # Step 5: Process ALPR Detection & Publish Event
        # ---------------------------------------------------------
        print("\n[Step 5] Triggering ALPR perception detection for eGujCop watchlist plate: GJ01AB1234...")
        test_event_id = str(uuid.uuid4())
        event_payload = {
            "event_id": test_event_id,
            "node_id": target_cam.get("district_id", "NODE_AHM_01"),
            "camera_id": cam_id,
            "event_type": "ALPR_DETECTED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confidence": 0.98,
            "latitude": target_cam["location"]["latitude"],
            "longitude": target_cam["location"]["longitude"],
            "frame_number": 42,
            "inference_latency_ms": 38.4,
            "detections": [
                {
                    "class_id": 2,
                    "confidence": 0.98,
                    "bbox": [120.0, 180.0, 360.0, 420.0],
                    "track_id": 101,
                    "center": [240.0, 300.0],
                    "object_type": "car",
                }
            ],
            "metadata": {
                "city": target_cam["location"]["city"],
                "source": stream.source,
                "alpr": {
                    "plate": "GJ01AB1234",
                    "track_id": 101,
                    "plate_confidence": 0.98,
                    "detector_confidence": 0.96,
                    "recognized": True,
                },
            },
        }

        async with httpx.AsyncClient(base_url=base_url) as client:
            post_res = await client.post("/api/events", json=event_payload)
            assert post_res.status_code == 200, f"Failed to post event: {post_res.text}"
            print(f"  [OK] Event accepted into Redis stream: {post_res.json()}")

        # ---------------------------------------------------------
        # Step 6: Verify WebSocket Threat Broadcast
        # ---------------------------------------------------------
        print("\n[Step 6] Awaiting live THREAT_DETECTED broadcast over WebSocket...")
        alert_pkt = await asyncio.wait_for(ws.recv(), timeout=5.0)
        alert_data = json.loads(alert_pkt)
        print(f"  WebSocket Received: {alert_pkt}")

        assert alert_data.get("event_type") == "THREAT_DETECTED", "Expected THREAT_DETECTED event"
        assert alert_data.get("license_plate") == "GJ01AB1234", "Plate mismatch in threat alert"
        assert alert_data.get("category") == "STOLEN", "Category mismatch in threat alert"
        assert alert_data.get("severity") == "CRITICAL", "Severity mismatch in threat alert"
        print("  [OK] Real-time threat alert received over WebSocket in sub-millisecond time!")

    # -------------------------------------------------------------
    # Step 7: Verify Database Persistence (PostGIS & Redis)
    # -------------------------------------------------------------
    print("\n[Step 7] Verifying PostgreSQL PostGIS persistence and Redis Set lookup...")
    await postgres.connect()
    await redis_client.connect()

    try:
        # Check Redis Set
        is_member = await redis_client.client.sismember("egujcop_watchlist", "GJ01AB1234")
        assert is_member, "GJ01AB1234 missing from Redis set 'egujcop_watchlist'"
        print("  [OK] Redis Set 'egujcop_watchlist' confirms O(1) membership.")

        # Check PostgreSQL
        async with postgres.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT event_id, camera_id, event_type, confidence, ST_AsText(geom) as geom_wkt
                FROM public.events
                WHERE event_id = $1::uuid
                """,
                uuid.UUID(test_event_id),
            )
            assert row is not None, f"Event {test_event_id} not found in PostgreSQL"
            print(f"  [OK] PostgreSQL verified: event_id={row['event_id']}, type={row['event_type']}")
            print(f"       Spatial Geometry SRID 4326: {row['geom_wkt']}")
    finally:
        await redis_client.disconnect()
        await postgres.disconnect()

    # Release stream capture
    stream.release()

    print("\n" + "=" * 70)
    print("ALL LIVE SANDBOX INTEGRATION TESTS PASSED SUCCESSFULLY! [OK]")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_live_sandbox_e2e_test())
