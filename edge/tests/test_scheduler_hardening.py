from sentinel_edge.offload.models import (
    ExecutionTarget,
    NodeHealth,
    Priority,
    WorkloadProfile,
    WorkloadType,
)
from sentinel_edge.offload.health import NodeHealthRegistry
from sentinel_edge.offload.scheduler import OffloadScheduler


def make_registry(*nodes):
    registry = NodeHealthRegistry()

    for node in nodes:
        registry.register(node)

    return registry


def make_workload(**kwargs):
    defaults = {
        "workload_type": WorkloadType.ALPR,
        "priority": Priority.MEDIUM,
        "estimated_compute_ms": 50.0,
        "maximum_latency_ms": 500.0,
        "minimum_gpu": 0.0,
        "minimum_memory_percent": 0.0,
        "minimum_bandwidth_mbps": 1.0,
        "allow_edge": True,
        "allow_local": True,
        "allow_cloud": True,
    }

    defaults.update(kwargs)

    return WorkloadProfile(**defaults)


def make_node(
    node_id="node-01",
    target=ExecutionTarget.LOCAL,
    **kwargs,
):
    defaults = {
        "node_id": node_id,
        "target": target,
        "cpu_percent": 20.0,
        "gpu_percent": 20.0,
        "memory_percent": 20.0,
        "network_latency_ms": 10.0,
        "bandwidth_mbps": 1000.0,
        "queue_depth": 0,
        "available": True,
        "gpu_available": True,
        "max_queue_depth": 10,
    }

    defaults.update(kwargs)

    return NodeHealth(**defaults)


def test_invalid_workload_is_rejected():
    registry = make_registry(
        make_node()
    )

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload(
        maximum_latency_ms=0
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is False
    assert result.decision.node_id == "NONE"
    assert "Invalid workload" in result.decision.reason


def test_no_allowed_targets_is_rejected():
    registry = make_registry(
        make_node()
    )

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload(
        allow_edge=False,
        allow_local=False,
        allow_cloud=False,
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is False
    assert result.decision.node_id == "NONE"


def test_latency_estimate_is_exposed_in_decision():
    node = make_node(
        network_latency_ms=25.0
    )

    registry = make_registry(node)

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload(
        estimated_compute_ms=100.0
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is True
    assert (
        result.decision.estimated_latency_ms
        == scheduler.policy.estimate_latency(
            node,
            workload,
        )
    )


def test_lower_latency_wins_when_scores_are_equal():
    fast = make_node(
        node_id="fast",
        network_latency_ms=5.0,
    )

    slow = make_node(
        node_id="slow",
        network_latency_ms=50.0,
    )

    registry = make_registry(
        fast,
        slow,
    )

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload()

    result = scheduler.schedule(workload)

    assert result.decision.accepted is True
    assert result.decision.node_id == "fast"


def test_queue_depth_breaks_equal_ranking():
    low_queue = make_node(
        node_id="low-queue",
        queue_depth=1,
    )

    high_queue = make_node(
        node_id="high-queue",
        queue_depth=2,
    )

    registry = make_registry(
        low_queue,
        high_queue,
    )

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload()

    result = scheduler.schedule(workload)

    assert result.decision.accepted is True
    assert result.decision.node_id == "low-queue"


def test_node_id_provides_deterministic_tiebreak():
    node_a = make_node(
        node_id="node-a"
    )

    node_b = make_node(
        node_id="node-b"
    )

    registry = make_registry(
        node_b,
        node_a,
    )

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload()

    first = scheduler.schedule(
        workload
    )

    second = scheduler.schedule(
        workload
    )

    assert first.decision.node_id == second.decision.node_id


def test_preferred_target_falls_back_to_best_capable_target():
    edge = make_node(
        node_id="edge-01",
        target=ExecutionTarget.EDGE,
        available=False,
    )

    local = make_node(
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
    )

    registry = make_registry(
        edge,
        local,
    )

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload()

    result = scheduler.schedule_with_preferred_target(
        workload,
        ExecutionTarget.EDGE,
    )

    assert result.decision.accepted is True
    assert result.decision.node_id == "local-01"
    assert result.decision.fallback_used is True


def test_preferred_target_does_not_override_hard_constraints():
    edge = make_node(
        node_id="edge-01",
        target=ExecutionTarget.EDGE,
        gpu_available=False,
    )

    local = make_node(
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
    )

    registry = make_registry(
        edge,
        local,
    )

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload(
        minimum_gpu=50.0
    )

    result = scheduler.schedule_with_preferred_target(
        workload,
        ExecutionTarget.EDGE,
    )

    assert result.decision.accepted is True
    assert result.decision.node_id == "local-01"
    assert result.decision.fallback_used is True


def test_critical_workload_has_deterministic_target_priority():
    edge = make_node(
        node_id="edge-01",
        target=ExecutionTarget.EDGE,
    )

    local = make_node(
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
    )

    cloud = make_node(
        node_id="cloud-01",
        target=ExecutionTarget.CLOUD,
    )

    registry = make_registry(
        edge,
        local,
        cloud,
    )

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload(
        priority=Priority.CRITICAL
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is True
    assert result.decision.target in {
        ExecutionTarget.EDGE,
        ExecutionTarget.LOCAL,
    }


def test_candidates_are_sorted_consistently():
    nodes = [
        make_node(
            node_id="node-c",
            network_latency_ms=30.0,
        ),
        make_node(
            node_id="node-a",
            network_latency_ms=10.0,
        ),
        make_node(
            node_id="node-b",
            network_latency_ms=20.0,
        ),
    ]

    registry = make_registry(*nodes)

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload()

    result = scheduler.schedule(workload)

    candidates = result.decision.candidates

    assert len(candidates) == 3
    assert len(set(candidates)) == 3


def test_rejected_decision_contains_no_candidates():
    registry = make_registry(
        make_node(
            available=False
        )
    )

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload()

    result = scheduler.schedule(workload)

    assert result.decision.accepted is False
    assert result.decision.candidates == ()


def test_candidate_explanations_match_candidate_order():
    nodes = [
        make_node(
            node_id="node-a",
            target=ExecutionTarget.EDGE,
        ),
        make_node(
            node_id="node-b",
            target=ExecutionTarget.LOCAL,
        ),
    ]

    registry = make_registry(*nodes)

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload()

    result = scheduler.schedule(workload)

    assert len(
        result.candidate_explanations
    ) == len(
        result.decision.candidates
    )

    for explanation, node_id in zip(
        result.candidate_explanations,
        result.decision.candidates,
    ):
        assert explanation.node_id == node_id


def test_preferred_target_preserves_explanations():
    edge = make_node(
        node_id="edge-01",
        target=ExecutionTarget.EDGE,
    )

    local = make_node(
        node_id="local-01",
        target=ExecutionTarget.LOCAL,
    )

    registry = make_registry(
        edge,
        local,
    )

    scheduler = OffloadScheduler(
        health_registry=registry
    )

    workload = make_workload()

    result = scheduler.schedule_with_preferred_target(
        workload,
        ExecutionTarget.EDGE,
    )

    assert result.decision.accepted is True
    assert result.decision.target == ExecutionTarget.EDGE
    assert result.decision.fallback_used is False

    assert result.adaptive_explanation is None
    assert len(result.candidate_explanations) >= 1