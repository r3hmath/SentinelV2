import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database.postgres import postgres
from app.database.redis import redis_client
from app.routers.events import router as events_router
from app.routers.health import router as health_router
from app.routers.tracking import router as tracking_router
from app.routers.watchlist import router as watchlist_router
from app.routers.websocket import router as websocket_router
from app.workers.event_worker import worker_loop


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):

    print("[Sentinel] Starting backend...")

    await postgres.connect()

    print(
        "[Sentinel] PostgreSQL connected"
    )

    await redis_client.connect()

    print(
        "[Sentinel] Redis connected"
    )

    worker_task = asyncio.create_task(worker_loop())
    print(
        "[Sentinel] Event Worker background task active"
    )

    yield

    print(
        "[Sentinel] Shutting down..."
    )

    worker_task.cancel()
    try:
        await worker_task
    except (asyncio.CancelledError, Exception):
        pass

    await redis_client.disconnect()

    await postgres.disconnect()


app = FastAPI(
    title="Sentinel API",
    description=(
        "Edge-Cloud AI Surveillance "
        "Intelligence Platform — Gujarat Police Hackathon"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "OPTIONS",
    ],

    allow_headers=["*"],
)


app.include_router(
    health_router,
    prefix="/api",
)

app.include_router(
    events_router,
    prefix="/api",
)

from pathlib import Path
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routers.ingest import router as ingest_router
from app.routers.camera_proxy import router as camera_proxy_router

# Phase 2 & Live Hackathon Routers
app.include_router(
    ingest_router,
)

app.include_router(
    camera_proxy_router,
)

app.include_router(
    tracking_router,
    prefix="/api/v1",
)


app.include_router(
    watchlist_router,
    prefix="/api/v1",
)

app.include_router(
    websocket_router,
)

frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    app.mount("/dashboard", StaticFiles(directory=str(frontend_dist), html=True), name="dashboard")

    @app.get("/")
    async def root():
        return RedirectResponse(url="/dashboard/")
else:
    @app.get("/")
    async def root():
        return {
            "service": "Sentinel",
            "status": "online",
            "version": "1.0.0",
        }