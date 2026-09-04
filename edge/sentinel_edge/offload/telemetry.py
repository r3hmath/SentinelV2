from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Deque

from sentinel_edge.offload.models import ExecutionTarget, WorkloadType
from sentinel_edge.offload.executor import ExecutionRequest, ExecutionResult


@dataclass(frozen=True)
class ExecutionTelemetry:
    """
    Immutable record describing one workload execution.

    This is the raw observation produced after an executor finishes
    processing an ExecutionRequest.
    """

    request_id: str
    executor_id: str
    node_id: str | None
    target: ExecutionTarget
    workload_type: WorkloadType
    success: bool
    latency_ms: float
    timestamp: datetime
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id must not be empty")
        if not self.executor_id:
            raise ValueError("executor_id must not be empty")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        if not isinstance(self.target, ExecutionTarget):
            raise TypeError("target must be an ExecutionTarget")
        if not isinstance(self.workload_type, WorkloadType):
            raise TypeError("workload_type must be a WorkloadType")
        if self.success and self.error is not None:
            raise ValueError("successful telemetry cannot contain an error")
    @classmethod
    def from_execution(
        cls,
        request: ExecutionRequest,
        result: ExecutionResult,
        *,
        node_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> "ExecutionTelemetry":
        """
        Convert an ExecutionRequest + ExecutionResult pair into
        one telemetry observation.
        """

        if result.request_id != request.request_id:
            raise ValueError(
                "request_id mismatch between request and result"
            )

        return cls(
            request_id=str(result.request_id),
            executor_id=str(result.executor_id),
            node_id=node_id,
            target=result.target,
            workload_type=result.workload_type,
            success=result.success,
            latency_ms=float(result.latency_ms),
            timestamp=(
                timestamp
                or datetime.now(timezone.utc)
            ),
            error=result.error,
        )

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "executor_id": self.executor_id,
            "node_id": self.node_id,
            "target": self.target.value,
            "workload_type": self.workload_type.value,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 4),
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
        }


@dataclass(frozen=True)
class ExecutionStatistics:
    """
    Rolling execution statistics for a node/executor + workload.
    """

    executions: int
    successful: int
    failed: int
    success_rate: float
    average_latency_ms: float
    p95_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    last_execution_at: datetime | None

    @property
    def failure_rate(self) -> float:
        return 1.0 - self.success_rate

    def to_dict(self) -> dict:
        return {
            "executions": self.executions,
            "successful": self.successful,
            "failed": self.failed,
            "success_rate": round(
                self.success_rate,
                4,
            ),
            "failure_rate": round(
                self.failure_rate,
                4,
            ),
            "average_latency_ms": round(
                self.average_latency_ms,
                4,
            ),
            "p95_latency_ms": round(
                self.p95_latency_ms,
                4,
            ),
            "min_latency_ms": round(
                self.min_latency_ms,
                4,
            ),
            "max_latency_ms": round(
                self.max_latency_ms,
                4,
            ),
            "last_execution_at": (
                self.last_execution_at.isoformat()
                if self.last_execution_at
                else None
            ),
        }


class ExecutionTelemetryCollector:
    """
    Thread-safe rolling telemetry collector.

    Statistics are maintained independently for:

        (node_id, workload_type)

    If node_id is unavailable, executor_id is used as the
    grouping identity.

    The collector intentionally keeps only a bounded rolling
    window so memory usage remains predictable.
    """

    def __init__(
        self,
        window_size: int = 100,
    ) -> None:

        if window_size <= 0:
            raise ValueError(
                "window_size must be > 0"
            )

        self.window_size = int(window_size)

        self._samples: dict[
            tuple[str, WorkloadType],
            Deque[ExecutionTelemetry],
        ] = {}

        self._lock = threading.RLock()

    # ============================================================
    # RECORD
    # ============================================================

    def record(
        self,
        telemetry: ExecutionTelemetry,
    ) -> None:
        """
        Record one execution observation.
        """

        if not isinstance(
            telemetry,
            ExecutionTelemetry,
        ):
            raise TypeError(
                "telemetry must be ExecutionTelemetry"
            )

        key = self._make_key(telemetry)

        with self._lock:

            samples = self._samples.setdefault(
                key,
                deque(maxlen=self.window_size),
            )

            samples.append(telemetry)

    # ============================================================
    # CONVENIENCE RECORD
    # ============================================================

    def record_execution(
        self,
        request: ExecutionRequest,
        result: ExecutionResult,
        *,
        node_id: str | None = None,
    ) -> ExecutionTelemetry:
        """
        Build and record telemetry directly from an execution.
        """

        telemetry = ExecutionTelemetry.from_execution(
            request,
            result,
            node_id=node_id,
        )

        self.record(telemetry)

        return telemetry

    # ============================================================
    # STATISTICS
    # ============================================================

    def statistics(
        self,
        *,
        node_id: str | None = None,
        executor_id: str | None = None,
        workload_type: WorkloadType,
    ) -> ExecutionStatistics:
        """
        Return rolling statistics for one workload on one
        execution identity.

        node_id is preferred.

        executor_id can be used when node_id is unavailable.
        """

        identity = (
            node_id
            if node_id
            else executor_id
        )

        if not identity:
            raise ValueError(
                "node_id or executor_id must be provided"
            )

        key = (
            str(identity),
            workload_type,
        )

        with self._lock:
            samples = tuple(
                self._samples.get(
                    key,
                    (),
                )
            )

        return self._calculate_statistics(samples)

    # ============================================================
    # ALL STATISTICS
    # ============================================================

    def all_statistics(self) -> dict:
        """
        Return statistics for every tracked
        node/workload combination.
        """

        with self._lock:

            keys = tuple(
                self._samples.keys()
            )

        result = {}

        for identity, workload_type in keys:

            result[
                (
                    identity,
                    workload_type.value,
                )
            ] = self.statistics(
                node_id=identity,
                workload_type=workload_type,
            ).to_dict()

        return result

    # ============================================================
    # SAMPLE ACCESS
    # ============================================================

    def samples(
        self,
        *,
        node_id: str | None = None,
        executor_id: str | None = None,
        workload_type: WorkloadType,
    ) -> tuple[ExecutionTelemetry, ...]:
        """
        Return the current rolling telemetry samples.
        """

        identity = (
            node_id
            if node_id
            else executor_id
        )

        if not identity:
            raise ValueError(
                "node_id or executor_id must be provided"
            )

        key = (
            str(identity),
            workload_type,
        )

        with self._lock:
            return tuple(
                self._samples.get(
                    key,
                    (),
                )
            )

    # ============================================================
    # COUNTS
    # ============================================================

    def total_samples(self) -> int:
        """
        Return total number of currently retained samples.
        """

        with self._lock:
            return sum(
                len(samples)
                for samples in self._samples.values()
            )

    # ============================================================
    # CLEAR
    # ============================================================

    def clear(self) -> None:
        """
        Remove all telemetry.
        """

        with self._lock:
            self._samples.clear()

    # ============================================================
    # INTERNAL HELPERS
    # ============================================================

    @staticmethod
    def _make_key(
        telemetry: ExecutionTelemetry,
    ) -> tuple[str, WorkloadType]:

        identity = (
            telemetry.node_id
            or telemetry.executor_id
        )

        return (
            str(identity),
            telemetry.workload_type,
        )

    @staticmethod
    def _calculate_statistics(
        samples: tuple[ExecutionTelemetry, ...],
    ) -> ExecutionStatistics:

        if not samples:
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

        executions = len(samples)

        successful = sum(
            1
            for sample in samples
            if sample.success
        )

        failed = executions - successful

        latencies = sorted(
            sample.latency_ms
            for sample in samples
        )

        average_latency = mean(
            latencies
        )

        p95_latency = (
            ExecutionTelemetryCollector
            ._percentile(
                latencies,
                95,
            )
        )

        success_rate = (
            successful / executions
        )

        last_execution = max(
            sample.timestamp
            for sample in samples
        )

        return ExecutionStatistics(
            executions=executions,
            successful=successful,
            failed=failed,
            success_rate=success_rate,
            average_latency_ms=average_latency,
            p95_latency_ms=p95_latency,
            min_latency_ms=min(latencies),
            max_latency_ms=max(latencies),
            last_execution_at=last_execution,
        )

    @staticmethod
    def _percentile(
        values: list[float],
        percentile: float,
    ) -> float:

        if not values:
            return 0.0

        if len(values) == 1:
            return float(values[0])

        rank = (
            percentile / 100
        ) * (len(values) - 1)

        lower = int(rank)
        upper = min(
            lower + 1,
            len(values) - 1,
        )

        weight = rank - lower

        return (
            values[lower]
            + (
                values[upper]
                - values[lower]
            ) * weight
        )