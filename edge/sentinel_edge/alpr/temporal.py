from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class PlateObservation:
    text: str
    confidence: float
    timestamp: float


class TemporalPlateAggregator:
    def __init__(self, max_observations: int = 10, minimum_votes: int = 2) -> None:
        if max_observations < 1 or minimum_votes < 1:
            raise ValueError("max_observations and minimum_votes must be >= 1")
        self.max_observations = int(max_observations)
        self.minimum_votes = int(minimum_votes)
        self._observations = defaultdict(list)

    def add(self, track_id: int, text: str, confidence: float, timestamp: float) -> None:
        observations = self._observations[int(track_id)]
        observations.append(PlateObservation(text, float(confidence), float(timestamp)))
        if len(observations) > self.max_observations:
            del observations[: len(observations) - self.max_observations]

    def best(self, track_id: int) -> tuple[str | None, float]:
        observations = self._observations.get(int(track_id), [])
        if not observations:
            return None, 0.0
        scores = defaultdict(float)
        votes = defaultdict(int)
        for observation in observations:
            scores[observation.text] += observation.confidence
            votes[observation.text] += 1
        candidates = [(text, votes[text], scores[text]) for text in scores]
        text, vote_count, score = max(candidates, key=lambda item: (item[1], item[2]))
        if vote_count < self.minimum_votes:
            return None, 0.0
        return text, score / vote_count

    def clear_track(self, track_id: int) -> None:
        self._observations.pop(int(track_id), None)

    def clear(self) -> None:
        self._observations.clear()
