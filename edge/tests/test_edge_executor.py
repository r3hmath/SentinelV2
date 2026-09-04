from __future__ import annotations

from uuid import uuid4

import pytest

from sentinel_edge.alpr.engine import ALPRResult
from sentinel_edge.offload.edge_executor import EdgeExecutor
from sentinel_edge.offload.executor import ExecutionRequest
from sentinel_edge.offload.models import (
    ExecutionTarget,
    Priority,
    WorkloadType,
)


class FakeALPREngine:
    """Deterministic ALPR engine for executor unit tests."""

    def __init__(self) -> None:
        self.calls = []

    def process(
        self,
        track_id: int,
        vehicle_crop,
        timestamp: float | None = None,
    ) -> ALPRResult:
        self.calls.append(
            {
                "track_id": track_id,
                "vehicle_crop": vehicle_crop,
                "timestamp": timestamp,
            }
        )

        return ALPRResult(
            track_id=track_id,
            plate_text="KA01AB1234",
            plate_confidence=0.91,
            detector_confidence=0.87,
            recognized=True,
            timestamp=timestamp if timestamp is not None else 123.0,
        )


def make_request(
    *,
    target: ExecutionTarget = ExecutionTarget.EDGE,
    workload_type: WorkloadType = WorkloadType.ALPR,
    payload="vehicle-crop",
    metadata=None,
) -> ExecutionRequest:
    return ExecutionRequest(
        request_id=uuid4(),
        camera_id="CAM-001",
        track_id=7,
        workload_type=workload_type,
        priority=Priority.HIGH,
        target=target,
        payload=payload,
        metadata=metadata or {},
    )


def test_edge_executor_has_edge_target():
    executor = EdgeExecutor("edge-executor-01")

    assert executor.target == ExecutionTarget.EDGE
    assert executor.executor_id == "edge-executor-01"


def test_edge_executor_supports_alpr():
    executor = EdgeExecutor("edge-executor-01")

    assert executor.supports(WorkloadType.ALPR)


def test_edge_executor_rejects_unsupported_workload():
    executor = EdgeExecutor("edge-executor-01")

    assert not executor.supports(
        WorkloadType.THREAT_CLASSIFICATION
    )


def test_edge_executor_rejects_target_mismatch():
    engine = FakeALPREngine()
    executor = EdgeExecutor(
        "edge-executor-01",
        alpr_engine=engine,
    )

    request = make_request(
        target=ExecutionTarget.LOCAL,
    )

    result = executor.execute(request)

    assert result.success is False
    assert result.target == ExecutionTarget.EDGE
    assert result.error is not None
    assert "Target mismatch" in result.error


def test_edge_executor_rejects_unsupported_workload():
    engine = FakeALPREngine()
    executor = EdgeExecutor(
        "edge-executor-01",
        alpr_engine=engine,
    )

    request = make_request(
        workload_type=WorkloadType.REID,
    )

    result = executor.execute(request)

    assert result.success is False
    assert result.error is not None
    assert "Unsupported workload type" in result.error


def test_edge_executor_fails_when_alpr_engine_missing():
    executor = EdgeExecutor("edge-executor-01")

    request = make_request()

    result = executor.execute(request)

    assert result.success is False
    assert result.error is not None
    assert "ALPR engine is not configured" in result.error


def test_edge_executor_executes_alpr():
    engine = FakeALPREngine()

    executor = EdgeExecutor(
        "edge-executor-01",
        alpr_engine=engine,
    )

    request = make_request(
        payload="fake-vehicle-crop",
        metadata={"timestamp": 42.5},
    )

    result = executor.execute(request)

    assert result.success is True
    assert result.target == ExecutionTarget.EDGE
    assert result.workload_type == WorkloadType.ALPR
    assert result.error is None

    assert result.result["track_id"] == 7
    assert result.result["plate_text"] == "KA01AB1234"
    assert result.result["recognized"] is True

    assert len(engine.calls) == 1
    assert engine.calls[0]["track_id"] == 7
    assert engine.calls[0]["vehicle_crop"] == "fake-vehicle-crop"
    assert engine.calls[0]["timestamp"] == 42.5


def test_edge_executor_returns_execution_latency():
    engine = FakeALPREngine()

    executor = EdgeExecutor(
        "edge-executor-01",
        alpr_engine=engine,
    )

    request = make_request()

    result = executor.execute(request)

    assert result.success is True
    assert result.latency_ms >= 0


def test_edge_executor_converts_runtime_failure_to_result():
    class FailingALPREngine:
        def process(
            self,
            track_id: int,
            vehicle_crop,
            timestamp: float | None = None,
        ):
            raise RuntimeError("simulated ALPR failure")

    executor = EdgeExecutor(
        "edge-executor-01",
        alpr_engine=FailingALPREngine(),
    )

    request = make_request()

    result = executor.execute(request)

    assert result.success is False
    assert result.error == "simulated ALPR failure"
    assert result.result is None
    assert result.executor_id == "edge-executor-01"
    assert result.latency_ms >= 0


def test_edge_executor_preserves_request_id():
    engine = FakeALPREngine()

    executor = EdgeExecutor(
        "edge-executor-01",
        alpr_engine=engine,
    )

    request = make_request()

    result = executor.execute(request)

    assert result.request_id == request.request_id