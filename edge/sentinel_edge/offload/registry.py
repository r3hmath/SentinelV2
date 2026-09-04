from __future__ import annotations

from threading import Lock

from sentinel_edge.offload.executor import WorkloadExecutor
from sentinel_edge.offload.models import (
    ExecutionTarget,
    WorkloadType,
)


class ExecutionRegistry:
    """
    Thread-safe registry of available workload executors.

    The registry answers:
        "Which executors are available?"

    It does NOT answer:
        "Which executor should handle this request?"

    Executor selection belongs to ExecutionRouter.
    """

    def __init__(self) -> None:
        self._executors: dict[str, WorkloadExecutor] = {}
        self._lock = Lock()

    def register(
        self,
        executor: WorkloadExecutor,
    ) -> None:
        """
        Register an executor.

        Executor IDs must be unique.
        """

        if not isinstance(executor, WorkloadExecutor):
            raise TypeError(
                "executor must be a WorkloadExecutor"
            )

        with self._lock:
            if executor.executor_id in self._executors:
                raise ValueError(
                    f"Executor already registered: "
                    f"{executor.executor_id}"
                )

            self._executors[executor.executor_id] = executor

    def unregister(
        self,
        executor_id: str,
    ) -> WorkloadExecutor | None:
        """
        Remove and return an executor.

        Returns None when the executor does not exist.
        """

        if not executor_id:
            raise ValueError(
                "executor_id cannot be empty"
            )

        with self._lock:
            return self._executors.pop(
                executor_id,
                None,
            )

    def get(
        self,
        executor_id: str,
    ) -> WorkloadExecutor | None:
        """Return an executor by ID."""

        if not executor_id:
            return None

        with self._lock:
            return self._executors.get(executor_id)

    def get_by_target(
        self,
        target: ExecutionTarget,
    ) -> list[WorkloadExecutor]:
        """Return all executors serving a target."""

        with self._lock:
            return [
                executor
                for executor in self._executors.values()
                if executor.target == target
            ]

    def find_supporting(
        self,
        workload_type: WorkloadType,
    ) -> list[WorkloadExecutor]:
        """
        Return all registered executors capable of a workload.
        """

        with self._lock:
            return [
                executor
                for executor in self._executors.values()
                if executor.supports(workload_type)
            ]

    def all(
        self,
    ) -> list[WorkloadExecutor]:
        """Return a snapshot of all registered executors."""

        with self._lock:
            return list(self._executors.values())

    def contains(
        self,
        executor_id: str,
    ) -> bool:
        """Return whether an executor is registered."""

        if not executor_id:
            return False

        with self._lock:
            return executor_id in self._executors

    def clear(self) -> None:
        """Remove all registered executors."""

        with self._lock:
            self._executors.clear()

    @property
    def size(self) -> int:
        """Return the number of registered executors."""

        with self._lock:
            return len(self._executors)