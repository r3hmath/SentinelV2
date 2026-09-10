from __future__ import annotations

from sentinel_edge.offload.health import NodeHealthRegistry
from sentinel_edge.offload.models import (
    CandidateExplanation,
    ExecutionTarget,
    NodeHealth,
    OffloadDecision,
    Priority,
    SchedulingResult,
    WorkloadProfile,
)
from sentinel_edge.offload.policy import SchedulingPolicy
from sentinel_edge.offload.adaptive_policy import (
    AdaptiveSchedulingPolicy,
)
from sentinel_edge.offload.telemetry import (
    ExecutionTelemetryCollector,
)


class OffloadScheduler:
    """
    Dynamic Edge / Local / Cloud workload scheduler.

    The scheduler is responsible for candidate selection and
    deterministic decision-making. Execution remains the responsibility
    of the execution router.
    """

    def __init__(
        self,
        health_registry: NodeHealthRegistry | None = None,
        policy: SchedulingPolicy | None = None,
        telemetry_collector: (
            ExecutionTelemetryCollector | None
        ) = None,
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

    # ------------------------------------------------------------------
    # Public scheduling API
    # ------------------------------------------------------------------

    def schedule(
        self,
        workload: WorkloadProfile,
    ) -> SchedulingResult:
        """
        Select the best currently available execution node.
        """

        nodes = self.health_registry.available_nodes()

        considered_nodes = tuple(
            node.node_id
            for node in nodes
        )

        if not self.policy.validate_workload(
            workload
        ):
            return self._rejected_decision(
                workload=workload,
                considered_nodes=considered_nodes,
                reason=(
                    "Invalid workload constraints; "
                    "no scheduling decision can be made"
                ),
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

        ranked = self._rank_candidates(
            candidates,
            workload,
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
            estimated_latency_ms=(
                self.policy.estimate_latency(
                    selected,
                    workload,
                )
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
            adaptive_explanation=(
                self._adaptive_explanation(
                    selected,
                    workload,
                )
            ),
            candidate_explanations=(
                self._candidate_explanations(
                    ranked,
                    workload,
                )
            ),
        )

    def schedule_with_preferred_target(
        self,
        workload: WorkloadProfile,
        preferred_target: ExecutionTarget,
    ) -> SchedulingResult:
        """
        Prefer a requested target when capable.

        Otherwise select the best valid fallback candidate.
        """

        nodes = self.health_registry.available_nodes()

        considered_nodes = tuple(
            node.node_id
            for node in nodes
        )

        if not self.policy.validate_workload(
            workload
        ):
            return self._rejected_decision(
                workload=workload,
                considered_nodes=considered_nodes,
                reason=(
                    "Invalid workload constraints; "
                    "preferred-target scheduling rejected"
                ),
            )

        preferred_candidates = [
            node
            for node in nodes
            if (
                node.target == preferred_target
                and self.policy.is_capable(
                    node,
                    workload,
                )
            )
        ]

        if preferred_candidates:
            ranked = self._rank_candidates(
                preferred_candidates,
                workload,
            )

            selected = ranked[0]

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
                estimated_latency_ms=(
                    self.policy.estimate_latency(
                        selected,
                        workload,
                    )
                ),
                reason=(
                    f"Preferred target "
                    f"{preferred_target.value} available"
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
                adaptive_explanation=(
                    self._adaptive_explanation(
                        selected,
                        workload,
                    )
                ),
                candidate_explanations=(
                    self._candidate_explanations(
                        ranked,
                        workload,
                    )
                ),
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
            adaptive_explanation=(
                fallback_result.adaptive_explanation
            ),
            candidate_explanations=(
                fallback_result.candidate_explanations
            ),
        )

    # ------------------------------------------------------------------
    # Candidate ranking
    # ------------------------------------------------------------------

    def _rank_candidates(
        self,
        candidates: list[NodeHealth],
        workload: WorkloadProfile,
    ) -> list[NodeHealth]:
        """
        Produce a deterministic candidate ordering.

        Ranking priority:

        1. Final scheduling score
        2. Target suitability for workload priority
        3. Lower estimated latency
        4. Lower queue depth
        5. Stable node ID
        """

        return sorted(
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
                -self.policy.estimate_latency(
                    node,
                    workload,
                ),
                -node.queue_depth,
                node.node_id,
            ),
            reverse=True,
        )

    @staticmethod
    def _target_tiebreaker(
        target: ExecutionTarget,
        priority: Priority,
    ) -> float:
        """
        Deterministic priority-aware target ordering.
        """

        if priority == Priority.CRITICAL:
            return {
                ExecutionTarget.EDGE: 3.0,
                ExecutionTarget.LOCAL: 2.0,
                ExecutionTarget.CLOUD: 1.0,
            }[target]

        if priority == Priority.HIGH:
            return {
                ExecutionTarget.EDGE: 3.0,
                ExecutionTarget.LOCAL: 2.0,
                ExecutionTarget.CLOUD: 1.0,
            }[target]

        if priority == Priority.MEDIUM:
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

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def _candidate_explanations(
        self,
        ranked: list[NodeHealth],
        workload: WorkloadProfile,
    ) -> tuple[CandidateExplanation, ...]:
        return tuple(
            CandidateExplanation(
                rank=index,
                node_id=node.node_id,
                target=node.target,
                score=self.policy.score(
                    node,
                    workload,
                ),
                adaptive_explanation=(
                    self._adaptive_explanation(
                        node,
                        workload,
                    )
                ),
            )
            for index, node in enumerate(
                ranked,
                start=1,
            )
        )

    def _adaptive_explanation(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ):
        if not isinstance(
            self.policy,
            AdaptiveSchedulingPolicy,
        ):
            return None

        return self.policy.explain(
            node,
            workload,
        )

    # ------------------------------------------------------------------
    # Rejection
    # ------------------------------------------------------------------

    @staticmethod
    def _rejected_decision(
        workload: WorkloadProfile,
        considered_nodes: tuple[str, ...],
        reason: str | None = None,
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
                reason
                or (
                    "No available node is capable of "
                    "executing the requested workload"
                )
            ),
            fallback_used=False,
            candidates=(),
        )

        return SchedulingResult(
            decision=decision,
            considered_nodes=considered_nodes,
        )