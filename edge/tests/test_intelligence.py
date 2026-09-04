from sentinel_edge.intelligence.fusion import (
    ContextFusionEngine,
)
from sentinel_edge.intelligence.risk import (
    RiskLevel,
    risk_level,
)


def test_low_risk():
    assert risk_level(0.10) == RiskLevel.LOW


def test_medium_risk():
    assert risk_level(0.50) == RiskLevel.MEDIUM


def test_high_risk():
    assert risk_level(0.75) == RiskLevel.HIGH


def test_critical_risk():
    assert risk_level(0.95) == RiskLevel.CRITICAL


def test_stolen_vehicle_remains_critical():
    engine = ContextFusionEngine()

    result = engine.assess(
        track_id=1,
        threat_risk=0.98,
    )

    assert result.risk_level == RiskLevel.CRITICAL
    assert result.risk_score == 0.98
    assert "threat_intelligence_match" in result.factors


def test_critical_behavior_escalates():
    engine = ContextFusionEngine()

    result = engine.assess(
        track_id=2,
        threat_risk=0.0,
        behavior_severity="CRITICAL",
    )

    assert result.risk_level == RiskLevel.CRITICAL
    assert result.risk_score == 0.95


def test_threat_and_behavior_do_not_exceed_one():
    engine = ContextFusionEngine()

    result = engine.assess(
        track_id=3,
        threat_risk=0.98,
        behavior_severity="CRITICAL",
    )

    assert result.risk_score <= 1.0
    assert result.risk_score == 0.98