from datetime import datetime, timezone
from uuid import uuid4

from sentinel_edge.offload.adaptive_policy import AdaptiveSchedulingPolicy
from sentinel_edge.offload.health import NodeHealthRegistry
from sentinel_edge.offload.models import (
    ExecutionTarget,
    NodeHealth,
    Priority,
    WorkloadProfile,
    WorkloadType,
)
from sentinel_edge.offload.scheduler import OffloadScheduler
from sentinel_edge.offload.telemetry import (
    ExecutionTelemetry,
    ExecutionTelemetryCollector,
)


def make_workload(
    workload_type: WorkloadType = WorkloadType.ALPR,
) -> WorkloadProfile:
    return WorkloadProfile(
        workload_type=workload_type,
        priority=Priority.HIGH,
        estimated_compute_ms=50.0,
        minimum_gpu=0.0,
        minimum_memory_percent=5.0,
        maximum_latency_ms=500.0,
        minimum_bandwidth_mbps=1.0,
        allow_edge=True,
        allow_local=True,
        allow_cloud=True,
    )


def make_node(
    node_id: str,
    target: ExecutionTarget,
    *,
    network_latency_ms: float = 10.0,
    cpu_percent: float = 40.0,
    gpu_percent: float = 40.0,
) -> NodeHealth:
    return NodeHealth(
        node_id=node_id,
        target=target,
        cpu_percent=cpu_percent,
        gpu_percent=gpu_percent,
        memory_percent=40.0,
        network_latency_ms=network_latency_ms,
        bandwidth_mbps=1000.0,
        queue_depth=0,
        available=True,
        gpu_available=True,
        max_queue_depth=10,
    )


def record_samples(
    collector: ExecutionTelemetryCollector,
    *,
    node_id: str,
    target: ExecutionTarget,
    latency_ms: float,
    success: bool,
    workload_type: WorkloadType = WorkloadType.ALPR,
    count: int = 5,
) -> None:
    for _ in range(count):
        collector.record(
            ExecutionTelemetry(
                request_id=str(uuid4()),
                executor_id=f"executor-{node_id}",
                node_id=node_id,
                target=target,
                workload_type=workload_type,
                success=success,
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
                error=None if success else "execution failed",
            )
        )


def make_registry(*nodes: NodeHealth) -> NodeHealthRegistry:
    registry = NodeHealthRegistry()

    for node in nodes:
        registry.register(node)

    return registry


def test_scheduler_without_telemetry_uses_base_policy():
    registry = make_registry(
        make_node("edge-01", ExecutionTarget.EDGE),
    )

    scheduler = OffloadScheduler(
        health_registry=registry,
    )

    assert not isinstance(
        scheduler.policy,
        AdaptiveSchedulingPolicy,
    )


def test_scheduler_with_telemetry_uses_adaptive_policy():
    collector = ExecutionTelemetryCollector()

    registry = make_registry(
        make_node("edge-01", ExecutionTarget.EDGE),
    )

    scheduler = OffloadScheduler(
        health_registry=registry,
        telemetry_collector=collector,
    )

    assert isinstance(
        scheduler.policy,
        AdaptiveSchedulingPolicy,
    )


def test_scheduler_accepts_custom_base_policy_with_telemetry():
    from sentinel_edge.offload.policy import SchedulingPolicy

    base_policy = SchedulingPolicy()
    collector = ExecutionTelemetryCollector()

    registry = make_registry(
        make_node("edge-01", ExecutionTarget.EDGE),
    )

    scheduler = OffloadScheduler(
        health_registry=registry,
        policy=base_policy,
        telemetry_collector=collector,
    )

    assert isinstance(
        scheduler.policy,
        AdaptiveSchedulingPolicy,
    )

    assert scheduler.policy.base_policy is base_policy


def test_scheduler_telemetry_can_reduce_poor_node_score():
    collector = ExecutionTelemetryCollector()

    edge = make_node(
        "edge-01",
        ExecutionTarget.EDGE,
        network_latency_ms=10.0,
    )

    local = make_node(
        "local-01",
        ExecutionTarget.LOCAL,
        network_latency_ms=10.0,
    )

    registry = make_registry(edge, local)

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=5000.0,
        success=False,
        count=20,
    )

    scheduler = OffloadScheduler(
        health_registry=registry,
        telemetry_collector=collector,
    )

    workload = make_workload()

    edge_score = scheduler.policy.score(
        edge,
        workload,
    )

    local_score = scheduler.policy.score(
        local,
        workload,
    )

    assert local_score < edge_score


def test_scheduler_ranking_uses_adaptive_score():
    collector = ExecutionTelemetryCollector()

    edge = make_node(
        "edge-01",
        ExecutionTarget.EDGE,
        network_latency_ms=10.0,
    )

    local = make_node(
        "local-01",
        ExecutionTarget.LOCAL,
        network_latency_ms=10.0,
    )

    registry = make_registry(edge, local)

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=5000.0,
        success=False,
        count=20,
    )

    scheduler = OffloadScheduler(
        health_registry=registry,
        telemetry_collector=collector,
    )

    result = scheduler.schedule(
        make_workload(),
    )

    assert result.decision.accepted is True
    assert result.decision.node_id == "edge-01"
    assert result.decision.candidates[0] == "edge-01"


def test_scheduler_without_telemetry_preserves_normal_ranking():
    edge = make_node(
        "edge-01",
        ExecutionTarget.EDGE,
        network_latency_ms=5.0,
    )

    local = make_node(
        "local-01",
        ExecutionTarget.LOCAL,
        network_latency_ms=10.0,
    )

    registry = make_registry(edge, local)

    scheduler = OffloadScheduler(
        health_registry=registry,
    )

    result = scheduler.schedule(
        make_workload(),
    )

    assert result.decision.accepted is True
    assert result.decision.node_id == "edge-01"


def test_scheduler_adaptive_feedback_is_workload_specific():
    collector = ExecutionTelemetryCollector()

    edge = make_node(
        "edge-01",
        ExecutionTarget.EDGE,
        network_latency_ms=10.0,
    )

    local = make_node(
        "local-01",
        ExecutionTarget.LOCAL,
        network_latency_ms=10.0,
    )

    registry = make_registry(edge, local)

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=5000.0,
        success=False,
        workload_type=WorkloadType.ALPR,
        count=20,
    )

    scheduler = OffloadScheduler(
        health_registry=registry,
        telemetry_collector=collector,
    )

    alpr_score = scheduler.policy.score(
        local,
        make_workload(WorkloadType.ALPR),
    )

    reid_score = scheduler.policy.score(
        local,
        make_workload(WorkloadType.REID),
    )

    assert alpr_score < reid_score


def test_scheduler_adaptive_feedback_is_node_specific():
    collector = ExecutionTelemetryCollector()

    healthy = make_node(
        "local-01",
        ExecutionTarget.LOCAL,
        network_latency_ms=10.0,
    )

    unhealthy = make_node(
        "local-02",
        ExecutionTarget.LOCAL,
        network_latency_ms=10.0,
    )

    registry = make_registry(
        healthy,
        unhealthy,
    )

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=20.0,
        success=True,
        count=10,
    )

    record_samples(
        collector,
        node_id="local-02",
        target=ExecutionTarget.LOCAL,
        latency_ms=5000.0,
        success=False,
        count=10,
    )

    scheduler = OffloadScheduler(
        health_registry=registry,
        telemetry_collector=collector,
    )

    workload = make_workload()

    healthy_score = scheduler.policy.score(
        healthy,
        workload,
    )

    unhealthy_score = scheduler.policy.score(
        unhealthy,
        workload,
    )

    assert healthy_score > unhealthy_score


def test_schedule_with_preferred_target_uses_adaptive_score():
    collector = ExecutionTelemetryCollector()

    edge = make_node(
        "edge-01",
        ExecutionTarget.EDGE,
        network_latency_ms=10.0,
    )

    local = make_node(
        "local-01",
        ExecutionTarget.LOCAL,
        network_latency_ms=10.0,
    )

    registry = make_registry(
        edge,
        local,
    )

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=5000.0,
        success=False,
        count=20,
    )

    scheduler = OffloadScheduler(
        health_registry=registry,
        telemetry_collector=collector,
    )

    result = scheduler.schedule_with_preferred_target(
        make_workload(),
        ExecutionTarget.LOCAL,
    )

    # Preferred LOCAL is available, so the scheduler intentionally
    # honors the preferred target. Adaptive feedback determines
    # which LOCAL node would win among multiple LOCAL candidates.
    assert result.decision.accepted is True
    assert result.decision.target == ExecutionTarget.LOCAL
    assert result.decision.node_id == "local-01"
    assert result.decision.fallback_used is False