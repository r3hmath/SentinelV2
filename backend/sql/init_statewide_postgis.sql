-- ==============================================================================
-- SENTINEL STATEWIDE CCTV INTELLIGENCE ENGINE (GUJARAT POLICE PoC)
-- MODULE 2: POSTGIS SPATIOTEMPORAL TRAJECTORY ENGINE & eGujCop WATCHLIST
-- 
-- Target Scale: 80,000-Node Gujarat Highway CCTV Grid (1,000 km Coverage)
-- Features:
--   1. PostGIS Spatial Extension & Topology Configuration
--   2. Dynamic Schemas: edge_nodes, cameras, events, and egujcop_watchlist
--   3. Spatial GIST Indexes & JSONB GIN Indexes (Sub-second Spatial Slicing)
--   4. RFC 7946 GeoJSON Trajectory Reconstruction Function (LineString + Points)
--   5. Seed Data: 10 Major Gujarat City Nodes & NH48/SG Highway Checkpoints
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------------------------
-- 1. EDGE NODES SCHEMA (Distributed Edge Sharding by District/Substation)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.edge_nodes (
    node_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    city VARCHAR(100) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'online',
    heartbeat_interval_sec INTEGER NOT NULL DEFAULT 5,
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------------------------
-- 2. DYNAMIC CAMERAS SCHEMA (Vendor-Agnostic, Multi-Protocol Ingestion)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.cameras (
    camera_id VARCHAR(50) PRIMARY KEY,
    node_id VARCHAR(50) REFERENCES public.edge_nodes(node_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    city VARCHAR(100),
    source VARCHAR(500) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    geom geometry(Point, 4326),
    enabled BOOLEAN NOT NULL DEFAULT true,
    status VARCHAR(20) NOT NULL DEFAULT 'online',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Spatial GIST Index for Sub-second Proximity and Radius Queries
CREATE INDEX IF NOT EXISTS idx_cameras_geom_gist
ON public.cameras USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_cameras_node
ON public.cameras (node_id);

-- ------------------------------------------------------------------------------
-- 3. STATEWIDE EVENTS SCHEMA (ALPR, Kinematics, Anomaly & Threat Detection)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID UNIQUE NOT NULL,
    node_id VARCHAR(50) NOT NULL,
    camera_id VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geom geometry(Point, 4326),
    frame_number BIGINT NOT NULL DEFAULT 0,
    inference_latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    processing_status VARCHAR(20) NOT NULL DEFAULT 'unprocessed',
    processing_attempts INTEGER NOT NULL DEFAULT 0,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Spatial GIST Index for Event Trajectory Reconstruction
CREATE INDEX IF NOT EXISTS idx_events_geom_gist
ON public.events USING GIST (geom);

-- GIN Index for Ultra-Fast JSONB Deep Querying (alpr, kinematics, track_ids)
CREATE INDEX IF NOT EXISTS idx_events_metadata_gin
ON public.events USING GIN (metadata jsonb_path_ops);

-- B-Tree Index on License Plate Variant Keys
CREATE INDEX IF NOT EXISTS idx_events_plate_extracted
ON public.events ((UPPER(COALESCE(metadata->'alpr'->>'plate', metadata->>'license_plate', metadata->>'plate'))));

-- Composite Temporal Indexes for Cross-Camera Time Slicing
CREATE INDEX IF NOT EXISTS idx_events_camera_timestamp
ON public.events (camera_id, event_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_events_type_timestamp
ON public.events (event_type, event_timestamp DESC);

-- ------------------------------------------------------------------------------
-- 4. eGujCop / VAHAN WATCHLIST SCHEMA (O(1) Memory Sync & Persistence)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.egujcop_watchlist (
    id BIGSERIAL PRIMARY KEY,
    license_plate VARCHAR(30) UNIQUE NOT NULL,
    vehicle_make VARCHAR(100),
    vehicle_model VARCHAR(100),
    vehicle_color VARCHAR(50),
    owner_name VARCHAR(200),
    category VARCHAR(50) NOT NULL DEFAULT 'STOLEN',
    severity VARCHAR(20) NOT NULL DEFAULT 'CRITICAL',
    notes TEXT,
    flagged_by VARCHAR(100) DEFAULT 'eGujCop / CID Crime Gujarat',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_watchlist_plate
ON public.egujcop_watchlist (license_plate);

CREATE INDEX IF NOT EXISTS idx_watchlist_severity
ON public.egujcop_watchlist (severity);

-- ------------------------------------------------------------------------------
-- 5. OPTIMIZED SPATIOTEMPORAL TRAJECTORY STITCHING FUNCTION (RFC 7946 GeoJSON)
-- ------------------------------------------------------------------------------

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

-- ------------------------------------------------------------------------------
-- 6. SEED DATA: GUJARAT SURVEILLANCE BACKBONE (1,000 km Network)
-- ------------------------------------------------------------------------------

INSERT INTO public.edge_nodes (node_id, name, city, latitude, longitude, status)
VALUES
    ('NODE_AHM_01', 'Ahmedabad Metro Control Node', 'Ahmedabad', 23.0225, 72.5714, 'online'),
    ('NODE_GND_01', 'Gandhinagar Secretariat Node', 'Gandhinagar', 23.2156, 72.6369, 'online'),
    ('NODE_VAD_01', 'Vadodara Central Highway Node', 'Vadodara', 22.3072, 73.1812, 'online'),
    ('NODE_SUR_01', 'Surat Industrial Corridor Node', 'Surat', 21.1702, 72.8311, 'online'),
    ('NODE_RJK_01', 'Rajkot Saurashtra Node', 'Rajkot', 22.3039, 70.8022, 'online'),
    ('NODE_BHV_01', 'Bhavnagar Coastal Highway Node', 'Bhavnagar', 21.7645, 72.1519, 'online'),
    ('NODE_JAM_01', 'Jamnagar Refinery Belt Node', 'Jamnagar', 22.4707, 70.0577, 'online'),
    ('NODE_MEH_01', 'Mehsana North Gujarat Node', 'Mehsana', 23.5880, 72.3693, 'online'),
    ('NODE_PAL_01', 'Palanpur Border Corridor Node', 'Palanpur', 24.1724, 72.4346, 'online'),
    ('NODE_BHJ_01', 'Bhuj Kutch Security Node', 'Bhuj', 23.2420, 69.6669, 'online')
ON CONFLICT (node_id) DO UPDATE
SET status = 'online', updated_at = NOW();

INSERT INTO public.cameras (camera_id, node_id, name, city, source, latitude, longitude, geom, enabled, status)
VALUES
    ('CAM_SUR_01', 'NODE_SUR_01', 'Surat Kamrej NH48 Toll Plaza', 'Surat', 'rtsp://mock/sur_kamrej', 21.2678, 72.9644, ST_SetSRID(ST_MakePoint(72.9644, 21.2678), 4326), true, 'online'),
    ('CAM_SUR_02', 'NODE_SUR_01', 'Surat Ring Road Majura Gate', 'Surat', 'rtsp://mock/sur_ringroad', 21.1764, 72.8123, ST_SetSRID(ST_MakePoint(72.8123, 21.1764), 4326), true, 'online'),
    ('CAM_VAD_01', 'NODE_VAD_01', 'Vadodara NH48 Golden Bridge Bypass', 'Vadodara', 'rtsp://mock/vad_nh48', 22.3129, 73.1926, ST_SetSRID(ST_MakePoint(73.1926, 22.3129), 4326), true, 'online'),
    ('CAM_VAD_02', 'NODE_VAD_01', 'Vadodara Alkapuri RC Dutt Road', 'Vadodara', 'rtsp://mock/vad_alkapuri', 22.3106, 73.1704, ST_SetSRID(ST_MakePoint(73.1704, 22.3106), 4326), true, 'online'),
    ('CAM_AHM_01', 'NODE_AHM_01', 'Ahmedabad SP Ring Road Expressway Entry', 'Ahmedabad', './media/ahmd.mp4', 23.0039, 72.5850, ST_SetSRID(ST_MakePoint(72.5850, 23.0039), 4326), true, 'online'),
    ('CAM_AHM_02', 'NODE_AHM_01', 'Ahmedabad SG Highway ISKCON Cross Road', 'Ahmedabad', 'rtsp://mock/ahm_sg_iskcon', 23.0278, 72.5074, ST_SetSRID(ST_MakePoint(72.5074, 23.0278), 4326), true, 'online'),
    ('CAM_AHM_03', 'NODE_AHM_01', 'Ahmedabad Ashram Road Vadaj Circle', 'Ahmedabad', 'rtsp://mock/ahm_ashram', 23.0569, 72.5714, ST_SetSRID(ST_MakePoint(72.5714, 23.0569), 4326), true, 'online'),
    ('CAM_GND_01', 'NODE_GND_01', 'Gandhinagar Infocity Junction CH-0', 'Gandhinagar', 'rtsp://mock/gnd_infocity', 23.1878, 72.6288, ST_SetSRID(ST_MakePoint(72.6288, 23.1878), 4326), true, 'online'),
    ('CAM_GND_02', 'NODE_GND_01', 'Gandhinagar Mahatma Mandir Entry', 'Gandhinagar', 'rtsp://mock/gnd_mahatma', 23.2324, 72.6580, ST_SetSRID(ST_MakePoint(72.6580, 23.2324), 4326), true, 'online'),
    ('CAM_MEH_01', 'NODE_MEH_01', 'Mehsana Bypass Highway Chowkdi', 'Mehsana', 'rtsp://mock/meh_bypass', 23.5937, 72.3962, ST_SetSRID(ST_MakePoint(72.3962, 23.5937), 4326), true, 'online'),
    ('CAM_PAL_01', 'NODE_PAL_01', 'Palanpur RTO Border Checkpost', 'Palanpur', 'rtsp://mock/pal_rto', 24.1792, 72.4412, ST_SetSRID(ST_MakePoint(72.4412, 24.1792), 4326), true, 'online'),
    ('CAM_RJK_01', 'NODE_RJK_01', 'Rajkot Madhapar Chowk 150ft Ring Road', 'Rajkot', './media/rajkor.mp4', 22.3168, 70.7681, ST_SetSRID(ST_MakePoint(70.7681, 22.3168), 4326), true, 'online'),
    ('CAM_RJK_02', 'NODE_RJK_01', 'Rajkot Gondal Road Highway Cross', 'Rajkot', 'rtsp://mock/rjk_gondal', 22.2612, 70.8015, ST_SetSRID(ST_MakePoint(70.8015, 22.2612), 4326), true, 'online'),
    ('CAM_BHV_01', 'NODE_BHV_01', 'Bhavnagar Nari Chowkdi Port Highway', 'Bhavnagar', 'rtsp://mock/bhv_nari', 21.7820, 72.1156, ST_SetSRID(ST_MakePoint(72.1156, 21.7820), 4326), true, 'online'),
    ('CAM_JAM_01', 'NODE_JAM_01', 'Jamnagar Lalpur Bypass Road', 'Jamnagar', 'rtsp://mock/jam_lalpur', 22.4512, 70.0415, ST_SetSRID(ST_MakePoint(70.0415, 22.4512), 4326), true, 'online'),
    ('CAM_BHJ_01', 'NODE_BHJ_01', 'Bhuj Mirzapar National Highway 341', 'Bhuj', 'rtsp://mock/bhj_mirzapar', 23.2389, 69.6514, ST_SetSRID(ST_MakePoint(69.6514, 23.2389), 4326), true, 'online')
ON CONFLICT (camera_id) DO UPDATE
SET latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    geom = EXCLUDED.geom,
    city = EXCLUDED.city,
    status = 'online';

INSERT INTO public.egujcop_watchlist (license_plate, vehicle_make, vehicle_model, vehicle_color, owner_name, category, severity, notes, flagged_by)
VALUES
    ('GJ01AB1234', 'Maruti Suzuki', 'Swift Dzire', 'White', 'Ramesh Patel (Wanted)', 'STOLEN', 'CRITICAL', 'Wanted in Diamond Heist Case FIR 104/2026. Suspect armed and traveling northbound along NH48.', 'eGujCop / CID Crime'),
    ('GJ05CD5678', 'Mahindra', 'Scorpio-N', 'Black', 'Unknown / Tampered Plates', 'STOLEN', 'CRITICAL', 'Stolen from Surat Diamond Bourse parking. Vehicle equipped with fake sirens.', 'Surat City Police Control'),
    ('GJ06EF9012', 'Hyundai', 'Creta', 'Red', 'Imran Sheikh (Suspect)', 'WANTED', 'HIGH', 'Suspect wanted for interrogation in narcotics transit case under NDPS Act.', 'Vadodara Crime Branch'),
    ('GJ27XY9999', 'Toyota', 'Fortuner', 'Dark Blue', 'Vikramaditya Gohil', 'WANTED', 'HIGH', 'Hit and Run accident on SG Highway causing critical injuries. Fled towards Gandhinagar.', 'Ahmedabad Traffic Police'),
    ('GJ03ZZ0007', 'Mahindra', 'Bolero Neo', 'Silver', 'Suresh Bharwad', 'SUSPECT', 'MEDIUM', 'Suspected inter-district illicit liquor transit vehicle. Regular movement on Gondal highway.', 'Rajkot Rural Police')
ON CONFLICT (license_plate) DO UPDATE
SET vehicle_make = EXCLUDED.vehicle_make,
    vehicle_model = EXCLUDED.vehicle_model,
    vehicle_color = EXCLUDED.vehicle_color,
    owner_name = EXCLUDED.owner_name,
    category = EXCLUDED.category,
    severity = EXCLUDED.severity,
    notes = EXCLUDED.notes;

-- ------------------------------------------------------------------------------
-- 7. REHYDRATE REALISTIC CROSS-STATE TRAJECTORY SIGHTINGS FOR GJ01AB1234
-- ------------------------------------------------------------------------------

INSERT INTO public.events (event_id, node_id, camera_id, event_type, confidence, event_timestamp, latitude, longitude, geom, frame_number, inference_latency_ms, metadata, processing_status, processing_attempts, processed_at)
VALUES
    ('a0000001-0000-0000-0000-000000000001', 'NODE_SUR_01', 'CAM_SUR_01', 'ALPR_DETECTED', 0.94, NOW() - INTERVAL '6 hours', 21.2678, 72.9644, ST_SetSRID(ST_MakePoint(72.9644, 21.2678), 4326), 1420, 48.2, 
    '{"city": "Surat", "source": "rtsp://mock/sur_kamrej", "alpr": {"plate": "GJ01AB1234", "track_id": 101, "recognized": true, "plate_confidence": 0.94, "detector_confidence": 0.92}}'::jsonb, 'processed', 1, NOW() - INTERVAL '6 hours'),
    
    ('a0000001-0000-0000-0000-000000000002', 'NODE_VAD_01', 'CAM_VAD_01', 'ALPR_DETECTED', 0.96, NOW() - INTERVAL '4 hours 30 minutes', 22.3129, 73.1926, ST_SetSRID(ST_MakePoint(73.1926, 22.3129), 4326), 2840, 45.1,
    '{"city": "Vadodara", "source": "rtsp://mock/vad_nh48", "alpr": {"plate": "GJ01AB1234", "track_id": 204, "recognized": true, "plate_confidence": 0.96, "detector_confidence": 0.95}}'::jsonb, 'processed', 1, NOW() - INTERVAL '4 hours 30 minutes'),
    
    ('a0000001-0000-0000-0000-000000000003', 'NODE_AHM_01', 'CAM_AHM_01', 'ALPR_DETECTED', 0.98, NOW() - INTERVAL '3 hours', 23.0039, 72.5850, ST_SetSRID(ST_MakePoint(72.5850, 23.0039), 4326), 4200, 42.8,
    '{"city": "Ahmedabad", "source": "./media/ahmd.mp4", "alpr": {"plate": "GJ01AB1234", "track_id": 315, "recognized": true, "plate_confidence": 0.98, "detector_confidence": 0.97}}'::jsonb, 'processed', 1, NOW() - INTERVAL '3 hours'),
    
    ('a0000001-0000-0000-0000-000000000004', 'NODE_GND_01', 'CAM_GND_01', 'ALPR_DETECTED', 0.95, NOW() - INTERVAL '2 hours 15 minutes', 23.1878, 72.6288, ST_SetSRID(ST_MakePoint(72.6288, 23.1878), 4326), 5120, 43.5,
    '{"city": "Gandhinagar", "source": "rtsp://mock/gnd_infocity", "alpr": {"plate": "GJ01AB1234", "track_id": 402, "recognized": true, "plate_confidence": 0.95, "detector_confidence": 0.94}}'::jsonb, 'processed', 1, NOW() - INTERVAL '2 hours 15 minutes'),
    
    ('a0000001-0000-0000-0000-000000000005', 'NODE_MEH_01', 'CAM_MEH_01', 'ALPR_DETECTED', 0.97, NOW() - INTERVAL '1 hour 15 minutes', 23.5937, 72.3962, ST_SetSRID(ST_MakePoint(72.3962, 23.5937), 4326), 6300, 44.0,
    '{"city": "Mehsana", "source": "rtsp://mock/meh_bypass", "alpr": {"plate": "GJ01AB1234", "track_id": 510, "recognized": true, "plate_confidence": 0.97, "detector_confidence": 0.96}}'::jsonb, 'processed', 1, NOW() - INTERVAL '1 hour 15 minutes'),
    
    ('a0000001-0000-0000-0000-000000000006', 'NODE_PAL_01', 'CAM_PAL_01', 'ALPR_DETECTED', 0.99, NOW() - INTERVAL '15 minutes', 24.1792, 72.4412, ST_SetSRID(ST_MakePoint(72.4412, 24.1792), 4326), 7480, 41.2,
    '{"city": "Palanpur", "source": "rtsp://mock/pal_rto", "alpr": {"plate": "GJ01AB1234", "track_id": 612, "recognized": true, "plate_confidence": 0.99, "detector_confidence": 0.98}}'::jsonb, 'processed', 1, NOW() - INTERVAL '15 minutes')
ON CONFLICT (event_id) DO NOTHING;
