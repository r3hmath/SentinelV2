from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Detection(BaseModel):
    object_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: list[float] | None = None
    track_id: int | None = None


class EventCreate(BaseModel):
    event_id: UUID

    node_id: str
    camera_id: str
    event_type: str

    timestamp: datetime

    confidence: float = Field(
        ge=0.0,
        le=1.0
    )

    latitude: float | None = None
    longitude: float | None = None

    frame_number: int | None = None

    inference_latency_ms: float | None = None

    detections: list[Detection] = Field(
        default_factory=list
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class EventResponse(BaseModel):
    status: str
    event_id: UUID
    message: str