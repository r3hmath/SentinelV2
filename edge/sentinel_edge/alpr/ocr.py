from __future__ import annotations

import logging
import re

import cv2
import easyocr

logger = logging.getLogger("sentinel.edge.alpr")


class PlateOCR:
    def __init__(self, languages: list[str] | None = None, gpu: bool = False) -> None:
        self.languages = languages or ["en"]
        self.gpu = gpu
        logger.info("Initializing ALPR OCR | languages=%s | gpu=%s", self.languages, self.gpu)
        self.reader = easyocr.Reader(self.languages, gpu=self.gpu)

    def read(self, plate_image) -> tuple[str | None, float]:
        if plate_image is None or plate_image.size == 0:
            return None, 0.0
        processed = self._preprocess(plate_image)
        results = self.reader.readtext(processed, detail=1, paragraph=False)
        candidates = []
        for result in results or []:
            if len(result) < 3:
                continue
            cleaned = self._clean(result[1])
            if cleaned:
                candidates.append((cleaned, float(result[2])))
        if not candidates:
            return None, 0.0
        return max(candidates, key=lambda item: item[1])

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", text.upper())

    @staticmethod
    def _preprocess(image):
        enlarged = cv2.resize(image, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        return cv2.bilateralFilter(gray, 9, 75, 75)
