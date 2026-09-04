from __future__ import annotations

import logging
import math
from typing import Any

from sentinel_edge.tracking.state import (
    TrackState,
)
from sentinel_edge.behavior.rules import (
    BehaviorConfig,
    BehaviorEvent,
)


logger = logging.getLogger(
    "sentinel.edge.behavior"
)


class BehaviorEngine:
    """
    Evaluates persistent TrackState objects and produces
    security-relevant behavior events.

    The engine does NOT perform object detection.

    It operates entirely on tracking state.
    """

    PERSON_CLASSES = {
        "person",
    }

    VEHICLE_CLASSES = {
        "car",
        "truck",
        "bus",
        "motorcycle",
    }

    def __init__(
        self,
        config: BehaviorConfig | None = None,
    ):

        self.config = (
            config
            if config is not None
            else BehaviorConfig()
        )

        logger.info(
            "Behavior engine initialized"
        )

    # ==============================================================
    # Public API
    # ==============================================================

    def analyze(
        self,
        track: TrackState,
    ) -> list[BehaviorEvent]:

        if (
            track.observations
            < self.config.minimum_observations
        ):
            return []

        events: list[BehaviorEvent] = []

        # ----------------------------------------------------------
        # Loitering
        # ----------------------------------------------------------

        if self._check_loitering(track):
            events.append(
                self._create_loitering_event(track)
            )

        # ----------------------------------------------------------
        # Suspicious stop
        # ----------------------------------------------------------

        if self._check_suspicious_stop(track):
            events.append(
                self._create_suspicious_stop_event(
                    track
                )
            )

        # ----------------------------------------------------------
        # Rapid movement
        # ----------------------------------------------------------

        if self._check_rapid_movement(track):
            events.append(
                self._create_rapid_movement_event(
                    track
                )
            )

        # ----------------------------------------------------------
        # Direction change
        # ----------------------------------------------------------

        if self._check_direction_change(track):
            events.append(
                self._create_direction_change_event(
                    track
                )
            )

        return events

    # ==============================================================
    # Loitering
    # ==============================================================

    def _check_loitering(
        self,
        track: TrackState,
    ) -> bool:

        config = self.config

        if not config.loitering_enabled:
            return False

        # Loitering is primarily meaningful for people.
        if track.object_type.lower() not in self.PERSON_CLASSES:
            return False

        if (
            track.lifetime_seconds
            < config.loitering_min_duration_seconds
        ):
            return False

        if (
            track.total_distance_px
            > config.loitering_max_movement_px
        ):
            return False

        if (
            track.current_speed_px_s
            > config.loitering_max_speed_px_s
        ):
            return False

        return True

    def _create_loitering_event(
        self,
        track: TrackState,
    ) -> BehaviorEvent:

        duration = track.lifetime_seconds

        # Increase score gradually with duration.
        score = min(
            95,
            50
            + int(
                max(
                    0,
                    duration
                    - self.config.loitering_min_duration_seconds,
                )
                * 1.5
            ),
        )

        severity = self._severity_from_score(score)

        return BehaviorEvent(
            behavior="LOITERING",
            track_id=track.track_id,
            object_type=track.object_type,
            severity=severity,
            score=score,
            details={
                "duration_seconds": round(
                    duration,
                    2,
                ),
                "distance_px": round(
                    track.total_distance_px,
                    2,
                ),
                "speed_px_s": round(
                    track.current_speed_px_s,
                    2,
                ),
            },
        )

    # ==============================================================
    # Suspicious stop
    # ==============================================================

    def _check_suspicious_stop(
        self,
        track: TrackState,
    ) -> bool:

        config = self.config

        if not config.suspicious_stop_enabled:
            return False

        # Currently focus this rule on vehicles.
        if (
            track.object_type.lower()
            not in self.VEHICLE_CLASSES
        ):
            return False

        if track.stopped_since is None:
            return False

        stopped_duration = (
            track.last_seen
            - track.stopped_since
        ).total_seconds()

        if (
            stopped_duration
            < config.suspicious_stop_min_duration_seconds
        ):
            return False

        if (
            track.current_speed_px_s
            > config.suspicious_stop_max_speed_px_s
        ):
            return False

        return True

    def _create_suspicious_stop_event(
        self,
        track: TrackState,
    ) -> BehaviorEvent:

        stopped_duration = (
            track.last_seen
            - track.stopped_since
        ).total_seconds()

        score = min(
            95,
            55
            + int(
                max(
                    0,
                    stopped_duration
                    - self.config.suspicious_stop_min_duration_seconds,
                )
                * 1.5
            ),
        )

        severity = self._severity_from_score(score)

        return BehaviorEvent(
            behavior="SUSPICIOUS_STOP",
            track_id=track.track_id,
            object_type=track.object_type,
            severity=severity,
            score=score,
            details={
                "stopped_duration_seconds": round(
                    stopped_duration,
                    2,
                ),
                "speed_px_s": round(
                    track.current_speed_px_s,
                    2,
                ),
            },
        )

    # ==============================================================
    # Rapid movement
    # ==============================================================

    def _check_rapid_movement(
        self,
        track: TrackState,
    ) -> bool:

        if not self.config.rapid_movement_enabled:
            return False

        return (
            track.current_speed_px_s
            >= self.config.rapid_movement_speed_threshold_px_s
        )

    def _create_rapid_movement_event(
        self,
        track: TrackState,
    ) -> BehaviorEvent:

        speed = track.current_speed_px_s

        threshold = (
            self.config.rapid_movement_speed_threshold_px_s
        )

        ratio = speed / threshold

        score = min(
            95,
            55 + int((ratio - 1.0) * 30),
        )

        severity = self._severity_from_score(score)

        return BehaviorEvent(
            behavior="RAPID_MOVEMENT",
            track_id=track.track_id,
            object_type=track.object_type,
            severity=severity,
            score=score,
            details={
                "speed_px_s": round(
                    speed,
                    2,
                ),
                "threshold_px_s": threshold,
                "acceleration_px_s2": round(
                    track.acceleration_px_s2,
                    2,
                ),
            },
        )

    # ==============================================================
    # Direction change
    # ==============================================================

    def _check_direction_change(
        self,
        track: TrackState,
    ) -> bool:

        if not self.config.direction_change_enabled:
            return False

        if len(track.trajectory) < 3:
            return False

        if (
            track.current_speed_px_s
            < self.config.direction_change_min_speed_px_s
        ):
            return False

        observations = list(
            track.trajectory
        )

        previous = observations[-2]
        current = observations[-1]

        # We need an earlier segment.
        if len(observations) < 3:
            return False

        before = observations[-3]

        v1_x = (
            previous.center[0]
            - before.center[0]
        )

        v1_y = (
            previous.center[1]
            - before.center[1]
        )

        v2_x = (
            current.center[0]
            - previous.center[0]
        )

        v2_y = (
            current.center[1]
            - previous.center[1]
        )

        magnitude_1 = math.hypot(
            v1_x,
            v1_y,
        )

        magnitude_2 = math.hypot(
            v2_x,
            v2_y,
        )

        if (
            magnitude_1 < 1e-6
            or magnitude_2 < 1e-6
        ):
            return False

        cosine = (
            (v1_x * v2_x)
            + (v1_y * v2_y)
        ) / (
            magnitude_1
            * magnitude_2
        )

        # Floating point protection.
        cosine = max(
            -1.0,
            min(1.0, cosine),
        )

        angle = math.degrees(
            math.acos(cosine)
        )

        return (
            angle
            >= self.config.direction_change_angle_threshold_degrees
        )

    def _create_direction_change_event(
        self,
        track: TrackState,
    ) -> BehaviorEvent:

        observations = list(
            track.trajectory
        )

        before = observations[-3]
        previous = observations[-2]
        current = observations[-1]

        v1 = (
            previous.center[0]
            - before.center[0],
            previous.center[1]
            - before.center[1],
        )

        v2 = (
            current.center[0]
            - previous.center[0],
            current.center[1]
            - previous.center[1],
        )

        magnitude_1 = math.hypot(*v1)
        magnitude_2 = math.hypot(*v2)

        cosine = (
            v1[0] * v2[0]
            + v1[1] * v2[1]
        ) / (
            magnitude_1
            * magnitude_2
        )

        cosine = max(
            -1.0,
            min(1.0, cosine),
        )

        angle = math.degrees(
            math.acos(cosine)
        )

        score = min(
            95,
            50
            + int(
                (
                    angle
                    / self.config.direction_change_angle_threshold_degrees
                )
                * 25
            ),
        )

        severity = self._severity_from_score(score)

        return BehaviorEvent(
            behavior="ABNORMAL_DIRECTION_CHANGE",
            track_id=track.track_id,
            object_type=track.object_type,
            severity=severity,
            score=score,
            details={
                "angle_degrees": round(
                    angle,
                    2,
                ),
                "speed_px_s": round(
                    track.current_speed_px_s,
                    2,
                ),
            },
        )

    # ==============================================================
    # Severity
    # ==============================================================

    @staticmethod
    def _severity_from_score(
        score: int,
    ) -> str:

        if score >= 80:
            return "high"

        if score >= 60:
            return "medium"

        return "low"