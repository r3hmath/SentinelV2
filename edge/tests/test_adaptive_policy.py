from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sentinel_edge.offload.adaptive_policy import (
    AdaptivePolicyConfig,
    AdaptiveSchedulingPolicy,
)
from sentinel_edge.offload.models import (
    ExecutionTarget,
    NodeHealth,
    Priority,
    WorkloadProfile,
    WorkloadType,
)
from sentinel_edge.offload.policy import SchedulingPolicy
from sentinel_edge.offload.telemetry import (
    ExecutionTelemetry,
    ExecutionTelemetryCollector,
)


def make_node(
    node_id: str = "local-gpu-01",
) -> NodeHealth:
    return NodeHealth(
        node_id=node_id,
        target=ExecutionTarget.LOCAL,
        cpu_percent=40.0,
        gpu_percent=45.0,
        memory_percent=50.0,
        network_latency_ms=2.0,
        bandwidth_mbps=1000.0,
        queue_depth=0,
        max_queue_depth=10,
        available=True,
        gpu_available=True,
    )


def make_workload() -> WorkloadProfile:
    return WorkloadProfile(
        workload_type=WorkloadType.ALPR,
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


def record_samples(
    collector: ExecutionTelemetryCollector,
    *,
    node_id: str,
    latency_ms: float,
    success: bool,
    count: int = 5,
) -> None:
    for _ in range(count):
        collector.record(
            ExecutionTelemetry(
                request_id=str(uuid4()),
                executor_id="local-executor-01",
                node_id=node_id,
                target=ExecutionTarget.LOCAL,
                workload_type=WorkloadType.ALPR,
                success=success,
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
                error=(
                    None
                    if success
                    else "simulated failure"
                ),
            )
        )


def test_no_telemetry_returns_base_score():
    base_policy = SchedulingPolicy()

    adaptive_policy = AdaptiveSchedulingPolicy(
        base_policy=base_policy,
        telemetry_collector=None,
    )

    node = make_node()
    workload = make_workload()

    assert (
        adaptive_policy.score(node, workload)
        == base_policy.score(node, workload)
    )


def test_insufficient_samples_do_not_change_score():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-gpu-01",
        latency_ms=100.0,
        success=True,
        count=4,
    )

    base_policy = SchedulingPolicy()

    adaptive_policy = AdaptiveSchedulingPolicy(
        base_policy=base_policy,
        telemetry_collector=collector,
    )

    node = make_node()
    workload = make_workload()

    assert (
        adaptive_policy.telemetry_adjustment(
            node,
            workload,
        )
        == 0.0
    )


def test_healthy_telemetry_produces_positive_adjustment():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-gpu-01",
        latency_ms=20.0,
        success=True,
        count=5,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(),
    )

    assert adjustment > 0.0
    assert adjustment <= policy.config.maximum_bonus


def test_poor_latency_produces_negative_adjustment():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-gpu-01",
        latency_ms=200.0,
        success=True,
        count=5,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(),
    )

    assert adjustment < 0.0
    assert adjustment >= -policy.config.maximum_penalty


def test_poor_reliability_produces_negative_adjustment():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-gpu-01",
        latency_ms=50.0,
        success=False,
        count=5,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(),
    )

    assert adjustment < 0.0
    assert adjustment >= -policy.config.maximum_penalty


def test_adjustment_is_bounded():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-gpu-01",
        latency_ms=5000.0,
        success=False,
        count=20,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(),
    )

    assert (
        adjustment
        >= -policy.config.maximum_penalty
    )

    assert (
        adjustment
        <= policy.config.maximum_bonus
    )


def test_adaptive_score_remains_between_zero_and_one():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-gpu-01",
        latency_ms=5000.0,
        success=False,
        count=20,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    score = policy.score(
        make_node(),
        make_workload(),
    )

    assert 0.0 <= score <= 1.0


def test_different_nodes_have_independent_feedback():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-gpu-01",
        latency_ms=20.0,
        success=True,
        count=5,
    )

    record_samples(
        collector,
        node_id="local-gpu-02",
        latency_ms=300.0,
        success=False,
        count=5,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    workload = make_workload()

    healthy_adjustment = policy.telemetry_adjustment(
        make_node("local-gpu-01"),
        workload,
    )

    poor_adjustment = policy.telemetry_adjustment(
        make_node("local-gpu-02"),
        workload,
    )

    assert healthy_adjustment > poor_adjustment


def test_different_workloads_have_independent_feedback():
    collector = ExecutionTelemetryCollector()

    for _ in range(5):
        collector.record(
            ExecutionTelemetry(
                request_id=str(uuid4()),
                executor_id="local-executor-01",
                node_id="local-gpu-01",
                target=ExecutionTarget.LOCAL,
                workload_type=WorkloadType.ALPR,
                success=True,
                latency_ms=20.0,
                timestamp=datetime.now(timezone.utc),
            )
        )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    alpr_adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(),
    )

    reid_workload = WorkloadProfile(
        workload_type=WorkloadType.REID,
        priority=Priority.HIGH,
        estimated_compute_ms=50.0,
        minimum_gpu=0.0,
        minimum_memory_percent=5.0,
        maximum_latency_ms=500.0,
        minimum_bandwidth_mbps=1.0,
        allow_edge=False,
        allow_local=True,
        allow_cloud=False,
)

    reid_adjustment = policy.telemetry_adjustment(
        make_node(),
        reid_workload,
    )

    assert alpr_adjustment > 0.0
    assert reid_adjustment == 0.0