from __future__ import annotations

from uuid import uuid4

from sentinel_edge.alpr.engine import ALPRResult
from sentinel_edge.offload.edge_executor import EdgeExecutor
from sentinel_edge.offload.executor import (
    ExecutionRequest,
    ExecutionResult,
    WorkloadExecutor,
)
from sentinel_edge.offload.local_executor import LocalExecutor
from sentinel_edge.offload.models import (
    ExecutionTarget,
    Priority,
    WorkloadType,
)
from sentinel_edge.offload.registry import ExecutionRegistry
from sentinel_edge.offload.router import ExecutionRouter
from sentinel_edge.offload.telemetry import (
    ExecutionTelemetryCollector,
)


class FakeALPREngine:
    """Deterministic ALPR engine for telemetry router tests."""

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
            timestamp=(
                timestamp
                if timestamp is not None
                else 1.0
            ),
        )


class FailingExecutor(WorkloadExecutor):
    """Executor that deliberately returns a failed result."""

    def __init__(
        self,
        executor_id: str = "failing-executor",
    ) -> None:
        super().__init__(
            executor_id=executor_id,
            target=ExecutionTarget.LOCAL,
        )

    def supports(
        self,
        workload_type: WorkloadType,
    ) -> bool:
        return workload_type == WorkloadType.ALPR

    def execute(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        return ExecutionResult(
            request_id=request.request_id,
            success=False,
            target=request.target,
            workload_type=request.workload_type,
            latency_ms=42.5,
            result=None,
            error="simulated execution failure",
            executor_id=self.executor_id,
        )

def make_request(
    target: ExecutionTarget,
    *,
    scheduled_node_id: str | None = None,
    workload_type: WorkloadType = WorkloadType.ALPR,
) -> ExecutionRequest:
    metadata = {}

    if scheduled_node_id is not None:
        metadata["scheduled_node_id"] = scheduled_node_id

    return ExecutionRequest(
        request_id=uuid4(),
        camera_id="CAM-TELEMETRY-001",
        track_id=5,
        workload_type=workload_type,
        priority=Priority.HIGH,
        target=target,
        payload="vehicle-crop",
        metadata=metadata,
    )


def make_router_with_telemetry(
    *,
    edge: bool = True,
    local: bool = True,
    window_size: int = 100,
):
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

    collector = ExecutionTelemetryCollector(
        window_size=window_size,
    )

    router = ExecutionRouter(
        registry,
        telemetry_collector=collector,
    )

    return router, collector


def test_successful_edge_execution_records_telemetry():
    router, collector = make_router_with_telemetry()

    request = make_request(
        ExecutionTarget.EDGE,
        scheduled_node_id="edge-node-01",
    )

    result = router.route(request)

    assert result.success is True
    assert collector.total_samples() == 1

    samples = collector.samples(
        node_id="edge-node-01",
        workload_type=WorkloadType.ALPR,
    )

    assert len(samples) == 1

    telemetry = samples[0]

    assert telemetry.request_id == str(
        request.request_id
    )
    assert telemetry.executor_id == "edge-01"
    assert telemetry.node_id == "edge-node-01"
    assert telemetry.target == ExecutionTarget.EDGE
    assert telemetry.workload_type == WorkloadType.ALPR
    assert telemetry.success is True
    assert telemetry.latency_ms >= 0


def test_successful_local_execution_records_telemetry():
    router, collector = make_router_with_telemetry()

    request = make_request(
        ExecutionTarget.LOCAL,
        scheduled_node_id="local-gpu-01",
    )

    result = router.route(request)

    assert result.success is True
    assert collector.total_samples() == 1

    stats = collector.statistics(
        node_id="local-gpu-01",
        workload_type=WorkloadType.ALPR,
    )

    assert stats.executions == 1
    assert stats.successful == 1
    assert stats.failed == 0
    assert stats.success_rate == 1.0
    assert stats.average_latency_ms >= 0


def test_failed_execution_records_telemetry():
    registry = ExecutionRegistry()

    failing_executor = FailingExecutor(
        "local-failing-01"
    )

    registry.register(failing_executor)

    collector = ExecutionTelemetryCollector()

    router = ExecutionRouter(
        registry,
        telemetry_collector=collector,
    )

    request = make_request(
        ExecutionTarget.LOCAL,
        scheduled_node_id="local-gpu-01",
    )

    result = router.route(request)

    assert result.success is False
    assert result.error == "simulated execution failure"

    assert collector.total_samples() == 1

    samples = collector.samples(
        node_id="local-gpu-01",
        workload_type=WorkloadType.ALPR,
    )

    assert len(samples) == 1

    telemetry = samples[0]

    assert telemetry.success is False
    assert telemetry.executor_id == "local-failing-01"
    assert telemetry.error == "simulated execution failure"
    assert telemetry.latency_ms == 42.5


def test_missing_executor_records_failed_telemetry():
    router, collector = make_router_with_telemetry(
        edge=False,
        local=False,
    )

    request = make_request(
        ExecutionTarget.CLOUD,
        scheduled_node_id="cloud-gpu-01",
    )

    result = router.route(request)

    assert result.success is False
    assert result.executor_id == "router"

    assert collector.total_samples() == 1

    samples = collector.samples(
        node_id="cloud-gpu-01",
        workload_type=WorkloadType.ALPR,
    )

    assert len(samples) == 1

    telemetry = samples[0]

    assert telemetry.success is False
    assert telemetry.executor_id == "router"
    assert telemetry.target == ExecutionTarget.CLOUD
    assert telemetry.latency_ms == 0.0
    assert telemetry.error is not None
    assert "No executor available" in telemetry.error


def test_unsupported_workload_records_failed_telemetry():
    router, collector = make_router_with_telemetry()

    request = make_request(
        ExecutionTarget.EDGE,
        scheduled_node_id="edge-node-01",
        workload_type=WorkloadType.REID,
    )

    result = router.route(request)

    assert result.success is False

    assert collector.total_samples() == 1

    stats = collector.statistics(
        node_id="edge-node-01",
        workload_type=WorkloadType.REID,
    )

    assert stats.executions == 1
    assert stats.successful == 0
    assert stats.failed == 1
    assert stats.success_rate == 0.0


def test_telemetry_groups_by_scheduled_node():
    router, collector = make_router_with_telemetry()

    request_1 = make_request(
        ExecutionTarget.LOCAL,
        scheduled_node_id="local-gpu-01",
    )

    request_2 = make_request(
        ExecutionTarget.LOCAL,
        scheduled_node_id="local-gpu-02",
    )

    router.route(request_1)
    router.route(request_2)

    assert collector.total_samples() == 2

    node_1_stats = collector.statistics(
        node_id="local-gpu-01",
        workload_type=WorkloadType.ALPR,
    )

    node_2_stats = collector.statistics(
        node_id="local-gpu-02",
        workload_type=WorkloadType.ALPR,
    )

    assert node_1_stats.executions == 1
    assert node_2_stats.executions == 1


def test_telemetry_falls_back_to_executor_identity():
    router, collector = make_router_with_telemetry()

    request = make_request(
        ExecutionTarget.LOCAL,
        scheduled_node_id=None,
    )

    result = router.route(request)

    assert result.success is True
    assert collector.total_samples() == 1

    samples = collector.samples(
        executor_id="local-01",
        workload_type=WorkloadType.ALPR,
    )

    assert len(samples) == 1
    assert samples[0].node_id is None
    assert samples[0].executor_id == "local-01"


def test_router_works_without_telemetry_collector():
    router, collector = make_router_with_telemetry()

    # Construct a second router using the same registry but
    # without telemetry instrumentation.
    plain_router = ExecutionRouter(
        router.registry,
    )

    request = make_request(
        ExecutionTarget.LOCAL,
        scheduled_node_id="local-gpu-01",
    )

    result = plain_router.route(request)

    assert result.success is True

    # The original collector was not used by plain_router.
    assert collector.total_samples() == 0


def test_telemetry_rolling_window_is_respected():
    router, collector = make_router_with_telemetry(
        window_size=2,
    )

    for _ in range(3):
        request = make_request(
            ExecutionTarget.LOCAL,
            scheduled_node_id="local-gpu-01",
        )

        router.route(request)

    assert collector.total_samples() == 2

    stats = collector.statistics(
        node_id="local-gpu-01",
        workload_type=WorkloadType.ALPR,
    )

    assert stats.executions == 2
    assert stats.successful == 2