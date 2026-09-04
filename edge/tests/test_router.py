from __future__ import annotations

from uuid import uuid4

from sentinel_edge.alpr.engine import ALPRResult
from sentinel_edge.offload.edge_executor import EdgeExecutor
from sentinel_edge.offload.executor import ExecutionRequest
from sentinel_edge.offload.local_executor import LocalExecutor
from sentinel_edge.offload.models import (
    ExecutionTarget,
    Priority,
    WorkloadType,
)
from sentinel_edge.offload.registry import ExecutionRegistry
from sentinel_edge.offload.router import ExecutionRouter


class FakeALPREngine:
    """Deterministic ALPR engine for router tests."""

    def process(
        self,
        track_id: int,
        vehicle_crop,
        timestamp: float | None = None,
    ) -> ALPRResult:
        return ALPRResult(
            track_id=track_id,
            plate_text="TS10EF9999",
            plate_confidence=0.95,
            detector_confidence=0.90,
            recognized=True,
            timestamp=timestamp if timestamp is not None else 1.0,
        )


def make_request(
    target: ExecutionTarget,
    workload_type: WorkloadType = WorkloadType.ALPR,
) -> ExecutionRequest:
    return ExecutionRequest(
        request_id=uuid4(),
        camera_id="CAM-ROUTER-001",
        track_id=5,
        workload_type=workload_type,
        priority=Priority.HIGH,
        target=target,
        payload="vehicle-crop",
    )


def make_router(
    *,
    edge: bool = True,
    local: bool = True,
) -> ExecutionRouter:
    registry = ExecutionRegistry()

    if edge:
        registry.register(
            EdgeExecutor(
                "edge-01",
                alpr_engine=FakeALPREngine(),
            )
        )

    if local:
        registry.register(
            LocalExecutor(
                "local-01",
                alpr_engine=FakeALPREngine(),
            )
        )

    return ExecutionRouter(registry)


def test_router_resolves_edge_executor():
    router = make_router()

    request = make_request(
        ExecutionTarget.EDGE
    )

    executor = router.resolve(request)

    assert executor is not None
    assert executor.executor_id == "edge-01"
    assert executor.target == ExecutionTarget.EDGE


def test_router_resolves_local_executor():
    router = make_router()

    request = make_request(
        ExecutionTarget.LOCAL
    )

    executor = router.resolve(request)

    assert executor is not None
    assert executor.executor_id == "local-01"
    assert executor.target == ExecutionTarget.LOCAL


def test_router_returns_none_when_target_executor_missing():
    router = make_router(
        edge=True,
        local=False,
    )

    request = make_request(
        ExecutionTarget.LOCAL
    )

    assert router.resolve(request) is None


def test_router_rejects_unsupported_workload():
    router = make_router()

    request = make_request(
        ExecutionTarget.EDGE,
        workload_type=WorkloadType.REID,
    )

    assert router.resolve(request) is None


def test_router_executes_edge_request():
    router = make_router()

    request = make_request(
        ExecutionTarget.EDGE
    )

    result = router.route(request)

    assert result.success is True
    assert result.target == ExecutionTarget.EDGE
    assert result.workload_type == WorkloadType.ALPR
    assert result.executor_id == "edge-01"
    assert result.result["plate_text"] == "TS10EF9999"


def test_router_executes_local_request():
    router = make_router()

    request = make_request(
        ExecutionTarget.LOCAL
    )

    result = router.route(request)

    assert result.success is True
    assert result.target == ExecutionTarget.LOCAL
    assert result.workload_type == WorkloadType.ALPR
    assert result.executor_id == "local-01"
    assert result.result["plate_text"] == "TS10EF9999"


def test_router_returns_failure_when_no_executor_exists():
    router = make_router(
        edge=False,
        local=False,
    )

    request = make_request(
        ExecutionTarget.EDGE
    )

    result = router.route(request)

    assert result.success is False
    assert result.target == ExecutionTarget.EDGE
    assert result.workload_type == WorkloadType.ALPR
    assert result.executor_id == "router"
    assert result.error is not None
    assert "No executor available" in result.error


def test_router_returns_failure_for_unsupported_workload():
    router = make_router()

    request = make_request(
        ExecutionTarget.EDGE,
        workload_type=WorkloadType.REID,
    )

    result = router.route(request)

    assert result.success is False
    assert result.error is not None
    assert "No executor available" in result.error


def test_router_preserves_request_id():
    router = make_router()

    request = make_request(
        ExecutionTarget.LOCAL
    )

    result = router.route(request)

    assert result.request_id == request.request_id


def test_router_reports_target_availability():
    router = make_router()

    assert router.has_executor(
        ExecutionTarget.EDGE
    )

    assert router.has_executor(
        ExecutionTarget.LOCAL
    )

    assert not router.has_executor(
        ExecutionTarget.CLOUD
    )