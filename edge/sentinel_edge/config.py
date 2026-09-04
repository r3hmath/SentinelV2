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


# ============================================================
# BEHAVIOR CONFIGURATION
# ============================================================

class BehaviorLoiteringConfig(BaseModel):
    enabled: bool = True

    min_duration_seconds: float = Field(
        default=30.0,
        ge=0.0,
    )

    max_movement_px: float = Field(
        default=100.0,
        ge=0.0,
    )

    max_speed_px_s: float = Field(
        default=8.0,
        ge=0.0,
    )


class BehaviorSuspiciousStopConfig(BaseModel):
    enabled: bool = True

    min_duration_seconds: float = Field(
        default=15.0,
        ge=0.0,
    )

    max_speed_px_s: float = Field(
        default=3.0,
        ge=0.0,
    )


class BehaviorRapidMovementConfig(BaseModel):
    enabled: bool = True

    speed_threshold_px_s: float = Field(
        default=180.0,
        ge=0.0,
    )


class BehaviorDirectionChangeConfig(BaseModel):
    enabled: bool = True

    angle_threshold_degrees: float = Field(
        default=90.0,
        ge=0.0,
        le=180.0,
    )

    min_speed_px_s: float = Field(
        default=10.0,
        ge=0.0,
    )


class BehaviorSettings(BaseModel):
    enabled: bool = True

    event_cooldown_seconds: float = Field(
        default=10.0,
        ge=0.0,
    )

    loitering: BehaviorLoiteringConfig = (
        BehaviorLoiteringConfig()
    )

    suspicious_stop: BehaviorSuspiciousStopConfig = (
        BehaviorSuspiciousStopConfig()
    )

    rapid_movement: BehaviorRapidMovementConfig = (
        BehaviorRapidMovementConfig()
    )

    abnormal_direction_change: BehaviorDirectionChangeConfig = (
        BehaviorDirectionChangeConfig()
    )

    minimum_observations: int = Field(
        default=5,
        ge=1,
    )


# ============================================================
# DECISION ENGINE CONFIGURATION
# ============================================================

class DecisionSettings(BaseModel):
    enabled: bool = True

    periodic_inference_seconds: float = Field(
        default=5.0,
        ge=0.0,
    )

    analyze_new_tracks: bool = True

    high_confidence_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
    )

    rapid_movement_threshold_px_s: float = Field(
        default=180.0,
        ge=0.0,
    )

    vehicle_types: list[str] = [
        "car",
        "truck",
        "bus",
        "motorcycle",
    ]

    person_enabled: bool = True

    behavior_priority_enabled: bool = True

    stable_track_observations: int = Field(
        default=10,
        ge=1,
    )


# ============================================================
# ALPR CONFIGURATION
# ============================================================

class ALPRSettings(BaseModel):
    enabled: bool = True

    plate_model_path: str = "./models/license_plate.pt"

    detector_confidence: float = Field(
        default=0.40,
        ge=0.0,
        le=1.0,
    )

    detector_image_size: int = Field(
        default=640,
        ge=320,
    )

    ocr_enabled: bool = True

    ocr_gpu: bool = False

    temporal_observations: int = Field(
        default=10,
        ge=2,
    )

    temporal_minimum_votes: int = Field(
        default=2,
        ge=1,
    )

    analyze_every_n_decisions: int = Field(
        default=1,
        ge=1,
    )


# ============================================================
# CAMERA
# ============================================================

class CameraConfig(BaseModel):
    id: str
    name: str
    source: str
    enabled: bool = True


# ============================================================
# SENTINEL CONFIG
# ============================================================

class SentinelConfig(BaseModel):
    node: NodeConfig

    api: APIConfig

    inference: InferenceConfig

    behavior: BehaviorSettings = BehaviorSettings()

    decision: DecisionSettings = DecisionSettings()

    alpr: ALPRSettings = ALPRSettings()

    cameras: list[CameraConfig]


# ============================================================
# CONFIG LOADER
# ============================================================

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