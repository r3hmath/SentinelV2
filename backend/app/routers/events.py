import json
import logging

from fastapi import APIRouter, HTTPException

from app.database.redis import redis_client
from app.models.schemas import EventCreate, EventResponse


logger = logging.getLogger("sentinel.api.events")

router = APIRouter()

EVENT_STREAM = "sentinel:events"


@router.post(
    "/events",
    response_model=EventResponse
)
async def create_event(event: EventCreate):

    if redis_client.client is None:
        raise HTTPException(
            status_code=503,
            detail="Redis is unavailable"
        )

    try:

        redis_payload = {
            "event_id": str(event.event_id),

            "node_id": event.node_id,

            "camera_id": event.camera_id,

            "event_type": event.event_type,

            "timestamp": event.timestamp.isoformat(),

            "confidence": str(event.confidence),

            "latitude": (
                str(event.latitude)
                if event.latitude is not None
                else ""
            ),

            "longitude": (
                str(event.longitude)
                if event.longitude is not None
                else ""
            ),

            "frame_number": (
                str(event.frame_number)
                if event.frame_number is not None
                else ""
            ),

            "inference_latency_ms": (
                str(event.inference_latency_ms)
                if event.inference_latency_ms is not None
                else ""
            ),

            "detections": json.dumps(
                [
                    detection.model_dump()
                    for detection in event.detections
                ]
            ),

            "metadata": json.dumps(
                event.metadata
            ),
        }

        redis_id = await redis_client.client.xadd(
            EVENT_STREAM,
            redis_payload,
            maxlen=10000,
            approximate=True,
        )

        logger.info(
            "Event queued | event_id=%s | redis_id=%s",
            event.event_id,
            redis_id,
        )

        return EventResponse(
            status="accepted",
            event_id=event.event_id,
            message="Event accepted into Sentinel event stream",
        )

    except Exception:

        logger.exception(
            "Failed to publish event"
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to publish event"
        )