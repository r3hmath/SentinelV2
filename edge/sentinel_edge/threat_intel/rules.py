from .models import ThreatSeverity, ThreatType


THREAT_RISK_SCORES = {
    ThreatType.NONE: 0.0,
    ThreatType.SUSPICIOUS: 0.60,
    ThreatType.WATCHLIST: 0.85,
    ThreatType.STOLEN_VEHICLE: 0.98,
}


SEVERITY_RISK_CAP = {
    ThreatSeverity.LOW: 0.40,
    ThreatSeverity.MEDIUM: 0.65,
    ThreatSeverity.HIGH: 0.85,
    ThreatSeverity.CRITICAL: 1.00,
}


def calculate_risk_score(
    threat_type: ThreatType,
    severity: ThreatSeverity,
) -> float:
    base_score = THREAT_RISK_SCORES[threat_type]
    severity_cap = SEVERITY_RISK_CAP[severity]

    return min(base_score, severity_cap)