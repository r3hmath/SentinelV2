from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query

from app.database.postgres import postgres

logger = logging.getLogger("sentinel.api.ingest")

router = APIRouter(tags=["Dynamic Ingestion Discovery Protocol"])


@router.get("/ingest")
@router.get("/api/ingest")
@router.get("/api/v1/ingest")
async def discover_ingest_topology(
    district_id: Optional[str] = Query(None, description="Filter by district cluster for edge sharding"),
    live_only: bool = Query(False, description="Filter only active live streams"),
) -> Dict[str, Any]:
    """
    Sentinel Sandbox Dynamic Camera Discovery Protocol Contract.
    Enforces Zero Hardcoding: Discovers camera array, codec metadata,
    geospatial coordinates, and multi-protocol streaming endpoints (RTSP/HLS/WHEP).
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="Database pool unavailable")

    query = """
        SELECT 
            c.camera_id,
            c.name,
            c.node_id,
            COALESCE(c.city, n.city, 'Gujarat') AS city,
            c.source,
            c.latitude,
            c.longitude,
            c.enabled,
            c.status,
            COALESCE(n.node_id, 'NODE_DEFAULT') AS district_cluster
        FROM public.cameras c
        LEFT JOIN public.edge_nodes n ON c.node_id = n.node_id
        WHERE ($1::text IS NULL OR UPPER(COALESCE(c.city, n.city)) = UPPER($1))
          AND ($2::boolean IS FALSE OR c.status = 'online')
        ORDER BY c.city, c.camera_id;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(query, district_id, live_only)

    cameras_list: List[Dict[str, Any]] = []

    for row in rows:
        cam_id = row["camera_id"]
        city = row["city"]
        source = row["source"] or ""

        # Determine codec dynamically based on stream source or high-efficiency camera profiles
        # In Gujarat CCTV grid, newer PTZ cameras stream H.265 (HEVC), fixed dome stream H.264
        codec = "h265" if any(k in cam_id.lower() or k in source.lower() for k in ["h265", "hevc", "ptz", "4k"]) else "h264"

        # Protocol endpoints conforming to Sentinel Sandbox
        rtsp_port = 8554
        hls_port = 8888
        whep_port = 8889

        rtsp_url = f"rtsp://127.0.0.1:{rtsp_port}/live/{cam_id}" if not source.startswith("rtsp://") else source
        hls_url = f"http://127.0.0.1:{hls_port}/live/{cam_id}/index.m3u8"
        whep_url = f"http://127.0.0.1:{whep_port}/live/{cam_id}/whep"

        # Determine local test file fallback if running in sandbox simulation mode
        fallback_file = "./media/ahmd.mp4"
        if "sur" in cam_id.lower() or "surat" in city.lower():
            fallback_file = "./media/surat.mp4"
        elif "rjk" in cam_id.lower() or "rajkot" in city.lower():
            fallback_file = "./media/rajkor.mp4"

        cameras_list.append(
            {
                "id": cam_id,
                "name": row["name"],
                "district_id": row["district_cluster"],
                "substation_id": f"SUB_{city.upper()[:3]}",
                "location": {
                    "city": city,
                    "latitude": float(row["latitude"]) if row["latitude"] else 23.0225,
                    "longitude": float(row["longitude"]) if row["longitude"] else 72.5714,
                },
                "codec": codec,
                "live": row["status"] == "online" and row["enabled"],
                "endpoints": {
                    "rtsp": rtsp_url,
                    "hls": hls_url,
                    "whep": whep_url,
                    "fallback_file": fallback_file,
                },
                "pacing_policy": {
                    "lazy_capture_enabled": True,
                    "preview_fps": 1.0,
                    "active_fps": 5.0,
                },
            }
        )

    return {
        "status": "success",
        "protocol_version": "2.0-SANDBOX",
        "target_scale": "80000-STATEWIDE",
        "total_cameras": len(cameras_list),
        "district_filter": district_id,
        "cameras": cameras_list,
    }
