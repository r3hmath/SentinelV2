from sentinel_edge.threat_intel import (
    ThreatIntelEngine,
    ThreatIntelRepository,
    ThreatRecord,
    ThreatSeverity,
    ThreatType,
)


def create_engine(tmp_path):
    repository = ThreatIntelRepository(
        str(tmp_path / "threat_intel.db")
    )

    return repository, ThreatIntelEngine(repository)


def test_unknown_plate_is_safe(tmp_path):
    _, engine = create_engine(tmp_path)

    result = engine.assess("KA 01 AB 1234")

    assert result.matched is False
    assert result.threat_type == ThreatType.NONE
    assert result.risk_score == 0.0


def test_watchlist_plate(tmp_path):
    repository, engine = create_engine(tmp_path)

    repository.add(
        ThreatRecord(
            plate="KA01AB1234",
            threat_type=ThreatType.WATCHLIST,
            severity=ThreatSeverity.HIGH,
            description="Vehicle is on security watchlist",
        )
    )

    result = engine.assess("KA 01 AB 1234")

    assert result.matched is True
    assert result.threat_type == ThreatType.WATCHLIST
    assert result.severity == ThreatSeverity.HIGH
    assert result.risk_score == 0.85


def test_stolen_vehicle_is_critical(tmp_path):
    repository, engine = create_engine(tmp_path)

    repository.add(
        ThreatRecord(
            plate="MH12XY9999",
            threat_type=ThreatType.STOLEN_VEHICLE,
            severity=ThreatSeverity.CRITICAL,
            description="Vehicle reported stolen",
        )
    )

    result = engine.assess("MH12XY9999")

    assert result.matched is True
    assert result.threat_type == ThreatType.STOLEN_VEHICLE
    assert result.severity == ThreatSeverity.CRITICAL
    assert result.risk_score == 0.98


def test_plate_normalization(tmp_path):
    repository, engine = create_engine(tmp_path)

    repository.add(
        ThreatRecord(
            plate="GJ-01-AB-1234",
            threat_type=ThreatType.WATCHLIST,
            severity=ThreatSeverity.HIGH,
            description="Test watchlist entry",
        )
    )

    result = engine.assess("GJ 01 AB 1234")

    assert result.matched is True
    assert result.plate == "GJ01AB1234"