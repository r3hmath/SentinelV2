import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger(
    "sentinel.edge.track_state"
)


@dataclass
class TrackState:

    track_id: int

    object_type: str

    first_seen: datetime

    last_seen: datetime

    first_center: tuple[float, float]

    last_center: tuple[float, float]

    observations: int = 0

    total_distance_px: float = 0.0

    current_speed_px_s: float = 0.0

    missing_frames: int = 0

    last_event_time: float = 0.0


class TrackStateManager:

    def __init__(
        self,
        max_missing_frames: int = 30,
        event_update_interval_seconds: float = 1.0,
        min_track_observations: int = 2,
    ):

        self.max_missing_frames = (
            max_missing_frames
        )

        self.event_update_interval_seconds = (
            event_update_interval_seconds
        )

        self.min_track_observations = (
            min_track_observations
        )

        self.tracks: dict[int, TrackState] = {}

    @staticmethod
    def _distance(
        point_a: tuple[float, float],
        point_b: tuple[float, float],
    ) -> float:

        return math.sqrt(
            (point_b[0] - point_a[0]) ** 2
            + (point_b[1] - point_a[1]) ** 2
        )

    def update(
        self,
        detections: list[dict[str, Any]],
        timestamp: datetime | None = None,
    ) -> list[dict[str, Any]]:

        if timestamp is None:

            timestamp = datetime.now(timezone.utc)

        timestamp_seconds = timestamp.timestamp()

        active_track_ids: set[int] = set()

        enriched_detections: list[
            dict[str, Any]
        ] = []

        for detection in detections:

            track_id = detection.get(
                "track_id"
            )

            if track_id is None:

                enriched_detections.append(
                    detection
                )

                continue

            center = detection.get("center")

            if not center or len(center) != 2:

                enriched_detections.append(
                    detection
                )

                continue

            center_point = (
                float(center[0]),
                float(center[1]),
            )

            active_track_ids.add(track_id)

            track = self.tracks.get(track_id)

            if track is None:

                track = TrackState(
                    track_id=track_id,
                    object_type=detection[
                        "object_type"
                    ],
                    first_seen=timestamp,
                    last_seen=timestamp,
                    first_center=center_point,
                    last_center=center_point,
                    observations=1,
                )

                self.tracks[track_id] = track

            else:

                elapsed_seconds = (
                    timestamp
                    - track.last_seen
                ).total_seconds()

                distance = self._distance(
                    track.last_center,
                    center_point,
                )

                track.total_distance_px += distance

                if elapsed_seconds > 0:

                    track.current_speed_px_s = (
                        distance
                        / elapsed_seconds
                    )

                track.last_center = center_point
                track.last_seen = timestamp
                track.observations += 1
                track.missing_frames = 0

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
            }

            enriched_detections.append(enriched)

        # Handle tracks that were not detected
        # in the current frame.
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

        for track_id in expired_tracks:

            del self.tracks[track_id]

            logger.debug(
                "Track expired | track_id=%s",
                track_id,
            )

        return enriched_detections

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

    def active_count(self) -> int:

        return len(self.tracks)

    def snapshot(self) -> list[dict[str, Any]]:

        return [
            {
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
                "missing_frames": track.missing_frames,
            }
            for track in self.tracks.values()
        ]

    def reset(self) -> None:

        self.tracks.clear()

        logger.info(
            "Track state manager reset"
        )