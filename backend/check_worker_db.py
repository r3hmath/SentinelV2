import asyncio

import asyncpg

from app.config import get_settings


async def main():

    settings = get_settings()

    print("====================================")
    print("Worker Database Diagnostic")
    print("====================================")

    print("Database :", settings.postgres_db)
    print("Host     :", settings.postgres_host)
    print("Port     :", settings.postgres_port)
    print("User     :", settings.postgres_user)

    connection = await asyncpg.connect(
        dsn=settings.postgres_url
    )

    try:

        result = await connection.fetchrow(
            """
            SELECT
                current_database() AS database,
                current_user AS user,
                inet_server_addr() AS server_ip,
                inet_server_port() AS server_port,
                current_schema() AS schema,
                to_regclass('public.events') AS events_table
            """
        )

        print()
        print("Actual PostgreSQL connection:")
        print("------------------------------------")
        print("Database :", result["database"])
        print("User     :", result["user"])
        print("Server IP:", result["server_ip"])
        print("Port     :", result["server_port"])
        print("Schema   :", result["schema"])
        print("Events   :", result["events_table"])

    finally:

        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())