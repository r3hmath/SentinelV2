import sqlite3
from pathlib import Path

from .models import ThreatRecord, ThreatSeverity, ThreatType


class ThreatIntelRepository:
    def __init__(self, db_path: str = "./data/threat_intel.db"):
        self.db_path = Path(db_path)

        if self.db_path.parent != Path("."):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._initialize()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _initialize(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS threat_records (
                    plate TEXT PRIMARY KEY,
                    threat_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _normalize_plate(plate: str) -> str:
        return "".join(
            char for char in plate.upper()
            if char.isalnum()
        )

    def add(self, record: ThreatRecord) -> None:
        plate = self._normalize_plate(record.plate)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO threat_records
                (plate, threat_type, severity, description, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    plate,
                    record.threat_type.value,
                    record.severity.value,
                    record.description,
                    record.source,
                ),
            )

    def get(self, plate: str) -> ThreatRecord | None:
        plate = self._normalize_plate(plate)

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    plate,
                    threat_type,
                    severity,
                    description,
                    source
                FROM threat_records
                WHERE plate = ?
                """,
                (plate,),
            ).fetchone()

        if row is None:
            return None

        return ThreatRecord(
            plate=row[0],
            threat_type=ThreatType(row[1]),
            severity=ThreatSeverity(row[2]),
            description=row[3],
            source=row[4],
        )

    def remove(self, plate: str) -> None:
        plate = self._normalize_plate(plate)

        with self._connect() as conn:
            conn.execute(
                "DELETE FROM threat_records WHERE plate = ?",
                (plate,),
            )

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM threat_records")