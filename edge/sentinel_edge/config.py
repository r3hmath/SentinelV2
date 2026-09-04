from pathlib import Path

import yaml
from pydantic import BaseModel


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

    confidence: float

    classes: list[int]

    process_every_n_frames: int


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