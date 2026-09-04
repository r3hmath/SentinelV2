import asyncpg

from app.config import get_settings


class Postgres:

    def __init__(self):
        self.pool: asyncpg.Pool | None = None

    async def connect(self):

        settings = get_settings()

        self.pool = await asyncpg.create_pool(
            dsn=settings.postgres_url,

            min_size=2,
            max_size=10,

            command_timeout=10,
        )

        # Force an actual connection immediately.
        async with self.pool.acquire() as connection:
            await connection.execute("SELECT 1")

    async def disconnect(self):

        if self.pool:

            await self.pool.close()

            self.pool = None

    async def health_check(self) -> bool:

        if self.pool is None:
            return False

        try:

            async with self.pool.acquire() as connection:

                await connection.fetchval(
                    "SELECT 1"
                )

            return True

        except Exception:

            return False


postgres = Postgres()