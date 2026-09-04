from __future__ import annotations

import time
from typing import Any

from ultralytics import YOLO

import logging

logger = logging.getLogger("sentinel.edge.tracker")


class VehicleTracker:
    """
    YOLO + ByteTrack inference wrapper.

    Responsibilities:
    - Run object detection + tracking.
    - Maintain persistent ByteTrack IDs.
    - Return normalized detection dictionaries.
    - Measure inference latency.
    - Support tracker reset.
    """

    def __init__(
        self,
        model_path: str,
        confidence: float,
        classes: list[int],
        tracker: str = "bytetrack.yaml",
        image_size: int = 640,
    ):
        self.model_path = model_path
        self.confidence = confidence
        self.classes = classes
        self.tracker = tracker
        self.image_size = image_size

        logger.info("Loading YOLO model: %s", model_path)

        self.model = YOLO(model_path)

        logger.info(
            "Tracker initialized | tracker=%s | classes=%s",
            tracker,
            classes,
        )

    def track(
        self,
        frame,
    ) -> tuple[list[dict[str, Any]], float]:

        start_time = time.perf_counter()

        try:
            results = self.model.track(
                source=frame,
                persist=True,
                tracker=self.tracker,
                classes=self.classes,
                conf=self.confidence,
                imgsz=self.image_size,
                verbose=False,
            )

        except Exception:
            logger.exception("YOLO tracking inference failed")
            raise

        latency_ms = (time.perf_counter() - start_time) * 1000

        detections: list[dict[str, Any]] = []

        if not results:
            return detections, latency_ms

        result = results[0]

        if result.boxes is None:
            return detections, latency_ms

        boxes = result.boxes

        names = self.model.names

        # Iterate over detection index directly.
        for i in range(len(boxes)):

            try:
                # -----------------------------
                # Class ID
                # -----------------------------
                if boxes.cls is not None:
                    cls_id = int(boxes.cls[i].item())
                else:
                    cls_id = -1

                # -----------------------------
                # Confidence
                # -----------------------------
                if boxes.conf is not None:
                    confidence = float(boxes.conf[i].item())
                else:
                    confidence = 0.0

                # -----------------------------
                # Bounding box
                # -----------------------------
                bbox_tensor = boxes.xyxy[i]

                bbox = [
                    float(bbox_tensor[0].item()),
                    float(bbox_tensor[1].item()),
                    float(bbox_tensor[2].item()),
                    float(bbox_tensor[3].item()),
                ]

                # -----------------------------
                # Track ID
                # -----------------------------
                track_id = None

                if boxes.id is not None:
                    track_id = int(boxes.id[i].item())

                # -----------------------------
                # Object name
                # -----------------------------
                if isinstance(names, dict):
                    object_type = names.get(
                        cls_id,
                        str(cls_id),
                    )
                else:
                    object_type = (
                        names[cls_id]
                        if 0 <= cls_id < len(names)
                        else str(cls_id)
                    )

                # -----------------------------
                # Center point
                # -----------------------------
                center_x = (bbox[0] + bbox[2]) / 2.0
                center_y = (bbox[1] + bbox[3]) / 2.0

                detection = {
                    "object_type": object_type,
                    "class_id": cls_id,
                    "confidence": confidence,
                    "bbox": bbox,
                    "track_id": track_id,
                    "center": [
                        center_x,
                        center_y,
                    ],
                }

                detections.append(detection)

            except Exception:
                logger.exception(
                    "Failed to parse detection | index=%s",
                    i,
                )

        return detections, latency_ms

    def reset(self) -> None:
        """
        Reset tracker state.

        Ultralytics keeps tracker state internally when
        persist=True is used. Setting predictor to None
        forces the next track() call to initialize a
        fresh tracking session.
        """

        try:
            # Ultralytics uses the predictor internally for
            # persistent tracking state.
            self.model.predictor = None

            logger.info("Tracker state reset")

        except Exception:
            logger.exception("Failed to reset tracker state")

    def metrics(self) -> dict[str, Any]:
        """
        Return basic tracker diagnostics.
        """

        return {
            "model": self.model_path,
            "tracker": self.tracker,
            "confidence": self.confidence,
            "classes": self.classes,
            "image_size": self.image_size,
        }