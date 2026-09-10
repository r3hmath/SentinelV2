from __future__ import annotations

from dataclasses import dataclass

from sentinel_edge.offload.models import (
    AdaptiveDecisionExplanation,
    NodeHealth,
    WorkloadProfile,
)
from sentinel_edge.offload.policy import SchedulingPolicy
from sentinel_edge.offload.telemetry import (
    ExecutionStatistics,
    ExecutionTelemetryCollector,
)


@dataclass(frozen=True)
class AdaptivePolicyConfig:
    """
    Controls how execution telemetry influences scheduling scores.

    Adaptive feedback is intentionally bounded so that telemetry can
    improve scheduling without completely overriding the base policy.
    """

    minimum_samples: int = 5

    latency_penalty_weight: float = 0.15
    failure_penalty_weight: float = 0.35

    maximum_penalty: float = 0.20
    maximum_bonus: float = 0.05

    healthy_latency_ratio: float = 0.75
    poor_latency_ratio: float = 1.50

    healthy_success_rate: float = 0.98
    poor_success_rate: float = 0.90

    def __post_init__(self) -> None:
        if self.minimum_samples <= 0:
            raise ValueError(
                "minimum_samples must be greater than zero"
            )

        if self.latency_penalty_weight < 0:
            raise ValueError(
                "latency_penalty_weight cannot be negative"
            )

        if self.failure_penalty_weight < 0:
            raise ValueError(
                "failure_penalty_weight cannot be negative"
            )

        if self.maximum_penalty < 0:
            raise ValueError(
                "maximum_penalty cannot be negative"
            )

        if self.maximum_bonus < 0:
            raise ValueError(
                "maximum_bonus cannot be negative"
            )

        if self.healthy_latency_ratio <= 0:
            raise ValueError(
                "healthy_latency_ratio must be greater than zero"
            )

        if self.poor_latency_ratio < self.healthy_latency_ratio:
            raise ValueError(
                "poor_latency_ratio must be greater than or equal to "
                "healthy_latency_ratio"
            )

        if not 0 <= self.poor_success_rate <= 1:
            raise ValueError(
                "poor_success_rate must be between 0 and 1"
            )

        if not 0 <= self.healthy_success_rate <= 1:
            raise ValueError(
                "healthy_success_rate must be between 0 and 1"
            )

        if self.poor_success_rate > self.healthy_success_rate:
            raise ValueError(
                "poor_success_rate must be less than or equal to "
                "healthy_success_rate"
            )


class AdaptiveSchedulingPolicy:
    """
    Decorates SchedulingPolicy with execution-telemetry feedback.

    The base scheduling policy remains responsible for:

        - capability checks
        - latency estimation
        - base scoring
        - human-readable scheduling reasons

    This class adds:

        - adaptive score adjustment
        - telemetry-based explanation
        - score/explanation consistency

    If telemetry is unavailable or insufficient, the base policy is
    preserved unchanged.
    """

    def __init__(
        self,
        base_policy: SchedulingPolicy | None = None,
        telemetry_collector: ExecutionTelemetryCollector | None = None,
        config: AdaptivePolicyConfig | None = None,
    ) -> None:
        self.base_policy = (
            base_policy
            or SchedulingPolicy()
        )

        self.telemetry_collector = telemetry_collector

        self.config = (
            config
            or AdaptivePolicyConfig()
        )

    def validate_workload(
        self,
        workload: WorkloadProfile,
    ) -> bool:
        return self.base_policy.validate_workload(
            workload,
        )

    def is_capable(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> bool:
        return self.base_policy.is_capable(
            node,
            workload,
        )

    def estimate_latency(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> float:
        return self.base_policy.estimate_latency(
            node,
            workload,
        )

    def reason(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> str:
        return self.base_policy.reason(
            node,
            workload,
        )

    def score(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> float:
        """
        Return the adaptive score.

        The score is derived from the same explanation object exposed
        by explain(), ensuring that observability cannot disagree with
        the actual scheduling score.
        """

        return self.explain(
            node,
            workload,
        ).final_score

    def explain(
    self,
    node: NodeHealth,
    workload: WorkloadProfile,
) -> AdaptiveDecisionExplanation:
        """
        Explain exactly how telemetry influenced the node score.

        The explanation is the single source of truth for the adaptive
        score. Individual adjustments are scaled together when the
        configured total adjustment bounds would otherwise be exceeded.
        """

        base_score = self.base_policy.score(
            node,
            workload,
        )

        if base_score == float("-inf"):
            return AdaptiveDecisionExplanation(
                node_id=node.node_id,
                target=node.target,
                base_score=base_score,
                latency_adjustment=0.0,
                reliability_adjustment=0.0,
                adaptive_adjustment=0.0,
                final_score=base_score,
                telemetry_samples=0,
                success_rate=0.0,
                average_latency_ms=0.0,
                adaptation_active=False,
            )

        (
            latency_adjustment,
            reliability_adjustment,
            statistics,
            adaptation_active,
        ) = self._telemetry_components(
            node,
            workload,
        )

        raw_adjustment = (
            latency_adjustment
            + reliability_adjustment
        )

        bounded_adjustment = max(
            -self.config.maximum_penalty,
            min(
                self.config.maximum_bonus,
                raw_adjustment,
            ),
        )

        # Keep the explanation mathematically consistent:
        #
        # adaptive_adjustment =
        #     latency_adjustment + reliability_adjustment
        #
        # If the combined adjustment exceeds the configured bound,
        # scale both components proportionally instead of clamping only
        # the combined value.
        if (
            raw_adjustment != 0.0
            and bounded_adjustment != raw_adjustment
        ):
            scale = bounded_adjustment / raw_adjustment

            latency_adjustment *= scale
            reliability_adjustment *= scale

        adaptive_adjustment = (
            latency_adjustment
            + reliability_adjustment
        )

        final_score = max(
            0.0,
            min(
                1.0,
                base_score + adaptive_adjustment,
            ),
        )

        return AdaptiveDecisionExplanation(
            node_id=node.node_id,
            target=node.target,
            base_score=base_score,
            latency_adjustment=latency_adjustment,
            reliability_adjustment=reliability_adjustment,
            adaptive_adjustment=adaptive_adjustment,
            final_score=final_score,
            telemetry_samples=statistics.executions,
            success_rate=statistics.success_rate,
            average_latency_ms=statistics.average_latency_ms,
            adaptation_active=adaptation_active,
        )

    def telemetry_adjustment(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> float:
        """
        Calculate bounded telemetry feedback for a node/workload pair.
        """

        return self.explain(
            node,
            workload,
        ).adaptive_adjustment
    

    def _telemetry_components(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> tuple[
        float,
        float,
        ExecutionStatistics,
        bool,
    ]:
    
        if self.telemetry_collector is None:
            return (
                0.0,
                0.0,
                self._empty_statistics(),
                False,
            )

        statistics = self.telemetry_collector.statistics(
            node_id=node.node_id,
            workload_type=workload.workload_type,
        )

        if statistics.executions < self.config.minimum_samples:
            return (
                0.0,
                0.0,
                statistics,
                False,
            )

        latency_adjustment = self._latency_adjustment(
            workload,
            statistics,
        )

        reliability_adjustment = self._reliability_adjustment(
            statistics,
        )

        return (
            latency_adjustment,
            reliability_adjustment,
            statistics,
            True,
        )
    def _empty_statistics(self) -> ExecutionStatistics:
        """Return empty telemetry statistics."""
        return ExecutionStatistics(
        executions=0,
        successful=0,
        failed=0,
        success_rate=0.0,
        average_latency_ms=0.0,
        p95_latency_ms=0.0,
        min_latency_ms=0.0,
        max_latency_ms=0.0,
        last_execution_at=None,
    )

    def _latency_adjustment(
        self,
        workload: WorkloadProfile,
        statistics: ExecutionStatistics,
    ) -> float:
        expected_latency = max(
            workload.estimated_compute_ms,
            1.0,
        )

        observed_latency = statistics.average_latency_ms

        ratio = (
            observed_latency
            / expected_latency
        )

        healthy_ratio = (
            self.config.healthy_latency_ratio
        )

        poor_ratio = (
            self.config.poor_latency_ratio
        )

        if ratio <= healthy_ratio:
            return (
                self.config.latency_penalty_weight
                * 0.25
            )

        if ratio >= poor_ratio:
            return -self.config.latency_penalty_weight

        progress = (
            (ratio - healthy_ratio)
            / (poor_ratio - healthy_ratio)
        )

        healthy_adjustment = (
            self.config.latency_penalty_weight
            * 0.25
        )

        poor_adjustment = (
            -self.config.latency_penalty_weight
        )

        return (
            healthy_adjustment
            + progress
            * (
                poor_adjustment
                - healthy_adjustment
            )
        )

    def _reliability_adjustment(
    self,
    statistics: ExecutionStatistics,
) -> float:
        """
        Calculate reliability feedback with evidence-aware scaling.

        Healthy execution history receives a positive reliability bonus.
        Failure penalties increase with observed failure evidence rather
        than immediately applying the maximum penalty.
        """

        if statistics.executions <= 0:
            return 0.0

        success_rate = statistics.success_rate

        healthy_rate = self.config.healthy_success_rate
        poor_rate = self.config.poor_success_rate

        healthy_adjustment = (
            self.config.failure_penalty_weight * 0.10
        )

        poor_adjustment = (
            -self.config.failure_penalty_weight
        )

        if success_rate >= healthy_rate:
            raw_adjustment = healthy_adjustment

        elif success_rate > poor_rate:
            progress = (
                (success_rate - poor_rate)
                / (healthy_rate - poor_rate)
            )

            raw_adjustment = (
                poor_adjustment
                + progress
                * (
                    healthy_adjustment
                    - poor_adjustment
                )
            )

        else:
            raw_adjustment = poor_adjustment

        # Positive reliability evidence needs successful executions.
        # Negative reliability evidence needs observed failures.
        if raw_adjustment > 0.0:
            evidence_factor = min(
                1.0,
                statistics.executions
                / self.config.minimum_samples,
            )
        else:
            evidence_factor = min(
                1.0,
                statistics.failed
                / self.config.minimum_samples,
            )

        return raw_adjustment * evidence_factor