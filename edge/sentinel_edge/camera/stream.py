from __future__ import annotations

import logging
import os
import socket
import threading
import time
from collections import deque
from typing import Callable, Optional, Tuple, Union
from urllib.parse import urlparse

import cv2
import numpy as np

# Enforce TCP transport for all RTSP sessions to eliminate UDP packet loss/jitter
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

logger = logging.getLogger("sentinel.edge.camera")


class CameraStream:
    """
    High-throughput asynchronous threaded RTSP / Video stream reader.

    Features:
    - Strictly enforces TCP transport for RTSP streams across enterprise networks.
    - Extracts frame presentation timestamps (PTS) via cap.get(cv2.CAP_PROP_POS_MSEC).
    - Monotonic PTS tracking & scene discontinuity/loop detection with automatic tracker reset callback.
    - Zero-latency buffer: uses deque(maxlen=1) so stale frames are dropped instantly,
      preventing RTSP socket buffer bloat and drift.
    - Automatic stream reconnection with fallback source resilience.
    """

    def __init__(
        self,
        source: Union[str, int],
        camera_id: str = "camera",
        buffer_size: int = 1,
        loop_video: bool = True,
        reconnect_interval_sec: float = 2.0,
        fallback_source: Optional[Union[str, int]] = None,
        on_pts_reset: Optional[Callable[[], None]] = None,
    ) -> None:
        self.source = source
        self.camera_id = camera_id
        self.buffer_size = max(1, buffer_size)
        self.loop_video = loop_video
        self.reconnect_interval_sec = reconnect_interval_sec
        self.fallback_source = fallback_source
        self.on_pts_reset = on_pts_reset

        self.capture: Optional[cv2.VideoCapture] = None
        self._frame_buffer: deque[Tuple[np.ndarray, float]] = deque(maxlen=self.buffer_size)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_frame_time = 0.0
        self._last_pts_ms: float = -1.0
        self._total_frames_read = 0
        self._dropped_frames = 0
        self._is_opened = False
        self._active_source_type = "UNKNOWN"

    @property
    def last_pts(self) -> float:
        """Return latest presentation timestamp in milliseconds."""
        with self._lock:
            return self._last_pts_ms

    @property
    def active_source_type(self) -> str:
        """Return the active capture transport type (e.g. RTSP_TCP, FALLBACK_LOOP)."""
        with self._lock:
            return self._active_source_type

    def open(self) -> None:
        """Open video stream and launch background grabber thread."""
        self._connect()
        self._running = True
        self._thread = threading.Thread(
            target=self._grabber_loop,
            name=f"CameraGrabber-{self.camera_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[%s] Asynchronous stream grabber launched | source=%s | type=%s",
            self.camera_id,
            self.source,
            self._active_source_type,
        )

    def _connect(self) -> bool:
        """Initialize or re-initialize cv2.VideoCapture with TCP RTSP options."""
        with self._lock:
            if self.capture is not None:
                try:
                    self.capture.release()
                except Exception:
                    pass

            # Enforce TCP transport for RTSP sessions
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

            if isinstance(self.source, str) and self.source.startswith("rtsp://"):
                # Probe TCP reachability first to avoid 30-second OpenCV hang if port is closed
                is_reachable = False
                try:
                    parsed = urlparse(self.source)
                    host = parsed.hostname or "127.0.0.1"
                    port = parsed.port or 8554
                    with socket.create_connection((host, port), timeout=0.3):
                        is_reachable = True
                except (socket.timeout, ConnectionRefusedError, OSError):
                    is_reachable = False

                if is_reachable:
                    logger.info("[%s] RTSP port open. Connecting RTSP over TCP via CAP_FFMPEG...", self.camera_id)
                    self.capture = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                    self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self._active_source_type = "RTSP_TCP"
                elif self.fallback_source:
                    logger.warning(
                        "[%s] RTSP source (%s) unreachable; engaging fallback (%s)...",
                        self.camera_id,
                        self.source,
                        self.fallback_source,
                    )
                    self.capture = cv2.VideoCapture(self.fallback_source)
                    self._active_source_type = "FALLBACK_LOOP"
                else:
                    logger.info("[%s] Attempting direct RTSP connection via CAP_FFMPEG...", self.camera_id)
                    self.capture = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                    self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self._active_source_type = "RTSP_TCP"
            else:
                self.capture = cv2.VideoCapture(self.source)
                self._active_source_type = "LOCAL_STREAM"

            self._is_opened = self.capture.isOpened()
            if not self._is_opened:
                logger.warning(
                    "[%s] Unable to open stream source: %s",
                    self.camera_id,
                    self.source,
                )
                return False

            return True

    def _grabber_loop(self) -> None:
        """Continuously drain frames into single-slot buffer to eliminate latency and track PTS."""
        backoff_delay = 2.0
        backoff_factor = 1.5
        backoff_max = 30.0

        while self._running:
            if self.capture is None or not self._is_opened:
                time.sleep(backoff_delay)
                reconnected = self._connect()
                if not reconnected:
                    backoff_delay = min(backoff_max, backoff_delay * backoff_factor)
                    logger.info("[%s] Reconnection backoff increased to %.1fs", self.camera_id, backoff_delay)
                else:
                    backoff_delay = 2.0
                continue

            success, frame = self.capture.read()

            if not success or frame is None:
                # If loop_video is enabled for files or fallback
                if self.loop_video and self._active_source_type != "RTSP_TCP":
                    try:
                        self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        success, frame = self.capture.read()
                    except Exception:
                        pass

                if not success or frame is None:
                    logger.debug("[%s] Stream read yielded no frame; reconnecting with backoff...", self.camera_id)
                    time.sleep(backoff_delay)
                    reconnected = self._connect()
                    if not reconnected:
                        backoff_delay = min(backoff_max, backoff_delay * backoff_factor)
                    else:
                        backoff_delay = 2.0
                    continue

            # Reset backoff upon healthy frame read
            backoff_delay = 2.0

            # Extract monotonic PTS directly from CAP_PROP_POS_MSEC (no wall-clock drift)
            raw_pts = float(self.capture.get(cv2.CAP_PROP_POS_MSEC))
            pts_ms = raw_pts if raw_pts >= 0 else (self._total_frames_read * 40.0)

            # Check for scene discontinuity or loop point cut (current_pts < last_pts)
            with self._lock:
                if self._last_pts_ms >= 0 and pts_ms < self._last_pts_ms:
                    logger.warning(
                        "[%s] PTS loop cut / scene discontinuity detected (last_pts=%.1fms, curr_pts=%.1fms). Triggering tracker reset.",
                        self.camera_id,
                        self._last_pts_ms,
                        pts_ms,
                    )
                    if self.on_pts_reset:
                        try:
                            self.on_pts_reset()
                        except Exception as cb_exc:
                            logger.exception("[%s] Error executing on_pts_reset callback: %s", self.camera_id, cb_exc)

                self._last_pts_ms = pts_ms

                # Store only the freshest frame + PTS (drops previous frame if unread)
                if len(self._frame_buffer) == self._frame_buffer.maxlen:
                    self._dropped_frames += 1
                self._frame_buffer.append((frame, pts_ms))
                self._last_frame_time = time.monotonic()
                self._total_frames_read += 1

            # Micro-sleep to yield CPU control
            time.sleep(0.001)

    def read(self, with_pts: bool = False) -> Union[Tuple[bool, Optional[np.ndarray]], Tuple[bool, Optional[np.ndarray], float]]:
        """
        Non-blocking read of the latest real-time frame.
        If with_pts=False: returns (True, frame) or (False, None).
        If with_pts=True:  returns (True, frame, pts_ms) or (False, None, -1.0).
        """
        with self._lock:
            if not self._frame_buffer:
                return (False, None, -1.0) if with_pts else (False, None)
            frame, pts_ms = self._frame_buffer.pop()
            return (True, frame, pts_ms) if with_pts else (True, frame)

    def stats(self) -> dict:
        """Return streaming diagnostics."""
        with self._lock:
            return {
                "camera_id": self.camera_id,
                "is_opened": self._is_opened,
                "total_frames_read": self._total_frames_read,
                "dropped_frames": self._dropped_frames,
                "last_frame_time": self._last_frame_time,
                "last_pts_ms": self._last_pts_ms,
                "source_type": self._active_source_type,
            }

    def release(self) -> None:
        """Stop grabber thread and release video capture resources."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

        with self._lock:
            if self.capture:
                self.capture.release()
                self.capture = None
            self._frame_buffer.clear()
            self._is_opened = False

        logger.info("[%s] Stream released.", self.camera_id)