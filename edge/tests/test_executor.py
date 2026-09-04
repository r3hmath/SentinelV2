from uuid import UUID

import pytest

from sentinel_edge.offload import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionTarget,
    Priority,
    WorkloadExecutor,
    WorkloadType,
)


def test_execution_request_creation():
    request = ExecutionRequest.create(
        camera_id="CAM_AHM_01",
        track_id=7,
        workload_type=WorkloadType.ALPR,
        priority=Priority.HIGH,
        target=ExecutionTarget.LOCAL,
        payload={"frame": "test-frame"},
        metadata={"object_type": "car"},
    )

    assert isinstance(request.request_id, UUID)
    assert request.camera_id == "CAM_AHM_01"
    assert request.track_id == 7
    assert request.workload_type == WorkloadType.ALPR
    assert request.priority == Priority.HIGH
    assert request.target == ExecutionTarget.LOCAL


def test_execution_request_serialization():
    request = ExecutionRequest.create(
        camera_id="CAM_AHM_01",
        track_id=1,
        workload_type=WorkloadType.ALPR,
        priority=Priority.HIGH,
        target=ExecutionTarget.EDGE,
        payload={"frame": "test"},
    )

    data = request.to_dict()

    assert isinstance(data["request_id"], str)
    assert data["camera_id"] == "CAM_AHM_01"
    assert data["track_id"] == 1
    assert data["workload_type"] == "ALPR"
    assert data["priority"] == "HIGH"
    assert data["target"] == "EDGE"


def test_execution_request_rejects_empty_camera():
    with pytest.raises(ValueError):
        ExecutionRequest.create(
            camera_id="",
            track_id=1,
            workload_type=WorkloadType.ALPR,
            priority=Priority.HIGH,
            target=ExecutionTarget.EDGE,
            payload={},
        )


def test_execution_request_rejects_negative_track():
    with pytest.raises(ValueError):
        ExecutionRequest.create(
            camera_id="CAM_AHM_01",
            track_id=-1,
            workload_type=WorkloadType.ALPR,
            priority=Priority.HIGH,
            target=ExecutionTarget.EDGE,
            payload={},
        )


def test_successful_execution_result():
    request = ExecutionRequest.create(
        camera_id="CAM_AHM_01",
        track_id=5,
        workload_type=WorkloadType.ALPR,
        priority=Priority.HIGH,
        target=ExecutionTarget.LOCAL,
        payload={},
    )

    result = ExecutionResult(
        request_id=request.request_id,
        success=True,
        target=ExecutionTarget.LOCAL,
        workload_type=WorkloadType.ALPR,
        latency_ms=42.5,
        result={"plate": "DOLIAP"},
        executor_id="local-gpu-01",
    )

    assert result.success is True
    assert result.latency_ms == 42.5
    assert result.result["plate"] == "DOLIAP"
    assert result.error is None


def test_failed_execution_result():
    request = ExecutionRequest.create(
        camera_id="CAM_AHM_01",
        track_id=5,
        workload_type=WorkloadType.ALPR,
        priority=Priority.HIGH,
        target=ExecutionTarget.LOCAL,
        payload={},
    )

    result = ExecutionResult(
        request_id=request.request_id,
        success=False,
        target=ExecutionTarget.LOCAL,
        workload_type=WorkloadType.ALPR,
        latency_ms=12.0,
        error="Executor unavailable",
        executor_id="local-gpu-01",
    )

    assert result.success is False
    assert result.error == "Executor unavailable"


def test_successful_result_cannot_have_error():
    request = ExecutionRequest.create(
        camera_id="CAM_AHM_01",
        track_id=1,
        workload_type=WorkloadType.ALPR,
        priority=Priority.HIGH,
        target=ExecutionTarget.EDGE,
        payload={},
    )

    with pytest.raises(ValueError):
        ExecutionResult(
            request_id=request.request_id,
            success=True,
            target=ExecutionTarget.EDGE,
            workload_type=WorkloadType.ALPR,
            latency_ms=10.0,
            error="Something went wrong",
        )


def test_executor_base_interface():
    executor = WorkloadExecutor(
        executor_id="test-executor",
        target=ExecutionTarget.EDGE,
    )

    assert executor.executor_id == "test-executor"
    assert executor.target == ExecutionTarget.EDGE
    assert executor.supports(WorkloadType.ALPR) is False

    request = ExecutionRequest.create(
        camera_id="CAM_AHM_01",
        track_id=1,
        workload_type=WorkloadType.ALPR,
        priority=Priority.HIGH,
        target=ExecutionTarget.EDGE,
        payload={},
    )

    with pytest.raises(NotImplementedError):
        executor.execute(request)