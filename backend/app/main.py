from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database.postgres import postgres
from app.database.redis import redis_client
from app.routers.events import router as events_router
from app.routers.health import router as health_router


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

    yield

    print(
        "[Sentinel] Shutting down..."
    )

    await redis_client.disconnect()

    await postgres.disconnect()


app = FastAPI(
    title="Sentinel API",
    description=(
        "Edge-Cloud AI Surveillance "
        "Intelligence Platform"
    ),
    version="0.2.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,

    allow_origins=settings.cors_origins,

    allow_credentials=True,

    allow_methods=[
        "GET",
        "POST",
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


@app.get("/")
async def root():

    return {
        "service": "Sentinel",
        "status": "online",
        "version": "0.2.0",
    }