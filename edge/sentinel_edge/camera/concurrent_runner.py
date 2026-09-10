from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import numpy as np

from sentinel_edge.camera.stream import CameraStream

logger = logging.getLogger("sentinel.edge.concurrent")


@dataclass
class CameraStats:
    camera_id: str
    frames_ingested: int = 0
    frames_processed: int = 0
    fps: float = 0.0
    last_process_time: float = 0.0
    error_count: int = 0


class ConcurrentCameraRunner:
    """
    Orchestrates high-concurrency ingestion and frame sampling across
    up to 50 heterogeneous camera streams on a single edge/gateway node.

    Features:
    - ThreadPoolExecutor managing concurrent ingestion loops.
    - Dynamic FPS Governor: limits frame processing rate per camera to target_fps
      (e.g., 3-5 FPS for tracking), ensuring 50 streams can be ingested concurrently
      without dropping packets, freezing, or crashing.
    - Real-time stream telemetry and aggregated performance statistics.
    """

    def __init__(
        self,
        target_fps: float = 3.0,
        max_workers: int = 50,
        inference_stride: int = 1,
    ) -> None:
        self.target_fps = max(0.5, target_fps)
        self.frame_interval = 1.0 / self.target_fps
        self.max_workers = max_workers
        self.inference_stride = max(1, inference_stride)

        self.streams: Dict[str, CameraStream] = {}
        self.stats: Dict[str, CameraStats] = {}
        self._running = False
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._futures: List[concurrent.futures.Future] = []
        self._lock = threading.Lock()

    def add_camera(
        self,
        camera_id: str,
        source: str | int,
        loop_video: bool = True,
        fallback_source: Optional[str | int] = None,
        on_pts_reset: Optional[Callable[[], None]] = None,
    ) -> CameraStream:
        """Register a camera source into the concurrent ingestion pool."""
        stream = CameraStream(
            source=source,
            camera_id=camera_id,
            buffer_size=1,
            loop_video=loop_video,
            fallback_source=fallback_source,
            on_pts_reset=on_pts_reset,
        )
        self.streams[camera_id] = stream
        self.stats[camera_id] = CameraStats(camera_id=camera_id)
        return stream

    def start(
        self,
        process_frame_fn: Callable[[str, np.ndarray, int], None],
    ) -> None:
        """
        Start concurrent ingestion across all registered cameras.
        process_frame_fn is invoked with: (camera_id, frame, frame_number).
        """
        self._running = True
        num_streams = len(self.streams)
        worker_count = min(self.max_workers, max(1, num_streams))

        logger.info(
            "Starting ConcurrentCameraRunner | cameras=%d | workers=%d | target_fps=%.1f | stride=%d",
            num_streams,
            worker_count,
            self.target_fps,
            self.inference_stride,
        )

        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="StreamWorker",
        )

        # Open each stream
        for stream in self.streams.values():
            stream.open()

        # Submit worker loop for each stream
        for camera_id, stream in self.streams.items():
            future = self._executor.submit(
                self._camera_worker_loop,
                camera_id,
                stream,
                process_frame_fn,
            )
            self._futures.append(future)

    def _camera_worker_loop(
        self,
        camera_id: str,
        stream: CameraStream,
        process_frame_fn: Callable[[str, np.ndarray, int], None],
    ) -> None:
        """Dedicated worker loop for one camera stream with FPS rate governor and inference stride."""
        logger.info("[%s] Ingestion worker active", camera_id)
        last_time = time.monotonic()
        frame_seq = 0

        while self._running:
            loop_start = time.monotonic()

            # Read latest fresh frame (non-blocking)
            has_frame, frame = stream.read()

            if has_frame and frame is not None:
                frame_seq += 1
                stats = self.stats[camera_id]
                stats.frames_ingested += 1

                # Employ inference stride: process 1 out of every N frames
                if (frame_seq % self.inference_stride) == 0:
                    try:
                        process_frame_fn(camera_id, frame, frame_seq)
                        stats.frames_processed += 1
                        stats.last_process_time = time.monotonic()
                    except Exception as exc:
                        stats.error_count += 1
                        logger.exception("[%s] Frame processing error: %s", camera_id, exc)

                # Update live FPS
                now = time.monotonic()
                elapsed = now - last_time
                if elapsed >= 1.0:
                    stats.fps = round(stats.frames_processed / max(1e-3, elapsed), 1)
                    last_time = now
                    stats.frames_processed = 0

            # Dynamic rate governor: sleep remaining duration to respect target_fps
            elapsed_processing = time.monotonic() - loop_start
            sleep_duration = max(0.005, self.frame_interval - elapsed_processing)
            time.sleep(sleep_duration)

    def get_aggregated_stats(self) -> dict:
        """Return real-time throughput metrics across all concurrent streams."""
        total_ingested = sum(s.frames_ingested for s in self.stats.values())
        avg_fps = (
            sum(s.fps for s in self.stats.values()) / max(1, len(self.stats))
        )
        total_errors = sum(s.error_count for s in self.stats.values())

        return {
            "total_cameras": len(self.streams),
            "total_frames_ingested": total_ingested,
            "average_fps": round(avg_fps, 2),
            "total_errors": total_errors,
            "running": self._running,
        }

    def stop(self) -> None:
        """Gracefully terminate all ingestion workers and release streams."""
        logger.info("Stopping ConcurrentCameraRunner...")
        self._running = False

        for stream in self.streams.values():
            stream.release()

        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

        logger.info("ConcurrentCameraRunner stopped.")
