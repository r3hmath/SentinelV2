import logging
import time
import uuid
from datetime import datetime, timezone

from sentinel_edge.config import load_config
from sentinel_edge.logging_config import setup_logging

from sentinel_edge.camera.stream import CameraStream
from sentinel_edge.inference.detector import VehicleDetector
from sentinel_edge.transport.event_client import EventClient


logger = logging.getLogger("sentinel.edge")


def process_camera(
    camera,
    config,
    detector,
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

    frame_number = 0

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

            # Selective frame processing.
            if (
                frame_number
                % config.inference.process_every_n_frames
                != 0
            ):
                continue


            detections, latency_ms = (
                detector.detect(frame)
            )


            if not detections:
                continue


            event = {

                "event_id": str(
                    uuid.uuid4()
                ),

                "node_id":
                    config.node.id,

                "camera_id":
                    camera.id,

                "event_type":
                    "OBJECT_DETECTED",

                "timestamp":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),

                "confidence":
                    max(
                        d["confidence"]
                        for d in detections
                    ),

                "latitude":
                    config.node.latitude,

                "longitude":
                    config.node.longitude,

                "frame_number":
                    frame_number,

                "inference_latency_ms":
                    round(
                        latency_ms,
                        2,
                    ),

                "detections":
                    detections,

                "metadata": {
                    "node_name":
                        config.node.name,

                    "city":
                        config.node.city,

                    "source":
                        str(camera.source),
                },
            }


            sent = event_client.send(event)


            if sent:

                logger.info(

                    "[%s] Event sent | "
                    "objects=%d | "
                    "latency=%.2fms",

                    camera.id,

                    len(detections),

                    latency_ms,
                )


    finally:

        stream.release()


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
        "===================================="
    )


    detector = VehicleDetector(

        model_path=
            config.inference.model_path,

        confidence=
            config.inference.confidence,

        classes=
            config.inference.classes,
    )


    event_client = EventClient(

        config.api.base_url
    )


    try:

        for camera in config.cameras:

            if not camera.enabled:
                continue

            process_camera(

                camera,

                config,

                detector,

                event_client,
            )

    finally:

        event_client.close()


if __name__ == "__main__":
    main()