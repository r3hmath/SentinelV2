from __future__ import annotations

import logging

from sentinel_edge.offload.executor import (
    ExecutionRequest,
    ExecutionResult,
)
from sentinel_edge.offload.models import ExecutionTarget
from sentinel_edge.offload.registry import ExecutionRegistry
from sentinel_edge.offload.telemetry import ExecutionTelemetryCollector

logger = logging.getLogger("sentinel.edge.router")


class ExecutionRouter:
    """
    Routes an execution request to a registered executor.

    Responsibilities:
        - resolve an executor for the requested target
        - verify workload support
        - invoke the executor
        - record execution telemetry when a collector is configured
        - return the executor's result

    The router does NOT make placement decisions.
    Placement is handled by OffloadScheduler.

    Telemetry is collected at the router boundary so every execution
    path is instrumented consistently, regardless of executor type.
    """

    def __init__(
        self,
        registry: ExecutionRegistry,
        telemetry_collector: ExecutionTelemetryCollector | None = None,
    ) -> None:
        self.registry = registry
        self.telemetry_collector = telemetry_collector

    def resolve(
        self,
        request: ExecutionRequest,
    ):
        """
        Resolve the executor responsible for a request.

        Returns None if no suitable executor exists.
        """

        executors = self.registry.get_by_target(
            request.target
        )

        for executor in executors:
            if executor.supports(request.workload_type):
                return executor

        return None

    def route(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        """
        Route and execute a request.

        Missing or incompatible executors are represented as a failed
        ExecutionResult rather than raising into the camera-processing loop.

        When telemetry collection is enabled, both successful and failed
        execution attempts are recorded.
        """

        executor = self.resolve(request)

        if executor is None:
            result = ExecutionResult(
                request_id=request.request_id,
                success=False,
                target=request.target,
                workload_type=request.workload_type,
                latency_ms=0.0,
                result=None,
                error=(
                    "No executor available for target "
                    f"{request.target.value} and workload "
                    f"{request.workload_type.value}"
                ),
                executor_id="router",
            )

            self._record_telemetry(
                request,
                result,
            )

            return result

        logger.debug(
            "Routing execution | request=%s | target=%s | executor=%s",
            request.request_id,
            request.target.value,
            executor.executor_id,
        )

        result = executor.execute(request)

        self._record_telemetry(
            request,
            result,
        )

        return result

    def _record_telemetry(
        self,
        request: ExecutionRequest,
        result: ExecutionResult,
    ) -> None:
        """
        Record telemetry for an execution result.

        The scheduler's selected node is carried through the request
        metadata as ``scheduled_node_id``. If it is unavailable,
        the collector will group the observation by executor ID.
        """

        if self.telemetry_collector is None:
            return

        scheduled_node_id = request.metadata.get(
            "scheduled_node_id"
        )

        node_id = (
            str(scheduled_node_id)
            if scheduled_node_id
            else None
        )

        try:
            telemetry = self.telemetry_collector.record_execution(
                request,
                result,
                node_id=node_id,
            )

            logger.debug(
                "Execution telemetry recorded | "
                "request=%s | executor=%s | node=%s | "
                "target=%s | workload=%s | success=%s | "
                "latency_ms=%.2f",
                telemetry.request_id,
                telemetry.executor_id,
                telemetry.node_id,
                telemetry.target.value,
                telemetry.workload_type.value,
                telemetry.success,
                telemetry.latency_ms,
            )

        except Exception:
            # Telemetry must never break the execution path.
            #
            # The execution result has already been produced and
            # remains the source of truth for the caller.
            logger.exception(
                "Failed to record execution telemetry | "
                "request=%s | executor=%s",
                request.request_id,
                result.executor_id,
            )

    def has_executor(
        self,
        target: ExecutionTarget,
    ) -> bool:
        """Return whether at least one executor exists for a target."""

        return bool(
            self.registry.get_by_target(target)
        )