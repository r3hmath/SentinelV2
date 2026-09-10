-- =========================================================
-- SENTINEL: PostGIS, Geospatial Trajectories & eGujCop Watchlist
-- Phase 2 / Hackathon Production Migration
-- =========================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------
-- 1. CAMERAS: Geospatial Columns & City Attribute
-- ---------------------------------------------------------

ALTER TABLE public.cameras
ADD COLUMN IF NOT EXISTS city VARCHAR(100);

ALTER TABLE public.cameras
ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);

UPDATE public.cameras
SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
WHERE geom IS NULL AND longitude IS NOT NULL AND latitude IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cameras_geom
ON public.cameras USING GIST (geom);

-- ---------------------------------------------------------
-- 2. EVENTS: Geospatial Columns & Plate Indexing
-- ---------------------------------------------------------

ALTER TABLE public.events
ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);

UPDATE public.events
SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
WHERE geom IS NULL AND longitude IS NOT NULL AND latitude IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_events_geom
ON public.events USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_events_alpr_plate
ON public.events ((COALESCE(metadata->'alpr'->>'plate', metadata->>'license_plate', metadata->>'plate')));

-- ---------------------------------------------------------
-- 3. eGujCop WATCHLIST TABLE
-- ---------------------------------------------------------

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

-- ---------------------------------------------------------
-- 4. SEED EDGE NODES (Gujarat 1,000 km Network)
-- ---------------------------------------------------------

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

-- ---------------------------------------------------------
-- 5. SEED CAMERAS WITH POSTGIS GEOMETRIES
-- ---------------------------------------------------------

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

-- ---------------------------------------------------------
-- 6. SEED eGujCop WATCHLIST
-- ---------------------------------------------------------

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

-- ---------------------------------------------------------
-- 7. SEED CROSS-CAMERA TRAJECTORY EVENTS FOR GJ01AB1234
-- (Simulating South-to-North highway route across Gujarat)
-- ---------------------------------------------------------

INSERT INTO public.events (event_id, node_id, camera_id, event_type, confidence, event_timestamp, latitude, longitude, geom, frame_number, inference_latency_ms, metadata, processing_status, processing_attempts, processed_at)
VALUES
    -- Checkpoint 1: Surat Kamrej Toll (08:30:00)
    ('a0000001-0000-0000-0000-000000000001', 'NODE_SUR_01', 'CAM_SUR_01', 'ALPR_DETECTED', 0.94, NOW() - INTERVAL '5 hours 30 minutes', 21.2678, 72.9644, ST_SetSRID(ST_MakePoint(72.9644, 21.2678), 4326), 1420, 48.2, 
    '{"city": "Surat", "source": "rtsp://mock/sur_kamrej", "alpr": {"plate": "GJ01AB1234", "track_id": 101, "recognized": true, "plate_confidence": 0.94, "detector_confidence": 0.92}}'::jsonb, 'processed', 1, NOW() - INTERVAL '5 hours 30 minutes'),
    
    -- Checkpoint 2: Vadodara NH48 (09:45:00)
    ('a0000001-0000-0000-0000-000000000002', 'NODE_VAD_01', 'CAM_VAD_01', 'ALPR_DETECTED', 0.96, NOW() - INTERVAL '4 hours 15 minutes', 22.3129, 73.1926, ST_SetSRID(ST_MakePoint(73.1926, 22.3129), 4326), 2840, 45.1,
    '{"city": "Vadodara", "source": "rtsp://mock/vad_nh48", "alpr": {"plate": "GJ01AB1234", "track_id": 204, "recognized": true, "plate_confidence": 0.96, "detector_confidence": 0.95}}'::jsonb, 'processed', 1, NOW() - INTERVAL '4 hours 15 minutes'),
    
    -- Checkpoint 3: Ahmedabad Ring Road (11:00:00)
    ('a0000001-0000-0000-0000-000000000003', 'NODE_AHM_01', 'CAM_AHM_01', 'ALPR_DETECTED', 0.98, NOW() - INTERVAL '3 hours 00 minutes', 23.0039, 72.5850, ST_SetSRID(ST_MakePoint(72.5850, 23.0039), 4326), 4210, 43.8,
    '{"city": "Ahmedabad", "source": "./media/ahmd.mp4", "alpr": {"plate": "GJ01AB1234", "track_id": 312, "recognized": true, "plate_confidence": 0.98, "detector_confidence": 0.96}}'::jsonb, 'processed', 1, NOW() - INTERVAL '3 hours 00 minutes'),

    -- Checkpoint 4: Gandhinagar Infocity (11:45:00)
    ('a0000001-0000-0000-0000-000000000004', 'NODE_GND_01', 'CAM_GND_01', 'ALPR_DETECTED', 0.95, NOW() - INTERVAL '2 hours 15 minutes', 23.1878, 72.6288, ST_SetSRID(ST_MakePoint(72.6288, 23.1878), 4326), 5690, 46.5,
    '{"city": "Gandhinagar", "source": "rtsp://mock/gnd_infocity", "alpr": {"plate": "GJ01AB1234", "track_id": 418, "recognized": true, "plate_confidence": 0.95, "detector_confidence": 0.93}}'::jsonb, 'processed', 1, NOW() - INTERVAL '2 hours 15 minutes'),

    -- Checkpoint 5: Mehsana Highway Junction (12:40:00)
    ('a0000001-0000-0000-0000-000000000005', 'NODE_MEH_01', 'CAM_MEH_01', 'ALPR_DETECTED', 0.97, NOW() - INTERVAL '1 hours 20 minutes', 23.5937, 72.3962, ST_SetSRID(ST_MakePoint(72.3962, 23.5937), 4326), 7120, 44.2,
    '{"city": "Mehsana", "source": "rtsp://mock/meh_bypass", "alpr": {"plate": "GJ01AB1234", "track_id": 521, "recognized": true, "plate_confidence": 0.97, "detector_confidence": 0.94}}'::jsonb, 'processed', 1, NOW() - INTERVAL '1 hours 20 minutes'),

    -- Checkpoint 6: Palanpur RTO Border Checkpost (13:50:00 - Latest Sighting)
    ('a0000001-0000-0000-0000-000000000006', 'NODE_PAL_01', 'CAM_PAL_01', 'ALPR_DETECTED', 0.99, NOW() - INTERVAL '10 minutes', 24.1792, 72.4412, ST_SetSRID(ST_MakePoint(72.4412, 24.1792), 4326), 8450, 42.9,
    '{"city": "Palanpur", "source": "rtsp://mock/pal_rto", "alpr": {"plate": "GJ01AB1234", "track_id": 634, "recognized": true, "plate_confidence": 0.99, "detector_confidence": 0.97}}'::jsonb, 'processed', 1, NOW() - INTERVAL '10 minutes')
ON CONFLICT (event_id) DO NOTHING;

-- Trajectory for second vehicle: GJ05CD5678 (Surat to Rajkot)
INSERT INTO public.events (event_id, node_id, camera_id, event_type, confidence, event_timestamp, latitude, longitude, geom, frame_number, inference_latency_ms, metadata, processing_status, processing_attempts, processed_at)
VALUES
    ('b0000001-0000-0000-0000-000000000001', 'NODE_SUR_01', 'CAM_SUR_02', 'ALPR_DETECTED', 0.93, NOW() - INTERVAL '6 hours', 21.1764, 72.8123, ST_SetSRID(ST_MakePoint(72.8123, 21.1764), 4326), 1100, 47.0,
    '{"city": "Surat", "source": "rtsp://mock/sur_ringroad", "alpr": {"plate": "GJ05CD5678", "track_id": 77, "recognized": true, "plate_confidence": 0.93, "detector_confidence": 0.91}}'::jsonb, 'processed', 1, NOW() - INTERVAL '6 hours'),

    ('b0000001-0000-0000-0000-000000000002', 'NODE_BHV_01', 'CAM_BHV_01', 'ALPR_DETECTED', 0.95, NOW() - INTERVAL '3 hours 30 minutes', 21.7820, 72.1156, ST_SetSRID(ST_MakePoint(72.1156, 21.7820), 4326), 3320, 45.4,
    '{"city": "Bhavnagar", "source": "rtsp://mock/bhv_nari", "alpr": {"plate": "GJ05CD5678", "track_id": 89, "recognized": true, "plate_confidence": 0.95, "detector_confidence": 0.94}}'::jsonb, 'processed', 1, NOW() - INTERVAL '3 hours 30 minutes'),

    ('b0000001-0000-0000-0000-000000000003', 'NODE_RJK_01', 'CAM_RJK_01', 'ALPR_DETECTED', 0.97, NOW() - INTERVAL '45 minutes', 22.3168, 70.7681, ST_SetSRID(ST_MakePoint(70.7681, 22.3168), 4326), 5540, 43.1,
    '{"city": "Rajkot", "source": "./media/rajkor.mp4", "alpr": {"plate": "GJ05CD5678", "track_id": 114, "recognized": true, "plate_confidence": 0.97, "detector_confidence": 0.95}}'::jsonb, 'processed', 1, NOW() - INTERVAL '45 minutes')
ON CONFLICT (event_id) DO NOTHING;
