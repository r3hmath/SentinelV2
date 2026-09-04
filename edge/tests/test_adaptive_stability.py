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
from sentinel_edge.offload.telemetry import (
    ExecutionTelemetry,
    ExecutionTelemetryCollector,
)


def make_node(
    node_id: str = "local-01",
) -> NodeHealth:
    return NodeHealth(
        node_id=node_id,
        target=ExecutionTarget.LOCAL,
        cpu_percent=40.0,
        gpu_percent=40.0,
        memory_percent=40.0,
        network_latency_ms=10.0,
        bandwidth_mbps=1000.0,
        queue_depth=0,
        available=True,
        gpu_available=True,
        max_queue_depth=10,
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


def record_sample(
    collector: ExecutionTelemetryCollector,
    *,
    node_id: str,
    workload_type: WorkloadType = WorkloadType.ALPR,
    latency_ms: float = 50.0,
    success: bool = True,
    target: ExecutionTarget = ExecutionTarget.LOCAL,
) -> None:
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


def record_samples(
    collector: ExecutionTelemetryCollector,
    *,
    node_id: str,
    count: int,
    workload_type: WorkloadType = WorkloadType.ALPR,
    latency_ms: float = 50.0,
    success: bool = True,
) -> None:
    for _ in range(count):
        record_sample(
            collector,
            node_id=node_id,
            workload_type=workload_type,
            latency_ms=latency_ms,
            success=success,
        )


def test_warmup_protection_requires_minimum_samples():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        count=4,
        latency_ms=5000.0,
        success=False,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(),
    )

    assert adjustment == 0.0


def test_single_failure_does_not_trigger_maximum_penalty():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        count=5,
        latency_ms=50.0,
        success=True,
    )

    record_sample(
        collector,
        node_id="local-01",
        latency_ms=50.0,
        success=False,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(),
    )

    assert adjustment > -policy.config.maximum_penalty


def test_healthy_execution_produces_small_positive_adjustment():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        count=20,
        latency_ms=20.0,
        success=True,
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


def test_persistent_bad_execution_is_penalized():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        count=20,
        latency_ms=5000.0,
        success=False,
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


def test_adaptive_score_is_always_bounded():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        count=100,
        latency_ms=100000.0,
        success=False,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    score = policy.score(
        make_node(),
        make_workload(),
    )

    assert 0.0 <= score <= 1.0


def test_worsening_telemetry_cannot_improve_score():
    collector_healthy = ExecutionTelemetryCollector()
    collector_poor = ExecutionTelemetryCollector()

    record_samples(
        collector_healthy,
        node_id="local-01",
        count=20,
        latency_ms=20.0,
        success=True,
    )

    record_samples(
        collector_poor,
        node_id="local-01",
        count=20,
        latency_ms=5000.0,
        success=False,
    )

    node = make_node()
    workload = make_workload()

    healthy_policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector_healthy,
    )

    poor_policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector_poor,
    )

    healthy_score = healthy_policy.score(
        node,
        workload,
    )

    poor_score = poor_policy.score(
        node,
        workload,
    )

    assert poor_score < healthy_score


def test_workload_feedback_is_isolated():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        workload_type=WorkloadType.ALPR,
        count=20,
        latency_ms=5000.0,
        success=False,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    alpr_adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(WorkloadType.ALPR),
    )

    reid_adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(WorkloadType.REID),
    )

    assert alpr_adjustment < 0.0
    assert reid_adjustment == 0.0


def test_node_feedback_is_isolated():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-bad",
        count=20,
        latency_ms=5000.0,
        success=False,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    bad_adjustment = policy.telemetry_adjustment(
        make_node("local-bad"),
        make_workload(),
    )

    unknown_adjustment = policy.telemetry_adjustment(
        make_node("local-unknown"),
        make_workload(),
    )

    assert bad_adjustment < 0.0
    assert unknown_adjustment == 0.0


def test_recovery_occurs_when_bad_samples_leave_rolling_window():
    collector = ExecutionTelemetryCollector(
        window_size=10,
    )

    record_samples(
        collector,
        node_id="local-01",
        count=10,
        latency_ms=5000.0,
        success=False,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    bad_adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(),
    )

    assert bad_adjustment < 0.0

    # Add healthy samples until the old failures roll out.
    record_samples(
        collector,
        node_id="local-01",
        count=10,
        latency_ms=20.0,
        success=True,
    )

    recovered_adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(),
    )

    assert recovered_adjustment > 0.0


def test_custom_config_can_make_adaptation_more_conservative():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        count=20,
        latency_ms=5000.0,
        success=False,
    )

    conservative_config = AdaptivePolicyConfig(
        maximum_penalty=0.05,
        maximum_bonus=0.01,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
        config=conservative_config,
    )

    adjustment = policy.telemetry_adjustment(
        make_node(),
        make_workload(),
    )

    assert adjustment >= -0.05
    assert adjustment <= 0.01