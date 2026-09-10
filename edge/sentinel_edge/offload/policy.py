from __future__ import annotations

from dataclasses import dataclass

from sentinel_edge.offload.models import (
    ExecutionTarget,
    NodeHealth,
    Priority,
    WorkloadProfile,
)


@dataclass(frozen=True)
class PolicyWeights:
    """
    Relative importance of each scheduling factor.
    """

    resource: float = 0.30
    latency: float = 0.25
    queue: float = 0.15
    priority: float = 0.15
    bandwidth: float = 0.10
    target_preference: float = 0.05


class SchedulingPolicy:
    """
    Deterministic suitability policy for Edge / Local / Cloud execution.
    """

    TARGET_BASE_PREFERENCE = {
        ExecutionTarget.EDGE: 1.00,
        ExecutionTarget.LOCAL: 0.90,
        ExecutionTarget.CLOUD: 0.70,
    }

    PRIORITY_PREFERENCE = {
        Priority.LOW: {
            ExecutionTarget.EDGE: 1.00,
            ExecutionTarget.LOCAL: 0.85,
            ExecutionTarget.CLOUD: 0.70,
        },
        Priority.MEDIUM: {
            ExecutionTarget.EDGE: 1.00,
            ExecutionTarget.LOCAL: 0.95,
            ExecutionTarget.CLOUD: 0.75,
        },
        Priority.HIGH: {
            ExecutionTarget.EDGE: 1.00,
            ExecutionTarget.LOCAL: 1.00,
            ExecutionTarget.CLOUD: 0.60,
        },
        Priority.CRITICAL: {
            ExecutionTarget.EDGE: 1.00,
            ExecutionTarget.LOCAL: 1.00,
            ExecutionTarget.CLOUD: 0.35,
        },
    }

    def __init__(
        self,
        weights: PolicyWeights | None = None,
    ) -> None:
        self.weights = weights or PolicyWeights()

    # ------------------------------------------------------------------
    # Workload validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_workload(
        workload: WorkloadProfile,
    ) -> bool:
        """
        Validate workload constraints before scheduling.

        Invalid workload requirements must never enter candidate
        ranking.
        """

        if workload.estimated_compute_ms < 0:
            return False

        if workload.minimum_gpu < 0:
            return False

        if workload.minimum_memory_percent < 0:
            return False

        if workload.maximum_latency_ms <= 0:
            return False

        if workload.minimum_bandwidth_mbps < 0:
            return False

        if not workload.allowed_targets:
            return False

        return True

    # ------------------------------------------------------------------
    # Capability evaluation
    # ------------------------------------------------------------------

    def is_capable(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> bool:
        """
        Determine whether a node satisfies hard execution constraints.

        This method deliberately excludes soft scoring factors.
        """

        if not self.validate_workload(workload):
            return False

        if not node.available:
            return False

        if node.target not in workload.allowed_targets:
            return False

        if node.queue_depth >= node.max_queue_depth:
            return False

        if workload.minimum_gpu > 0:
            if not node.gpu_available:
                return False

            available_gpu = 100.0 - node.gpu_percent

            if available_gpu < workload.minimum_gpu:
                return False

        available_memory = (
            100.0 - node.memory_percent
        )

        if available_memory < workload.minimum_memory_percent:
            return False

        if (
            workload.minimum_bandwidth_mbps > 0
            and node.bandwidth_mbps
            < workload.minimum_bandwidth_mbps
        ):
            return False

        return True
    def validate_workload(
        self,
        workload: WorkloadProfile,
    ) -> bool:
        """
        Validate workload constraints before candidate evaluation.

        Invalid workloads must never enter the ranking stage.
        """

        if workload.estimated_compute_ms < 0:
            return False

        if workload.minimum_gpu < 0:
            return False

        if workload.minimum_memory_percent < 0:
            return False

        if workload.maximum_latency_ms <= 0:
            return False

        if workload.minimum_bandwidth_mbps < 0:
            return False

        if not workload.allowed_targets:
            return False

        return True

        def latency_feasible(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> bool:
            """
        Determine whether estimated execution latency satisfies
        the workload's maximum latency requirement.
        """

        estimated_latency = self.estimate_latency(
            node,
            workload,
        )

        return (
            estimated_latency
            <= workload.maximum_latency_ms
        )

        def priority_score(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> float:
            """
        Return target suitability for the workload priority.
        """

        return self.PRIORITY_PREFERENCE[
            workload.priority
        ][node.target]
    # ------------------------------------------------------------------
    # Latency estimation
    # ------------------------------------------------------------------

    def estimate_latency(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> float:
        """
        Estimate end-to-end workload latency.
        """

        queue_penalty = (
            node.queue_depth
            * workload.estimated_compute_ms
            * 0.25
        )

        resource_load = (
            node.cpu_percent
            + node.memory_percent
        ) / 2.0

        if node.gpu_available:
            resource_load = (
                resource_load
                + node.gpu_percent
            ) / 2.0

        contention_penalty = (
            workload.estimated_compute_ms
            * (resource_load / 100.0)
            * 0.50
        )

        return (
            workload.estimated_compute_ms
            + node.network_latency_ms
            + queue_penalty
            + contention_penalty
        )

    def latency_feasible(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> bool:
        """
        Determine whether the node can satisfy the workload deadline.

        Latency is treated as a hard constraint only when the workload
        explicitly specifies a maximum latency.
        """

        if workload.maximum_latency_ms <= 0:
            return False

        return (
            self.estimate_latency(
                node,
                workload,
            )
            <= workload.maximum_latency_ms
        )

    # ------------------------------------------------------------------
    # Priority handling
    # ------------------------------------------------------------------

    def priority_score(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> float:
        """
        Return the priority suitability of a target.
        """

        return self.PRIORITY_PREFERENCE[
            workload.priority
        ][node.target]

    # ------------------------------------------------------------------
    # Main score
    # ------------------------------------------------------------------

    def score(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> float:
        if not self.is_capable(
            node,
            workload,
        ):
            return float("-inf")

        resource_score = (
            node.resource_headroom / 100.0
        )

        latency = self.estimate_latency(
            node,
            workload,
        )

        latency_score = max(
            0.0,
            1.0 - (
                latency
                / workload.maximum_latency_ms
            ),
        )

        queue_score = (
            1.0
            - node.queue_utilization
        )

        priority_score = self.priority_score(
            node,
            workload,
        )

        if workload.minimum_bandwidth_mbps <= 0:
            bandwidth_score = 1.0
        else:
            bandwidth_score = min(
                node.bandwidth_mbps
                / workload.minimum_bandwidth_mbps,
                1.0,
            )

        target_score = self.TARGET_BASE_PREFERENCE[
            node.target
        ]

        score = (
            resource_score
            * self.weights.resource
            + latency_score
            * self.weights.latency
            + queue_score
            * self.weights.queue
            + priority_score
            * self.weights.priority
            + bandwidth_score
            * self.weights.bandwidth
            + target_score
            * self.weights.target_preference
        )

        return max(
            0.0,
            min(score, 1.0),
        )

    # ------------------------------------------------------------------
    # Decision explanation
    # ------------------------------------------------------------------

    def reason(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> str:
        latency = self.estimate_latency(
            node,
            workload,
        )

        if not self.is_capable(
            node,
            workload,
        ):
            return (
                f"{node.target.value} rejected because "
                f"hard workload constraints are not satisfied"
            )

        if workload.priority == Priority.CRITICAL:
            return (
                f"CRITICAL workload routed to "
                f"{node.target.value}; "
                f"estimated latency={latency:.1f}ms"
            )

        if workload.priority == Priority.HIGH:
            return (
                f"HIGH priority workload routed to "
                f"{node.target.value}; "
                f"estimated latency={latency:.1f}ms"
            )

        if node.target == ExecutionTarget.EDGE:
            return (
                f"EDGE selected for low-latency processing; "
                f"estimated latency={latency:.1f}ms"
            )

        if node.target == ExecutionTarget.LOCAL:
            return (
                f"LOCAL selected based on available resources; "
                f"estimated latency={latency:.1f}ms"
            )

        return (
            f"CLOUD selected based on available capacity; "
            f"estimated latency={latency:.1f}ms"
        )