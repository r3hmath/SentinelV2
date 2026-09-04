import time

from ultralytics import YOLO


class VehicleDetector:

    def __init__(
        self,
        model_path: str,
        confidence: float,
        classes: list[int],
    ):

        self.model = YOLO(model_path)

        self.confidence = confidence

        self.classes = classes


    def detect(self, frame):

        start = time.perf_counter()

        results = self.model.predict(

            source=frame,

            classes=self.classes,

            conf=self.confidence,

            verbose=False,
        )

        latency_ms = (
            time.perf_counter() - start
        ) * 1000

        detections = []

        result = results[0]

        if result.boxes is None:
            return detections, latency_ms


        for box in result.boxes:

            cls_id = int(
                box.cls[0].item()
            )

            confidence = float(
                box.conf[0].item()
            )

            x1, y1, x2, y2 = map(
                int,
                box.xyxy[0].tolist()
            )

            detections.append({

                "object_type":
                    self.model.names[cls_id],

                "class_id":
                    cls_id,

                "confidence":
                    confidence,

                "bbox":
                    [x1, y1, x2, y2],

            })


        return detections, latency_ms