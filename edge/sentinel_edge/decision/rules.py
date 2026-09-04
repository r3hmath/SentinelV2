from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DecisionAction(str, Enum):
    SKIP = "SKIP"
    LOCAL_AI = "LOCAL_AI"
    CLOUD_AI = "CLOUD_AI"


class DecisionPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class DecisionConfig:
    """
    Configuration for selective AI decisions.
    """

    enabled: bool = True

    # Run secondary AI periodically even when
    # nothing suspicious is happening.
    periodic_inference_seconds: float = 5.0

    # New tracks receive secondary analysis.
    analyze_new_tracks: bool = True

    # Analyze objects whose confidence is above this value.
    high_confidence_threshold: float = 0.85

    # Objects moving faster than this receive attention.
    rapid_movement_threshold_px_s: float = 180.0

    # Vehicle classes eligible for expensive analysis.
    vehicle_types: tuple[str, ...] = (
        "car",
        "truck",
        "bus",
        "motorcycle",
    )

    # Person objects can trigger analysis when
    # they remain in the scene.
    person_enabled: bool = True

    # Suspicious behavior always gets priority.
    behavior_priority_enabled: bool = True

    # After this many observations a stable track
    # can be skipped unless another trigger fires.
    stable_track_observations: int = 10

    def __post_init__(self) -> None:
        if self.periodic_inference_seconds < 0:
            raise ValueError(
                "periodic_inference_seconds must be >= 0"
            )

        if not 0.0 <= self.high_confidence_threshold <= 1.0:
            raise ValueError(
                "high_confidence_threshold must be between 0 and 1"
            )

        if self.rapid_movement_threshold_px_s < 0:
            raise ValueError(
                "rapid_movement_threshold_px_s must be >= 0"
            )

        if self.stable_track_observations < 1:
            raise ValueError(
                "stable_track_observations must be >= 1"
            )


@dataclass(frozen=True)
class AIDecision:
    """
    Decision produced for one tracked object.
    """

    action: DecisionAction
    priority: DecisionPriority
    reason: str
    track_id: int
    object_type: str
    confidence: float
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "priority": self.priority.value,
            "reason": self.reason,
            "track_id": self.track_id,
            "object_type": self.object_type,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }