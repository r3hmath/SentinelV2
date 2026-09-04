from enum import Enum


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


def risk_level(score: float) -> RiskLevel:
    if score >= 0.90:
        return RiskLevel.CRITICAL

    if score >= 0.70:
        return RiskLevel.HIGH

    if score >= 0.40:
        return RiskLevel.MEDIUM

    return RiskLevel.LOW