from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ExecutionTarget(str, Enum):
    """
    Where an AI workload can be executed.
    """

    EDGE = "EDGE"
    LOCAL = "LOCAL"
    CLOUD = "CLOUD"


class WorkloadType(str, Enum):
    """
    Types of secondary/expensive AI workloads that Sentinel may offload.
    """

    ALPR = "ALPR"
    THREAT_CLASSIFICATION = "THREAT_CLASSIFICATION"
    REID = "REID"
    BEHAVIOR_ANALYSIS = "BEHAVIOR_ANALYSIS"
    ADVANCED_AI = "ADVANCED_AI"


class Priority(str, Enum):
    """
    Workload urgency.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class WorkloadProfile:
    """
    Describes the computational and latency requirements of a workload.
    """

    workload_type: WorkloadType

    priority: Priority = Priority.MEDIUM

    estimated_compute_ms: float = 50.0

    minimum_gpu: float = 0.0
    minimum_memory_percent: float = 0.0

    maximum_latency_ms: float = 1000.0

    minimum_bandwidth_mbps: float = 0.0

    allow_edge: bool = True
    allow_local: bool = True
    allow_cloud: bool = True

    @property
    def allowed_targets(self) -> set[ExecutionTarget]:
        targets: set[ExecutionTarget] = set()

        if self.allow_edge:
            targets.add(ExecutionTarget.EDGE)

        if self.allow_local:
            targets.add(ExecutionTarget.LOCAL)

        if self.allow_cloud:
            targets.add(ExecutionTarget.CLOUD)

        return targets


@dataclass
class NodeHealth:
    """
    Current resource and connectivity state of an execution node.

    Utilization values are percentages in the range 0-100.
    """

    node_id: str
    target: ExecutionTarget

    cpu_percent: float = 0.0
    gpu_percent: float = 0.0
    memory_percent: float = 0.0

    network_latency_ms: float = 0.0
    bandwidth_mbps: float = 1000.0

    queue_depth: int = 0

    available: bool = True

    gpu_available: bool = True

    max_queue_depth: int = 100

    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.cpu_percent = self._clamp_percentage(self.cpu_percent)
        self.gpu_percent = self._clamp_percentage(self.gpu_percent)
        self.memory_percent = self._clamp_percentage(self.memory_percent)

        if self.network_latency_ms < 0:
            raise ValueError("network_latency_ms cannot be negative")

        if self.bandwidth_mbps < 0:
            raise ValueError("bandwidth_mbps cannot be negative")

        if self.queue_depth < 0:
            raise ValueError("queue_depth cannot be negative")

        if self.max_queue_depth <= 0:
            raise ValueError("max_queue_depth must be greater than zero")

    @staticmethod
    def _clamp_percentage(value: float) -> float:
        if not 0 <= value <= 100:
            raise ValueError("utilization percentage must be between 0 and 100")
        return float(value)

    @property
    def queue_utilization(self) -> float:
        return min(self.queue_depth / self.max_queue_depth, 1.0)

    @property
    def resource_headroom(self) -> float:
        """
        Average remaining CPU/GPU/memory capacity.

        GPU is excluded when the node has no GPU.
        """

        values = [
            100.0 - self.cpu_percent,
            100.0 - self.memory_percent,
        ]

        if self.gpu_available:
            values.append(100.0 - self.gpu_percent)

        return sum(values) / len(values)


@dataclass(frozen=True)
class OffloadDecision:
    """
    Result produced by the scheduler.
    """

    target: ExecutionTarget
    node_id: str

    accepted: bool

    workload_type: WorkloadType
    priority: Priority

    score: float
    estimated_latency_ms: float

    reason: str

    fallback_used: bool = False

    candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "target": self.target.value,
            "node_id": self.node_id,
            "accepted": self.accepted,
            "workload_type": self.workload_type.value,
            "priority": self.priority.value,
            "score": round(self.score, 4),
            "estimated_latency_ms": round(
                self.estimated_latency_ms,
                2,
            ),
            "reason": self.reason,
            "fallback_used": self.fallback_used,
            "candidates": list(self.candidates),
        }


@dataclass(frozen=True)
class SchedulingResult:
    """
    Complete scheduling response.

    This wraps the decision and exposes the nodes considered by
    the scheduler.
    """

    decision: OffloadDecision
    considered_nodes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.to_dict(),
            "considered_nodes": list(self.considered_nodes),
        }