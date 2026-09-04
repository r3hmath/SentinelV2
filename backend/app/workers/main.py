import asyncio
import logging

from app.database.postgres import postgres
from app.database.redis import redis_client
from app.workers.event_worker import worker_loop


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)


async def main():

    print("====================================")
    print("Sentinel Event Worker")
    print("====================================")

    try:

        await postgres.connect()

        print(
            "[Worker] PostgreSQL connected"
        )

        await redis_client.connect()

        print(
            "[Worker] Redis connected"
        )

        await worker_loop()

    except Exception:

        logging.exception(
            "[Worker] Fatal startup error"
        )

        raise

    finally:

        await redis_client.disconnect()

        await postgres.disconnect()

        print(
            "[Worker] Shutdown complete"
        )


if __name__ == "__main__":

    asyncio.run(main())