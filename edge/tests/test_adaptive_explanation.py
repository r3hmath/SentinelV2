from datetime import datetime, timezone
from uuid import uuid4

from sentinel_edge.offload.adaptive_policy import (
    AdaptiveSchedulingPolicy,
)
from sentinel_edge.offload.health import NodeHealthRegistry
from sentinel_edge.offload.models import (
    AdaptiveDecisionExplanation,
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
    node_id: str = "local-01",
    target: ExecutionTarget = ExecutionTarget.LOCAL,
) -> NodeHealth:
    return NodeHealth(
        node_id=node_id,
        target=target,
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


def make_registry(
    *nodes: NodeHealth,
) -> NodeHealthRegistry:
    registry = NodeHealthRegistry()

    for node in nodes:
        registry.register(node)

    return registry


def test_explanation_without_telemetry_is_inactive():
    policy = AdaptiveSchedulingPolicy()

    explanation = policy.explain(
        make_node(),
        make_workload(),
    )

    assert isinstance(
        explanation,
        AdaptiveDecisionExplanation,
    )

    assert explanation.adaptation_active is False
    assert explanation.telemetry_samples == 0
    assert explanation.adaptive_adjustment == 0.0


def test_explanation_during_warmup_is_inactive():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=50.0,
        success=True,
        count=4,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    explanation = policy.explain(
        make_node(),
        make_workload(),
    )

    assert explanation.adaptation_active is False
    assert explanation.telemetry_samples == 4
    assert explanation.adaptive_adjustment == 0.0


def test_healthy_telemetry_produces_positive_explanation():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=20.0,
        success=True,
        count=10,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    explanation = policy.explain(
        make_node(),
        make_workload(),
    )

    assert explanation.adaptation_active is True
    assert explanation.telemetry_samples == 10
    assert explanation.success_rate == 1.0
    assert explanation.average_latency_ms == 20.0

    assert explanation.latency_adjustment > 0
    assert explanation.reliability_adjustment > 0
    assert explanation.adaptive_adjustment > 0


def test_bad_telemetry_produces_negative_explanation():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=5000.0,
        success=False,
        count=20,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    explanation = policy.explain(
        make_node(),
        make_workload(),
    )

    assert explanation.adaptation_active is True
    assert explanation.latency_adjustment < 0
    assert explanation.reliability_adjustment < 0
    assert explanation.adaptive_adjustment < 0


def test_explanation_adjustment_arithmetic_is_consistent():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=60.0,
        success=True,
        count=10,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    explanation = policy.explain(
        make_node(),
        make_workload(),
    )

    expected = (
        explanation.latency_adjustment
        + explanation.reliability_adjustment
    )

    assert (
        explanation.adaptive_adjustment
        == expected
    )


def test_score_matches_explanation_final_score():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=60.0,
        success=True,
        count=10,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    node = make_node()
    workload = make_workload()

    score = policy.score(
        node,
        workload,
    )

    explanation = policy.explain(
        node,
        workload,
    )

    assert score == explanation.final_score


def test_explanation_is_node_specific():
    collector = ExecutionTelemetryCollector()

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

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    workload = make_workload()

    healthy = policy.explain(
        make_node("local-01"),
        workload,
    )

    unhealthy = policy.explain(
        make_node("local-02"),
        workload,
    )

    assert healthy.adaptive_adjustment > 0
    assert unhealthy.adaptive_adjustment < 0


def test_explanation_is_workload_specific():
    collector = ExecutionTelemetryCollector()

    record_samples(
        collector,
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
        latency_ms=5000.0,
        success=False,
        workload_type=WorkloadType.ALPR,
        count=10,
    )

    policy = AdaptiveSchedulingPolicy(
        telemetry_collector=collector,
    )

    alpr = policy.explain(
        make_node(),
        make_workload(WorkloadType.ALPR),
    )

    reid = policy.explain(
        make_node(),
        make_workload(WorkloadType.REID),
    )

    assert alpr.adaptive_adjustment < 0
    assert reid.adaptive_adjustment == 0.0


def test_scheduler_exposes_selected_node_explanation():
    collector = ExecutionTelemetryCollector()

    edge = make_node(
        "edge-01",
        ExecutionTarget.EDGE,
    )

    local = make_node(
        "local-01",
        ExecutionTarget.LOCAL,
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
        health_registry=make_registry(
            edge,
            local,
        ),
        telemetry_collector=collector,
    )

    result = scheduler.schedule(
        make_workload(),
    )

    assert result.adaptive_explanation is not None

    assert (
        result.adaptive_explanation.node_id
        == result.decision.node_id
    )

    assert (
        result.adaptive_explanation.final_score
        == result.decision.score
    )


def test_scheduler_exposes_all_candidate_explanations():
    collector = ExecutionTelemetryCollector()

    edge = make_node(
        "edge-01",
        ExecutionTarget.EDGE,
    )

    local = make_node(
        "local-01",
        ExecutionTarget.LOCAL,
    )

    cloud = make_node(
        "cloud-01",
        ExecutionTarget.CLOUD,
    )

    scheduler = OffloadScheduler(
        health_registry=make_registry(
            edge,
            local,
            cloud,
        ),
        telemetry_collector=collector,
    )

    result = scheduler.schedule(
        make_workload(),
    )

    explanations = result.candidate_explanations

    assert len(explanations) == 3

    assert [
        explanation.rank
        for explanation in explanations
    ] == [1, 2, 3]

    assert [
        explanation.node_id
        for explanation in explanations
    ] == list(
        result.decision.candidates
    )


def test_candidate_explanation_scores_match_scheduler_scores():
    collector = ExecutionTelemetryCollector()

    edge = make_node(
        "edge-01",
        ExecutionTarget.EDGE,
    )

    local = make_node(
        "local-01",
        ExecutionTarget.LOCAL,
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
        health_registry=make_registry(
            edge,
            local,
        ),
        telemetry_collector=collector,
    )

    workload = make_workload()

    result = scheduler.schedule(
        workload,
    )

    for explanation in result.candidate_explanations:
        node = (
            edge
            if explanation.node_id == edge.node_id
            else local
        )

        assert explanation.score == scheduler.policy.score(
            node,
            workload,
        )


def test_candidate_explanations_are_serializable():
    collector = ExecutionTelemetryCollector()

    edge = make_node(
        "edge-01",
        ExecutionTarget.EDGE,
    )

    scheduler = OffloadScheduler(
        health_registry=make_registry(edge),
        telemetry_collector=collector,
    )

    result = scheduler.schedule(
        make_workload(),
    )

    payload = result.to_dict()

    assert "decision" in payload
    assert "considered_nodes" in payload
    assert "adaptive_explanation" in payload
    assert "candidate_explanations" in payload

    assert isinstance(
        payload["candidate_explanations"],
        list,
    )

    assert payload["candidate_explanations"][0][
        "node_id"
    ] == "edge-01"


def test_non_adaptive_scheduler_remains_serializable():
    edge = make_node(
        "edge-01",
        ExecutionTarget.EDGE,
    )

    scheduler = OffloadScheduler(
        health_registry=make_registry(edge),
    )

    result = scheduler.schedule(
        make_workload(),
    )

    assert result.adaptive_explanation is None

    assert all(
        candidate.adaptive_explanation is None
        for candidate in result.candidate_explanations
    )

    payload = result.to_dict()

    assert payload["adaptive_explanation"] is None