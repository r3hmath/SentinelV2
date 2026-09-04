from sentinel_edge.offload import (
    ExecutionTarget,
    NodeHealth,
    NodeHealthRegistry,
    OffloadScheduler,
    Priority,
    WorkloadProfile,
    WorkloadType,
)


def make_registry() -> NodeHealthRegistry:
    registry = NodeHealthRegistry()

    registry.register(
        NodeHealth(
            node_id="edge-01",
            target=ExecutionTarget.EDGE,
            cpu_percent=30,
            gpu_percent=30,
            memory_percent=40,
            network_latency_ms=5,
            bandwidth_mbps=100,
            queue_depth=1,
        )
    )

    registry.register(
        NodeHealth(
            node_id="local-01",
            target=ExecutionTarget.LOCAL,
            cpu_percent=40,
            gpu_percent=45,
            memory_percent=50,
            network_latency_ms=2,
            bandwidth_mbps=1000,
            queue_depth=2,
        )
    )

    registry.register(
        NodeHealth(
            node_id="cloud-01",
            target=ExecutionTarget.CLOUD,
            cpu_percent=20,
            gpu_percent=20,
            memory_percent=30,
            network_latency_ms=80,
            bandwidth_mbps=500,
            queue_depth=1,
        )
    )

    return registry


def test_scheduler_selects_capable_node():
    registry = make_registry()
    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ALPR,
        priority=Priority.HIGH,
        estimated_compute_ms=40,
        maximum_latency_ms=500,
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is True
    assert result.decision.node_id != "NONE"
    assert result.decision.target in {
        ExecutionTarget.EDGE,
        ExecutionTarget.LOCAL,
        ExecutionTarget.CLOUD,
    }


def test_unavailable_node_is_not_selected():
    registry = make_registry()

    registry.update(
        NodeHealth(
            node_id="edge-01",
            target=ExecutionTarget.EDGE,
            cpu_percent=30,
            gpu_percent=30,
            memory_percent=40,
            network_latency_ms=5,
            bandwidth_mbps=100,
            queue_depth=1,
            available=False,
        )
    )

    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ALPR,
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is True
    assert result.decision.node_id != "edge-01"


def test_full_queue_node_is_rejected():
    registry = NodeHealthRegistry()

    registry.register(
        NodeHealth(
            node_id="edge-full",
            target=ExecutionTarget.EDGE,
            queue_depth=100,
            max_queue_depth=100,
        )
    )

    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ALPR,
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is False
    assert result.decision.node_id == "NONE"


def test_gpu_requirement_rejects_cpu_only_node():
    registry = NodeHealthRegistry()

    registry.register(
        NodeHealth(
            node_id="edge-cpu",
            target=ExecutionTarget.EDGE,
            gpu_available=False,
        )
    )

    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ADVANCED_AI,
        minimum_gpu=20,
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is False


def test_bandwidth_requirement_is_respected():
    registry = NodeHealthRegistry()

    registry.register(
        NodeHealth(
            node_id="cloud-slow",
            target=ExecutionTarget.CLOUD,
            bandwidth_mbps=10,
        )
    )

    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ADVANCED_AI,
        minimum_bandwidth_mbps=100,
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is False


def test_preferred_target_is_selected_when_available():
    registry = make_registry()
    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ALPR,
        priority=Priority.HIGH,
    )

    result = scheduler.schedule_with_preferred_target(
        workload,
        ExecutionTarget.LOCAL,
    )

    assert result.decision.accepted is True
    assert result.decision.target == ExecutionTarget.LOCAL
    assert result.decision.node_id == "local-01"
    assert result.decision.fallback_used is False


def test_preferred_target_falls_back_when_unavailable():
    registry = make_registry()

    registry.update(
        NodeHealth(
            node_id="local-01",
            target=ExecutionTarget.LOCAL,
            cpu_percent=40,
            gpu_percent=45,
            memory_percent=50,
            network_latency_ms=2,
            bandwidth_mbps=1000,
            queue_depth=100,
            max_queue_depth=100,
        )
    )

    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ALPR,
        priority=Priority.HIGH,
    )

    result = scheduler.schedule_with_preferred_target(
        workload,
        ExecutionTarget.LOCAL,
    )

    assert result.decision.accepted is True
    assert result.decision.target != ExecutionTarget.LOCAL
    assert result.decision.fallback_used is True


def test_preferred_target_failure_does_not_drop_workload():
    registry = make_registry()

    registry.update(
        NodeHealth(
            node_id="local-01",
            target=ExecutionTarget.LOCAL,
            available=False,
        )
    )

    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ALPR,
        priority=Priority.CRITICAL,
    )

    result = scheduler.schedule_with_preferred_target(
        workload,
        ExecutionTarget.LOCAL,
    )

    assert result.decision.accepted is True
    assert result.decision.fallback_used is True


def test_critical_workload_prefers_edge_or_local_over_cloud():
    registry = NodeHealthRegistry()

    registry.register(
        NodeHealth(
            node_id="edge-critical",
            target=ExecutionTarget.EDGE,
            cpu_percent=20,
            gpu_percent=20,
            memory_percent=30,
            network_latency_ms=5,
            bandwidth_mbps=100,
            queue_depth=0,
        )
    )

    registry.register(
        NodeHealth(
            node_id="cloud-critical",
            target=ExecutionTarget.CLOUD,
            cpu_percent=5,
            gpu_percent=5,
            memory_percent=10,
            network_latency_ms=200,
            bandwidth_mbps=1000,
            queue_depth=0,
        )
    )

    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.THREAT_CLASSIFICATION,
        priority=Priority.CRITICAL,
        estimated_compute_ms=50,
        maximum_latency_ms=1000,
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is True
    assert result.decision.target == ExecutionTarget.EDGE


def test_cloud_can_be_selected_when_edge_and_local_are_disallowed():
    registry = make_registry()
    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ADVANCED_AI,
        priority=Priority.LOW,
        allow_edge=False,
        allow_local=False,
        allow_cloud=True,
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is True
    assert result.decision.target == ExecutionTarget.CLOUD


def test_workload_target_restrictions_are_respected():
    registry = make_registry()
    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ALPR,
        allow_edge=False,
        allow_local=True,
        allow_cloud=False,
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is True
    assert result.decision.target == ExecutionTarget.LOCAL


def test_result_serialization():
    registry = make_registry()
    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ALPR,
        priority=Priority.HIGH,
    )

    result = scheduler.schedule(workload)

    data = result.to_dict()

    assert "decision" in data
    assert "considered_nodes" in data
    assert "target" in data["decision"]
    assert "estimated_latency_ms" in data["decision"]
    assert "fallback_used" in data["decision"]


def test_registry_remove():
    registry = make_registry()

    assert registry.get("edge-01") is not None
    assert registry.remove("edge-01") is True
    assert registry.get("edge-01") is None
    assert registry.remove("edge-01") is False


def test_no_nodes_available():
    registry = NodeHealthRegistry()
    scheduler = OffloadScheduler(registry)

    workload = WorkloadProfile(
        workload_type=WorkloadType.ALPR,
    )

    result = scheduler.schedule(workload)

    assert result.decision.accepted is False
    assert result.decision.node_id == "NONE"
    assert result.decision.target == ExecutionTarget.EDGE
