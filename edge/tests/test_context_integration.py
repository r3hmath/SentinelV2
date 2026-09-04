from sentinel_edge.intelligence.fusion import (
    ContextFusionEngine,
)
from sentinel_edge.intelligence.risk import (
    RiskLevel,
)


def test_unknown_plate_without_behavior_is_low_risk():
    engine = ContextFusionEngine()

    result = engine.assess(
        track_id=1,
        threat_risk=0.0,
        behavior_severity=None,
    )

    assert result.risk_score == 0.0
    assert result.risk_level == RiskLevel.LOW
    assert result.factors == []


def test_watchlist_plate_is_high_risk():
    engine = ContextFusionEngine()

    result = engine.assess(
        track_id=2,
        threat_risk=0.85,
        behavior_severity=None,
    )

    assert result.risk_score == 0.85
    assert result.risk_level == RiskLevel.HIGH
    assert "threat_intelligence_match" in result.factors


def test_stolen_vehicle_is_critical():
    engine = ContextFusionEngine()

    result = engine.assess(
        track_id=3,
        threat_risk=0.98,
        behavior_severity=None,
    )

    assert result.risk_score == 0.98
    assert result.risk_level == RiskLevel.CRITICAL


def test_critical_behavior_escalates_unknown_plate():
    engine = ContextFusionEngine()

    result = engine.assess(
        track_id=4,
        threat_risk=0.0,
        behavior_severity="CRITICAL",
    )

    assert result.risk_score == 0.95
    assert result.risk_level == RiskLevel.CRITICAL
    assert "critical_behavior" in result.factors


def test_high_behavior_escalates_unknown_plate():
    engine = ContextFusionEngine()

    result = engine.assess(
        track_id=5,
        threat_risk=0.0,
        behavior_severity="HIGH",
    )

    assert result.risk_score == 0.75
    assert result.risk_level == RiskLevel.HIGH
    assert "high_severity_behavior" in result.factors


def test_watchlist_plus_critical_behavior_remains_critical():
    engine = ContextFusionEngine()

    result = engine.assess(
        track_id=6,
        threat_risk=0.85,
        behavior_severity="CRITICAL",
    )

    assert result.risk_score == 0.95
    assert result.risk_level == RiskLevel.CRITICAL

    assert "threat_intelligence_match" in result.factors
    assert "critical_behavior" in result.factors


def test_stolen_vehicle_plus_critical_behavior_does_not_exceed_one():
    engine = ContextFusionEngine()

    result = engine.assess(
        track_id=7,
        threat_risk=0.98,
        behavior_severity="CRITICAL",
    )

    assert result.risk_score == 0.98
    assert result.risk_score <= 1.0
    assert result.risk_level == RiskLevel.CRITICAL

    assert "threat_intelligence_match" in result.factors
    assert "critical_behavior" in result.factors