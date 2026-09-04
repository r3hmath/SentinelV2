from __future__ import annotations

import re


class PlateValidator:
    MIN_LENGTH = 4
    MAX_LENGTH = 12

    @classmethod
    def normalize(cls, text: str | None) -> str | None:
        if not text:
            return None
        normalized = re.sub(r"[^A-Z0-9]", "", text.upper())
        if not cls.MIN_LENGTH <= len(normalized) <= cls.MAX_LENGTH:
            return None
        return normalized

    @classmethod
    def validate(cls, text: str | None) -> bool:
        return cls.normalize(text) is not None
