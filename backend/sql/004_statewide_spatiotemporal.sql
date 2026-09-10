-- =========================================================
-- SENTINEL: Statewide PostGIS Spatiotemporal Hardening
-- Module 2: Scalable Trajectory Reconstruction for 80,000 Nodes
-- =========================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------
-- 1. Performance Indexes on Events Table
-- ---------------------------------------------------------

-- GIN index for ultra-fast JSONB metadata filtering (alpr, tracking, kinematics)
CREATE INDEX IF NOT EXISTS idx_events_metadata_gin
ON public.events USING GIN (metadata jsonb_path_ops);

-- B-Tree index for plate lookups across multiple metadata variants
CREATE INDEX IF NOT EXISTS idx_events_plate_extracted
ON public.events ((UPPER(COALESCE(metadata->'alpr'->>'plate', metadata->>'license_plate', metadata->>'plate'))));

-- Composite index for temporal slicing per camera
CREATE INDEX IF NOT EXISTS idx_events_camera_timestamp
ON public.events (camera_id, event_timestamp DESC);

-- Composite index for event type and timestamp
CREATE INDEX IF NOT EXISTS idx_events_type_timestamp
ON public.events (event_type, event_timestamp DESC);

-- ---------------------------------------------------------
-- 2. Spatial Index on Cameras
-- ---------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_cameras_geom_gist
ON public.cameras USING GIST (geom);

-- ---------------------------------------------------------
-- 3. Optimized Spatiotemporal Function for Route Stitching
-- ---------------------------------------------------------

CREATE OR REPLACE FUNCTION get_vehicle_trajectory_geojson(
    p_license_plate TEXT,
    p_start_time TIMESTAMPTZ DEFAULT NULL,
    p_end_time TIMESTAMPTZ DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_result JSONB;
BEGIN
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
          AND UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) = UPPER(p_license_plate)
          AND (p_start_time IS NULL OR e.event_timestamp >= p_start_time)
          AND (p_end_time IS NULL OR e.event_timestamp <= p_end_time)
          AND (e.latitude IS NOT NULL OR c.latitude IS NOT NULL)
          AND (e.longitude IS NOT NULL OR c.longitude IS NOT NULL)
        GROUP BY 
            e.camera_id, c.name, c.city, e.metadata->>'city', 
            e.longitude, c.longitude, e.latitude, c.latitude,
            e.geom, c.geom, c.source, e.metadata->>'source'
        ORDER BY MIN(e.event_timestamp) ASC
    ),
    point_features AS (
        SELECT 
            jsonb_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(geom)::jsonb,
                'properties', jsonb_build_object(
                    'checkpoint_order', row_number() OVER (ORDER BY first_seen ASC),
                    'camera_id', camera_id,
                    'camera_name', camera_name,
                    'city', city,
                    'first_seen', first_seen,
                    'last_seen', last_seen,
                    'detections_count', detections_count,
                    'avg_confidence', avg_confidence,
                    'best_confidence', best_confidence,
                    'stream_source', stream_source
                )
            ) AS feature,
            geom,
            first_seen,
            last_seen,
            detections_count
        FROM sightings
    ),
    line_feature AS (
        SELECT 
            CASE 
                WHEN COUNT(geom) >= 2 THEN
                    jsonb_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(ST_MakeLine(geom ORDER BY first_seen ASC))::jsonb,
                        'properties', jsonb_build_object(
                            'route_name', 'Traversed Route (' || UPPER(p_license_plate) || ')',
                            'checkpoint_count', COUNT(geom),
                            'total_distance_km', ROUND((ST_Length(ST_MakeLine(geom ORDER BY first_seen ASC)::geography) / 1000.0)::numeric, 2),
                            'start_time', MIN(first_seen),
                            'end_time', MAX(last_seen)
                        )
                    )
                ELSE NULL
            END AS feature
        FROM sightings
    )
    SELECT 
        jsonb_build_object(
            'type', 'FeatureCollection',
            'properties', jsonb_build_object(
                'license_plate', UPPER(p_license_plate),
                'total_sightings', COALESCE((SELECT SUM(detections_count) FROM sightings), 0),
                'unique_cameras', (SELECT COUNT(*) FROM sightings),
                'start_time', (SELECT MIN(first_seen) FROM sightings),
                'end_time', (SELECT MAX(last_seen) FROM sightings),
                'total_distance_km', COALESCE((SELECT ROUND((ST_Length(ST_MakeLine(geom ORDER BY first_seen ASC)::geography) / 1000.0)::numeric, 2) FROM sightings HAVING COUNT(geom) >= 2), 0)
            ),
            'features', (
                SELECT COALESCE(
                    jsonb_agg(feature) FILTER (WHERE feature IS NOT NULL),
                    '[]'::jsonb
                )
                FROM (
                    SELECT feature FROM point_features
                    UNION ALL
                    SELECT feature FROM line_feature WHERE feature IS NOT NULL
                ) combined
            )
        )
    INTO v_result;

    RETURN v_result;
END;
$$;
