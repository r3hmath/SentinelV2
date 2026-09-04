from dataclasses import dataclass

from sentinel_edge.intelligence.risk import (
    RiskLevel,
    risk_level,
)


@dataclass(frozen=True)
class ContextAssessment:
    track_id: int
    risk_score: float
    risk_level: RiskLevel
    factors: list[str]

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "risk_score": round(self.risk_score, 4),
            "risk_level": self.risk_level.value,
            "factors": self.factors,
        }


class ContextFusionEngine:

    def assess(
        self,
        track_id: int,
        threat_risk: float = 0.0,
        behavior_severity: str | None = None,
    ) -> ContextAssessment:

        score = threat_risk
        factors = []

        if threat_risk > 0:
            factors.append("threat_intelligence_match")

        if behavior_severity == "HIGH":
            score = max(score, 0.75)
            factors.append("high_severity_behavior")

        elif behavior_severity == "CRITICAL":
            score = max(score, 0.95)
            factors.append("critical_behavior")

        return ContextAssessment(
            track_id=track_id,
            risk_score=min(score, 1.0),
            risk_level=risk_level(score),
            factors=factors,
        )