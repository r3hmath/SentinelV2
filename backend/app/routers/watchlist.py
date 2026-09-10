import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database.postgres import postgres
from app.database.redis import redis_client

logger = logging.getLogger("sentinel.api.watchlist")

router = APIRouter(prefix="/watchlist", tags=["eGujCop Watchlist"])


class WatchlistCreate(BaseModel):
    license_plate: str
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_color: Optional[str] = None
    owner_name: Optional[str] = None
    category: str = "STOLEN"
    severity: str = "CRITICAL"
    notes: Optional[str] = None
    flagged_by: str = "eGujCop / CID Crime Gujarat"


class SimulateDetectionRequest(BaseModel):
    license_plate: str
    camera_id: str = "CAM_AHM_01"
    city: str = "Ahmedabad"
    confidence: float = 0.98


@router.get("")
async def get_watchlist():
    """
    Retrieve all registered vehicles on the eGujCop criminal/stolen watchlist.
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    query = """
        SELECT 
            id,
            license_plate,
            vehicle_make,
            vehicle_model,
            vehicle_color,
            owner_name,
            category,
            severity,
            notes,
            flagged_by,
            created_at,
            updated_at
        FROM public.egujcop_watchlist
        ORDER BY severity DESC, created_at DESC;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(query)

    items = []
    for r in rows:
        items.append(
            {
                "id": r["id"],
                "license_plate": r["license_plate"],
                "vehicle_make": r["vehicle_make"],
                "vehicle_model": r["vehicle_model"],
                "vehicle_color": r["vehicle_color"],
                "owner_name": r["owner_name"],
                "category": r["category"],
                "severity": r["severity"],
                "notes": r["notes"],
                "flagged_by": r["flagged_by"],
                "created_at": r["created_at"].isoformat(),
            }
        )

    return {"count": len(items), "watchlist": items}


@router.post("")
async def add_to_watchlist(entry: WatchlistCreate):
    """
    Add a vehicle license plate to the eGujCop Watchlist (updates PostgreSQL and Redis).
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    plate = entry.license_plate.strip().upper()

    query = """
        INSERT INTO public.egujcop_watchlist (
            license_plate, vehicle_make, vehicle_model, vehicle_color,
            owner_name, category, severity, notes, flagged_by
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (license_plate) DO UPDATE
        SET vehicle_make = EXCLUDED.vehicle_make,
            vehicle_model = EXCLUDED.vehicle_model,
            vehicle_color = EXCLUDED.vehicle_color,
            owner_name = EXCLUDED.owner_name,
            category = EXCLUDED.category,
            severity = EXCLUDED.severity,
            notes = EXCLUDED.notes,
            updated_at = NOW()
        RETURNING id;
    """

    async with postgres.pool.acquire() as conn:
        entry_id = await conn.fetchval(
            query,
            plate,
            entry.vehicle_make,
            entry.vehicle_model,
            entry.vehicle_color,
            entry.owner_name,
            entry.category.upper(),
            entry.severity.upper(),
            entry.notes,
            entry.flagged_by,
        )

    # Sync to Redis Set
    if redis_client.client:
        try:
            await redis_client.client.sadd("egujcop_watchlist", plate)
        except Exception:
            logger.warning("Failed to sync plate %s to Redis watchlist set", plate)

    return {
        "status": "success",
        "id": entry_id,
        "license_plate": plate,
        "message": f"License plate {plate} registered in eGujCop Watchlist",
    }


@router.post("/simulate")
async def simulate_threat_detection(req: SimulateDetectionRequest):
    """
    Simulate an ALPR detection event against a camera to test the real-time threat alert pipeline.
    If the plate is on the watchlist, broadcasts a THREAT_DETECTED WebSocket alert and saves to PostgreSQL.
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    plate = req.license_plate.strip().upper()

    # 1. Fetch camera details
    async with postgres.pool.acquire() as conn:
        cam = await conn.fetchrow(
            "SELECT camera_id, node_id, name, city, latitude, longitude FROM public.cameras WHERE camera_id = $1",
            req.camera_id,
        )
        watchlist_item = await conn.fetchrow(
            "SELECT * FROM public.egujcop_watchlist WHERE UPPER(license_plate) = $1",
            plate,
        )

    lat = float(cam["latitude"]) if cam and cam["latitude"] else 23.0225
    lon = float(cam["longitude"]) if cam and cam["longitude"] else 72.5714
    camera_name = cam["name"] if cam else f"Camera {req.camera_id}"
    city = cam["city"] if cam and cam["city"] else req.city
    node_id = cam["node_id"] if cam and cam["node_id"] else "NODE_AHM_01"

    now = datetime.now(timezone.utc)
    event_id = uuid4()

    # 2. Insert ALPR event
    event_metadata = {
        "city": city,
        "source": "rtsp://simulated_feed",
        "alpr": {
            "plate": plate,
            "track_id": 999,
            "plate_confidence": req.confidence,
            "detector_confidence": 0.95,
            "recognized": True,
        },
    }

    async with postgres.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.events (
                event_id, node_id, camera_id, event_type, confidence,
                event_timestamp, latitude, longitude, geom,
                inference_latency_ms, metadata, processing_status, processed_at
            )
            VALUES (
                $1, $2, $3, 'ALPR_DETECTED', $4,
                $5, $6, $7, ST_SetSRID(ST_MakePoint($7, $6), 4326),
                42.5, $8::jsonb, 'processed', NOW()
            )
            """,
            event_id,
            node_id,
            req.camera_id,
            req.confidence,
            now,
            lat,
            lon,
            json.dumps(event_metadata),
        )

    # 3. If matched on watchlist, fire THREAT_DETECTED
    threat_payload = None
    if watchlist_item:
        threat_payload = {
            "event_type": "THREAT_DETECTED",
            "alert_id": str(uuid4()),
            "license_plate": plate,
            "category": watchlist_item["category"],
            "severity": watchlist_item["severity"],
            "owner_name": watchlist_item["owner_name"],
            "vehicle_info": f"{watchlist_item.get('vehicle_color', '')} {watchlist_item.get('vehicle_make', '')} {watchlist_item.get('vehicle_model', '')}".strip(),
            "notes": watchlist_item["notes"],
            "flagged_by": watchlist_item["flagged_by"],
            "camera_id": req.camera_id,
            "camera_name": camera_name,
            "city": city,
            "node_id": node_id,
            "latitude": lat,
            "longitude": lon,
            "timestamp": now.isoformat(),
            "confidence": req.confidence,
            "source_event_id": str(event_id),
        }

        # Store threat event
        async with postgres.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.events (
                    event_id, node_id, camera_id, event_type, confidence,
                    event_timestamp, latitude, longitude, geom,
                    inference_latency_ms, metadata, processing_status, processed_at
                )
                VALUES (
                    $1, $2, $3, 'THREAT_DETECTED', $4,
                    $5, $6, $7, ST_SetSRID(ST_MakePoint($7, $6), 4326),
                    25.0, $8::jsonb, 'processed', NOW()
                )
                """,
                uuid4(),
                node_id,
                req.camera_id,
                req.confidence,
                now,
                lat,
                lon,
                json.dumps(threat_payload),
            )

        # Publish to Redis channel for WebSocket broadcasting
        if redis_client.client:
            try:
                await redis_client.client.publish(
                    "sentinel:alerts", json.dumps(threat_payload)
                )
                logger.info(
                    "Broadcasted THREAT_DETECTED via Redis Pub/Sub: %s", plate
                )
            except Exception:
                logger.exception("Failed to publish alert to Redis channel")

    return {
        "status": "success",
        "license_plate": plate,
        "is_watchlist_match": watchlist_item is not None,
        "threat_alert": threat_payload,
    }
