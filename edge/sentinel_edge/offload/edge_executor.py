from __future__ import annotations

import logging
import time
from typing import Any

from sentinel_edge.alpr.engine import ALPREngine
from sentinel_edge.offload.executor import (
    ExecutionRequest,
    ExecutionResult,
    WorkloadExecutor,
)
from sentinel_edge.offload.models import (
    ExecutionTarget,
    WorkloadType,
)

logger = logging.getLogger("sentinel.edge.offload")


class EdgeExecutor(WorkloadExecutor):
    """
    Executes supported AI workloads on the edge node.

    Responsibilities:
    - validate execution requests
    - dispatch workloads to the appropriate local engine
    - measure execution latency
    - return normalized ExecutionResult objects
    - prevent workload exceptions from crashing the camera loop

    This class does NOT decide where a workload should run.
    Placement is handled by OffloadScheduler.
    """

    def __init__(
        self,
        executor_id: str,
        alpr_engine: ALPREngine | None = None,
    ) -> None:
        super().__init__(
            executor_id=executor_id,
            target=ExecutionTarget.EDGE,
        )

        self.alpr_engine = alpr_engine

    def supports(
        self,
        workload_type: WorkloadType,
    ) -> bool:
        """
        Return whether this executor can execute the workload.

        Only workloads with an implemented execution path are advertised.
        """

        return workload_type == WorkloadType.ALPR

    def execute(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        """
        Execute a workload request on the edge node.

        Every execution returns an ExecutionResult. Runtime failures are
        converted into failed results instead of propagating into the
        camera-processing loop.
        """

        started_at = time.perf_counter()

        if request.target != self.target:
            return self._failure(
                request=request,
                started_at=started_at,
                error=(
                    f"Target mismatch: request targets "
                    f"{request.target.value}, executor targets "
                    f"{self.target.value}"
                ),
            )

        if not self.supports(request.workload_type):
            return self._failure(
                request=request,
                started_at=started_at,
                error=(
                    f"Unsupported workload type: "
                    f"{request.workload_type.value}"
                ),
            )

        try:
            if request.workload_type == WorkloadType.ALPR:
                result = self._execute_alpr(request)
            else:
                # Defensive branch. supports() above should prevent this.
                raise RuntimeError(
                    f"No execution handler for "
                    f"{request.workload_type.value}"
                )

            latency_ms = self._latency_ms(started_at)

            return ExecutionResult(
                request_id=request.request_id,
                success=True,
                target=self.target,
                workload_type=request.workload_type,
                latency_ms=latency_ms,
                result=result,
                executor_id=self.executor_id,
            )

        except Exception as exc:
            logger.exception(
                "Edge workload execution failed | "
                "executor=%s | request=%s | workload=%s",
                self.executor_id,
                request.request_id,
                request.workload_type.value,
            )

            return self._failure(
                request=request,
                started_at=started_at,
                error=str(exc),
            )

    def _execute_alpr(
        self,
        request: ExecutionRequest,
    ) -> dict[str, Any]:
        """
        Execute ALPR against the vehicle crop contained in the request.

        Required metadata:
            timestamp: optional float timestamp

        Payload:
            vehicle crop accepted by ALPREngine.process().
        """

        if self.alpr_engine is None:
            raise RuntimeError("ALPR engine is not configured")

        timestamp = request.metadata.get("timestamp")

        alpr_result = self.alpr_engine.process(
            track_id=request.track_id,
            vehicle_crop=request.payload,
            timestamp=timestamp,
        )

        return {
            "track_id": alpr_result.track_id,
            "plate_text": alpr_result.plate_text,
            "plate_confidence": alpr_result.plate_confidence,
            "detector_confidence": alpr_result.detector_confidence,
            "recognized": alpr_result.recognized,
            "timestamp": alpr_result.timestamp,
        }

    def _failure(
        self,
        request: ExecutionRequest,
        started_at: float,
        error: str,
    ) -> ExecutionResult:
        """Build a normalized failed execution result."""

        return ExecutionResult(
            request_id=request.request_id,
            success=False,
            target=self.target,
            workload_type=request.workload_type,
            latency_ms=self._latency_ms(started_at),
            result=None,
            error=error,
            executor_id=self.executor_id,
        )

    @staticmethod
    def _latency_ms(started_at: float) -> float:
        """Return elapsed execution time in milliseconds."""

        return (time.perf_counter() - started_at) * 1000.0