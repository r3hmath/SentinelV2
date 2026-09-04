CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- =========================================================
-- EDGE NODES
-- =========================================================

CREATE TABLE IF NOT EXISTS edge_nodes (

    id BIGSERIAL PRIMARY KEY,

    node_id VARCHAR(100) UNIQUE NOT NULL,

    name VARCHAR(200) NOT NULL,

    city VARCHAR(100),

    latitude DOUBLE PRECISION,

    longitude DOUBLE PRECISION,

    status VARCHAR(30) NOT NULL DEFAULT 'offline',

    last_heartbeat TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =========================================================
-- CAMERAS
-- =========================================================

CREATE TABLE IF NOT EXISTS cameras (

    id BIGSERIAL PRIMARY KEY,

    camera_id VARCHAR(100) UNIQUE NOT NULL,

    node_id VARCHAR(100) NOT NULL,

    name VARCHAR(200) NOT NULL,

    source VARCHAR(500),

    latitude DOUBLE PRECISION,

    longitude DOUBLE PRECISION,

    enabled BOOLEAN NOT NULL DEFAULT TRUE,

    status VARCHAR(30) NOT NULL DEFAULT 'offline',

    last_seen TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_camera_node
        FOREIGN KEY (node_id)
        REFERENCES edge_nodes(node_id)
        ON DELETE CASCADE
);


-- =========================================================
-- EVENTS
-- =========================================================

CREATE TABLE IF NOT EXISTS events (

    id BIGSERIAL PRIMARY KEY,

    event_id UUID UNIQUE NOT NULL,

    node_id VARCHAR(100) NOT NULL,

    camera_id VARCHAR(100) NOT NULL,

    event_type VARCHAR(100) NOT NULL,

    confidence DOUBLE PRECISION,

    event_timestamp TIMESTAMPTZ NOT NULL,

    latitude DOUBLE PRECISION,

    longitude DOUBLE PRECISION,

    frame_number BIGINT,

    inference_latency_ms DOUBLE PRECISION,

    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =========================================================
-- INDEXES
-- =========================================================

CREATE INDEX IF NOT EXISTS idx_events_camera
ON events(camera_id);


CREATE INDEX IF NOT EXISTS idx_events_node
ON events(node_id);


CREATE INDEX IF NOT EXISTS idx_events_timestamp
ON events(event_timestamp DESC);


CREATE INDEX IF NOT EXISTS idx_events_type
ON events(event_type);


CREATE INDEX IF NOT EXISTS idx_cameras_node
ON cameras(node_id);


CREATE INDEX IF NOT EXISTS idx_nodes_status
ON edge_nodes(status);