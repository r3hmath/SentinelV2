from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sentinel_edge.offload.models import (
    ExecutionTarget,
    Priority,
    WorkloadType,
)


@dataclass(frozen=True)
class ExecutionRequest:
    """
    Immutable request describing an AI workload that must be executed.

    The scheduler decides WHERE the workload should run.
    The executor decides HOW the workload is actually executed.
    """

    request_id: UUID
    camera_id: str
    track_id: int
    workload_type: WorkloadType
    priority: Priority
    target: ExecutionTarget
    payload: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not self.camera_id:
            raise ValueError("camera_id cannot be empty")

        if self.track_id < 0:
            raise ValueError("track_id must be non-negative")

        if not isinstance(self.workload_type, WorkloadType):
            raise TypeError("workload_type must be a WorkloadType")

        if not isinstance(self.priority, Priority):
            raise TypeError("priority must be a Priority")

        if not isinstance(self.target, ExecutionTarget):
            raise TypeError("target must be an ExecutionTarget")

    @classmethod
    def create(
        cls,
        camera_id: str,
        track_id: int,
        workload_type: WorkloadType,
        priority: Priority,
        target: ExecutionTarget,
        payload: Any,
        metadata: dict[str, Any] | None = None,
    ) -> "ExecutionRequest":
        return cls(
            request_id=uuid4(),
            camera_id=camera_id,
            track_id=track_id,
            workload_type=workload_type,
            priority=priority,
            target=target,
            payload=payload,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": str(self.request_id),
            "camera_id": self.camera_id,
            "track_id": self.track_id,
            "workload_type": self.workload_type.value,
            "priority": self.priority.value,
            "target": self.target.value,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ExecutionResult:
    """
    Result returned by an executor after processing a workload.
    """

    request_id: UUID
    success: bool
    target: ExecutionTarget
    workload_type: WorkloadType
    latency_ms: float
    result: Any = None
    error: str | None = None
    executor_id: str = "unknown"
    completed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")

        if not isinstance(self.target, ExecutionTarget):
            raise TypeError("target must be an ExecutionTarget")

        if not isinstance(self.workload_type, WorkloadType):
            raise TypeError("workload_type must be a WorkloadType")

        if self.success and self.error is not None:
            raise ValueError(
                "successful execution cannot contain an error"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": str(self.request_id),
            "success": self.success,
            "target": self.target.value,
            "workload_type": self.workload_type.value,
            "latency_ms": round(self.latency_ms, 3),
            "result": self.result,
            "error": self.error,
            "executor_id": self.executor_id,
            "completed_at": self.completed_at.isoformat(),
        }


class WorkloadExecutor:
    """
    Base interface for all workload executors.

    Concrete executors must implement execute().
    """

    executor_id: str
    target: ExecutionTarget

    def __init__(
        self,
        executor_id: str,
        target: ExecutionTarget,
    ) -> None:
        if not executor_id:
            raise ValueError("executor_id cannot be empty")

        self.executor_id = executor_id
        self.target = target

    def execute(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        raise NotImplementedError(
            "Concrete executors must implement execute()"
        )

    def supports(
        self,
        workload_type: WorkloadType,
    ) -> bool:
        """
        Return whether this executor supports a workload type.
        """

        return False