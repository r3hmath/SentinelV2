import logging
import uuid
from datetime import datetime, timezone

from sentinel_edge.camera.stream import CameraStream
from sentinel_edge.config import load_config
from sentinel_edge.inference.detector import VehicleTracker
from sentinel_edge.logging_config import setup_logging
from sentinel_edge.tracking.state import TrackStateManager
from sentinel_edge.transport.event_client import EventClient


logger = logging.getLogger("sentinel.edge")


def build_event(
    camera,
    config,
    event_type: str,
    detections: list[dict],
    frame_number: int,
    latency_ms: float,
) -> dict:

    timestamp = datetime.now(timezone.utc)

    confidence = 0.0

    if detections:

        confidence = max(
            detection["confidence"]
            for detection in detections
        )

    return {
        "event_id": str(uuid.uuid4()),

        "node_id": config.node.id,

        "camera_id": camera.id,

        "event_type": event_type,

        "timestamp": timestamp.isoformat(),

        "confidence": confidence,

        "latitude": config.node.latitude,

        "longitude": config.node.longitude,

        "frame_number": frame_number,

        "inference_latency_ms": round(
            latency_ms,
            2,
        ),

        "detections": detections,

        "metadata": {
            "node_name": config.node.name,

            "city": config.node.city,

            "source": str(camera.source),

            "tracking": {
                "tracker": config.inference.tracker,

                "active_tracks": len(
                    {
                        d["track_id"]
                        for d in detections
                        if d.get("track_id")
                        is not None
                    }
                ),
            },
        },
    }


def process_camera(
    camera,
    config,
    tracker,
    event_client,
):

    logger.info(
        "[%s] Starting camera: %s",
        camera.id,
        camera.source,
    )

    stream = CameraStream(
        camera.source
    )

    stream.open()

    state_manager = TrackStateManager(
        max_missing_frames=(
            config.inference.max_missing_frames
        ),

        event_update_interval_seconds=(
            config.inference
            .event_update_interval_seconds
        ),

        min_track_observations=(
            config.inference
            .min_track_observations
        ),
    )

    frame_number = 0

    events_sent = 0

    try:

        while True:

            success, frame = stream.read()

            if not success:

                logger.info(
                    "[%s] Stream ended",
                    camera.id,
                )

                break

            frame_number += 1

            # Tracking runs on every frame.
            if (
                frame_number
                % config.inference
                .track_every_n_frames
                != 0
            ):

                continue

            detections, latency_ms = tracker.track(
                frame
            )

            timestamp = datetime.now(
                timezone.utc
            )

            enriched_detections = (
                state_manager.update(
                    detections,
                    timestamp,
                )
            )

            if not enriched_detections:

                continue

            # Only send stable/newly-updated tracks.
            emit_detections = []

            for detection in enriched_detections:

                track_id = detection.get(
                    "track_id"
                )

                if track_id is None:

                    continue

                if state_manager.should_emit_update(
                    track_id,
                    timestamp,
                ):

                    emit_detections.append(
                        detection
                    )

            if not emit_detections:

                continue

            event = build_event(
                camera=camera,
                config=config,
                event_type="OBJECT_TRACKED",
                detections=emit_detections,
                frame_number=frame_number,
                latency_ms=latency_ms,
            )

            sent = event_client.send(event)

            if sent:

                events_sent += 1

                logger.info(
                    "[%s] Track event sent | "
                    "tracks=%d | active=%d | "
                    "latency=%.2fms",
                    camera.id,
                    len(emit_detections),
                    state_manager.active_count(),
                    latency_ms,
                )

    finally:

        stream.release()

        state_manager.reset()

        tracker.reset()

        logger.info(
            "[%s] Camera stopped | "
            "frames=%d | events=%d | "
            "active_tracks=%d",
            camera.id,
            frame_number,
            events_sent,
            state_manager.active_count(),
        )


def main():

    setup_logging()

    config = load_config()

    logger.info(
        "===================================="
    )

    logger.info(
        "Sentinel Edge Node Starting"
    )

    logger.info(
        "Node: %s",
        config.node.id,
    )

    logger.info(
        "City: %s",
        config.node.city,
    )

    logger.info(
        "Tracker: %s",
        config.inference.tracker,
    )

    logger.info(
        "===================================="
    )

    event_client = EventClient(
        config.api.base_url
    )

    try:

        for camera in config.cameras:

            if not camera.enabled:

                continue

            # A separate tracker instance is created
            # for each camera so tracker state cannot
            # leak between independent streams.
            tracker = VehicleTracker(
                model_path=(
                    config.inference.model_path
                ),

                confidence=(
                    config.inference.confidence
                ),

                classes=(
                    config.inference.classes
                ),

                tracker=(
                    config.inference.tracker
                ),

                image_size=(
                    config.inference.image_size
                ),
            )

            process_camera(
                camera=camera,
                config=config,
                tracker=tracker,
                event_client=event_client,
            )

    finally:

        event_client.close()

        logger.info(
            "Sentinel Edge Node stopped"
        )


if __name__ == "__main__":

    main()