from fastapi import APIRouter

from app.database.postgres import postgres
from app.database.redis import redis_client


router = APIRouter()


@router.get("/health")
async def health():

    postgres_ok = await postgres.health_check()
    redis_ok = await redis_client.health_check()

    overall_status = (
        "healthy"
        if postgres_ok and redis_ok
        else "degraded"
    )

    return {
        "status": overall_status,
        "service": "sentinel-api",
        "dependencies": {
            "postgres": (
                "up"
                if postgres_ok
                else "down"
            ),
            "redis": (
                "up"
                if redis_ok
                else "down"
            ),
        },
    }