from .models import (
    ThreatAssessment,
    ThreatSeverity,
    ThreatType,
)
from .repository import ThreatIntelRepository
from .rules import calculate_risk_score


class ThreatIntelEngine:
    def __init__(
        self,
        repository: ThreatIntelRepository | None = None,
    ):
        self.repository = repository or ThreatIntelRepository()

    def assess(self, plate: str) -> ThreatAssessment:
        normalized_plate = self.repository._normalize_plate(plate)

        record = self.repository.get(normalized_plate)

        if record is None:
            return ThreatAssessment(
                plate=normalized_plate,
                matched=False,
                threat_type=ThreatType.NONE,
                severity=ThreatSeverity.LOW,
                risk_score=0.0,
                description="No threat intelligence match",
                source="local",
            )

        risk_score = calculate_risk_score(
            threat_type=record.threat_type,
            severity=record.severity,
        )

        return ThreatAssessment(
            plate=normalized_plate,
            matched=True,
            threat_type=record.threat_type,
            severity=record.severity,
            risk_score=risk_score,
            description=record.description,
            source=record.source,
        )