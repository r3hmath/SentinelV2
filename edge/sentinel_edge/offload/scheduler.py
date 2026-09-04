from __future__ import annotations

from sentinel_edge.offload.health import NodeHealthRegistry
from sentinel_edge.offload.models import (
    ExecutionTarget,
    NodeHealth,
    OffloadDecision,
    Priority,
    SchedulingResult,
    WorkloadProfile,
)
from sentinel_edge.offload.policy import SchedulingPolicy
from sentinel_edge.offload.adaptive_policy import AdaptiveSchedulingPolicy
from sentinel_edge.offload.telemetry import ExecutionTelemetryCollector

class OffloadScheduler:
    """
    Dynamic Edge / Local / Cloud workload scheduler.

    The scheduler itself is deliberately stateless. Current node
    state is provided by NodeHealthRegistry, while the decision
    algorithm lives in SchedulingPolicy.
    """

    def __init__(
    self,
    health_registry: NodeHealthRegistry | None = None,
    policy: SchedulingPolicy | None = None,
    telemetry_collector: ExecutionTelemetryCollector | None = None,
) -> None:
        self.health_registry = health_registry

        base_policy = policy or SchedulingPolicy()

        if telemetry_collector is not None:
            self.policy = AdaptiveSchedulingPolicy(
                base_policy=base_policy,
                telemetry_collector=telemetry_collector,
            )
        else:
            self.policy = base_policy

        self.telemetry_collector = telemetry_collector

    def schedule(
        self,
        workload: WorkloadProfile,
    ) -> SchedulingResult:
        """
        Select the best currently available node.
        """

        nodes = self.health_registry.available_nodes()

        considered_nodes = tuple(
            node.node_id
            for node in nodes
        )

        candidates = [
            node
            for node in nodes
            if self.policy.is_capable(
                node,
                workload,
            )
        ]

        if not candidates:
            return self._rejected_decision(
                workload=workload,
                considered_nodes=considered_nodes,
            )

        ranked = sorted(
            candidates,
            key=lambda node: (
                self.policy.score(
                    node,
                    workload,
                ),
                self._target_tiebreaker(
                    node.target,
                    workload.priority,
                ),
                -node.network_latency_ms,
                -node.queue_depth,
            ),
            reverse=True,
        )

        selected = ranked[0]

        score = self.policy.score(
            selected,
            workload,
        )

        decision = OffloadDecision(
            target=selected.target,
            node_id=selected.node_id,
            accepted=True,
            workload_type=workload.workload_type,
            priority=workload.priority,
            score=score,
            estimated_latency_ms=self.policy.estimate_latency(
                selected,
                workload,
            ),
            reason=self.policy.reason(
                selected,
                workload,
            ),
            fallback_used=False,
            candidates=tuple(
                node.node_id
                for node in ranked
            ),
        )

        return SchedulingResult(
            decision=decision,
            considered_nodes=considered_nodes,
        )

    def schedule_with_preferred_target(
        self,
        workload: WorkloadProfile,
        preferred_target: ExecutionTarget,
    ) -> SchedulingResult:
        """
        Try a preferred execution target first.

        If the preferred target cannot execute the workload,
        automatically falls back to the best capable target.
        """

        nodes = self.health_registry.available_nodes()

        considered_nodes = tuple(
            node.node_id
            for node in nodes
        )

        preferred_candidates = [
            node
            for node in nodes
            if node.target == preferred_target
            and self.policy.is_capable(
                node,
                workload,
            )
        ]

        if preferred_candidates:
            selected = max(
                preferred_candidates,
                key=lambda node: self.policy.score(
                    node,
                    workload,
                ),
            )

            decision = OffloadDecision(
                target=selected.target,
                node_id=selected.node_id,
                accepted=True,
                workload_type=workload.workload_type,
                priority=workload.priority,
                score=self.policy.score(
                    selected,
                    workload,
                ),
                estimated_latency_ms=self.policy.estimate_latency(
                    selected,
                    workload,
                ),
                reason=(
                    f"Preferred target "
                    f"{preferred_target.value} available"
                ),
                fallback_used=False,
                candidates=tuple(
                    node.node_id
                    for node in preferred_candidates
                ),
            )

            return SchedulingResult(
                decision=decision,
                considered_nodes=considered_nodes,
            )

        fallback_result = self.schedule(
            workload,
        )

        if not fallback_result.decision.accepted:
            return fallback_result

        fallback_decision = OffloadDecision(
            target=fallback_result.decision.target,
            node_id=fallback_result.decision.node_id,
            accepted=True,
            workload_type=workload.workload_type,
            priority=workload.priority,
            score=fallback_result.decision.score,
            estimated_latency_ms=(
                fallback_result.decision.estimated_latency_ms
            ),
            reason=(
                f"Preferred target "
                f"{preferred_target.value} unavailable; "
                f"fallback to "
                f"{fallback_result.decision.target.value}"
            ),
            fallback_used=True,
            candidates=fallback_result.decision.candidates,
        )

        return SchedulingResult(
            decision=fallback_decision,
            considered_nodes=considered_nodes,
        )

    @staticmethod
    def _target_tiebreaker(
        target: ExecutionTarget,
        priority: Priority,
    ) -> float:
        """
        Deterministic tie-breaker.

        For equal scores, critical/high workloads prefer Edge/Local
        over Cloud.
        """

        if priority in {
            Priority.HIGH,
            Priority.CRITICAL,
        }:
            return {
                ExecutionTarget.EDGE: 3.0,
                ExecutionTarget.LOCAL: 2.0,
                ExecutionTarget.CLOUD: 1.0,
            }[target]

        return {
            ExecutionTarget.EDGE: 3.0,
            ExecutionTarget.LOCAL: 2.0,
            ExecutionTarget.CLOUD: 1.0,
        }[target]

    @staticmethod
    def _rejected_decision(
        workload: WorkloadProfile,
        considered_nodes: tuple[str, ...],
    ) -> SchedulingResult:
        decision = OffloadDecision(
            target=ExecutionTarget.EDGE,
            node_id="NONE",
            accepted=False,
            workload_type=workload.workload_type,
            priority=workload.priority,
            score=0.0,
            estimated_latency_ms=float("inf"),
            reason=(
                "No available node is capable of executing "
                "the requested workload"
            ),
            fallback_used=False,
            candidates=(),
        )

        return SchedulingResult(
            decision=decision,
            considered_nodes=considered_nodes,
        )