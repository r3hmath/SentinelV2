import json
import logging
import math
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.database.postgres import postgres

logger = logging.getLogger("sentinel.api.tracking")

router = APIRouter(prefix="/tracking", tags=["Tracking & Route Reconstruction"])


def haversine_distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Calculate great-circle distance between two points on the Earth."""
    r = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(r * c, 2)


@router.get("/route/{license_plate}")
async def get_vehicle_route(license_plate: str):
    """
    Reconstruct chronological cross-camera route trajectory for a vehicle registration number.
    Returns an RFC 7946 GeoJSON FeatureCollection with Point checkpoint features and
    a LineString trajectory feature.
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    normalized_plate = license_plate.strip().upper()

    query_sightings = """
        WITH sightings AS (
            SELECT 
                e.camera_id,
                COALESCE(c.name, 'Camera ' || e.camera_id) AS camera_name,
                COALESCE(c.city, e.metadata->>'city', 'Gujarat') AS city,
                COALESCE(e.longitude, c.longitude) AS longitude,
                COALESCE(e.latitude, c.latitude) AS latitude,
                COALESCE(e.geom, c.geom, ST_SetSRID(ST_MakePoint(COALESCE(e.longitude, c.longitude), COALESCE(e.latitude, c.latitude)), 4326)) AS geom,
                MIN(e.event_timestamp) AS first_seen,
                MAX(e.event_timestamp) AS last_seen,
                COUNT(e.id) AS detections_count,
                ROUND(AVG(e.confidence)::numeric, 4) AS avg_confidence,
                ROUND(MAX(COALESCE((e.metadata->'alpr'->>'plate_confidence')::float, e.confidence))::numeric, 4) AS best_confidence,
                COALESCE(c.source, e.metadata->>'source') AS stream_source
            FROM public.events e
            LEFT JOIN public.cameras c ON e.camera_id = c.camera_id
            WHERE e.event_type = 'ALPR_DETECTED'
              AND UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) = UPPER($1)
              AND (e.latitude IS NOT NULL OR c.latitude IS NOT NULL)
              AND (e.longitude IS NOT NULL OR c.longitude IS NOT NULL)
            GROUP BY 
                e.camera_id, 
                c.name, 
                c.city, 
                e.metadata->>'city', 
                e.longitude, 
                c.longitude, 
                e.latitude, 
                c.latitude,
                e.geom,
                c.geom,
                c.source,
                e.metadata->>'source'
            ORDER BY MIN(e.event_timestamp) ASC
        )
        SELECT 
            camera_id,
            camera_name,
            city,
            longitude,
            latitude,
            ST_AsGeoJSON(geom)::json AS point_geojson,
            first_seen,
            last_seen,
            detections_count,
            avg_confidence,
            best_confidence,
            stream_source
        FROM sightings;
    """

    query_watchlist = """
        SELECT 
            license_plate,
            vehicle_make,
            vehicle_model,
            vehicle_color,
            owner_name,
            category,
            severity,
            notes,
            flagged_by
        FROM public.egujcop_watchlist
        WHERE UPPER(license_plate) = UPPER($1);
    """

    query_postgis_trajectory = """
        WITH sightings AS (
            SELECT 
                COALESCE(e.geom, c.geom, ST_SetSRID(ST_MakePoint(COALESCE(e.longitude, c.longitude), COALESCE(e.latitude, c.latitude)), 4326)) AS geom,
                MIN(e.event_timestamp) AS first_seen
            FROM public.events e
            LEFT JOIN public.cameras c ON e.camera_id = c.camera_id
            WHERE e.event_type = 'ALPR_DETECTED'
              AND UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) = UPPER($1)
              AND (e.latitude IS NOT NULL OR c.latitude IS NOT NULL)
              AND (e.longitude IS NOT NULL OR c.longitude IS NOT NULL)
            GROUP BY 
                e.camera_id, 
                e.geom, 
                c.geom, 
                e.longitude, 
                c.longitude, 
                e.latitude, 
                c.latitude
            ORDER BY MIN(e.event_timestamp) ASC
        )
        SELECT 
            ST_AsGeoJSON(ST_MakeLine(geom ORDER BY first_seen ASC))::json AS linestring_geojson,
            ROUND((ST_Length(ST_MakeLine(geom ORDER BY first_seen ASC)::geography) / 1000.0)::numeric, 2) AS postgis_distance_km
        FROM sightings;
    """

    async with postgres.pool.acquire() as conn:
        sightings_rows = await conn.fetch(query_sightings, normalized_plate)
        watchlist_row = await conn.fetchrow(query_watchlist, normalized_plate)
        trajectory_row = await conn.fetchrow(query_postgis_trajectory, normalized_plate)

    watchlist_info = None
    if watchlist_row:
        watchlist_info = {
            "license_plate": watchlist_row["license_plate"],
            "vehicle_make": watchlist_row["vehicle_make"],
            "vehicle_model": watchlist_row["vehicle_model"],
            "vehicle_color": watchlist_row["vehicle_color"],
            "owner_name": watchlist_row["owner_name"],
            "category": watchlist_row["category"],
            "severity": watchlist_row["severity"],
            "notes": watchlist_row["notes"],
            "flagged_by": watchlist_row["flagged_by"],
        }

    if not sightings_rows:
        return {
            "type": "FeatureCollection",
            "properties": {
                "license_plate": normalized_plate,
                "total_sightings": 0,
                "unique_cameras": 0,
                "is_watchlist_match": watchlist_info is not None,
                "watchlist_details": watchlist_info,
                "message": f"No sightings detected for license plate '{normalized_plate}'",
            },
            "features": [],
        }

    features = []
    coordinates = []
    total_detections = 0
    total_distance_km = 0.0

    prev_lon, prev_lat = None, None

    for idx, row in enumerate(sightings_rows, start=1):
        lon = float(row["longitude"])
        lat = float(row["latitude"])
        coordinates.append([lon, lat])

        if prev_lon is not None and prev_lat is not None:
            total_distance_km += haversine_distance_km(prev_lon, prev_lat, lon, lat)
        prev_lon, prev_lat = lon, lat

        detections = int(row["detections_count"])
        total_detections += detections

        point_feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
            "properties": {
                "checkpoint_order": idx,
                "camera_id": row["camera_id"],
                "camera_name": row["camera_name"],
                "city": row["city"],
                "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
                "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
                "detections_count": detections,
                "avg_confidence": float(row["avg_confidence"]),
                "best_confidence": float(row["best_confidence"]),
                "stream_source": row["stream_source"],
                "is_threat": watchlist_info is not None,
            },
        }
        features.append(point_feature)

    start_time = sightings_rows[0]["first_seen"]
    end_time = sightings_rows[-1]["last_seen"]
    transit_duration_minutes = 0.0
    if start_time and end_time:
        transit_duration_minutes = round(
            max(0.0, (end_time - start_time).total_seconds() / 60.0), 1
        )

    # Add connecting trajectory line if more than 1 point
    if len(coordinates) >= 2:
        # Use PostGIS ST_MakeLine geometry if available, with coordinate fallback
        raw_linestring = (
            trajectory_row["linestring_geojson"]
            if trajectory_row and trajectory_row.get("linestring_geojson")
            else None
        )
        if isinstance(raw_linestring, str):
            try:
                linestring_geom = json.loads(raw_linestring)
            except Exception:
                linestring_geom = {"type": "LineString", "coordinates": coordinates}
        elif isinstance(raw_linestring, dict):
            linestring_geom = raw_linestring
        else:
            linestring_geom = {"type": "LineString", "coordinates": coordinates}

        final_distance = (
            float(trajectory_row["postgis_distance_km"])
            if trajectory_row and trajectory_row.get("postgis_distance_km") is not None
            else round(total_distance_km, 2)
        )

        line_feature = {
            "type": "Feature",
            "geometry": linestring_geom,
            "properties": {
                "route_name": f"Traversed Route ({normalized_plate})",
                "checkpoint_count": len(coordinates),
                "total_distance_km": final_distance,
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None,
                "duration_minutes": transit_duration_minutes,
                "is_threat": watchlist_info is not None,
                "postgis_generated": True,
            },
        }
        features.append(line_feature)

    return {
        "type": "FeatureCollection",
        "properties": {
            "license_plate": normalized_plate,
            "total_sightings": total_detections,
            "unique_cameras": len(sightings_rows),
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
            "transit_duration_minutes": transit_duration_minutes,
            "total_distance_km": round(total_distance_km, 2),
            "is_watchlist_match": watchlist_info is not None,
            "watchlist_details": watchlist_info,
        },
        "features": features,
    }


@router.get("/plates")
async def get_tracked_plates(limit: int = Query(default=50, ge=1, le=200)):
    """
    List recently tracked vehicle registration numbers with sighting counts and watchlist status.
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    query = """
        SELECT 
            UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) AS plate,
            MAX(e.event_timestamp) AS last_seen,
            MIN(e.event_timestamp) AS first_seen,
            COUNT(DISTINCT e.camera_id) AS camera_count,
            COUNT(e.id) AS total_detections,
            MAX(COALESCE(c.city, e.metadata->>'city', 'Gujarat')) AS last_city,
            w.category AS watchlist_category,
            w.severity AS watchlist_severity,
            w.vehicle_make,
            w.vehicle_model,
            w.owner_name
        FROM public.events e
        LEFT JOIN public.cameras c ON e.camera_id = c.camera_id
        LEFT JOIN public.egujcop_watchlist w 
            ON UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) = UPPER(w.license_plate)
        WHERE e.event_type = 'ALPR_DETECTED'
          AND COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate') IS NOT NULL
        GROUP BY 
            UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')),
            w.category,
            w.severity,
            w.vehicle_make,
            w.vehicle_model,
            w.owner_name
        ORDER BY MAX(e.event_timestamp) DESC
        LIMIT $1;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(query, limit)

    results = []
    for r in rows:
        results.append(
            {
                "plate": r["plate"],
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                "camera_count": int(r["camera_count"]),
                "total_detections": int(r["total_detections"]),
                "last_city": r["last_city"],
                "is_watchlist_match": r["watchlist_category"] is not None,
                "watchlist_category": r["watchlist_category"],
                "watchlist_severity": r["watchlist_severity"],
                "vehicle_make": r["vehicle_make"],
                "vehicle_model": r["vehicle_model"],
                "owner_name": r["owner_name"],
            }
        )

    return {"count": len(results), "plates": results}


@router.get("/cameras")
async def get_surveillance_cameras():
    """
    Get all Gujarat surveillance cameras as a GeoJSON FeatureCollection with statuses and locations.
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    query = """
        SELECT 
            c.camera_id,
            c.name,
            c.node_id,
            c.city,
            c.source,
            c.latitude,
            c.longitude,
            c.enabled,
            c.status,
            c.last_seen,
            COUNT(e.id) AS events_count
        FROM public.cameras c
        LEFT JOIN public.events e ON c.camera_id = e.camera_id
        GROUP BY c.camera_id, c.name, c.node_id, c.city, c.source, c.latitude, c.longitude, c.enabled, c.status, c.last_seen
        ORDER BY c.city, c.name;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(query)

    features = []
    for r in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(r["longitude"]), float(r["latitude"])],
                },
                "properties": {
                    "camera_id": r["camera_id"],
                    "name": r["name"],
                    "node_id": r["node_id"],
                    "city": r["city"],
                    "source": r["source"],
                    "status": r["status"],
                    "enabled": r["enabled"],
                    "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                    "events_count": int(r["events_count"]),
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "properties": {
            "total_cameras": len(features),
            "region": "Gujarat Surveillance Grid",
        },
        "features": features,
    }
