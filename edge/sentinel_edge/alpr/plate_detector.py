from __future__ import annotations

import logging
from dataclasses import dataclass

from ultralytics import YOLO

logger = logging.getLogger("sentinel.edge.alpr")


@dataclass(frozen=True)
class PlateDetection:
    bbox: tuple[int, int, int, int]
    confidence: float


class PlateDetector:
    def __init__(self, model_path: str, confidence: float = 0.40, image_size: int = 640) -> None:
        if not model_path:
            raise ValueError("ALPR plate model path cannot be empty")
        self.model_path = model_path
        self.confidence = float(confidence)
        self.image_size = int(image_size)
        logger.info("Loading ALPR plate detector | model=%s", model_path)
        self.model = YOLO(model_path)

    def detect(self, vehicle_crop) -> PlateDetection | None:
        if vehicle_crop is None or vehicle_crop.size == 0:
            return None
        results = self.model.predict(source=vehicle_crop, conf=self.confidence, imgsz=self.image_size, verbose=False)
        if not results:
            return None
        result = results[0]
        if result.boxes is None or len(result.boxes) == 0:
            return None
        best = None
        h, w = vehicle_crop.shape[:2]
        for box in result.boxes:
            confidence = float(box.conf[0].item())
            if confidence < self.confidence:
                continue
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int).tolist()
            x1, y1 = max(0, min(x1, w - 1)), max(0, min(y1, h - 1))
            x2, y2 = max(0, min(x2, w)), max(0, min(y2, h))
            if x2 <= x1 or y2 <= y1:
                continue
            candidate = PlateDetection((x1, y1, x2, y2), confidence)
            if best is None or confidence > best.confidence:
                best = candidate
        return best

    @staticmethod
    def crop_plate(vehicle_crop, detection: PlateDetection):
        x1, y1, x2, y2 = detection.bbox
        plate = vehicle_crop[y1:y2, x1:x2]
        return plate if plate.size else None
