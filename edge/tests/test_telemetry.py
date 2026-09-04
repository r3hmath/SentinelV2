from datetime import datetime, timezone

import pytest

from sentinel_edge.offload.executor import (
    ExecutionRequest,
    ExecutionResult,
)

from sentinel_edge.offload.models import (
    ExecutionTarget,
    Priority,
    WorkloadType,
)

from sentinel_edge.offload.telemetry import (
    ExecutionTelemetry,
    ExecutionTelemetryCollector,
)


def make_request(
    *,
    target=ExecutionTarget.LOCAL,
    workload_type=WorkloadType.ALPR,
):
    return ExecutionRequest.create(
        camera_id="CAM_AHM_01",
        track_id=1,
        workload_type=workload_type,
        priority=Priority.HIGH,
        target=target,
        payload={"test": "payload"},
        metadata={
            "scheduled_node_id": "local-gpu-01",
        },
    )


def make_result(
    request,
    *,
    success=True,
    latency_ms=100.0,
    executor_id="local-executor-01",
    error=None,
):
    return ExecutionResult(
        request_id=request.request_id,
        success=success,
        target=request.target,
        workload_type=request.workload_type,
        latency_ms=latency_ms,
        result={"ok": True} if success else None,
        error=error,
        executor_id=executor_id,
        completed_at=datetime.now(timezone.utc),
    )


# ============================================================
# EXECUTION TELEMETRY
# ============================================================

def test_telemetry_creation():

    telemetry = ExecutionTelemetry(
        request_id="req-1",
        executor_id="local-executor-01",
        node_id="local-gpu-01",
        target=ExecutionTarget.LOCAL,
        workload_type=WorkloadType.ALPR,
        success=True,
        latency_ms=125.5,
        timestamp=datetime.now(timezone.utc),
    )

    assert telemetry.request_id == "req-1"
    assert telemetry.executor_id == "local-executor-01"
    assert telemetry.node_id == "local-gpu-01"
    assert telemetry.success is True
    assert telemetry.latency_ms == 125.5


def test_telemetry_rejects_negative_latency():

    with pytest.raises(ValueError):

        ExecutionTelemetry(
            request_id="req-1",
            executor_id="executor-1",
            node_id="node-1",
            target=ExecutionTarget.LOCAL,
            workload_type=WorkloadType.ALPR,
            success=True,
            latency_ms=-1,
            timestamp=datetime.now(timezone.utc),
        )


def test_successful_telemetry_cannot_have_error():

    with pytest.raises(ValueError):

        ExecutionTelemetry(
            request_id="req-1",
            executor_id="executor-1",
            node_id="node-1",
            target=ExecutionTarget.LOCAL,
            workload_type=WorkloadType.ALPR,
            success=True,
            latency_ms=100,
            timestamp=datetime.now(timezone.utc),
            error="unexpected error",
        )


def test_from_execution():

    request = make_request()

    result = make_result(
        request,
        latency_ms=250.0,
    )

    telemetry = (
        ExecutionTelemetry.from_execution(
            request,
            result,
            node_id="local-gpu-01",
        )
    )

    assert (
        telemetry.request_id
        == str(request.request_id)
    )

    assert (
        telemetry.executor_id
        == "local-executor-01"
    )

    assert (
        telemetry.node_id
        == "local-gpu-01"
    )

    assert telemetry.latency_ms == 250.0
    assert telemetry.success is True


def test_from_execution_rejects_request_mismatch():

    request = make_request()

    result = make_result(
        request,
    )

    fake_request = make_request()

    with pytest.raises(ValueError):

        ExecutionTelemetry.from_execution(
            fake_request,
            result,
        )


def test_telemetry_serialization():

    telemetry = ExecutionTelemetry(
        request_id="req-1",
        executor_id="executor-1",
        node_id="node-1",
        target=ExecutionTarget.LOCAL,
        workload_type=WorkloadType.ALPR,
        success=True,
        latency_ms=123.456789,
        timestamp=datetime(
            2026,
            9,
            5,
            tzinfo=timezone.utc,
        ),
    )

    data = telemetry.to_dict()

    assert data["request_id"] == "req-1"
    assert data["executor_id"] == "executor-1"
    assert data["node_id"] == "node-1"
    assert data["target"] == "LOCAL"
    assert data["workload_type"] == "ALPR"
    assert data["success"] is True
    assert data["latency_ms"] == 123.4568


# ============================================================
# COLLECTOR
# ============================================================

def test_collector_records_execution():

    request = make_request()

    result = make_result(
        request,
        latency_ms=100,
    )

    collector = ExecutionTelemetryCollector()

    telemetry = collector.record_execution(
        request,
        result,
        node_id="local-gpu-01",
    )

    assert telemetry.node_id == "local-gpu-01"

    assert (
        collector.total_samples()
        == 1
    )


def test_statistics():

    collector = ExecutionTelemetryCollector()

    request = make_request()

    latencies = [
        100,
        200,
        300,
        400,
        500,
    ]

    for latency in latencies:

        result = make_result(
            request,
            latency_ms=latency,
        )

        collector.record_execution(
            request,
            result,
            node_id="local-gpu-01",
        )

    stats = collector.statistics(
        node_id="local-gpu-01",
        workload_type=WorkloadType.ALPR,
    )

    assert stats.executions == 5
    assert stats.successful == 5
    assert stats.failed == 0
    assert stats.success_rate == 1.0

    assert (
        stats.average_latency_ms
        == 300
    )

    assert stats.min_latency_ms == 100
    assert stats.max_latency_ms == 500


def test_failed_execution_statistics():

    collector = ExecutionTelemetryCollector()

    request = make_request()

    collector.record_execution(
        request,
        make_result(
            request,
            success=True,
            latency_ms=100,
        ),
        node_id="local-gpu-01",
    )

    collector.record_execution(
        request,
        make_result(
            request,
            success=False,
            latency_ms=200,
            error="OCR failure",
        ),
        node_id="local-gpu-01",
    )

    stats = collector.statistics(
        node_id="local-gpu-01",
        workload_type=WorkloadType.ALPR,
    )

    assert stats.executions == 2
    assert stats.successful == 1
    assert stats.failed == 1
    assert stats.success_rate == 0.5
    assert stats.failure_rate == 0.5


def test_rolling_window():

    collector = ExecutionTelemetryCollector(
        window_size=3,
    )

    request = make_request()

    for latency in [100, 200, 300, 400, 500]:

        result = make_result(
            request,
            latency_ms=latency,
        )

        collector.record_execution(
            request,
            result,
            node_id="local-gpu-01",
        )

    stats = collector.statistics(
        node_id="local-gpu-01",
        workload_type=WorkloadType.ALPR,
    )

    assert stats.executions == 3

    assert (
        stats.average_latency_ms
        == 400
    )


def test_workloads_are_tracked_separately():

    collector = ExecutionTelemetryCollector()

    alpr_request = make_request(
        workload_type=WorkloadType.ALPR,
    )

    behavior_request = make_request(
        workload_type=(
            WorkloadType.BEHAVIOR_ANALYSIS
        ),
    )

    collector.record_execution(
        alpr_request,
        make_result(
            alpr_request,
            latency_ms=100,
        ),
        node_id="local-gpu-01",
    )

    collector.record_execution(
        behavior_request,
        make_result(
            behavior_request,
            latency_ms=500,
        ),
        node_id="local-gpu-01",
    )

    alpr_stats = collector.statistics(
        node_id="local-gpu-01",
        workload_type=WorkloadType.ALPR,
    )

    behavior_stats = collector.statistics(
        node_id="local-gpu-01",
        workload_type=(
            WorkloadType.BEHAVIOR_ANALYSIS
        ),
    )

    assert (
        alpr_stats.average_latency_ms
        == 100
    )

    assert (
        behavior_stats.average_latency_ms
        == 500
    )


def test_empty_statistics():

    collector = ExecutionTelemetryCollector()

    stats = collector.statistics(
        node_id="unknown-node",
        workload_type=WorkloadType.ALPR,
    )

    assert stats.executions == 0
    assert stats.successful == 0
    assert stats.failed == 0
    assert stats.success_rate == 0.0
    assert stats.average_latency_ms == 0.0


def test_clear():

    collector = ExecutionTelemetryCollector()

    request = make_request()

    collector.record_execution(
        request,
        make_result(request),
        node_id="local-gpu-01",
    )

    assert collector.total_samples() == 1

    collector.clear()

    assert collector.total_samples() == 0