from functools import lru_cache
from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


# sentinel_phase1/
PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = PROJECT_ROOT / ".env.example"


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    sentinel_env: str = "development"

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    postgres_db: str = "sentinel"
    postgres_user: str = "postgres"
    postgres_password: str = "admin"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432

    redis_host: str = "127.0.0.1"
    redis_port: int = 6379

    allowed_origins: str = (
        "http://localhost:5173,"
        "http://127.0.0.1:5173"
    )

    @property
    def postgres_url(self) -> str:

        return (
            f"postgresql://"
            f"{self.postgres_user}:"
            f"{self.postgres_password}@"
            f"{self.postgres_host}:"
            f"{self.postgres_port}/"
            f"{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:

        return (
            f"redis://"
            f"{self.redis_host}:"
            f"{self.redis_port}"
        )

    @property
    def cors_origins(self) -> list[str]:

        return [
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:

    return Settings()