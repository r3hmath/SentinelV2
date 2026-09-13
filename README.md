# SENTINEL — Phase 1 Foundation

This is the Phase 1 refactor of the existing Sentinel prototype.

Goal:
- one reusable edge-node application instead of separate Ahmedabad/Rajkot/Surat scripts
- configuration-driven cameras/nodes
- structured logging
- environment-based backend configuration
- clean Edge -> API event boundary
- health/status endpoint foundation
- PostgreSQL + Redis infrastructure for later phases

Phase 1 intentionally does NOT implement:
- dynamic edge/local/cloud scheduling
- production ALPR
- multi-person tracking
- RBAC
- WebSocket dashboard
- cloud object storage

Those are Phase 2+ components.

## Run

1. Copy `.env.example` to `.env`.
2. Start infrastructure:

```bash
docker compose up -d postgres redis
```

3. Install edge dependencies:

```bash
cd edge
pip install -r requirements.txt
```

4. Install backend dependencies:

```bash
cd backend
pip install -r requirements.txt
```

5. Start the backend:

```bash
uvicorn app.main:app --reload --port 8000
```

6. Configure an edge node in `edge/config/node.yaml`.
7. Start the edge node:

```bash
python -m sentinel_edge.main
```

## Migration from the old prototype

The old project had separate node files and hardcoded values. Phase 1 replaces those with one executable:

`edge/sentinel_edge/main.py`

Node-specific values now live in:

`edge/config/node.yaml`

Do not hardcode camera IDs, coordinates, backend URLs, or database credentials inside Python source files.

---

## Phase 2: Live CCTV Ingestion & Vehicle Re-ID Infrastructure

### 1. Mock RTSP Streaming Setup (Local Development)

To test the live ingestion worker without live government CCTV endpoints, run a local RTSP server using **MediaMTX** (formerly `rtsp-simple-server`) and loop a sample video file from `edge/media/`:

#### Option A: Running MediaMTX via Docker
```bash
docker run --rm -it -e MTX_PROTOCOLS=tcp -p 8554:8554 bluenviron/mediamtx
```

#### Option B: Looping Sample Video Stream to Mock RTSP via FFmpeg
Once MediaMTX is running on port 8554, publish a continuous looped stream using FFmpeg:
```bash
ffmpeg -re -stream_loop -1 -i edge/media/ahmd.mp4 -c copy -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/live/CAM_AHM_01
```

### 2. Environment Configuration
Configure the RTSP stream URL dynamically via the `CAMERA_RTSP_URL` environment variable:
```bash
# Windows PowerShell
$env:CAMERA_RTSP_URL="rtsp://127.0.0.1:8554/live/CAM_AHM_01"

# Linux / macOS
export CAMERA_RTSP_URL="rtsp://127.0.0.1:8554/live/CAM_AHM_01"
```

### 3. Running the Ingestion Worker
```bash
python edge/ingest_gujarat_live.py --camera-id CAM_AHM_01 --city Ahmedabad --fps 5.0
```

### 4. Running the Vehicle Re-ID Engine
```bash
# Pairwise vehicle crop comparison (Cosine Similarity & Euclidean Distance)
python edge/reid_engine.py --image edge/media/sample_vehicle.jpg --compare edge/media/sample_vehicle_enhanced.jpg

# Watchlist matching with synthetic/live PostGIS database
python edge/reid_engine.py --image edge/media/sample_vehicle.jpg --threshold 0.75
```

