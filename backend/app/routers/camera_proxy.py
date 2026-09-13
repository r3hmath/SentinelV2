import os
import time
import logging
from typing import Any, Dict, Optional
import httpx
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("sentinel.api.camera_proxy")

router = APIRouter(prefix="/api/v1/cameras", tags=["Camera Proxy & Ingestion"])

# 5-Second In-Memory Response Cache
_cache_data: Optional[Dict[str, Any]] = None
_cache_timestamp: float = 0.0
CACHE_TTL_SECONDS: float = 5.0


@router.get("/ingest")
async def get_sandbox_cameras(
    district_id: Optional[str] = Query(None, description="Optional district cluster filter"),
    force_refresh: bool = Query(False, description="Bypass 5-second cache"),
) -> Dict[str, Any]:
    """
    FastAPI Proxy Router for Sentinel Sandbox Dynamic Ingestion.
    Proxies GET http://<SANDBOX_HOST>/api/ingest with a 5-second in-memory cache.
    Eliminates CORS constraints and protects gateway from high-frequency polling.
    """
    global _cache_data, _cache_timestamp

    now = time.monotonic()
    cache_age = now - _cache_timestamp

    # 1. Return valid cached response if within 5-second TTL
    if not force_refresh and _cache_data is not None and cache_age < CACHE_TTL_SECONDS:
        return {
            **_cache_data,
            "cached": True,
            "cache_age_seconds": round(cache_age, 2),
        }

    # 2. Resolve Sandbox Host from environment variable (Strict Compliance)
    sandbox_host = os.getenv("SANDBOX_HOST", "127.0.0.1:8001")
    if not sandbox_host.startswith("http://") and not sandbox_host.startswith("https://"):
        sandbox_url = f"http://{sandbox_host.rstrip('/')}/api/ingest"
    else:
        sandbox_url = f"{sandbox_host.rstrip('/')}/api/ingest"

    params = {}
    if district_id:
        params["district_id"] = district_id

    # 3. Asynchronously fetch from Government Sentinel Sandbox
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            logger.info("Proxying camera discovery to Sentinel Sandbox: %s", sandbox_url)
            response = await client.get(sandbox_url, params=params)
            response.raise_for_status()
            payload = response.json()

        # Update cache on success
        _cache_data = payload
        _cache_timestamp = time.monotonic()

        return {
            **payload,
            "cached": False,
            "cache_age_seconds": 0.0,
        }

    except httpx.HTTPStatusError as http_err:
        logger.error("Sandbox returned HTTP error: %s (status: %d)", http_err, http_err.response.status_code)
        if _cache_data is not None:
            logger.warning("Serving stale cache due to upstream HTTP error")
            return {
                **_cache_data,
                "cached": True,
                "stale": True,
                "cache_age_seconds": round(now - _cache_timestamp, 2),
            }
        raise HTTPException(
            status_code=http_err.response.status_code,
            detail=f"Sentinel Sandbox returned HTTP {http_err.response.status_code}",
        )

    except Exception as exc:
        logger.error("Failed to connect to Sentinel Sandbox at %s: %s", sandbox_url, exc)
        if _cache_data is not None:
            logger.warning("Serving stale cache due to upstream connection failure")
            return {
                **_cache_data,
                "cached": True,
                "stale": True,
                "cache_age_seconds": round(now - _cache_timestamp, 2),
            }
        raise HTTPException(
            status_code=503,
            detail=f"Unable to reach Sentinel Sandbox gateway at {sandbox_host}: {str(exc)}",
        )


@router.post("/ingest")
async def post_sandbox_cameras_ingest(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Proxy / Direct ingest handler for /api/v1/cameras/ingest telemetry.
    """
    camera_id = payload.get("camera_id") or payload.get("id") or "UNKNOWN_CAM"
    frame_number = payload.get("frame_number", 0)
    logger.info(
        "Direct camera ingest telemetry accepted | camera_id=%s | frame=%s",
        camera_id,
        frame_number,
    )
    return {
        "status": "accepted",
        "endpoint": "/api/v1/cameras/ingest",
        "camera_id": camera_id,
        "frame_number": frame_number,
        "timestamp": payload.get("timestamp"),
    }

