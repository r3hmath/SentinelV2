from dataclasses import dataclass
from enum import Enum


class ThreatType(str, Enum):
    NONE = "NONE"
    WATCHLIST = "WATCHLIST"
    STOLEN_VEHICLE = "STOLEN_VEHICLE"
    SUSPICIOUS = "SUSPICIOUS"


class ThreatSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class ThreatRecord:
    plate: str
    threat_type: ThreatType
    severity: ThreatSeverity
    description: str
    source: str = "local"


@dataclass(frozen=True)
class ThreatAssessment:
    plate: str
    matched: bool
    threat_type: ThreatType
    severity: ThreatSeverity
    risk_score: float
    description: str
    source: str

    def to_dict(self) -> dict:
        return {
            "plate": self.plate,
            "matched": self.matched,
            "threat_type": self.threat_type.value,
            "severity": self.severity.value,
            "risk_score": round(self.risk_score, 4),
            "description": self.description,
            "source": self.source,
        }