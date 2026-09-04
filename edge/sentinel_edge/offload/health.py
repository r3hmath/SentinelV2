from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from sentinel_edge.offload.models import ExecutionTarget, NodeHealth


@dataclass(frozen=True)
class HealthSnapshot:
    """
    Immutable snapshot of all registered execution nodes.
    """

    nodes: tuple[NodeHealth, ...]

    def get_by_target(
        self,
        target: ExecutionTarget,
    ) -> list[NodeHealth]:
        return [
            node
            for node in self.nodes
            if node.target == target
        ]


class NodeHealthRegistry:
    """
    In-memory registry of Edge / Local / Cloud node health.

    Later this abstraction can be backed by Redis, PostgreSQL,
    Prometheus, Kubernetes, or another control-plane service
    without changing the scheduler interface.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, NodeHealth] = {}
        self._lock = Lock()

    def register(self, health: NodeHealth) -> None:
        if not health.node_id.strip():
            raise ValueError("node_id cannot be empty")

        with self._lock:
            self._nodes[health.node_id] = health

    def update(self, health: NodeHealth) -> None:
        self.register(health)

    def remove(self, node_id: str) -> bool:
        with self._lock:
            return self._nodes.pop(node_id, None) is not None

    def get(self, node_id: str) -> NodeHealth | None:
        with self._lock:
            return self._nodes.get(node_id)

    def all(self) -> list[NodeHealth]:
        with self._lock:
            return list(self._nodes.values())

    def snapshot(self) -> HealthSnapshot:
        with self._lock:
            return HealthSnapshot(
                nodes=tuple(self._nodes.values())
            )

    def available_nodes(self) -> list[NodeHealth]:
        with self._lock:
            return [
                node
                for node in self._nodes.values()
                if node.available
            ]

    def available_targets(
        self,
    ) -> set[ExecutionTarget]:
        return {
            node.target
            for node in self.available_nodes()
        }

    def clear(self) -> None:
        with self._lock:
            self._nodes.clear()