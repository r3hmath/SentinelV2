from __future__ import annotations

import logging
import time
from typing import Any

from sentinel_edge.tracking.state import TrackState

from .rules import (
    AIDecision,
    DecisionAction,
    DecisionConfig,
    DecisionPriority,
)


logger = logging.getLogger("sentinel.edge.decision")


class DecisionEngine:
    """
    Selective AI Decision Engine.

    This layer sits AFTER lightweight object detection
    and tracking.

    It decides whether expensive secondary AI should run.

    Possible actions:

        SKIP
        LOCAL_AI
        CLOUD_AI
    """

    def __init__(
        self,
        config: DecisionConfig | None = None,
    ):
        self.config = config or DecisionConfig()

        # Track ID -> timestamp of last expensive AI inference.
        self._last_inference: dict[int, float] = {}

        # Track IDs that have already been seen.
        self._known_tracks: set[int] = set()

        logger.info(
            "Decision engine initialized | enabled=%s",
            self.config.enabled,
        )

    # ============================================================
    # PUBLIC API
    # ============================================================

    def decide(
        self,
        track: TrackState,
        behavior_events: list[Any] | None = None,
        confidence: float = 0.0,
        now: float | None = None,
    ) -> AIDecision:
        """
        Decide whether expensive AI should run.

        Parameters
        ----------
        track:
            Current TrackState.

        behavior_events:
            Behavior events already calculated by BehaviorEngine.

        confidence:
            Current detection confidence.

        now:
            Monotonic timestamp.

            Primarily supplied by tests for deterministic behavior.
            Runtime calls can omit it.
        """

        if now is None:
            now = time.monotonic()

        track_id = int(track.track_id)

        object_type = str(
            track.object_type
        )

        # --------------------------------------------------------
        # ENGINE DISABLED
        # --------------------------------------------------------

        if not self.config.enabled:

            return self._decision(
                action=DecisionAction.SKIP,
                priority=DecisionPriority.LOW,
                reason="decision_engine_disabled",
                track=track,
                confidence=confidence,
                now=now,
            )

        # --------------------------------------------------------
        # CRITICAL: BEHAVIOR EVENT
        # --------------------------------------------------------

        if (
            self.config.behavior_priority_enabled
            and behavior_events
        ):

            return self._decision(
                action=DecisionAction.LOCAL_AI,
                priority=DecisionPriority.CRITICAL,
                reason="suspicious_behavior",
                track=track,
                confidence=confidence,
                metadata={
                    "behaviors": [
                        event.behavior
                        for event in behavior_events
                    ]
                },
                now=now,
            )

        # --------------------------------------------------------
        # NEW TRACK
        # --------------------------------------------------------

        if (
            self.config.analyze_new_tracks
            and track_id not in self._known_tracks
        ):

            self._known_tracks.add(track_id)

            return self._decision(
                action=DecisionAction.LOCAL_AI,
                priority=DecisionPriority.HIGH,
                reason="new_track",
                track=track,
                confidence=confidence,
                now=now,
            )

        # --------------------------------------------------------
        # HIGH CONFIDENCE OBJECT
        # --------------------------------------------------------

        if (
            confidence
            >= self.config.high_confidence_threshold
        ):

            if self._cooldown_expired(
                track_id,
                now,
            ):

                return self._decision(
                    action=DecisionAction.LOCAL_AI,
                    priority=DecisionPriority.HIGH,
                    reason="high_confidence_detection",
                    track=track,
                    confidence=confidence,
                    now=now,
                )

        # --------------------------------------------------------
        # RAPID MOVEMENT
        # --------------------------------------------------------

        current_speed = float(
            getattr(
                track,
                "current_speed_px_s",
                0.0,
            )
            or 0.0
        )

        if (
            current_speed
            >= self.config.rapid_movement_threshold_px_s
        ):

            if self._cooldown_expired(
                track_id,
                now,
            ):

                return self._decision(
                    action=DecisionAction.LOCAL_AI,
                    priority=DecisionPriority.HIGH,
                    reason="rapid_movement",
                    track=track,
                    confidence=confidence,
                    now=now,
                )

        # --------------------------------------------------------
        # VEHICLE
        # --------------------------------------------------------

        if object_type.lower() in (
            self.config.vehicle_types
        ):

            if self._periodic_due(
                track_id,
                now,
            ):

                return self._decision(
                    action=DecisionAction.LOCAL_AI,
                    priority=DecisionPriority.MEDIUM,
                    reason="periodic_vehicle_analysis",
                    track=track,
                    confidence=confidence,
                    now=now,
                )

        # --------------------------------------------------------
        # PERSON
        # --------------------------------------------------------

        if (
            self.config.person_enabled
            and object_type.lower() == "person"
        ):

            if self._periodic_due(
                track_id,
                now,
            ):

                return self._decision(
                    action=DecisionAction.LOCAL_AI,
                    priority=DecisionPriority.MEDIUM,
                    reason="periodic_person_analysis",
                    track=track,
                    confidence=confidence,
                    now=now,
                )

        # --------------------------------------------------------
        # STABLE TRACK
        # --------------------------------------------------------

        observations = int(
            getattr(
                track,
                "observations",
                0,
            )
            or 0
        )

        if (
            observations
            >= self.config.stable_track_observations
        ):

            return self._decision(
                action=DecisionAction.SKIP,
                priority=DecisionPriority.LOW,
                reason="stable_track",
                track=track,
                confidence=confidence,
                now=now,
            )

        # --------------------------------------------------------
        # DEFAULT
        # --------------------------------------------------------

        return self._decision(
            action=DecisionAction.SKIP,
            priority=DecisionPriority.LOW,
            reason="no_trigger",
            track=track,
            confidence=confidence,
            now=now,
        )

    # ============================================================
    # COOLDOWN
    # ============================================================

    def _cooldown_expired(
        self,
        track_id: int,
        now: float,
    ) -> bool:
        """
        Return True if this track is allowed to trigger
        another expensive AI inference.
        """

        last = self._last_inference.get(
            track_id
        )

        if last is None:
            return True

        return (
            now - last
            >= self.config.periodic_inference_seconds
        )

    # ============================================================
    # PERIODIC INFERENCE
    # ============================================================

    def _periodic_due(
        self,
        track_id: int,
        now: float,
    ) -> bool:
        """
        Determine whether periodic AI analysis is due.
        """

        interval = (
            self.config.periodic_inference_seconds
        )

        # No cooldown means every evaluation is due.
        if interval == 0:

            self._last_inference[
                track_id
            ] = now

            return True

        last = self._last_inference.get(
            track_id
        )

        # First periodic evaluation.
        if last is None:

            self._last_inference[
                track_id
            ] = now

            return True

        # Interval expired.
        if (
            now - last
            >= interval
        ):

            self._last_inference[
                track_id
            ] = now

            return True

        return False

    # ============================================================
    # DECISION CREATION
    # ============================================================

    def _decision(
        self,
        action: DecisionAction,
        priority: DecisionPriority,
        reason: str,
        track: TrackState,
        confidence: float,
        now: float,
        metadata: dict[str, Any] | None = None,
    ) -> AIDecision:
        """
        Construct an AIDecision.

        IMPORTANT:
        Use the same `now` clock supplied to `decide()`.

        This keeps cooldown calculations deterministic.
        """

        if action != DecisionAction.SKIP:

            self._last_inference[
                track.track_id
            ] = now

        return AIDecision(
            action=action,
            priority=priority,
            reason=reason,
            track_id=track.track_id,
            object_type=track.object_type,
            confidence=confidence,
            metadata=metadata or {},
        )

    # ============================================================
    # LIFECYCLE
    # ============================================================

    def reset_track(
        self,
        track_id: int,
    ) -> None:
        """
        Remove all Decision Engine state for a track.
        """

        self._known_tracks.discard(
            track_id
        )

        self._last_inference.pop(
            track_id,
            None,
        )

    def reset(self) -> None:
        """
        Reset all Decision Engine state.
        """

        self._known_tracks.clear()

        self._last_inference.clear()