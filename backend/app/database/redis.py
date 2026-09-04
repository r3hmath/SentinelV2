import redis.asyncio as redis

from app.config import get_settings


class RedisClient:

    def __init__(self):
        self.client: redis.Redis | None = None

    async def connect(self):

        settings = get_settings()

        self.client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )

        await self.client.ping()

    async def disconnect(self):

        if self.client:

            await self.client.aclose()

            self.client = None

    async def health_check(self) -> bool:

        if self.client is None:
            return False

        try:

            return bool(
                await self.client.ping()
            )

        except Exception:

            return False


redis_client = RedisClient()