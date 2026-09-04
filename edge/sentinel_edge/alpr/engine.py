from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .ocr import PlateOCR
from .plate_detector import PlateDetector
from .temporal import TemporalPlateAggregator
from .validator import PlateValidator

logger = logging.getLogger("sentinel.edge.alpr")


@dataclass(frozen=True)
class ALPRResult:
    track_id: int
    plate_text: str | None
    plate_confidence: float
    detector_confidence: float
    recognized: bool
    timestamp: float


class ALPREngine:
    def __init__(self, plate_model_path: str, detector_confidence: float = 0.40,
                 detector_image_size: int = 640, ocr_gpu: bool = False,
                 temporal_observations: int = 10, temporal_minimum_votes: int = 2) -> None:
        self.detector = PlateDetector(plate_model_path, detector_confidence, detector_image_size)
        self.ocr = PlateOCR(["en"], ocr_gpu)
        self.temporal = TemporalPlateAggregator(temporal_observations, temporal_minimum_votes)

    def process(self, track_id: int, vehicle_crop, timestamp: float | None = None) -> ALPRResult:
        timestamp = time.monotonic() if timestamp is None else timestamp
        detection = self.detector.detect(vehicle_crop)
        if detection is None:
            return ALPRResult(int(track_id), None, 0.0, 0.0, False, timestamp)
        plate_crop = self.detector.crop_plate(vehicle_crop, detection)
        if plate_crop is None:
            return ALPRResult(int(track_id), None, 0.0, detection.confidence, False, timestamp)
        raw_text, ocr_confidence = self.ocr.read(plate_crop)
        normalized = PlateValidator.normalize(raw_text)
        if normalized is None:
            return ALPRResult(int(track_id), None, 0.0, detection.confidence, False, timestamp)
        self.temporal.add(int(track_id), normalized, ocr_confidence, timestamp)
        best_text, best_confidence = self.temporal.best(track_id)
        if best_text is not None:
            logger.info("ALPR recognized | track=%s | plate=%s | confidence=%.3f", track_id, best_text, best_confidence)
        return ALPRResult(int(track_id), best_text, best_confidence, detection.confidence, best_text is not None, timestamp)

    def clear_track(self, track_id: int) -> None:
        self.temporal.clear_track(track_id)

    def reset(self) -> None:
        self.temporal.clear()
