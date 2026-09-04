from types import SimpleNamespace

from sentinel_edge.decision.engine import DecisionEngine
from sentinel_edge.decision.rules import (
    DecisionAction,
    DecisionConfig,
)


def make_track(
    track_id=1,
    object_type="car",
    observations=10,
    speed=0.0,
    acceleration=0.0,
    lifetime=10.0,
):
    return SimpleNamespace(
        track_id=track_id,
        object_type=object_type,
        observations=observations,
        current_speed_px_s=speed,
        acceleration_px_s2=acceleration,
        lifetime_seconds=lifetime,
    )


def test_new_track_triggers_local_ai():

    engine = DecisionEngine(
        DecisionConfig()
    )

    track = make_track(
        track_id=1,
        object_type="car",
        observations=1,
    )

    decision = engine.decide(
        track=track,
        confidence=0.60,
        now=100.0,
    )

    assert decision.action == DecisionAction.LOCAL_AI
    assert decision.reason == "new_track"


def test_stable_track_is_skipped():

    engine = DecisionEngine(
        DecisionConfig()
    )

    track = make_track(
        track_id=1,
        object_type="car",
        observations=20,
    )

    # First decision registers the track.
    engine.decide(
        track=track,
        confidence=0.60,
        now=100.0,
    )

    decision = engine.decide(
        track=track,
        confidence=0.60,
        now=101.0,
    )

    assert decision.action == DecisionAction.SKIP


def test_high_confidence_triggers_local_ai():

    engine = DecisionEngine(
        DecisionConfig(
            high_confidence_threshold=0.85
        )
    )

    track = make_track(
        track_id=1,
        object_type="car",
        observations=20,
    )

    # Register track.
    engine.decide(
        track=track,
        confidence=0.50,
        now=100.0,
    )

    # Wait beyond the inference cooldown.
    decision = engine.decide(
        track=track,
        confidence=0.95,
        now=111.0,
    )

    assert decision.action == DecisionAction.LOCAL_AI
    assert decision.reason == "high_confidence_detection"


def test_rapid_movement_triggers_local_ai():

    engine = DecisionEngine(
        DecisionConfig(
            rapid_movement_threshold_px_s=180
        )
    )

    track = make_track(
        track_id=1,
        object_type="car",
        observations=20,
        speed=250,
    )

    # Register track.
    engine.decide(
        track=track,
        confidence=0.50,
        now=100.0,
    )

    # Wait beyond the inference cooldown.
    decision = engine.decide(
        track=track,
        confidence=0.50,
        now=111.0,
    )

    assert decision.action == DecisionAction.LOCAL_AI
    assert decision.reason == "rapid_movement"


def test_behavior_triggers_local_ai():

    engine = DecisionEngine(
        DecisionConfig()
    )

    track = make_track(
        track_id=1,
        object_type="person",
        observations=20,
    )

    behavior_event = SimpleNamespace(
        behavior="loitering",
    )

    decision = engine.decide(
        track=track,
        behavior_events=[behavior_event],
        confidence=0.50,
        now=100.0,
    )

    assert decision.action == DecisionAction.LOCAL_AI
    assert decision.reason == "suspicious_behavior"


def test_unknown_object_defaults_to_skip():

    engine = DecisionEngine(
        DecisionConfig()
    )

    track = make_track(
        track_id=1,
        object_type="dog",
        observations=20,
    )

    engine.decide(
        track=track,
        confidence=0.50,
        now=100.0,
    )

    decision = engine.decide(
        track=track,
        confidence=0.50,
        now=101.0,
    )

    assert decision.action == DecisionAction.SKIP