from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger("sentinel.edge.track_state")


@dataclass
class TrackObservation:
    """
    Single observation of a tracked object.
    """

    timestamp: datetime
    center: tuple[float, float]
    speed_px_s: float
    distance_px: float


@dataclass
class TrackState:
    """
    Persistent state for one tracked object.
    """

    track_id: int
    object_type: str

    first_seen: datetime
    last_seen: datetime

    first_center: tuple[float, float]
    last_center: tuple[float, float]

    observations: int = 0

    total_distance_px: float = 0.0

    current_speed_px_s: float = 0.0
    previous_speed_px_s: float = 0.0

    acceleration_px_s2: float = 0.0

    missing_frames: int = 0

    last_event_time: float = 0.0

    # Maximum trajectory points retained per track.
    trajectory: deque[TrackObservation] = field(
        default_factory=lambda: deque(maxlen=100)
    )

    # Used for behavior analysis.
    stopped_since: datetime | None = None

    # Number of seconds the object has existed in this track.
    @property
    def lifetime_seconds(self) -> float:
        return max(
            0.0,
            (
                self.last_seen - self.first_seen
            ).total_seconds(),
        )

    @property
    def dwell_time_seconds(self) -> float:
        """
        Alias for track lifetime.

        Behavior engines can later apply their own
        movement thresholds to distinguish dwelling
        from simply moving through the scene.
        """

        return self.lifetime_seconds

    @property
    def direction_degrees(self) -> float | None:
        """
        Calculate direction from first position to current position.

        0°   = East
        90°  = South
        180° = West
        270° = North

        Returns None when there is insufficient movement.
        """

        dx = self.last_center[0] - self.first_center[0]
        dy = self.last_center[1] - self.first_center[1]

        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return None

        angle = math.degrees(math.atan2(dy, dx))

        if angle < 0:
            angle += 360

        return angle


class TrackStateManager:
    """
    Maintains independent tracking state for one camera.

    Important:
    Each camera must have its own TrackStateManager.
    """

    def __init__(
        self,
        max_missing_frames: int = 30,
        event_update_interval_seconds: float = 1.0,
        min_track_observations: int = 2,
        trajectory_size: int = 100,
    ):

        if max_missing_frames < 1:
            raise ValueError(
                "max_missing_frames must be >= 1"
            )

        if event_update_interval_seconds < 0:
            raise ValueError(
                "event_update_interval_seconds must be >= 0"
            )

        if min_track_observations < 1:
            raise ValueError(
                "min_track_observations must be >= 1"
            )

        if trajectory_size < 2:
            raise ValueError(
                "trajectory_size must be >= 2"
            )

        self.max_missing_frames = max_missing_frames

        self.event_update_interval_seconds = (
            event_update_interval_seconds
        )

        self.min_track_observations = (
            min_track_observations
        )

        self.trajectory_size = trajectory_size

        self.tracks: dict[int, TrackState] = {}

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    @staticmethod
    def _distance(
        point_a: tuple[float, float],
        point_b: tuple[float, float],
    ) -> float:

        return math.hypot(
            point_b[0] - point_a[0],
            point_b[1] - point_a[1],
        )

    # ------------------------------------------------------------------
    # Track update
    # ------------------------------------------------------------------

    def update(
        self,
        detections: list[dict[str, Any]],
        timestamp: datetime | None = None,
    ) -> list[dict[str, Any]]:

        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        active_track_ids: set[int] = set()

        enriched_detections: list[
            dict[str, Any]
        ] = []

        for detection in detections:

            track_id = detection.get("track_id")

            # Detection exists but ByteTrack did not
            # provide a valid ID.
            if track_id is None:

                enriched_detections.append(
                    detection
                )

                continue

            try:
                track_id = int(track_id)
            except (TypeError, ValueError):

                logger.warning(
                    "Invalid track_id: %r",
                    track_id,
                )

                enriched_detections.append(
                    detection
                )

                continue

            center = detection.get("center")

            if (
                not isinstance(center, (list, tuple))
                or len(center) != 2
            ):

                enriched_detections.append(
                    detection
                )

                continue

            try:
                center_point = (
                    float(center[0]),
                    float(center[1]),
                )
            except (TypeError, ValueError):

                enriched_detections.append(
                    detection
                )

                continue

            active_track_ids.add(track_id)

            track = self.tracks.get(track_id)

            # ----------------------------------------------------------
            # New track
            # ----------------------------------------------------------

            if track is None:

                track = TrackState(
                    track_id=track_id,
                    object_type=str(
                        detection.get(
                            "object_type",
                            "unknown",
                        )
                    ),
                    first_seen=timestamp,
                    last_seen=timestamp,
                    first_center=center_point,
                    last_center=center_point,
                    observations=1,
                    trajectory=deque(
                        maxlen=self.trajectory_size
                    ),
                )

                track.trajectory.append(
                    TrackObservation(
                        timestamp=timestamp,
                        center=center_point,
                        speed_px_s=0.0,
                        distance_px=0.0,
                    )
                )

                self.tracks[track_id] = track

            # ----------------------------------------------------------
            # Existing track
            # ----------------------------------------------------------

            else:

                elapsed_seconds = (
                    timestamp - track.last_seen
                ).total_seconds()

                distance = self._distance(
                    track.last_center,
                    center_point,
                )

                track.total_distance_px += distance

                # Preserve previous velocity.
                track.previous_speed_px_s = (
                    track.current_speed_px_s
                )

                # Calculate current velocity.
                if elapsed_seconds > 0:

                    track.current_speed_px_s = (
                        distance / elapsed_seconds
                    )

                    # Calculate acceleration.
                    track.acceleration_px_s2 = (
                        track.current_speed_px_s
                        - track.previous_speed_px_s
                    ) / elapsed_seconds

                else:

                    track.current_speed_px_s = 0.0
                    track.acceleration_px_s2 = 0.0

                # Detect stationary state.
                if track.current_speed_px_s < 2.0:

                    if track.stopped_since is None:
                        track.stopped_since = timestamp

                else:

                    track.stopped_since = None

                track.last_center = center_point
                track.last_seen = timestamp

                track.observations += 1

                track.missing_frames = 0

                track.trajectory.append(
                    TrackObservation(
                        timestamp=timestamp,
                        center=center_point,
                        speed_px_s=(
                            track.current_speed_px_s
                        ),
                        distance_px=distance,
                    )
                )

            # ----------------------------------------------------------
            # Enrich detection
            # ----------------------------------------------------------

            enriched = dict(detection)

            enriched["track"] = {
                "track_id": track.track_id,

                "first_seen": (
                    track.first_seen.isoformat()
                ),

                "last_seen": (
                    track.last_seen.isoformat()
                ),

                "observations": track.observations,

                "distance_px": round(
                    track.total_distance_px,
                    2,
                ),

                "speed_px_s": round(
                    track.current_speed_px_s,
                    2,
                ),

                "acceleration_px_s2": round(
                    track.acceleration_px_s2,
                    2,
                ),

                "lifetime_seconds": round(
                    track.lifetime_seconds,
                    2,
                ),

                "dwell_time_seconds": round(
                    track.dwell_time_seconds,
                    2,
                ),

                "direction_degrees": (
                    round(
                        track.direction_degrees,
                        2,
                    )
                    if track.direction_degrees
                    is not None
                    else None
                ),

                "missing_frames": (
                    track.missing_frames
                ),

                "stopped": (
                    track.stopped_since is not None
                ),
            }

            enriched_detections.append(
                enriched
            )

        # ------------------------------------------------------------------
        # Handle tracks missing from current frame
        # ------------------------------------------------------------------

        expired_tracks: list[int] = []

        for track_id, track in self.tracks.items():

            if track_id in active_track_ids:
                continue

            track.missing_frames += 1

            if (
                track.missing_frames
                > self.max_missing_frames
            ):

                expired_tracks.append(track_id)

        # ------------------------------------------------------------------
        # Remove expired tracks
        # ------------------------------------------------------------------

        for track_id in expired_tracks:

            del self.tracks[track_id]

            logger.debug(
                "Track expired | track_id=%s",
                track_id,
            )

        return enriched_detections

    # ------------------------------------------------------------------
    # Event throttling
    # ------------------------------------------------------------------

    def should_emit_update(
        self,
        track_id: int,
        now: datetime | None = None,
    ) -> bool:

        track = self.tracks.get(track_id)

        if track is None:
            return False

        if (
            track.observations
            < self.min_track_observations
        ):
            return False

        if now is None:
            now = datetime.now(timezone.utc)

        now_seconds = now.timestamp()

        if (
            now_seconds - track.last_event_time
            < self.event_update_interval_seconds
        ):
            return False

        track.last_event_time = now_seconds

        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_track(
        self,
        track_id: int,
    ) -> TrackState | None:

        return self.tracks.get(track_id)

    def active_count(self) -> int:

        return len(self.tracks)

    def snapshot(self) -> list[TrackState]:
        return list(self.tracks.values())

    @staticmethod
    def _track_to_dict(
        track: TrackState,
    ) -> dict[str, Any]:

        return {
            "track_id": track.track_id,

            "object_type": track.object_type,

            "first_seen": (
                track.first_seen.isoformat()
            ),

            "last_seen": (
                track.last_seen.isoformat()
            ),

            "observations": track.observations,

            "distance_px": round(
                track.total_distance_px,
                2,
            ),

            "speed_px_s": round(
                track.current_speed_px_s,
                2,
            ),

            "acceleration_px_s2": round(
                track.acceleration_px_s2,
                2,
            ),

            "lifetime_seconds": round(
                track.lifetime_seconds,
                2,
            ),

            "dwell_time_seconds": round(
                track.dwell_time_seconds,
                2,
            ),

            "direction_degrees": (
                round(
                    track.direction_degrees,
                    2,
                )
                if track.direction_degrees is not None
                else None
            ),

            "missing_frames": (
                track.missing_frames
            ),

            "stopped": (
                track.stopped_since is not None
            ),
        }

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:

        self.tracks.clear()

        logger.info(
            "Track state manager reset"
        )