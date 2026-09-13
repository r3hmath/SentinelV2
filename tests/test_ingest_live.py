"""
Sentinel Video Intelligence Platform — Unit Test Suite
Module: tests/test_ingest_live.py
Description: Unit tests for Live CCTV Ingestion Module (edge/ingest_gujarat_live.py).
             Covers:
             1. Socket probe timeout behavior
             2. Backoff timing sequence
             3. Deque overwrite semantics (maxlen=1)
             4. Offline queue flush-on-reconnect
             5. Frame pacing and normalized metadata packaging
"""

import collections
import os
import socket
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from edge.ingest_gujarat_live import (
    LiveStreamIngestor,
    NormalizedSpatialMetadata,
    OfflineTelemetryQueue,
    ReconnectStateMachine,
    probe_tcp_socket,
)


@pytest.fixture
def local_sample_video():
    """Resolves path to local mock video media."""
    root = Path(__file__).resolve().parent.parent
    path = root / "edge" / "media" / "ahmd.mp4"
    assert path.exists(), f"Mock video file missing at {path}"
    return str(path)


# ==============================================================================
# 1. SOCKET PROBE TIMEOUT BEHAVIOR TESTS
# ==============================================================================

def test_socket_probe_timeout_behavior():
    """Verify pre-flight TCP socket probe returns False on timeout without hanging."""
    # Test against non-routable / closed local port with very low timeout
    start_time = time.monotonic()
    reachable = probe_tcp_socket("rtsp://127.0.0.1:59998/live", timeout_sec=0.2)
    elapsed = time.monotonic() - start_time

    assert reachable is False
    assert elapsed < 0.6, f"Probe took too long: {elapsed:.2f}s (expected <0.6s)"


def test_socket_probe_mocked_timeout():
    """Verify probe cleanly catches socket.timeout and returns False."""
    with patch("socket.socket.connect", side_effect=socket.timeout):
        result = probe_tcp_socket("rtsp://192.0.2.1:8554/stream", timeout_sec=0.1)
        assert result is False


def test_socket_probe_local_file(local_sample_video):
    """Verify probe returns True immediately for existing local mock video files."""
    assert probe_tcp_socket(local_sample_video) is True
    assert probe_tcp_socket("non_existent_file_path.mp4") is False


# ==============================================================================
# 2. BACKOFF TIMING SEQUENCE TESTS
# ==============================================================================

def test_backoff_timing_sequence():
    """
    Verify exponential backoff state machine matches exact formula:
    delta_t = min(30.0, 1.5 * 1.5**attempts + jitter), with jitter in [0, 0.5).
    """
    machine = ReconnectStateMachine(base_delay=1.5, multiplier=1.5, max_delay=30.0)

    # Attempt 0: 1.5 * (1.5**0) = 1.5 -> [1.5, 2.0)
    delay_0 = machine.compute_backoff(0)
    assert 1.5 <= delay_0 < 2.0

    # Attempt 1: 1.5 * (1.5**1) = 2.25 -> [2.25, 2.75)
    delay_1 = machine.compute_backoff(1)
    assert 2.25 <= delay_1 < 2.75

    # Attempt 2: 1.5 * (1.5**2) = 3.375 -> [3.375, 3.875)
    delay_2 = machine.compute_backoff(2)
    assert 3.375 <= delay_2 < 3.875

    # Attempt 3: 1.5 * (1.5**3) = 5.0625 -> [5.0625, 5.5625)
    delay_3 = machine.compute_backoff(3)
    assert 5.0625 <= delay_3 < 5.5625

    # Attempt 10: exponential growth capped strictly at 30.0s max
    delay_10 = machine.compute_backoff(10)
    assert delay_10 == 30.0

    # Sequential next_delay tracking
    machine.reset()
    assert machine.attempts == 0
    d0 = machine.next_delay()
    assert machine.attempts == 1
    assert 1.5 <= d0 < 2.0
    machine.reset()
    assert machine.attempts == 0


# ==============================================================================
# 3. DEQUE OVERWRITE SEMANTICS TESTS
# ==============================================================================

def test_deque_overwrite_semantics():
    """
    Verify collections.deque(maxlen=1) strictly discards stale frames
    so downstream consumers always pull the freshest frame with zero lag.
    """
    buf: collections.deque = collections.deque(maxlen=1)

    frame1 = np.ones((50, 50, 3), dtype=np.uint8) * 10
    frame2 = np.ones((50, 50, 3), dtype=np.uint8) * 20
    frame3 = np.ones((50, 50, 3), dtype=np.uint8) * 30

    buf.append((frame1, 100.0))
    assert len(buf) == 1
    assert buf[0][1] == 100.0

    # Overwrite with frame 2
    buf.append((frame2, 200.0))
    assert len(buf) == 1
    assert buf[0][1] == 200.0
    assert np.array_equal(buf[0][0], frame2)

    # Overwrite with frame 3
    buf.append((frame3, 300.0))
    assert len(buf) == 1
    assert buf[0][1] == 300.0
    assert np.array_equal(buf[0][0], frame3)

    # Pop returns the freshest (frame 3)
    popped_frame, pts = buf.pop()
    assert pts == 300.0
    assert np.array_equal(popped_frame, frame3)
    assert len(buf) == 0


# ==============================================================================
# 4. OFFLINE QUEUE FLUSH-ON-RECONNECT TESTS
# ==============================================================================

def test_offline_queue_flush_on_reconnect():
    """
    Verify OfflineTelemetryQueue buffers events during partition
    and flushes them sequentially upon reconnect through a dispatch function.
    """
    queue = OfflineTelemetryQueue(maxlen=50)

    # Enqueue 5 telemetry events during simulated network outage
    for i in range(5):
        queue.push({"event_id": i, "camera_id": "CAM_AHM_01", "frame_id": i + 1})

    assert queue.size == 5
    assert queue.is_empty() is False

    dispatched_ids = []

    def mock_successful_dispatch(event):
        dispatched_ids.append(event["event_id"])
        return True

    # Flush on reconnect
    flushed_count = queue.flush(mock_successful_dispatch, batch_size=10)

    assert flushed_count == 5
    assert queue.size == 0
    assert queue.is_empty() is True
    assert dispatched_ids == [0, 1, 2, 3, 4]


def test_offline_queue_partial_flush_preserves_order():
    """
    Verify that if dispatch fails midway, unsent events remain at the head
    of the queue preserving strict FIFO ordering.
    """
    queue = OfflineTelemetryQueue(maxlen=10)
    for i in range(4):
        queue.push({"id": i})

    # Dispatch succeeds for id=0, fails for id=1
    call_count = 0

    def mock_flaky_dispatch(event):
        nonlocal call_count
        call_count += 1
        return event["id"] == 0

    flushed = queue.flush(mock_flaky_dispatch)
    assert flushed == 1
    assert queue.size == 3

    # Ensure id=1 remains at the front of the queue
    next_item = queue._queue[0]
    assert next_item["id"] == 1


# ==============================================================================
# 5. FRAME PACING & SPATIAL METADATA PACKAGING
# ==============================================================================

def test_frame_pacing_and_metadata_packaging(local_sample_video):
    """
    Verify LiveStreamIngestor samples local video at target FPS and
    packages normalized spatial metadata (camera_id, timestamp, frame_id, pts_ms).
    """
    ingestor = LiveStreamIngestor(
        source=local_sample_video,
        camera_id="CAM_PACING_TEST",
        city="Ahmedabad",
        latitude=23.0225,
        longitude=72.5714,
        target_fps=10.0,
    )

    ingestor.start()
    try:
        frames_captured = 0
        last_pts = -1.0

        for _ in range(12):
            success, frame, metadata = ingestor.read_frame()
            if not success or frame is None or metadata is None:
                time.sleep(0.04)
                continue

            frames_captured += 1
            assert metadata.camera_id == "CAM_PACING_TEST"
            assert metadata.frame_id == frames_captured
            assert metadata.city == "Ahmedabad"
            assert metadata.latitude == 23.0225
            assert metadata.longitude == 72.5714
            assert metadata.pts_ms >= last_pts
            assert "T" in metadata.timestamp  # Valid ISO-8601 UTC string
            last_pts = metadata.pts_ms

            if frames_captured >= 4:
                break

        assert frames_captured >= 3
    finally:
        ingestor.stop()


def test_tcp_transport_environment_variable():
    """Verify OPENCV_FFMPEG_CAPTURE_OPTIONS is set to rtsp_transport;tcp."""
    assert os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS") == "rtsp_transport;tcp"
