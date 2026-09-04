from sentinel_edge.alpr.temporal import TemporalPlateAggregator
from sentinel_edge.alpr.validator import PlateValidator


def test_plate_validator_accepts_valid_plate():
    assert PlateValidator.normalize("KA 01 AB 1234") == "KA01AB1234"


def test_plate_validator_rejects_short_text():
    assert PlateValidator.normalize("AB1") is None


def test_temporal_voting_selects_consistent_plate():
    aggregator = TemporalPlateAggregator(10, 2)
    aggregator.add(10, "KA01AB1234", 0.90, 1)
    aggregator.add(10, "KA01AB1234", 0.85, 2)
    aggregator.add(10, "KA01A81234", 0.95, 3)
    plate, confidence = aggregator.best(10)
    assert plate == "KA01AB1234"
    assert confidence > 0.80


def test_temporal_voting_requires_minimum_votes():
    aggregator = TemporalPlateAggregator(10, 2)
    aggregator.add(20, "MH12XY1234", 0.90, 1)
    plate, confidence = aggregator.best(20)
    assert plate is None
    assert confidence == 0.0
