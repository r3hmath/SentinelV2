from __future__ import annotations

import pytest

from sentinel_edge.offload.edge_executor import EdgeExecutor
from sentinel_edge.offload.local_executor import LocalExecutor
from sentinel_edge.offload.models import (
    ExecutionTarget,
    WorkloadType,
)
from sentinel_edge.offload.registry import ExecutionRegistry


def test_registry_starts_empty():
    registry = ExecutionRegistry()

    assert registry.size == 0
    assert registry.all() == []


def test_register_executor():
    registry = ExecutionRegistry()
    executor = EdgeExecutor("edge-01")

    registry.register(executor)

    assert registry.size == 1
    assert registry.get("edge-01") is executor
    assert registry.contains("edge-01")


def test_register_multiple_executors():
    registry = ExecutionRegistry()

    edge = EdgeExecutor("edge-01")
    local = LocalExecutor("local-01")

    registry.register(edge)
    registry.register(local)

    assert registry.size == 2
    assert registry.get("edge-01") is edge
    assert registry.get("local-01") is local


def test_duplicate_executor_id_is_rejected():
    registry = ExecutionRegistry()

    registry.register(EdgeExecutor("executor-01"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            LocalExecutor("executor-01")
        )


def test_invalid_executor_type_is_rejected():
    registry = ExecutionRegistry()

    with pytest.raises(TypeError, match="WorkloadExecutor"):
        registry.register("not-an-executor")


def test_unregister_executor():
    registry = ExecutionRegistry()
    executor = EdgeExecutor("edge-01")

    registry.register(executor)

    removed = registry.unregister("edge-01")

    assert removed is executor
    assert registry.size == 0
    assert registry.get("edge-01") is None


def test_unregister_missing_executor_returns_none():
    registry = ExecutionRegistry()

    assert registry.unregister("missing") is None


def test_get_by_target():
    registry = ExecutionRegistry()

    edge = EdgeExecutor("edge-01")
    local = LocalExecutor("local-01")

    registry.register(edge)
    registry.register(local)

    edge_executors = registry.get_by_target(
        ExecutionTarget.EDGE
    )

    local_executors = registry.get_by_target(
        ExecutionTarget.LOCAL
    )

    assert edge_executors == [edge]
    assert local_executors == [local]


def test_find_supporting_workload():
    registry = ExecutionRegistry()

    edge = EdgeExecutor("edge-01")
    local = LocalExecutor("local-01")

    registry.register(edge)
    registry.register(local)

    executors = registry.find_supporting(
        WorkloadType.ALPR
    )

    assert len(executors) == 2
    assert edge in executors
    assert local in executors


def test_find_unsupported_workload():
    registry = ExecutionRegistry()

    registry.register(
        EdgeExecutor("edge-01")
    )

    executors = registry.find_supporting(
        WorkloadType.REID
    )

    assert executors == []


def test_contains_missing_executor():
    registry = ExecutionRegistry()

    assert not registry.contains("missing")


def test_get_missing_executor():
    registry = ExecutionRegistry()

    assert registry.get("missing") is None


def test_clear_registry():
    registry = ExecutionRegistry()

    registry.register(
        EdgeExecutor("edge-01")
    )
    registry.register(
        LocalExecutor("local-01")
    )

    registry.clear()

    assert registry.size == 0
    assert registry.all() == []