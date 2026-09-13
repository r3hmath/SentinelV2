"""
Sentinel Video Intelligence Platform — Gujarat Police CCTV Infrastructure
Module: edge/ingest_gujarat_live.py
Description: Production-grade modular RTSP/HLS CCTV live ingestion worker.

Architecture & Transport Guarantees:
1. Stream Configuration:
   - RTSP stream URL is sourced dynamically from the environment variable CAMERA_RTSP_URL.
   - Zero hardcoding of live stream endpoints or credentials.
   - Defaults to local mock RTSP server (rtsp://127.0.0.1:8554/live/CAM_AHM_01) or local mock file.
2. Transport Enforcement:
   - Sets OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp before opening capture.
3. Pre-Flight TCP Socket Probe:
   - Probes target host:port with configurable timeout (default 0.8s) before OpenCV binding
     to avoid indefinite hangs on dead or unreachable streams.
4. Zero-Lag Frame Grabber:
   - Background capture thread writes into a collections.deque(maxlen=1) so downstream
     consumers always get the freshest frame with zero latency or buffer bloat.
5. Exponential Backoff Reconnect State Machine:
   - delta_t = min(30.0, 1.5 * 1.5**attempts + jitter), with jitter in [0, 0.5).
6. Frame Pacing & Spatial Metadata:
   - Paces capture at configurable FPS (default 5.0 FPS).
   - Normalizes camera_id, timestamp (ISO-8601 UTC), frame_id, and monotonic PTS.
7. OfflineTelemetryQueue:
   - Bounded FIFO buffer (collections.deque with maxlen) buffering telemetry during network
     partitions and flushing once connectivity is restored.
8. Graceful Shutdown:
   - Handles SIGINT/SIGTERM to cleanly release capture, drain buffers, and stop worker threads.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import datetime
import logging
import os
import random
import signal
import socket
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import cv2
import httpx
import numpy as np

# ==============================================================================
# 1. TRANSPORT ENFORCEMENT & LOGGING
# ==============================================================================
# Strict requirement: Force TCP transport using semicolon format for OpenCV FFmpeg
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger("sentinel.edge.ingest_live")


# ==============================================================================
# 2. DATA MODELS & SPATIAL METADATA CONTRACT
# ==============================================================================

@dataclass
class NormalizedSpatialMetadata:
    """
    Standardized frame context metadata conforming to Gujarat Police GIS standards.
    """
    camera_id: str
    timestamp: str  # ISO-8601 UTC
    frame_id: int
    pts_ms: float
    fps: float
    latitude: float
    longitude: float
    city: str
    source: str
    transport_type: str
    resolution_width: int
    resolution_height: int
    node_id: str = "NODE_DEFAULT"
    extra_attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==============================================================================
# 3. PRE-FLIGHT TCP SOCKET PROBE
# ==============================================================================

def probe_tcp_socket(source_url: str, timeout_sec: float = 0.8) -> bool:
    """
    Pre-flight TCP socket probe against stream host:port before OpenCV handoff.
    Prevents OpenCV VideoCapture from hanging indefinitely on dead or firewalled streams.
    
    Returns:
        bool: True if TCP connection succeeds (or if source is an existing local file).
              False if the host:port is unreachable or connection times out.
    """
    if not source_url:
        return False

    parsed = urlparse(source_url)
    scheme = parsed.scheme.lower()

    if scheme in ("rtsp", "http", "https"):
        host = parsed.hostname or "127.0.0.1"
        default_port = 8554 if scheme == "rtsp" else (443 if scheme == "https" else 80)
        port = parsed.port or default_port

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_sec)
        try:
            sock.connect((host, port))
            sock.close()
            return True
        except (socket.timeout, ConnectionRefusedError, OSError) as err:
            logger.debug("Socket probe failed for %s:%d (timeout=%.2fs): %s", host, port, timeout_sec, err)
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass
    else:
        # Local video file path
        return Path(source_url).resolve().exists()


# ==============================================================================
# 4. EXPONENTIAL BACKOFF STATE MACHINE
# ==============================================================================

class ReconnectStateMachine:
    """
    Calculates exponential backoff delay with random jitter:
    delta_t = min(30.0, 1.5 * 1.5**attempts + jitter), with jitter in [0, 0.5).
    """

    def __init__(self, base_delay: float = 1.5, multiplier: float = 1.5, max_delay: float = 30.0) -> None:
        self.base_delay = base_delay
        self.multiplier = multiplier
        self.max_delay = max_delay
        self.attempts: int = 0

    def compute_backoff(self, attempts: Optional[int] = None) -> float:
        """Calculate backoff duration for a given attempt index."""
        k = attempts if attempts is not None else self.attempts
        jitter = random.uniform(0.0, 0.5)
        raw_backoff = self.base_delay * (self.multiplier ** k)
        return min(self.max_delay, raw_backoff + jitter)

    def next_delay(self) -> float:
        """Computes current delay and increments internal attempt counter."""
        delay = self.compute_backoff(self.attempts)
        self.attempts += 1
        return delay

    def reset(self) -> None:
        """Resets attempt counter upon receiving healthy frames."""
        self.attempts = 0


# ==============================================================================
# 5. BOUNDED OFFLINE TELEMETRY QUEUE
# ==============================================================================

class OfflineTelemetryQueue:
    """
    Bounded FIFO (collections.deque with maxlen) that buffers normalized telemetry
    events during network partitions and flushes them once connectivity is restored.
    """

    def __init__(self, maxlen: int = 1000) -> None:
        self.maxlen = maxlen
        self._queue: collections.deque[Dict[str, Any]] = collections.deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._total_enqueued = 0
        self._total_flushed = 0
        self._total_dropped = 0

    def push(self, event: Dict[str, Any]) -> bool:
        """Push normalized event into the FIFO buffer. Drops oldest if full."""
        with self._lock:
            if len(self._queue) == self.maxlen:
                self._total_dropped += 1
            self._queue.append(event)
            self._total_enqueued += 1
            return True

    def flush(self, dispatch_fn: Callable[[Dict[str, Any]], bool], batch_size: int = 50) -> int:
        """
        Flushes buffered events through dispatch_fn.
        If dispatch_fn returns False for an event, re-queues it and stops flushing.
        Returns the count of successfully flushed events.
        """
        flushed_count = 0
        with self._lock:
            while self._queue and flushed_count < batch_size:
                event = self._queue.popleft()
                try:
                    success = dispatch_fn(event)
                except Exception as exc:
                    logger.debug("Dispatch function raised exception during flush: %s", exc)
                    success = False

                if success:
                    flushed_count += 1
                    self._total_flushed += 1
                else:
                    # Put event back at the front and abort batch flush
                    self._queue.appendleft(event)
                    break

        return flushed_count

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._queue) == 0

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "current_size": len(self._queue),
                "total_enqueued": self._total_enqueued,
                "total_flushed": self._total_flushed,
                "total_dropped": self._total_dropped,
            }


# ==============================================================================
# 6. ASYNCHRONOUS TELEMETRY DISPATCHER
# ==============================================================================

class TelemetryDispatcher:
    """
    Streams normalized telemetry events to Sentinel backend APIs:
    - Primary:   /api/ingest
    - Secondary: /api/v1/cameras/ingest
    Falls back to OfflineTelemetryQueue during backend service interruptions,
    and automatically flushes buffered items when endpoints become reachable.
    """

    def __init__(
        self,
        base_urls: Optional[List[str]] = None,
        offline_queue: Optional[OfflineTelemetryQueue] = None,
        request_timeout: float = 2.5,
    ) -> None:
        self.base_urls = [u.rstrip("/") for u in (base_urls or ["http://127.0.0.1:8000", "http://127.0.0.1:8001"])]
        self.queue = offline_queue or OfflineTelemetryQueue()
        self.timeout = request_timeout
        self._endpoints = ["/api/ingest", "/api/v1/cameras/ingest"]
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._pending_events: collections.deque[Dict[str, Any]] = collections.deque(maxlen=500)
        self._lock = threading.Lock()
        self._backend_online = True

    def start(self) -> None:
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._run_async_worker,
            name="TelemetryDispatcherWorker",
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def dispatch(self, payload: Dict[str, Any]) -> None:
        """Asynchronously queues an event for dispatch."""
        with self._lock:
            self._pending_events.append(payload)

    def _run_async_worker(self) -> None:
        asyncio.run(self._worker_loop())

    async def _worker_loop(self) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while self._running:
                event = None
                with self._lock:
                    if self._pending_events:
                        event = self._pending_events.popleft()

                if event is not None:
                    success = await self._send_event(client, event)
                    if not success:
                        self.queue.push(event)
                        self._backend_online = False
                    else:
                        self._backend_online = True

                # Flush offline queue if backend is reachable
                if self._backend_online and not self.queue.is_empty():
                    # Synchronous-style flush wrapper using current client
                    def _sync_send(item: Dict[str, Any]) -> bool:
                        try:
                            # Quick non-blocking probe
                            for base_url in self.base_urls:
                                r = httpx.post(f"{base_url}/api/ingest", json=item, timeout=1.0)
                                if r.status_code in (200, 201, 202):
                                    return True
                        except Exception:
                            return False
                        return False

                    self.queue.flush(_sync_send, batch_size=10)

                await asyncio.sleep(0.02)

    async def _send_event(self, client: httpx.AsyncClient, event: Dict[str, Any]) -> bool:
        overall_ok = False
        for base_url in self.base_urls:
            for ep in self._endpoints:
                url = f"{base_url}{ep}"
                try:
                    resp = await client.post(url, json=event)
                    if resp.status_code in (200, 201, 202):
                        overall_ok = True
                except Exception:
                    pass
        return overall_ok


# ==============================================================================
# 7. LIVE CCTV INGESTION MODULE CORE
# ==============================================================================

class LiveStreamIngestor:
    """
    Production-grade RTSP/HLS CCTV Stream Ingestor.
    
    Key Features:
    - Zero hardcoded URLs: sources CAMERA_RTSP_URL from environment variable.
    - Strict TCP transport enforcement (`rtsp_transport;tcp`).
    - Pre-flight TCP socket probe (default 0.8s) before OpenCV VideoCapture binding.
    - Zero-lag frame grabber writing into `collections.deque(maxlen=1)`.
    - Exponential backoff reconnect state machine.
    - Frame pacing at configurable FPS (default 5.0).
    - Normalized spatial metadata contract with monotonic PTS calculation.
    - Fault-tolerant OfflineTelemetryQueue buffering and flushing.
    - Graceful shutdown handling (SIGINT/SIGTERM).
    """

    def __init__(
        self,
        source: Optional[str] = None,
        camera_id: str = "CAM_AHM_01",
        city: str = "Ahmedabad",
        latitude: float = 23.0225,
        longitude: float = 72.5714,
        target_fps: float = 5.0,
        probe_timeout_sec: float = 0.8,
        api_base_urls: Optional[List[str]] = None,
        max_offline_queue_size: int = 1000,
        on_frame_callback: Optional[Callable[[np.ndarray, NormalizedSpatialMetadata], None]] = None,
    ) -> None:
        # Source resolution: Priority: Explicit argument -> CAMERA_RTSP_URL env var -> local mock fallback
        resolved_source = source or os.getenv("CAMERA_RTSP_URL")
        if not resolved_source:
            # Fallback to local test infrastructure
            default_file = Path(__file__).resolve().parent / "media" / "ahmd.mp4"
            resolved_source = str(default_file) if default_file.exists() else "rtsp://127.0.0.1:8554/live/CAM_AHM_01"

        self.source = str(resolved_source)
        self.camera_id = camera_id
        self.city = city
        self.latitude = latitude
        self.longitude = longitude
        self.target_fps = max(0.1, float(target_fps))
        self.probe_timeout_sec = probe_timeout_sec
        self.on_frame_callback = on_frame_callback

        # Offline queue & telemetry dispatcher
        self.offline_queue = OfflineTelemetryQueue(maxlen=max_offline_queue_size)
        self.dispatcher = TelemetryDispatcher(
            base_urls=api_base_urls,
            offline_queue=self.offline_queue,
        )

        # Frame Buffer: collections.deque(maxlen=1) ensures zero buffer lag
        self._frame_buffer: collections.deque[Tuple[np.ndarray, float]] = collections.deque(maxlen=1)
        self._buffer_lock = threading.Lock()

        # Reconnection State Machine
        self.backoff_machine = ReconnectStateMachine(base_delay=1.5, multiplier=1.5, max_delay=30.0)

        # Worker thread and capture state
        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._grabber_thread: Optional[threading.Thread] = None

        # Telemetry metrics
        self.frame_id = 0
        self.dropped_frames = 0
        self.reconnect_count = 0
        self.last_pts_ms = -1.0
        self.active_transport = "UNKNOWN"
        self.resolution: Tuple[int, int] = (1920, 1080)

    # --------------------------------------------------------------------------
    # Capture Connection & Pre-Flight Verification
    # --------------------------------------------------------------------------
    def _connect(self) -> bool:
        """Opens capture with TCP options after pre-flight socket verification."""
        with self._buffer_lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None

            # 1. Strict TCP Transport Enforcement
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

            # 2. Pre-flight TCP Socket Probe
            is_reachable = probe_tcp_socket(self.source, timeout_sec=self.probe_timeout_sec)
            if not is_reachable:
                logger.warning(
                    "[%s] Pre-flight socket probe failed for source: %s (timeout: %.2fs)",
                    self.camera_id,
                    self.source,
                    self.probe_timeout_sec,
                )
                return False

            # 3. OpenCV Capture Initialization
            if self.source.startswith("rtsp://"):
                logger.info("[%s] Attaching TCP RTSP source via CAP_FFMPEG: %s", self.camera_id, self.source)
                self._cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self.active_transport = "RTSP_TCP"
            else:
                logger.info("[%s] Opening stream source: %s", self.camera_id, self.source)
                self._cap = cv2.VideoCapture(self.source)
                self.active_transport = "LOCAL_MOCK" if Path(self.source).exists() else "NETWORK_STREAM"

            if self._cap and self._cap.isOpened():
                w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
                h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
                self.resolution = (w, h)
                self.backoff_machine.reset()
                logger.info(
                    "[%s] Stream opened successfully | Transport: %s | Resolution: %dx%d",
                    self.camera_id,
                    self.active_transport,
                    w,
                    h,
                )
                return True
            else:
                logger.warning("[%s] Failed to open capture source: %s", self.camera_id, self.source)
                return False

    # --------------------------------------------------------------------------
    # Background Frame Grabber Worker (deque maxlen=1)
    # --------------------------------------------------------------------------
    def _grabber_loop(self) -> None:
        """Continuously drains frames into collections.deque(maxlen=1) with zero lag."""
        logger.debug("[%s] Zero-lag capture worker active.", self.camera_id)

        while self._running:
            if self._cap is None or not self._cap.isOpened():
                self.reconnect_count += 1
                backoff_time = self.backoff_machine.next_delay()
                logger.warning(
                    "[%s] Stream disconnected. Reconnection attempt #%d in %.2fs...",
                    self.camera_id,
                    self.reconnect_count,
                    backoff_time,
                )
                time.sleep(backoff_time)
                self._connect()
                continue

            success, frame = self._cap.read()

            if not success or frame is None:
                # Handle looping for local mock files
                if self.active_transport == "LOCAL_MOCK":
                    try:
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        success, frame = self._cap.read()
                    except Exception:
                        pass

                if not success or frame is None:
                    logger.debug("[%s] Frame read error; reconnecting...", self.camera_id)
                    time.sleep(0.05)
                    self._cap.release()
                    self._cap = None
                    continue

            # Successful frame: reset backoff state machine
            self.backoff_machine.reset()

            # Hardware PTS extraction or monotonic fallback
            raw_pts = float(self._cap.get(cv2.CAP_PROP_POS_MSEC))
            pts_ms = raw_pts if raw_pts >= 0 else (self.frame_id * (1000.0 / self.target_fps))

            with self._buffer_lock:
                if len(self._frame_buffer) == self._frame_buffer.maxlen:
                    self.dropped_frames += 1
                # Overwrites single slot: downstream consumers always receive freshest frame
                self._frame_buffer.append((frame, pts_ms))
                self.last_pts_ms = pts_ms

            time.sleep(0.001)

    # --------------------------------------------------------------------------
    # Lifecycle: Start, Stop, Read Frame
    # --------------------------------------------------------------------------
    def start(self) -> None:
        """Starts background grabber and dispatcher threads."""
        self._running = True
        self._connect()

        self._grabber_thread = threading.Thread(
            target=self._grabber_loop,
            name=f"CaptureWorker-{self.camera_id}",
            daemon=True,
        )
        self._grabber_thread.start()
        self.dispatcher.start()
        logger.info("[%s] Live CCTV Ingestion Worker active at %.1f FPS.", self.camera_id, self.target_fps)

    def stop(self) -> None:
        """Releases capture resources, terminates workers, and flushes buffers."""
        self._running = False
        if self._grabber_thread and self._grabber_thread.is_alive():
            self._grabber_thread.join(timeout=2.0)

        with self._buffer_lock:
            if self._cap:
                self._cap.release()
                self._cap = None
            self._frame_buffer.clear()

        self.dispatcher.stop()
        logger.info("[%s] Capture released and workers stopped.", self.camera_id)

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray], Optional[NormalizedSpatialMetadata]]:
        """Pulls the freshest frame from single-slot deque and packages normalized metadata."""
        with self._buffer_lock:
            if not self._frame_buffer:
                return False, None, None
            frame, pts_ms = self._frame_buffer.pop()

        self.frame_id += 1
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

        metadata = NormalizedSpatialMetadata(
            camera_id=self.camera_id,
            timestamp=now_utc,
            frame_id=self.frame_id,
            pts_ms=pts_ms,
            fps=self.target_fps,
            latitude=self.latitude,
            longitude=self.longitude,
            city=self.city,
            source=self.source,
            transport_type=self.active_transport,
            resolution_width=frame.shape[1],
            resolution_height=frame.shape[0],
            extra_attributes={
                "reconnect_count": self.reconnect_count,
                "dropped_frames": self.dropped_frames,
            },
        )
        return True, frame, metadata

    def run_paced_loop(
        self,
        max_frames: Optional[int] = None,
        duration_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Runs inter-frame paced ingestion loop (default 5.0 FPS)."""
        self.start()
        start_time = time.monotonic()
        target_interval = 1.0 / self.target_fps
        processed_count = 0

        try:
            while self._running:
                loop_start = time.monotonic()

                if duration_sec and (loop_start - start_time) >= duration_sec:
                    break
                if max_frames and processed_count >= max_frames:
                    break

                success, frame, metadata = self.read_frame()
                if not success or frame is None or metadata is None:
                    time.sleep(0.01)
                    continue

                processed_count += 1

                if self.on_frame_callback:
                    try:
                        self.on_frame_callback(frame, metadata)
                    except Exception as err:
                        logger.exception("Callback error: %s", err)

                # Stream normalized telemetry event
                self.dispatcher.dispatch(metadata.to_dict())

                # Precise inter-frame pacing
                elapsed = time.monotonic() - loop_start
                sleep_remainder = max(0.001, target_interval - elapsed)
                time.sleep(sleep_remainder)

        finally:
            self.stop()

        total_duration = time.monotonic() - start_time
        return {
            "camera_id": self.camera_id,
            "processed_frames": processed_count,
            "dropped_frames": self.dropped_frames,
            "reconnect_count": self.reconnect_count,
            "total_duration_sec": round(total_duration, 2),
            "effective_fps": round(processed_count / max(0.001, total_duration), 2),
            "offline_queue_stats": self.offline_queue.stats(),
        }


# ==============================================================================
# 8. COMMAND-LINE INTERFACE
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinel Live CCTV Ingestion Module")
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Stream URL (RTSP/HLS/video file). Defaults to CAMERA_RTSP_URL environment variable.",
    )
    parser.add_argument("--camera-id", type=str, default="CAM_AHM_01", help="Camera identifier")
    parser.add_argument("--city", type=str, default="Ahmedabad", help="Camera location city")
    parser.add_argument("--lat", type=float, default=23.0225, help="WGS84 Latitude")
    parser.add_argument("--lon", type=float, default=72.5714, help="WGS84 Longitude")
    parser.add_argument("--fps", type=float, default=5.0, help="Frame sampling rate (default 5.0 FPS)")
    parser.add_argument("--max-frames", type=int, default=None, help="Stop after N frames")
    parser.add_argument("--duration", type=float, default=None, help="Stop after duration (seconds)")
    args = parser.parse_args()

    ingestor = LiveStreamIngestor(
        source=args.source,
        camera_id=args.camera_id,
        city=args.city,
        latitude=args.lat,
        longitude=args.lon,
        target_fps=args.fps,
    )

    def handle_signal(sig, frame):
        logger.info("Signal %d received. Graceful shutdown initiated...", sig)
        ingestor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print("=" * 70)
    print("SENTINEL LIVE CCTV INGESTION MODULE — PHASE 2")
    print(f"  Camera ID:      {args.camera_id} ({args.city})")
    print(f"  Stream Source:  {ingestor.source}")
    print(f"  Paced Rate:     {args.fps} FPS")
    print(f"  Transport:      OPENCV_FFMPEG_CAPTURE_OPTIONS='rtsp_transport;tcp'")
    print("=" * 70)

    summary = ingestor.run_paced_loop(max_frames=args.max_frames, duration_sec=args.duration)
    print(f"Ingestion completed: {summary}")


if __name__ == "__main__":
    main()
