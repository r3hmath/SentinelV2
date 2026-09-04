from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class NodeConfig(BaseModel):
    id: str
    name: str
    city: str
    latitude: float
    longitude: float


class APIConfig(BaseModel):
    base_url: str


class InferenceConfig(BaseModel):
    model_path: str

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    classes: list[int]

    tracker: str = "bytetrack.yaml"

    track_every_n_frames: int = Field(
        default=1,
        ge=1,
    )

    event_update_interval_seconds: float = Field(
        default=1.0,
        ge=0.0,
    )

    min_track_observations: int = Field(
        default=2,
        ge=1,
    )

    max_missing_frames: int = Field(
        default=30,
        ge=1,
    )

    image_size: int = Field(
        default=640,
        ge=320,
    )


class CameraConfig(BaseModel):
    id: str
    name: str
    source: str
    enabled: bool = True


class SentinelConfig(BaseModel):
    node: NodeConfig
    api: APIConfig
    inference: InferenceConfig
    cameras: list[CameraConfig]


def load_config(
    path: str = "config/node.yaml",
) -> SentinelConfig:

    config_path = Path(path)

    if not config_path.exists():
        raise FileNotFoundError(
            f"Configuration not found: {config_path}"
        )

    with open(
        config_path,
        "r",
        encoding="utf-8",
    ) as file:

        raw_config = yaml.safe_load(file)

    return SentinelConfig(**raw_config)