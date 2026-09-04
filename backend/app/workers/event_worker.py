import asyncio
import json
import logging
import os
from datetime import datetime
from uuid import UUID

from app.database.postgres import postgres
from app.database.redis import redis_client


logger = logging.getLogger("sentinel.worker")


STREAM_NAME = "sentinel:events"

GROUP_NAME = "sentinel-workers"

CONSUMER_NAME = os.getenv(
    "SENTINEL_CONSUMER_NAME",
    "worker-1",
)

BLOCK_MS = 5000

BATCH_SIZE = 10


async def create_consumer_group():
    """
    Create the Redis consumer group if it
    does not already exist.
    """

    try:

        await redis_client.client.xgroup_create(
            name=STREAM_NAME,

            groupname=GROUP_NAME,

            id="0",

            mkstream=True,
        )

        logger.info(
            "Created consumer group: %s",
            GROUP_NAME,
        )

    except Exception as exc:

        if "BUSYGROUP" in str(exc):

            logger.info(
                "Consumer group already exists: %s",
                GROUP_NAME,
            )

        else:

            raise


async def save_event(event_data: dict):
    """
    Convert a Redis event into a PostgreSQL row.
    """

    event_id = UUID(
        event_data["event_id"]
    )

    node_id = event_data["node_id"]

    camera_id = event_data["camera_id"]

    event_type = event_data["event_type"]

    timestamp = datetime.fromisoformat(
        event_data["timestamp"]
    )

    confidence = float(
        event_data["confidence"]
    )

    latitude = (
        float(event_data["latitude"])
        if event_data.get("latitude")
        else None
    )

    longitude = (
        float(event_data["longitude"])
        if event_data.get("longitude")
        else None
    )

    frame_number = (
        int(event_data["frame_number"])
        if event_data.get("frame_number")
        else None
    )

    inference_latency_ms = (
        float(
            event_data["inference_latency_ms"]
        )
        if event_data.get(
            "inference_latency_ms"
        )
        else None
    )

    detections = json.loads(
        event_data.get(
            "detections",
            "[]"
        )
    )

    metadata = json.loads(
        event_data.get(
            "metadata",
            "{}"
        )
    )

    stored_metadata = {
        "detections": detections,
        **metadata,
    }

    async with postgres.pool.acquire() as connection:

        await connection.execute(
            """
            INSERT INTO public.events (
                event_id,
                node_id,
                camera_id,
                event_type,
                confidence,
                event_timestamp,
                latitude,
                longitude,
                frame_number,
                inference_latency_ms,
                metadata,
                processing_status,
                processing_attempts,
                processed_at
            )

            VALUES (
                $1,
                $2,
                $3,
                $4,
                $5,
                $6,
                $7,
                $8,
                $9,
                $10,
                $11::jsonb,
                'processed',
                1,
                NOW()
            )

            ON CONFLICT (event_id)
            DO NOTHING
            """,

            event_id,

            node_id,

            camera_id,

            event_type,

            confidence,

            timestamp,

            latitude,

            longitude,

            frame_number,

            inference_latency_ms,

            json.dumps(
                stored_metadata
            ),
        )


async def process_message(
    message_id: str,
    fields: dict,
):
    """
    Process one Redis message.

    ACK happens ONLY after PostgreSQL
    persistence succeeds.
    """

    try:

        await save_event(fields)

        await redis_client.client.xack(
            STREAM_NAME,
            GROUP_NAME,
            message_id,
        )

        logger.info(
            "Event persisted | redis_id=%s | event_id=%s",
            message_id,
            fields.get("event_id"),
        )

        return True

    except Exception:

        logger.exception(
            "Event processing failed | redis_id=%s | event_id=%s",
            message_id,
            fields.get("event_id"),
        )

        return False


async def process_pending_messages():
    """
    Recover messages previously delivered to
    this consumer but never ACKed.
    """

    logger.info(
        "Checking for pending messages..."
    )

    total_processed = 0

    while True:

        messages = await redis_client.client.xreadgroup(
            groupname=GROUP_NAME,

            consumername=CONSUMER_NAME,

            streams={
                STREAM_NAME: "0"
            },

            count=BATCH_SIZE,
        )

        if not messages:
            break

        found_message = False

        for stream_name, stream_messages in messages:

            for message_id, fields in stream_messages:

                found_message = True

                success = await process_message(
                    message_id,
                    fields,
                )

                if success:

                    total_processed += 1

                else:

                    logger.error(
                        "Pending event failed again | redis_id=%s",
                        message_id,
                    )

        if not found_message:
            break

    logger.info(
        "Pending recovery complete | processed=%d",
        total_processed,
    )


async def worker_loop():

    await create_consumer_group()

    logger.info(
        "Sentinel Event Worker started | consumer=%s",
        CONSUMER_NAME,
    )

    # ----------------------------------
    # Recover previously pending events
    # ----------------------------------

    await process_pending_messages()

    # ----------------------------------
    # Process new events
    # ----------------------------------

    logger.info(
        "Waiting for new events..."
    )

    while True:

        try:

            messages = await redis_client.client.xreadgroup(
                groupname=GROUP_NAME,

                consumername=CONSUMER_NAME,

                streams={
                    STREAM_NAME: ">"
                },

                count=BATCH_SIZE,

                block=BLOCK_MS,
            )

            if not messages:
                continue

            for stream_name, stream_messages in messages:

                for message_id, fields in stream_messages:

                    await process_message(
                        message_id,
                        fields,
                    )

        except asyncio.CancelledError:

            logger.info(
                "Worker shutdown requested"
            )

            break

        except Exception:

            logger.exception(
                "Worker loop error"
            )

            await asyncio.sleep(2)