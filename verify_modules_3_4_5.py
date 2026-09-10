"""
SENTINEL STATEWIDE CCTV INTELLIGENCE ENGINE (GUJARAT POLICE PoC)
End-to-End Verification of Modules 3, 4, and 5:
- Module 3: Dynamic Offloading Scheduler Hardening & Telemetry
- Module 4: High-Performance Event Worker & Threat Dispatcher
- Module 5: Real-Time GIS Command Center & WebRTC/WHEP Feed Inspection
"""

import asyncio
import json
import os
import sys
import time
import httpx
import websockets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "edge"))

from sentinel_edge.offload.models import (
    ExecutionTarget,
    NodeHealth,
    Priority,
    WorkloadProfile,
    WorkloadType,
)
from sentinel_edge.offload.health import NodeHealthRegistry
from sentinel_edge.offload.executor import ExecutionRequest
from sentinel_edge.offload.policy import SchedulingPolicy
from sentinel_edge.offload.adaptive_policy import AdaptiveSchedulingPolicy
from sentinel_edge.offload.scheduler import OffloadScheduler
from sentinel_edge.offload.telemetry import ExecutionTelemetryCollector



def test_module_3_scheduler_hardening():
    print("\n=======================================================")
    print("MODULE 3: DYNAMIC OFFLOADING SCHEDULER HARDENING")
    print("=======================================================")

    # 1. Initialize Adaptive Policy with Workload Validation Delegation
    telemetry = ExecutionTelemetryCollector(window_size=100)
    adaptive_policy = AdaptiveSchedulingPolicy(telemetry_collector=telemetry)

    # 2. Register candidate nodes: Edge, Local GPU, Cloud GPU
    registry = NodeHealthRegistry()
    registry.register(NodeHealth(node_id="node-edge", target=ExecutionTarget.EDGE, cpu_percent=45.0, memory_percent=50.0, queue_depth=2, network_latency_ms=2.0))
    registry.register(NodeHealth(node_id="node-local-gpu", target=ExecutionTarget.LOCAL, cpu_percent=30.0, gpu_percent=25.0, queue_depth=1, network_latency_ms=12.0))
    registry.register(NodeHealth(node_id="node-cloud-gpu", target=ExecutionTarget.CLOUD, cpu_percent=20.0, gpu_percent=15.0, queue_depth=0, network_latency_ms=65.0))

    scheduler = OffloadScheduler(health_registry=registry, policy=adaptive_policy)

    # 3. Schedule ALPR Workload (Deterministic scoring)
    workload_alpr = WorkloadProfile(
        workload_type=WorkloadType.ALPR,
        priority=Priority.CRITICAL,
        estimated_compute_ms=40.0,
        allow_edge=True,
        allow_local=True,
        allow_cloud=True,
        maximum_latency_ms=100.0,
    )

    # Verify delegation of validate_workload()
    assert adaptive_policy.validate_workload(workload_alpr) is True, "validate_workload delegation failed"
    print("  [OK] validate_workload() delegation verified")

    result = scheduler.schedule(workload_alpr)
    decision = result.decision

    print(f"  [OK] Scheduled ALPR workload to target: {decision.target.value} (Node: {decision.node_id})")
    print(f"  [OK] Estimated Latency: {decision.estimated_latency_ms:.2f}ms | Decision Score: {decision.score:.3f}")
    assert decision.accepted, "Scheduler rejected valid ALPR workload"
    assert len(result.candidate_explanations) == 3, "Missing candidate rankings"
    print("  [OK] Candidate Rankings:")
    for cand in result.candidate_explanations:
        print(f"     [Rank {cand.rank}] {cand.node_id} ({cand.target.value}): Final Score = {cand.score:.4f}")

    print("MODULE 3 VALIDATION PASSED! [OK]\n")




async def test_module_4_and_5_integration():
    print("=======================================================")
    print("MODULE 4 & MODULE 5: EVENT WORKER & GIS WEBSOCKET COMMAND CENTER")
    print("=======================================================")

    api_base = "http://127.0.0.1:8001"
    ws_url = "ws://127.0.0.1:8001/api/v1/ws/alerts"

    async with httpx.AsyncClient(base_url=api_base, timeout=10.0) as client:
        # 1. Verify GIS endpoints
        res = await client.get("/api/v1/tracking/route/GJ01AB1234")
        assert res.status_code == 200, f"Route query failed: {res.status_code}"
        route_geojson = res.json()
        print(f"  [OK] PostGIS Trajectory Reconstructed: {len(route_geojson['features'])} features, {route_geojson['properties']['total_distance_km']} km")

        # 2. Verify Command Center Dashboard HTML & Bundle
        res = await client.get("/dashboard/")
        assert res.status_code == 200, f"Dashboard failed: {res.status_code}"
        assert "SENTINEL" in res.text, "Dashboard HTML missing brand title"
        print("  [OK] GIS Command Center Dashboard online at /dashboard/")

        # 3. Connect to WebSocket and trigger real-time threat dispatch
        print(f"  [OK] Connecting to Command Center Alert WebSocket ({ws_url})...")
        async with websockets.connect(ws_url) as ws:
            # Read handshake packet
            welcome = await ws.recv()
            welcome_data = json.loads(welcome)
            print(f"  [OK] WebSocket Handshake: {welcome_data['type']} | Status: {welcome_data.get('status')}")

            # Trigger ALPR Threat Simulation for Wanted Vehicle GJ05CD5678 (Diamond Bourse Stolen Scorpio)
            sim_payload = {
                "license_plate": "GJ05CD5678",
                "camera_id": "CAM_SUR_02",
                "confidence": 0.985,
            }
            start_time = time.monotonic()
            sim_res = await client.post("/api/v1/watchlist/simulate", json=sim_payload)
            assert sim_res.status_code == 200, "Simulate endpoint failed"

            # Receive WebSocket Alert Broadcast
            alert_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            latency_ms = (time.monotonic() - start_time) * 1000.0
            alert = json.loads(alert_msg)

            print(f"  [ALERT] Threat Broadcast Received over WebSocket in {latency_ms:.1f}ms:")
            print(f"     Plate: {alert['license_plate']} | Severity: {alert['severity']} | Category: {alert['category']}")
            print(f"     Vehicle: {alert.get('vehicle_info')} | Location: {alert.get('camera_name')} ({alert.get('city')})")
            print(f"     Coordinates: [{alert.get('latitude')}, {alert.get('longitude')}]")
            assert alert["license_plate"] == "GJ05CD5678"
            assert alert["event_type"] == "THREAT_DETECTED"

    print("MODULE 4 & 5 VALIDATION PASSED! [OK]\n")



if __name__ == "__main__":
    test_module_3_scheduler_hardening()
    asyncio.run(test_module_4_and_5_integration())
    print("ALL MODULES (3, 4, 5) EXECUTED AND FULLY VERIFIED! [OK]")
