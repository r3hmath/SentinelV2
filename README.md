# SENTINEL

## Statewide CCTV & Spatiotemporal Vehicle Tracking Platform

**Sentinel** is an enterprise-grade video intelligence and spatiotemporal vehicle tracking platform designed for statewide public-safety and traffic-surveillance infrastructure.

The platform provides a reusable edge-node architecture for CCTV ingestion, low-quality video processing, vehicle re-identification, watchlist matching, and—through the upcoming Phase 3—cross-camera spatiotemporal trajectory analysis.

> **Current status:** Phase 1 and Phase 2 are complete and locally verified.
> **Test status:** **192 / 192 tests passing**
> **Next milestone:** Phase 3 — Spatiotemporal Trajectory & Multi-Camera Tracking

---

## Table of Contents

* [Overview](#overview)
* [Architecture](#architecture)
* [Current Project Status](#current-project-status)
* [Phase 1 — Foundation](#phase-1--foundation)
* [Phase 2 — Live CCTV Ingestion & Vehicle Re-ID](#phase-2--live-cctv-ingestion--vehicle-re-id)
* [Infrastructure](#infrastructure)
* [Database & Migrations](#database--migrations)
* [Project Structure](#project-structure)
* [Installation](#installation)
* [Running the Platform](#running-the-platform)
* [Testing](#testing)
* [Phase 3 — Spatiotemporal Tracking](#phase-3--spatiotemporal-tracking)
* [Phase 4 — Alert Dispatch & Scale-Out](#phase-4--alert-dispatch--scale-out)
* [Security & Authorization](#security--authorization)
* [Development Principles](#development-principles)
* [License](#license)

---

# Overview

Sentinel is designed around a distributed **Edge → API → Database → Intelligence** architecture.

The system is intended to ingest video observations from CCTV camera nodes, normalize detection metadata, generate vehicle visual embeddings, compare observations against authorized watchlists, and reconstruct vehicle movement across geographically distributed camera nodes.

### Core capabilities

* Live RTSP video ingestion
* TCP-enforced RTSP transport
* Pre-flight camera connectivity probing
* Zero-lag single-slot frame buffering
* Configurable frame pacing
* Offline telemetry buffering
* Structured spatial and temporal metadata
* Low-light / high-beam glare preprocessing
* Vehicle image enhancement
* OSNet-based vehicle Re-ID
* ResNet-18 vehicle Re-ID
* 512-dimensional normalized embeddings
* Cosine similarity
* Euclidean distance
* PostgreSQL / PostGIS watchlist matching
* Camera-aware event ingestion
* Spatiotemporal trajectory reconstruction *(Phase 3)*
* Travel-speed anomaly detection *(Phase 3)*
* Geographic control-room visualization *(Phase 3)*
* Real-time alert dispatch *(Phase 4)*

---

# Architecture

```text
                         SENTINEL
                            │
             ┌──────────────┴──────────────┐
             │                             │
        EDGE NODES                    BACKEND API
             │                             │
       ┌─────┴─────┐                 FastAPI
       │           │                     │
    Camera      Camera                   │
       │           │                     │
       └─────┬─────┘                     │
             │                           │
      RTSP / Video                       │
             │                           │
             ▼                           │
   Live Ingestion Engine                 │
             │                           │
             ▼                           │
    Frame Normalization                  │
             │                           │
             ▼                           │
       Vehicle Re-ID ────────────────────┤
             │                           │
             ▼                           ▼
      Vehicle Embedding            Event Ingestion
             │                           │
             └─────────────┬─────────────┘
                           │
                           ▼
                  PostgreSQL + PostGIS
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
        Watchlist Matching       Spatial Events
                                        │
                                        ▼
                             Phase 3 Trajectory Engine
                                        │
                           ┌────────────┼────────────┐
                           │            │            │
                           ▼            ▼            ▼
                       Trajectory    Speed       Anomaly
                       Reconstruction Analysis   Detection
                           │            │            │
                           └────────────┴────────────┘
                                        │
                                        ▼
                              Control Room Dashboard
```

---

# Current Project Status

| Component                    |                Status |
| ---------------------------- | --------------------: |
| Phase 1 Foundation           |            ✅ Complete |
| Phase 2 Live Ingestion       |            ✅ Complete |
| Phase 2 Vehicle Re-ID        |            ✅ Complete |
| Low-Light / Glare Processing |            ✅ Complete |
| Watchlist Matching           |            ✅ Complete |
| PostgreSQL 18                |         ✅ Operational |
| PostGIS 3                    |         ✅ Operational |
| Memurai Redis                |         ✅ Operational |
| Python 3.11 `.venv`          |         ✅ Operational |
| SQL Migrations 001–004       |             ✅ Applied |
| Test Suite                   | **192 / 192 Passing** |
| Phase 3 Trajectory Engine    |               🚧 Next |
| Phase 3 Dashboard            |            🚧 Planned |
| Phase 4 Alert Dispatch       |            📋 Planned |
| Phase 4 GPU Scale-Out        |            📋 Planned |

---

# Phase 1 — Foundation

Phase 1 refactored the original Sentinel prototype into a reusable, configuration-driven edge-node architecture.

## Objectives

* One reusable edge-node application
* Configuration-driven camera and node definitions
* Structured logging
* Environment-based backend configuration
* Clean Edge → API event boundary
* Health/status endpoint foundation
* PostgreSQL infrastructure
* Redis infrastructure
* Modular backend routing

### Phase 1 architecture

```text
edge/
   │
   ▼
sentinel_edge/
   │
   ├── camera/
   ├── routers/
   └── transport/
          │
          ▼
      FastAPI API
          │
          ├── PostgreSQL
          └── Redis
```

## Intentionally deferred from Phase 1

The following were deliberately reserved for later phases:

* Dynamic edge/local/cloud scheduling
* Production ALPR
* Multi-person tracking
* RBAC
* WebSocket dashboard
* Cloud object storage
* Advanced vehicle Re-ID
* Statewide trajectory reconstruction

---

# Phase 2 — Live CCTV Ingestion & Vehicle Re-ID

Phase 2 implements the live video ingestion and vehicle visual-identification foundation.

The implementation has been locally verified with:

```text
192 / 192 tests passing
```

Both ingestion and Re-ID/night-preprocessing test suites are included in this verified baseline.

---

## 2.1 Live CCTV Ingestion

Implementation:

```text
edge/ingest_gujarat_live.py
```

### Features

#### TCP RTSP transport

The ingestion worker forces TCP transport to reduce UDP packet loss:

```python
OPENCV_FFMPEG_CAPTURE_OPTIONS = "rtsp_transport;tcp"
```

The setting is asserted during connection establishment as well.

#### Pre-flight connectivity probe

Before OpenCV attempts to bind to a stream, Sentinel performs a TCP connectivity probe.

Default timeout:

```text
0.8 seconds
```

This prevents an unavailable camera from blocking the ingestion worker indefinitely.

#### Single-slot frame buffer

The ingestion worker uses:

```python
collections.deque(maxlen=1)
```

Only the freshest frame is retained.

This deliberately prioritizes:

```text
LOW LATENCY > FRAME COMPLETENESS
```

rather than allowing stale frames to accumulate.

#### Exponential reconnect backoff

Reconnect attempts use bounded exponential backoff:

```text
Δt = min(30.0, 1.5 × 1.5^attempts + jitter)
```

where:

```text
jitter ∈ [0, 0.5)
```

#### Frame pacing

Default processing rate:

```text
5 FPS
```

The target FPS is configurable.

#### Normalized metadata

Each processed frame can be represented with normalized metadata including:

* Camera ID
* UTC timestamp
* Frame ID
* Monotonic presentation timestamp
* Latitude
* Longitude
* Frame resolution

#### Offline telemetry buffering

When backend connectivity is unavailable, telemetry is stored in a bounded FIFO queue.

The queue supports:

* Bounded memory usage
* FIFO ordering
* Drop-oldest behavior when full
* Retry/requeue semantics
* Event flushing after connectivity recovery

---

# 2.2 Mock RTSP Streaming

For local development, Sentinel can be tested against a locally generated RTSP stream rather than a production CCTV endpoint.

## MediaMTX

Start MediaMTX:

```bash
docker run --rm -it \
  -e MTX_PROTOCOLS=tcp \
  -p 8554:8554 \
  bluenviron/mediamtx
```

## Publish a sample video

Using FFmpeg:

```bash
ffmpeg -re \
  -stream_loop -1 \
  -i edge/media/ahmd.mp4 \
  -c copy \
  -f rtsp \
  -rtsp_transport tcp \
  rtsp://127.0.0.1:8554/live/CAM_AHM_01
```

The resulting test stream is:

```text
rtsp://127.0.0.1:8554/live/CAM_AHM_01
```

---

# 2.3 Environment Configuration

Configure the camera stream through the environment rather than hardcoding it into Python.

### Windows PowerShell

```powershell
$env:CAMERA_RTSP_URL="rtsp://127.0.0.1:8554/live/CAM_AHM_01"
```

### Linux / macOS

```bash
export CAMERA_RTSP_URL="rtsp://127.0.0.1:8554/live/CAM_AHM_01"
```

---

# 2.4 Running the Ingestion Worker

```bash
python edge/ingest_gujarat_live.py \
  --camera-id CAM_AHM_01 \
  --city Ahmedabad \
  --fps 5.0
```

---

# 2.5 Vehicle Re-ID Engine

Implementation:

```text
edge/reid_engine.py
```

The Re-ID engine provides visual vehicle matching when license plates are unavailable, unreliable, damaged, obscured, or otherwise unsuitable as the sole identity signal.

---

## NightGlarePreprocessor

The preprocessing pipeline performs:

```text
BGR Frame
    │
    ▼
CIE LAB Conversion
    │
    ▼
High-Luminance Detection
    │
    ▼
Localized Glare Attenuation
    │
    ▼
CLAHE Contrast Recovery
    │
    ▼
Bilateral Filtering
    │
    ▼
Enhanced Frame
```

### High-beam detection

The L channel is analyzed for high-intensity regions.

Default glare threshold:

```text
L > 230
```

### CLAHE

Contrast enhancement uses:

```text
clipLimit = 2.5
tileGridSize = (8, 8)
```

### Bilateral filtering

A final bilateral filter is applied to preserve important edges while reducing noise.

---

# 2.6 Vehicle Embedding Models

Sentinel currently supports two vehicle Re-ID backbones.

### OSNet

A custom omni-scale architecture with:

* Multi-scale feature streams
* Gated feature aggregation
* 512-dimensional embedding head

### ResNet-18

The implementation supports:

* torchvision ResNet-18
* ImageNet pretrained weights
* Fine-tuned weight loading

---

## Embedding Contract

Both architectures produce:

```text
512-dimensional
L2-normalized
float vector
```

The system enforces normalization both inside the model and during embedding extraction.

Mathematically:

```text
||v||₂ = 1
```

---

# 2.7 Similarity Engine

Sentinel currently supports:

### Cosine similarity

```text
similarity(a,b) =
(a · b) / (||a||₂ ||b||₂)
```

### Euclidean distance

```text
d(a,b) = ||a-b||₂
```

Both metrics are tested against known identical and orthogonal vector cases.

---

# 2.8 Watchlist Matching

Vehicle embeddings can be compared against:

```text
public.egujcop_watchlist
```

The matching pipeline:

```text
Vehicle Crop
     │
     ▼
Preprocessing
     │
     ▼
Re-ID Embedding
     │
     ▼
512-D Normalized Vector
     │
     ▼
Watchlist Comparison
     │
     ▼
Similarity Threshold
     │
     ▼
Ranked Candidates
```

Candidates are filtered using the configured similarity threshold and returned in descending similarity order.

---

# Running Vehicle Re-ID

### Pairwise comparison

```bash
python edge/reid_engine.py \
  --image edge/media/sample_vehicle.jpg \
  --compare edge/media/sample_vehicle_enhanced.jpg
```

### Watchlist matching

```bash
python edge/reid_engine.py \
  --image edge/media/sample_vehicle.jpg \
  --threshold 0.75
```

---

# Infrastructure

Sentinel currently operates on a native Windows environment.

## Runtime

| Component               | Version / Configuration   |
| ----------------------- | ------------------------- |
| OS                      | Windows 11 Enterprise     |
| Python                  | 3.11                      |
| PostgreSQL              | 18                        |
| PostGIS                 | 3                         |
| PostgreSQL Port         | `5433`                    |
| Database                | `sentinel`                |
| Redis-compatible engine | Memurai Developer Edition |
| Redis Port              | `6379`                    |

---

# Database & Migrations

Sentinel uses PostgreSQL with PostGIS for relational and spatial workloads.

Migration files:

```text
backend/sql/
├── 001_initial.sql
├── 002_phase12.sql
├── 003_postgis_and_watchlist.sql
└── 004_statewide_spatiotemporal.sql
```

## Migration 001

Establishes the core platform foundation:

* Users
* Roles
* Audit logging
* Alert routing

## Migration 002

Adds:

* Edge nodes
* Cameras
* Detection events
* Raw telemetry structures

## Migration 003

Adds:

* PostGIS
* Vehicle/suspect watchlist
* Spatial indexes
* Vehicle embedding storage
* Watchlist matching structures

## Migration 004

Adds the database foundation required for statewide spatiotemporal analysis, including structures supporting:

* Camera relationships
* Temporal event analysis
* Speed estimation
* Trajectory direction
* Cross-camera travel-time analysis

---

# Project Structure

```text
SentineL/
│
├── backend/
│   ├── sql/
│   │   ├── 001_initial.sql
│   │   ├── 002_phase12.sql
│   │   ├── 003_postgis_and_watchlist.sql
│   │   └── 004_statewide_spatiotemporal.sql
│   │
│   ├── audit_inspect_db.py
│   └── test_backend_routes.py
│
├── edge/
│   ├── ingest_gujarat_live.py
│   ├── reid_engine.py
│   └── media/
│
├── sentinel_edge/
│   ├── camera/
│   ├── routers/
│   └── transport/
│
├── tests/
│   ├── test_ingest_live.py
│   └── test_reid.py
│
├── .env
├── pytest.ini
└── requirements.txt
```

---

# Installation

Create and activate the Python virtual environment:

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

---

# Database Configuration

Sentinel uses PostgreSQL on port `5433`.

Example configuration:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_DB=sentinel
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<your-password>
```

Redis/Memurai:

```env
REDIS_HOST=localhost
REDIS_PORT=6379
```

> Never commit production credentials or secrets to GitHub.

---

# Running the Backend

Start the FastAPI backend using the project's configured application entry point.

Example:

```bash
uvicorn app.main:app --reload --port 8000
```

The exact backend module should match the application's current package layout.

---

# Testing

Sentinel currently has a fully verified test baseline:

```text
192 / 192 tests passing
```

Run the complete suite:

```bash
pytest -q
```

For verbose output:

```bash
pytest -v
```

### Ingestion tests

```bash
pytest tests/test_ingest_live.py -v
```

### Re-ID tests

```bash
pytest tests/test_reid.py -v
```

The test suite covers, among other areas:

* TCP socket probing
* Timeout handling
* RTSP transport configuration
* Reconnect backoff
* Frame-buffer semantics
* Offline telemetry buffering
* Frame pacing
* Metadata normalization
* Glare preprocessing
* CLAHE processing
* OSNet embedding dimensions
* ResNet-18 embedding dimensions
* L2 normalization
* Cosine similarity
* Euclidean distance
* Watchlist matching
* Similarity thresholds
* Candidate ranking

---

# Phase 3 — Spatiotemporal Tracking

## Status: NEXT IMPLEMENTATION PHASE

Phase 3 extends Sentinel from **individual vehicle observations** into a **statewide multi-camera movement intelligence layer**.

The primary objective is to reconstruct probable vehicle trajectories across camera nodes using spatial and temporal relationships.

---

## Phase 3 Architecture

```text
Camera A
   │
   ▼
Vehicle Observation
   │
   ├── Plate Identity
   ├── Re-ID Identity
   ├── Timestamp
   └── Camera Coordinates
   │
   ▼
PostgreSQL + PostGIS
   │
   ▼
Trajectory Solver
   │
   ├── Temporal Ordering
   ├── Spatial Distance
   ├── Δt Calculation
   ├── Velocity Estimation
   └── Identity Association
   │
   ▼
Camera B
   │
   ▼
Vehicle Trajectory
   │
   ├── Route Reconstruction
   ├── Speed Analysis
   ├── Impossible Transit Detection
   └── Clone-Plate Detection
```

---

## 3.1 Cross-Camera Path Reconstruction

Phase 3 will reconstruct vehicle paths from normalized observations.

Conceptually:

```text
Observation 1
     ↓
Camera A
     ↓
Observation 2
     ↓
Camera B
     ↓
Observation 3
     ↓
Camera C
```

PostGIS geometry will be used to calculate spatial relationships between camera nodes.

Trajectory geometry can be represented using:

```sql
ST_MakeLine(...)
```

with observations ordered chronologically.

---

# 3.2 Travel-Time & Speed Analysis

For two observations:

```text
Camera A → Camera B
```

the system calculates:

```text
Δd = distance(Camera A, Camera B)

Δt = timestamp_B - timestamp_A
```

Estimated velocity:

```text
v = Δd / Δt
```

The result can then be compared against configured or statistically derived thresholds.

---

# 3.3 Anomaly Detection

Phase 3 will identify patterns such as:

### Impossible travel time

A vehicle appears at two geographically separated cameras within a physically implausible interval.

```text
Camera A
10:00:00

Camera B
10:02:00

Required speed:
> physically plausible threshold
```

### Excessive speed

Estimated inter-camera velocity exceeds the configured threshold.

### Simultaneous sightings

The same identity appears at geographically incompatible camera nodes at approximately the same time.

### Potential cloned plate

A single license plate appears at different locations with physically impossible transit times.

---

# 3.4 Identity Fusion

Phase 3 will combine multiple identity signals.

Priority can be represented conceptually as:

```text
Reliable License Plate
          │
          ▼
      Plate Match
          │
     unavailable?
          │
          ▼
     Vehicle Re-ID
          │
          ▼
 Visual Similarity
          │
          ▼
Spatiotemporal Consistency
```

The trajectory engine should avoid merging unrelated vehicles solely because they have similar visual embeddings.

Identity confidence should incorporate:

* Plate evidence
* Re-ID similarity
* Camera sequence
* Temporal consistency
* Geographic consistency

---

# 3.5 Phase 3 API

Planned API capabilities include:

```text
GET /api/v1/vehicles/{vehicle_id}/trajectory
```

Retrieve a reconstructed vehicle trajectory.

```text
GET /api/v1/cameras/{camera_id}/neighbors
```

Retrieve geographically relevant camera nodes.

```text
GET /api/v1/vehicles/{vehicle_id}/sightings
```

Retrieve historical observations.

```text
GET /api/v1/trajectory/anomalies
```

Retrieve detected trajectory anomalies.

```text
GET /api/v1/vehicles/{vehicle_id}/latest
```

Retrieve the latest known vehicle observation.

> Endpoint paths are part of the Phase 3 implementation design and may be finalized during implementation to match the existing API conventions.

---

# 3.6 Phase 3 Dashboard

The planned geographic control-room interface will use:

* MapLibre GL or Leaflet
* Camera-node visualization
* Vehicle trajectory rendering
* Historical trajectory replay
* Camera checkpoint sequencing
* Anomaly visualization
* Timestamp filtering
* Vehicle identity inspection

Conceptual UI:

```text
┌─────────────────────────────────────────────────────┐
│ SENTINEL CONTROL ROOM                               │
├─────────────────────────────────────────────────────┤
│                                                     │
│       ● Camera A                                    │
│        \                                            │
│         \                                           │
│          ● Camera B ─────────● Camera C             │
│                    VEHICLE PATH                     │
│                                                     │
│              ⚠ SPEED ANOMALY                       │
│                                                     │
├─────────────────────────────────────────────────────┤
│ Vehicle ID     Last Seen      Confidence   Status   │
│ VEH-001        12:42:18       0.94         TRACKED  │
└─────────────────────────────────────────────────────┘
```

---

# Phase 4 — Alert Dispatch & Scale-Out

## Status: PLANNED

Phase 4 will extend Sentinel from analytical infrastructure into a larger-scale real-time alerting platform.

Planned components include:

### Real-time alert dispatch

Similarity-based or trajectory-based alerts can be routed to authorized downstream systems.

Example conceptual threshold:

```text
Similarity >= 0.75
```

The final threshold should be configurable and validated against operational requirements.

### GPU acceleration

Potential acceleration technologies:

* ONNX Runtime
* TensorRT
* CUDA
* GPU-optimized inference pipelines

### Message bus

At large statewide scale, a message broker such as:

```text
Apache Kafka
```

can be introduced between high-volume edge/event producers and downstream persistence/analytics services.

### Geographic scaling

Potential database scaling strategies include:

* Regional partitioning
* Citus
* Read replicas
* Geographic sharding
* Time-based partitioning

---

# Security & Authorization

Sentinel is intended for authorized public-safety infrastructure.

Production deployment must enforce:

* Authenticated camera access
* Credential management
* TLS for network communications
* Role-based access control
* Audit logging
* Least-privilege database access
* Secure secret storage
* Access logging
* Data retention policies
* Appropriate legal and operational authorization

Live government CCTV integrations must only use feeds and APIs for which the deployment has documented authorization.

The local development configuration intentionally supports mock/local RTSP streams so the platform can be developed and tested without requiring access to restricted surveillance infrastructure.

---

# Development Principles

## Configuration over hardcoding

Camera IDs, coordinates, backend URLs, credentials, and environment-specific values should not be hardcoded into Python source files.

Use:

```text
.env
```

and configuration files such as:

```text
edge/config/node.yaml
```

where appropriate.

---

## Low-latency over stale-frame accumulation

The ingestion layer intentionally uses a single-slot frame buffer:

```python
deque(maxlen=1)
```

This ensures that processing remains focused on the newest available frame.

---

## Bounded resource usage

Queues, retry loops, buffers, and network operations should remain bounded.

The system should fail gracefully rather than allowing:

```text
unbounded memory growth
```

or:

```text
unbounded reconnect loops
```

---

## Test-first progression

Every phase should preserve the existing test baseline.

The current verified baseline is:

```text
192 / 192 passing
```

Phase 3 should add coverage without regressing Phase 1 or Phase 2 behavior.

---

# Phase Roadmap

```text
PHASE 1
Foundation
   │
   ├── Edge architecture
   ├── FastAPI backend
   ├── PostgreSQL
   ├── Redis
   └── Configuration system
   │
   ▼
PHASE 2
Live Ingestion + Vehicle Re-ID
   │
   ├── RTSP ingestion
   ├── TCP transport
   ├── Offline buffering
   ├── Night/glare processing
   ├── OSNet
   ├── ResNet-18
   └── Watchlist matching
   │
   ▼
PHASE 3
Spatiotemporal Intelligence
   │
   ├── Multi-camera tracking
   ├── Trajectory reconstruction
   ├── Speed estimation
   ├── Impossible travel detection
   ├── Clone-plate detection
   └── Geographic dashboard
   │
   ▼
PHASE 4
Statewide Scale & Alerting
   │
   ├── Real-time dispatch
   ├── GPU inference
   ├── Message bus
   ├── Geographic scaling
   └── High-volume production deployment
```

---

# Project Status Summary

### Completed

* [x] Phase 1 architecture refactor
* [x] Configuration-driven edge nodes
* [x] FastAPI backend foundation
* [x] PostgreSQL infrastructure
* [x] Redis/Memurai infrastructure
* [x] Database migrations 001–004
* [x] Live RTSP ingestion
* [x] TCP transport enforcement
* [x] Camera connectivity probing
* [x] Single-slot low-latency frame buffer
* [x] Exponential reconnect backoff
* [x] Frame pacing
* [x] Offline telemetry buffering
* [x] Normalized event metadata
* [x] Night/glare preprocessing
* [x] CLAHE enhancement
* [x] Bilateral filtering
* [x] OSNet vehicle Re-ID
* [x] ResNet-18 vehicle Re-ID
* [x] 512-dimensional normalized embeddings
* [x] Cosine similarity
* [x] Euclidean distance
* [x] Watchlist matching
* [x] Async event-loop safety correction
* [x] **192 / 192 tests passing**

### In Progress

* [ ] Phase 3 trajectory data layer
* [ ] Cross-camera trajectory solver
* [ ] Spatiotemporal anomaly engine
* [ ] Vehicle identity fusion
* [ ] Trajectory API
* [ ] Geographic control-room dashboard

### Planned

* [ ] Phase 4 alert dispatch
* [ ] GPU inference optimization
* [ ] Message-bus architecture
* [ ] Geographic database scaling
* [ ] Production-scale deployment

---

# License

This repository is intended for authorized development and deployment of the Sentinel platform.

Add the project's applicable license and usage terms here before public distribution.
