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
