import asyncio
import json
import logging
import os
from datetime import datetime
from uuid import UUID, uuid4

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


async def check_watchlist_and_alert(
    event_id: UUID,
    node_id: str,
    camera_id: str,
    latitude: float | None,
    longitude: float | None,
    confidence: float,
    timestamp: datetime,
    stored_metadata: dict,
):
    """
    Cross-reference ALPR detection with eGujCop Watchlist (Redis Set + PostgreSQL).
    If a match is found, creates a THREAT_DETECTED event and broadcasts via Redis Pub/Sub.
    """
    alpr_meta = stored_metadata.get("alpr", {})
    plate = (
        alpr_meta.get("plate")
        or stored_metadata.get("license_plate")
        or stored_metadata.get("plate")
    )

    if not plate:
        return

    normalized_plate = str(plate).strip().upper()

    # 1. Fast O(1) Redis set check
    is_on_watchlist = False
    if redis_client.client:
        try:
            is_on_watchlist = await redis_client.client.sismember(
                "egujcop_watchlist", normalized_plate
            )
        except Exception:
            logger.exception("Redis watchlist check error; falling back to PostgreSQL")

    # 2. Query PostgreSQL for complete details if matched or fallback
    watchlist_item = None
    try:
        async with postgres.pool.acquire() as connection:
            watchlist_item = await connection.fetchrow(
                """
                SELECT license_plate, vehicle_make, vehicle_model, vehicle_color,
                       owner_name, category, severity, notes, flagged_by
                FROM public.egujcop_watchlist
                WHERE UPPER(license_plate) = UPPER($1)
                """,
                normalized_plate,
            )
    except Exception:
        logger.exception("PostgreSQL watchlist query error")

    if watchlist_item:
        logger.warning(
            "🚨 eGujCop THREAT DETECTED | Plate: %s | Category: %s | Severity: %s | Camera: %s",
            normalized_plate,
            watchlist_item["category"],
            watchlist_item["severity"],
            camera_id,
        )

        threat_id = uuid4()
        threat_payload = {
            "event_type": "THREAT_DETECTED",
            "alert_id": str(threat_id),
            "license_plate": normalized_plate,
            "category": watchlist_item["category"],
            "severity": watchlist_item["severity"],
            "owner_name": watchlist_item["owner_name"],
            "vehicle_info": f"{watchlist_item.get('vehicle_color', '')} {watchlist_item.get('vehicle_make', '')} {watchlist_item.get('vehicle_model', '')}".strip(),
            "notes": watchlist_item["notes"],
            "flagged_by": watchlist_item["flagged_by"],
            "camera_id": camera_id,
            "node_id": node_id,
            "latitude": latitude,
            "longitude": longitude,
            "timestamp": timestamp.isoformat(),
            "confidence": confidence,
            "source_event_id": str(event_id),
        }

        # Persist THREAT_DETECTED event in PostgreSQL
        try:
            async with postgres.pool.acquire() as connection:
                geom_sql = (
                    "ST_SetSRID(ST_MakePoint($7, $6), 4326)"
                    if (latitude is not None and longitude is not None)
                    else "NULL"
                )
                await connection.execute(
                    f"""
                    INSERT INTO public.events (
                        event_id,
                        node_id,
                        camera_id,
                        event_type,
                        confidence,
                        event_timestamp,
                        latitude,
                        longitude,
                        geom,
                        inference_latency_ms,
                        metadata,
                        processing_status,
                        processing_attempts,
                        processed_at
                    )
                    VALUES (
                        $1, $2, $3, 'THREAT_DETECTED', $4, $5, $6, $7,
                        {geom_sql}, 25.0, $8::jsonb, 'processed', 1, NOW()
                    )
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    threat_id,
                    node_id,
                    camera_id,
                    confidence,
                    timestamp,
                    latitude,
                    longitude,
                    json.dumps(threat_payload),
                )
        except Exception:
            logger.exception("Failed to insert THREAT_DETECTED into database")

        # Broadcast via Redis Pub/Sub to all connected WebSockets
        if redis_client.client:
            try:
                await redis_client.client.publish(
                    "sentinel:alerts", json.dumps(threat_payload)
                )
                logger.info(
                    "Broadcasted THREAT_DETECTED alert to 'sentinel:alerts' channel | plate=%s",
                    normalized_plate,
                )
            except Exception:
                logger.exception("Failed to publish alert to Redis Pub/Sub")


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

    geom_expr = (
        "ST_SetSRID(ST_MakePoint($8, $7), 4326)"
        if (latitude is not None and longitude is not None)
        else "NULL"
    )

    async with postgres.pool.acquire() as connection:

        await connection.execute(
            f"""
            INSERT INTO public.events (
                event_id,
                node_id,
                camera_id,
                event_type,
                confidence,
                event_timestamp,
                latitude,
                longitude,
                geom,
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
                {geom_expr},
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

    # If this is an ALPR detection, check against eGujCop watchlist
    if event_type == "ALPR_DETECTED":
        await check_watchlist_and_alert(
            event_id=event_id,
            node_id=node_id,
            camera_id=camera_id,
            latitude=latitude,
            longitude=longitude,
            confidence=confidence,
            timestamp=timestamp,
            stored_metadata=stored_metadata,
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


async def sync_watchlist_cache():
    """
    Sync all active watchlist plates from PostgreSQL into Redis in-memory set (egujcop_watchlist)
    for O(1) matching during stream processing.
    """
    if not redis_client.client or not postgres.pool:
        return
    try:
        async with postgres.pool.acquire() as conn:
            rows = await conn.fetch("SELECT UPPER(license_plate) as plate FROM public.egujcop_watchlist")
            if rows:
                plates = [r["plate"] for r in rows]
                await redis_client.client.sadd("egujcop_watchlist", *plates)
                logger.info(
                    "Synchronized %d watchlist plates into Redis Set 'egujcop_watchlist'",
                    len(plates),
                )
    except Exception:
        logger.exception("Failed to synchronize watchlist into Redis cache")


async def worker_loop():

    await create_consumer_group()
    await sync_watchlist_cache()

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