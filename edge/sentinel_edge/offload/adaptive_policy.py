from __future__ import annotations

from dataclasses import dataclass

from sentinel_edge.offload.models import NodeHealth, WorkloadProfile
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
            raise ValueError("minimum_samples must be greater than zero")

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

    This class only modifies the score using observed execution
    performance.

    If telemetry is unavailable or insufficient, the base policy is
    preserved unchanged.
    """

    def __init__(
        self,
        base_policy: SchedulingPolicy | None = None,
        telemetry_collector: ExecutionTelemetryCollector | None = None,
        config: AdaptivePolicyConfig | None = None,
    ) -> None:
        self.base_policy = base_policy or SchedulingPolicy()
        self.telemetry_collector = telemetry_collector
        self.config = config or AdaptivePolicyConfig()

    def is_capable(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> bool:
        """
        Delegate capability decisions to the base policy.
        """

        return self.base_policy.is_capable(
            node,
            workload,
        )

    def estimate_latency(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> float:
        """
        Delegate latency estimation to the base policy.

        Telemetry feedback currently affects ranking score only.
        """

        return self.base_policy.estimate_latency(
            node,
            workload,
        )

    def reason(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> str:
        """
        Delegate the scheduling explanation to the base policy.

        Adaptive feedback changes the ranking score, but the existing
        policy remains the source of the human-readable reason.
        """

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
        Return the base score adjusted by observed execution telemetry.
        """

        base_score = self.base_policy.score(
            node,
            workload,
        )

        if base_score == float("-inf"):
            return base_score

        adjustment = self.telemetry_adjustment(
            node,
            workload,
        )

        adaptive_score = base_score + adjustment

        return max(
            0.0,
            min(1.0, adaptive_score),
        )

    def telemetry_adjustment(
        self,
        node: NodeHealth,
        workload: WorkloadProfile,
    ) -> float:
        """
        Calculate bounded telemetry feedback for a node/workload pair.
        """

        if self.telemetry_collector is None:
            return 0.0

        statistics = self.telemetry_collector.statistics(
            node_id=node.node_id,
            workload_type=workload.workload_type,
        )

        if statistics.executions < self.config.minimum_samples:
            return 0.0

        latency_adjustment = self._latency_adjustment(
            workload,
            statistics,
        )

        reliability_adjustment = self._reliability_adjustment(
            statistics,
        )

        adjustment = (
            latency_adjustment
            + reliability_adjustment
        )

        return max(
            -self.config.maximum_penalty,
            min(
                self.config.maximum_bonus,
                adjustment,
            ),
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

        ratio = observed_latency / expected_latency

        healthy_ratio = self.config.healthy_latency_ratio
        poor_ratio = self.config.poor_latency_ratio

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

        A small number of failures should not immediately produce the
        maximum scheduling penalty. As failures accumulate, the penalty
        approaches the configured maximum reliability penalty.

        This prevents short-lived/transient failures from destabilizing
        scheduling decisions while still allowing persistent failures
        to strongly influence ranking.
        """

        if statistics.executions <= 0:
            return 0.0

        success_rate = statistics.success_rate
        healthy_rate = self.config.healthy_success_rate
        poor_rate = self.config.poor_success_rate

        if success_rate >= healthy_rate:
            return (
                self.config.failure_penalty_weight
                * 0.10
            )

        if success_rate > poor_rate:
            progress = (
                (success_rate - poor_rate)
                / (healthy_rate - poor_rate)
            )

            healthy_adjustment = (
                self.config.failure_penalty_weight
                * 0.10
            )

            poor_adjustment = (
                -self.config.failure_penalty_weight
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
            raw_adjustment = -self.config.failure_penalty_weight

        # Scale the penalty according to the amount of failure evidence.
        #
        # One failure should not immediately destabilize scheduling.
        # Once failures reach minimum_samples, the full reliability
        # penalty is allowed.
        evidence_factor = min(
            1.0,
            statistics.failed / self.config.minimum_samples,
        )

        return raw_adjustment * evidence_factor