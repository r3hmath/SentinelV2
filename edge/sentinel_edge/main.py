import concurrent.futures
import logging
import time
import uuid
from datetime import datetime, timezone

from sentinel_edge.camera.stream import CameraStream
from sentinel_edge.config import load_config
from sentinel_edge.inference.detector import VehicleTracker
from sentinel_edge.logging_config import setup_logging
from sentinel_edge.tracking.state import TrackStateManager
from sentinel_edge.transport.event_client import EventClient

from sentinel_edge.behavior.engine import BehaviorEngine
from sentinel_edge.behavior.rules import BehaviorConfig

from sentinel_edge.decision.engine import DecisionEngine
from sentinel_edge.decision.rules import DecisionConfig

from sentinel_edge.alpr import ALPREngine
from sentinel_edge.threat_intel import ThreatIntelEngine
from sentinel_edge.intelligence.fusion import ContextFusionEngine

from sentinel_edge.offload import (
    EdgeExecutor,
    ExecutionRequest,
    ExecutionRegistry,
    ExecutionRouter,
    ExecutionTarget,
    LocalExecutor,
    NodeHealth,
    NodeHealthRegistry,
    OffloadScheduler,
    Priority,
    WorkloadProfile,
    WorkloadType,
)

logger = logging.getLogger("sentinel.edge")

# ============================================================
# EVENT BUILDER
# ============================================================

def build_event(
    camera,
    config,
    event_type: str,
    detections: list[dict],
    frame_number: int,
    latency_ms: float,
    metadata_extra: dict | None = None,
) -> dict:
    """
    Build the canonical Sentinel event payload.
    """

    timestamp = datetime.now(timezone.utc)

    confidence = 0.0

    if detections:
        confidence = max(
            float(detection.get("confidence", 0.0))
            for detection in detections
        )

    active_tracks = {
        detection["track_id"]
        for detection in detections
        if detection.get("track_id") is not None
    }

    metadata = {
        "node_name": config.node.name,
        "city": config.node.city,
        "source": str(camera.source),
        "tracking": {
            "tracker": config.inference.tracker,
            "active_tracks": len(active_tracks),
        },
    }

    if metadata_extra:
        metadata.update(metadata_extra)

    return {
        "event_id": str(uuid.uuid4()),
        "node_id": config.node.id,
        "camera_id": camera.id,
        "event_type": event_type,
        "timestamp": timestamp.isoformat(),
        "confidence": confidence,
        "latitude": config.node.latitude,
        "longitude": config.node.longitude,
        "frame_number": frame_number,
        "inference_latency_ms": round(latency_ms, 2),
        "detections": detections,
        "metadata": metadata,
    }

# ============================================================
# BEHAVIOR EVENT DEDUPLICATOR
# ============================================================

class BehaviorEventDeduplicator:
    """
    Prevent repeated behavior alerts for the same:

        camera + track + behavior

    until the cooldown expires.
    """

    def __init__(self, cooldown_seconds: float = 10.0):

        if cooldown_seconds < 0:
            raise ValueError(
                "cooldown_seconds must be >= 0"
            )

        self.cooldown_seconds = float(cooldown_seconds)

        self._last_emitted: dict[
            tuple[str, int, str],
            datetime,
        ] = {}

    def should_emit(
        self,
        camera_id: str,
        track_id: int,
        behavior: str,
        timestamp: datetime,
    ) -> bool:

        key = (
            str(camera_id),
            int(track_id),
            str(behavior),
        )

        previous = self._last_emitted.get(key)

        # First occurrence
        if previous is None:
            self._last_emitted[key] = timestamp
            return True

        elapsed = (
            timestamp - previous
        ).total_seconds()

        # Cooldown expired
        if elapsed >= self.cooldown_seconds:
            self._last_emitted[key] = timestamp
            return True

        return False

    def clear(self) -> None:
        self._last_emitted.clear()

# ============================================================
# BEHAVIOR CONFIGURATION
# ============================================================

def build_behavior_config(config) -> BehaviorConfig:
    """
    Convert Sentinel YAML/Pydantic behavior settings
    into BehaviorEngine configuration.
    """

    behavior = getattr(config, "behavior", None)

    if behavior is None:
        logger.warning(
            "Behavior configuration not found. "
            "Using BehaviorConfig defaults."
        )

        return BehaviorConfig()

    return BehaviorConfig(

        # Loitering
        loitering_enabled=(
            behavior.loitering.enabled
        ),

        loitering_min_duration_seconds=(
            behavior.loitering.min_duration_seconds
        ),

        loitering_max_movement_px=(
            behavior.loitering.max_movement_px
        ),

        loitering_max_speed_px_s=(
            behavior.loitering.max_speed_px_s
        ),

        # Suspicious stop
        suspicious_stop_enabled=(
            behavior.suspicious_stop.enabled
        ),

        suspicious_stop_min_duration_seconds=(
            behavior.suspicious_stop.min_duration_seconds
        ),

        suspicious_stop_max_speed_px_s=(
            behavior.suspicious_stop.max_speed_px_s
        ),

        # Rapid movement
        rapid_movement_enabled=(
            behavior.rapid_movement.enabled
        ),

        rapid_movement_speed_threshold_px_s=(
            behavior.rapid_movement.speed_threshold_px_s
        ),

        # Direction change
        direction_change_enabled=(
            behavior.abnormal_direction_change.enabled
        ),

        direction_change_angle_threshold_degrees=(
            behavior.abnormal_direction_change.angle_threshold_degrees
        ),

        direction_change_min_speed_px_s=(
            behavior.abnormal_direction_change.min_speed_px_s
        ),

        # General
        minimum_observations=(
            behavior.minimum_observations
        ),
    )

# ============================================================
# DECISION CONFIGURATION
# ============================================================

def build_decision_config(config) -> DecisionConfig:
    """
    Convert Sentinel YAML/Pydantic decision settings
    into DecisionEngine configuration.
    """

    decision = getattr(config, "decision", None)

    if decision is None:

        logger.warning(
            "Decision configuration not found. "
            "Using DecisionConfig defaults."
        )

        return DecisionConfig()

    return DecisionConfig(

        enabled=decision.enabled,

        periodic_inference_seconds=(
            decision.periodic_inference_seconds
        ),

        analyze_new_tracks=(
            decision.analyze_new_tracks
        ),

        high_confidence_threshold=(
            decision.high_confidence_threshold
        ),

        rapid_movement_threshold_px_s=(
            decision.rapid_movement_threshold_px_s
        ),

        vehicle_types=tuple(
            decision.vehicle_types
        ),

        person_enabled=(
            decision.person_enabled
        ),

        behavior_priority_enabled=(
            decision.behavior_priority_enabled
        ),

        stable_track_observations=(
            decision.stable_track_observations
        ),
    )

# ============================================================
# OFFLOAD CONFIGURATION
# ============================================================

def build_offload_scheduler(config) -> OffloadScheduler:
    """
    Build the Dynamic Edge / Local / Cloud scheduler.

    Phase 4.1 initially registers the current Edge node plus
    configurable Local/Cloud execution nodes.

    Actual remote execution is intentionally handled by later
    phases. The scheduler is responsible only for selecting
    the execution target.
    """

    registry = NodeHealthRegistry()

    # --------------------------------------------------------
    # Current Edge Node
    # --------------------------------------------------------

    registry.register(
        NodeHealth(
            node_id=config.node.id,
            target=ExecutionTarget.EDGE,
            cpu_percent=30.0,
            gpu_percent=30.0,
            memory_percent=40.0,
            network_latency_ms=1.0,
            bandwidth_mbps=1000.0,
            queue_depth=0,
            available=True,
            gpu_available=True,
        )
    )

    # --------------------------------------------------------
    # Local AI Node
    # --------------------------------------------------------

    registry.register(
        NodeHealth(
            node_id="local-gpu-01",
            target=ExecutionTarget.LOCAL,
            cpu_percent=40.0,
            gpu_percent=45.0,
            memory_percent=50.0,
            network_latency_ms=2.0,
            bandwidth_mbps=1000.0,
            queue_depth=0,
            available=True,
            gpu_available=True,
        )
    )

    # --------------------------------------------------------
    # Cloud AI Node
    # --------------------------------------------------------

    registry.register(
        NodeHealth(
            node_id="cloud-gpu-01",
            target=ExecutionTarget.CLOUD,
            cpu_percent=20.0,
            gpu_percent=25.0,
            memory_percent=35.0,
            network_latency_ms=80.0,
            bandwidth_mbps=500.0,
            queue_depth=0,
            available=True,
            gpu_available=True,
        )
    )

    scheduler = OffloadScheduler(
        health_registry=registry,
    )

    logger.info(
        "Offload Scheduler initialized | nodes=%s",
        [
            node.node_id
            for node in registry.all()
        ],
    )

    return scheduler

def build_offload_workload(
    decision,
    detection,
) -> WorkloadProfile:
    """
    Convert a Phase 2.3 Decision Engine result into a
    Phase 4.1 workload description.
    """

    priority_value = (
        decision.priority.value
        if hasattr(decision.priority, "value")
        else str(decision.priority)
    )

    try:
        priority = Priority(
            priority_value.upper()
        )
    except ValueError:
        priority = Priority.MEDIUM

    object_type = str(
        detection.get(
            "object_type",
            "unknown",
        )
    ).lower()

    # ALPR is currently the main expensive secondary AI
    # workload executed by the Edge pipeline.
    workload_type = WorkloadType.ALPR

    # Vehicles require ALPR.
    if object_type not in {
        "car",
        "truck",
        "bus",
        "motorcycle",
    }:
        workload_type = WorkloadType.ADVANCED_AI

    return WorkloadProfile(
        workload_type=workload_type,
        priority=priority,
        estimated_compute_ms=50.0,
        minimum_gpu=0.0,
        minimum_memory_percent=5.0,
        maximum_latency_ms=500.0,
        minimum_bandwidth_mbps=1.0,
        allow_edge=True,
        allow_local=True,
        allow_cloud=True,
    )

def crop_detection(frame, detection):
    """Crop a detected object from the current frame."""

    bbox = detection.get("bbox")

    if not bbox:
        return None

    x1, y1, x2, y2 = map(int, bbox)

    height, width = frame.shape[:2]

    x1 = max(0, min(x1, width - 1))
    y1 = max(0, min(y1, height - 1))
    x2 = max(0, min(x2, width))
    y2 = max(0, min(y2, height))

    if x2 <= x1 or y2 <= y1:
        return None

    return frame[y1:y2, x1:x2]

# ============================================================
# OFFLOAD PROCESSING
# ============================================================

def process_offload_decisions(
    camera,
    config,
    enriched_detections,
    decisions_by_track,
    offload_scheduler,
):
    """
    Translate Decision Engine actions into actual
    Edge / Local / Cloud scheduling decisions.

    Returns:

        offload_decisions_by_track

    The scheduler selects where the workload SHOULD execute.
    It does not execute the workload itself.
    """

    offload_decisions_by_track = {}

    if offload_scheduler is None:
        return offload_decisions_by_track

    detection_by_track = {}

    for detection in enriched_detections:
        track_id = detection.get("track_id")

        if track_id is None:
            continue

        detection_by_track[int(track_id)] = detection

    for track_id, decision in decisions_by_track.items():

        action = decision.action.value

        # ----------------------------------------------------
        # SKIP means no expensive AI workload is scheduled.
        # ----------------------------------------------------

        if action == "SKIP":
            continue

        detection = detection_by_track.get(
            int(track_id)
        )

        if detection is None:
            continue

        workload = build_offload_workload(
            decision=decision,
            detection=detection,
        )

        # ----------------------------------------------------
        # Map Decision Engine action to preferred target.
        # ----------------------------------------------------

        if action == "LOCAL_AI":
            preferred_target = ExecutionTarget.LOCAL

        elif action == "CLOUD_AI":
            preferred_target = ExecutionTarget.CLOUD

        else:
            logger.warning(
                "[%s] Unknown Decision Engine action | "
                "track=%s | action=%s",
                camera.id,
                track_id,
                action,
            )
            continue

        result = (
            offload_scheduler.schedule_with_preferred_target(
                workload=workload,
                preferred_target=preferred_target,
            )
        )

        offload_decisions_by_track[
            int(track_id)
        ] = result.decision

        logger.info(
            "[%s] Offload decision | "
            "track=%s | "
            "workload=%s | "
            "decision=%s | "
            "target=%s | "
            "node=%s | "
            "score=%.3f | "
            "latency=%.2fms | "
            "fallback=%s",
            camera.id,
            track_id,
            workload.workload_type.value,
            action,
            result.decision.target.value,
            result.decision.node_id,
            result.decision.score,
            result.decision.estimated_latency_ms,
            result.decision.fallback_used,
        )

    return offload_decisions_by_track

def process_alpr(
    camera,
    config,
    frame,
    enriched_detections,
    decisions_by_track,
    offload_decisions_by_track,
    behavior_events_by_track,
    execution_router,
    execution_counts,
    alpr_engine,
    threat_intel_engine,
    context_fusion_engine,
    event_client,
    frame_number,
    latency_ms,
    emitted_plates,
    emitted_threats,
):
    """Run ALPR and Threat Intelligence for selected vehicle tracks."""

    if alpr_engine is None:
        return 0, 0, 0, 0

    alpr_settings = getattr(config, "alpr", None)

    if alpr_settings is None or not alpr_settings.enabled:
        return 0, 0, 0, 0

    analyzed = 0
    alpr_events_sent = 0
    threat_checks = 0
    threat_events_sent = 0

    for detection in enriched_detections:

        object_type = detection.get("object_type")

        if object_type not in {
            "car",
            "truck",
            "bus",
            "motorcycle",
        }:
            continue

        track_id = detection.get("track_id")

        if track_id is None:
            continue

        track_id = int(track_id)

        decision = decisions_by_track.get(track_id)

        if decision is None:
            continue
    
        offload_decision = offload_decisions_by_track.get(
    track_id)

        if offload_decision is None:
            continue

        if not offload_decision.accepted:
            logger.warning(
        "[%s] AI workload rejected by scheduler | "
        "track=%s | reason=%s",
        camera.id,
        track_id,
        offload_decision.reason,
        )
            continue

        if execution_router is None:
            logger.error(
        "[%s] Execution router unavailable | track=%s",
        camera.id,
        track_id,
    )
            continue
        
        vehicle_crop = crop_detection(
            frame,
            detection,
        )

        if vehicle_crop is None:
            continue

        analyzed += 1

        # ========================================================
# EXECUTION ROUTER
# ========================================================

        execution_request = ExecutionRequest.create(
            camera_id=camera.id,
            track_id=track_id,
            workload_type=WorkloadType.ALPR,
            priority=(
                Priority(
                    decision.priority.value.upper()
                )
                if hasattr(decision.priority, "value")
                else Priority.MEDIUM
            ),
            target=offload_decision.target,
            payload=vehicle_crop,
            metadata={
                "timestamp": time.monotonic(),
                "frame_number": frame_number,
                "node_id": config.node.id,
                "scheduled_node_id": offload_decision.node_id,
                "object_type": object_type,
            },
        )

        execution_result = execution_router.route(
            execution_request
        )

        if execution_result.success:
            execution_counts["successful"] += 1
        else:
            execution_counts["failed"] += 1


        if not execution_result.success:
            logger.warning(
                "[%s] AI execution failed | "
                "track=%s | target=%s | node=%s | error=%s",
                camera.id,
                track_id,
                offload_decision.target.value,
                offload_decision.node_id,
                execution_result.error,
            )
            continue

        logger.info(
            "[%s] AI execution completed | "
            "track=%s | target=%s | executor=%s | "
            "latency=%.2fms",
            camera.id,
            track_id,
            execution_result.target.value,
            execution_result.executor_id,
            execution_result.latency_ms,
        )

        if execution_result.workload_type != WorkloadType.ALPR:
            logger.error(
                "[%s] Unexpected execution workload | "
                "track=%s | workload=%s",
                camera.id,
                track_id,
                execution_result.workload_type.value,
            )
            continue

        execution_payload = execution_result.result

        if not isinstance(execution_payload, dict):
            logger.error(
                "[%s] Invalid ALPR execution result | track=%s",
                camera.id,
                track_id,
            )
            continue
        class _ALPRExecutionView:
            """Compatibility view over the normalized ALPR execution result."""

            def __init__(self, payload: dict):
                self.track_id = payload.get("track_id")
                self.plate_text = payload.get("plate_text")
                self.plate_confidence = float(
                    payload.get("plate_confidence", 0.0)
                )
                self.detector_confidence = float(
                    payload.get("detector_confidence", 0.0)
                )
                self.recognized = bool(
                    payload.get("recognized", False)
                )
                self.timestamp = payload.get("timestamp")

        # --------------------------------------------------------
        # Normalize execution result for existing ALPR pipeline
        # --------------------------------------------------------

        result = _ALPRExecutionView(execution_payload)

        # OCR may fail to recognize a valid plate.
        # Do not run threat intelligence on an empty plate.
        if not result.recognized or not result.plate_text:
            logger.info(
                "[%s] ALPR completed without recognized plate | "
                "track=%s | target=%s",
                camera.id,
                track_id,
                execution_result.target.value,
            )
            continue

        plate = result.plate_text

        # ========================================================
        # ALPR EVENT
        # ========================================================

        plate_key = (
            track_id,
            plate,
        )

        if plate_key not in emitted_plates:

            event = build_event(
                camera=camera,
                config=config,
                event_type="ALPR_DETECTED",
                detections=[
                    {
                        "object_type": object_type,
                        "track_id": track_id,
                        "confidence": float(
                            result.plate_confidence
                        ),
                    }
                ],
                frame_number=frame_number,
                latency_ms=latency_ms,
                metadata_extra={
                    "alpr": {
                        "track_id": track_id,
                        "plate": plate,
                        "plate_confidence": round(
                            result.plate_confidence,
                            4,
                        ),
                        "detector_confidence": round(
                            result.detector_confidence,
                            4,
                        ),
                        "recognized": result.recognized,
                    }
                },
            )

            try:
                sent = event_client.send(event)

            except Exception:
                logger.exception(
                    "[%s] Failed to send ALPR event | "
                    "track=%s | plate=%s",
                    camera.id,
                    track_id,
                    plate,
                )
                sent = False

            if sent:
                emitted_plates.add(plate_key)
                alpr_events_sent += 1

                logger.info(
                    "[%s] ALPR event sent | "
                    "track=%s | plate=%s | confidence=%.3f",
                    camera.id,
                    track_id,
                    plate,
                    result.plate_confidence,
                )

        # ========================================================
        # THREAT INTELLIGENCE
        # ========================================================

        if threat_intel_engine is None:
            continue

        threat_checks += 1

        try:
            assessment = threat_intel_engine.assess(
                plate
            )

        except Exception:
            logger.exception(
                "[%s] Threat intelligence assessment failed | "
                "track=%s | plate=%s",
                camera.id,
                track_id,
                plate,
            )
            continue

        behavior_events = behavior_events_by_track.get(
    track_id,
    [],
)

        behavior_severity = None
        severity_rank = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}
        for behavior_event in behavior_events:
            severity = str(
        getattr(
            behavior_event,
            "severity",
            "",
        )
    ).upper()
            if not behavior_severity:
                behavior_severity = severity
                continue

            if severity_rank.get(
        severity,
        0,
        ) > severity_rank.get(
        behavior_severity,
        0,
    ):
                behavior_severity = severity

        context_assessment = context_fusion_engine.assess(
    track_id=track_id,
    threat_risk=float(
        assessment.risk_score
    ),
    behavior_severity=behavior_severity,
)
        logger.info(
    "[%s] Context assessment | "
    "track=%s | plate=%s | "
    "risk=%.3f | level=%s | factors=%s",
    camera.id,
    track_id,
    assessment.plate,
    context_assessment.risk_score,
    context_assessment.risk_level.value,
    context_assessment.factors,
)
        if not assessment.matched:
            continue
            
        threat_key = (
            track_id,
            assessment.plate,
            assessment.threat_type.value,
        )

        if threat_key in emitted_threats:
            continue

        threat_event = build_event(
            camera=camera,
            config=config,
            event_type="THREAT_DETECTED",
            detections=[
                {
                    "object_type": object_type,
                    "track_id": track_id,
                    "confidence": float(
                        result.plate_confidence
                    ),
                }
            ],
            frame_number=frame_number,
            latency_ms=latency_ms,
            metadata_extra={
                "alpr": {
                    "track_id": track_id,
                    "plate": assessment.plate,
                    "plate_confidence": round(
                        result.plate_confidence,
                        4,
                    ),
                },
                "threat_intelligence": (
                    assessment.to_dict()
                ),
                "context_assessment": (
                    context_assessment.to_dict()
                ),
            },
        )

        try:
            sent = event_client.send(
                threat_event
            )

        except Exception:
            logger.exception(
                "[%s] Failed to send threat event | "
                "track=%s | plate=%s",
                camera.id,
                track_id,
                assessment.plate,
            )
            sent = False

        if sent:
            emitted_threats.add(threat_key)
            threat_events_sent += 1

            logger.warning(
                "[%s] THREAT DETECTED | "
                "track=%s | plate=%s | "
                "type=%s | severity=%s | risk=%.3f",
                camera.id,
                track_id,
                assessment.plate,
                assessment.threat_type.value,
                assessment.severity.value,
                assessment.risk_score,
            )

    return (
        analyzed,
        alpr_events_sent,
        threat_checks,
        threat_events_sent,
    )


def build_alpr_engine(config):
    """
    Build the ALPR engine from Sentinel configuration.
    """

    alpr = getattr(
        config,
        "alpr",
        None,
    )

    if alpr is None:
        logger.warning(
            "ALPR configuration not found. "
            "ALPR disabled."
        )
        return None

    if not alpr.enabled:
        logger.info(
            "ALPR disabled by configuration."
        )
        return None

    try:
        engine = ALPREngine(
            plate_model_path=(
                alpr.plate_model_path
            ),
            detector_confidence=(
                alpr.detector_confidence
            ),
            detector_image_size=(
                alpr.detector_image_size
            ),
            ocr_gpu=(
                alpr.ocr_gpu
            ),
            temporal_observations=(
                alpr.temporal_observations
            ),
            temporal_minimum_votes=(
                alpr.temporal_minimum_votes
            ),
        )

        logger.info(
            "ALPR engine initialized | "
            "model=%s",
            alpr.plate_model_path,
        )

        return engine

    except Exception:
        logger.exception(
            "Failed to initialize ALPR engine"
        )
        return None

# ============================================================
# BEHAVIOR PROCESSING
# ============================================================

def analyze_behaviors(
    camera,
    config,
    behavior_engine,
    behavior_deduplicator,
    state_manager,
    event_client,
    frame_number,
    latency_ms,
):
    """
    Analyze every active TrackState exactly once.

    Returns:

        behavior_events_sent
        behavior_events_by_track

    The second value is passed directly into the
    Decision Engine so that behavior analysis is not
    performed twice.
    """

    behavior_events_by_track = {}

    if not getattr(config, "behavior", None):
        return 0, behavior_events_by_track

    if not config.behavior.enabled:
        return 0, behavior_events_by_track

    timestamp = datetime.now(timezone.utc)

    events_sent = 0

    active_tracks = state_manager.snapshot()

    for track in active_tracks:

        track_id = getattr(
            track,
            "track_id",
            None,
        )

        if track_id is None:
            continue

        # --------------------------------------------------------
        # Analyze behavior ONCE
        # --------------------------------------------------------

        try:

            behavior_events = (
                behavior_engine.analyze(track)
            )

        except Exception:

            logger.exception(
                "[%s] Behavior analysis failed | track=%s",
                camera.id,
                track_id,
            )

            continue

        # Store events for Decision Engine
        behavior_events_by_track[int(track_id)] = (
            behavior_events
        )

        if not behavior_events:
            continue

        # --------------------------------------------------------
        # Emit behavior events
        # --------------------------------------------------------

        for behavior_event in behavior_events:

            try:

                behavior_track_id = int(
                    behavior_event.track_id
                )

                # Deduplication
                if not behavior_deduplicator.should_emit(
                    camera_id=camera.id,
                    track_id=behavior_track_id,
                    behavior=behavior_event.behavior,
                    timestamp=timestamp,
                ):
                    continue

                # Metadata
                behavior_metadata = {
                    "behavior": (
                        behavior_event.to_dict()
                    ),
                    "behavior_engine": {
                        "version": "2.2",
                    },
                }

                # Build event
                event = build_event(
                    camera=camera,
                    config=config,
                    event_type="BEHAVIOR_DETECTED",
                    detections=[
                        {
                            "object_type": (
                                behavior_event.object_type
                            ),
                            "confidence": (
                                behavior_event.score / 100.0
                            ),
                            "track_id": behavior_track_id,
                        }
                    ],
                    frame_number=frame_number,
                    latency_ms=latency_ms,
                    metadata_extra=behavior_metadata,
                )

                # Send event
                sent = event_client.send(event)

                if sent:

                    events_sent += 1

                    logger.warning(
                        "[%s] Behavior detected | "
                        "track=%s | "
                        "behavior=%s | "
                        "severity=%s | "
                        "score=%s",
                        camera.id,
                        behavior_track_id,
                        behavior_event.behavior,
                        behavior_event.severity,
                        behavior_event.score,
                    )

            except Exception:

                logger.exception(
                    "[%s] Failed to emit behavior event",
                    camera.id,
                )

    return events_sent, behavior_events_by_track

# ============================================================
# DECISION PROCESSING
# ============================================================

def process_decisions(
    camera,
    state_manager,
    decision_engine,
    behavior_events_by_track,
    confidence_by_track,
):
    """
    Run the Phase 2.3 Decision Engine.

    The Decision Engine does NOT execute Local AI or Cloud AI.

    It only decides:

        SKIP
        LOCAL_AI
        CLOUD_AI

    based on:

        - new tracks
        - behavior
        - confidence
        - movement
        - periodic analysis
        - stable tracks
    """

    decisions_by_track = {}

    active_tracks = state_manager.snapshot()

    for track in active_tracks:

        track_id = getattr(
            track,
            "track_id",
            None,
        )

        if track_id is None:
            continue

        try:

            confidence = confidence_by_track.get(
                int(track_id),
                0.0,
            )

            behavior_events = (
                behavior_events_by_track.get(
                    int(track_id),
                    [],
                )
            )

            decision = decision_engine.decide(
                track=track,
                behavior_events=behavior_events,
                confidence=confidence,
            )

            decisions_by_track[int(track_id)] = decision

            logger.info(
                "[%s] AI decision | "
                "track=%s | "
                "object=%s | "
                "action=%s | "
                "priority=%s | "
                "reason=%s | "
                "confidence=%.2f",
                camera.id,
                track_id,
                getattr(
                    track,
                    "object_type",
                    "unknown",
                ),
                decision.action.value,
                decision.priority.value,
                decision.reason,
                confidence,
            )

        except Exception:

            logger.exception(
                "[%s] Decision analysis failed | track=%s",
                camera.id,
                track_id,
            )

    return decisions_by_track

# ============================================================
# CAMERA PROCESSING
# ============================================================

def process_camera(
    camera,
    config,
    tracker,
    event_client,
    offload_scheduler,
):
    """
    Complete Edge processing pipeline.

    Camera
       ↓
    YOLO + ByteTrack
       ↓
    TrackStateManager
       ↓
    Behavior Engine
       ↓
    Decision Engine
       ↓
    OBJECT_TRACKED / BEHAVIOR_DETECTED
    """

    logger.info(
        "[%s] Starting camera: %s",
        camera.id,
        camera.source,
    )

    # --------------------------------------------------------
    # Tracking State
    # --------------------------------------------------------

    state_manager = TrackStateManager(
        max_missing_frames=(
            config.inference.max_missing_frames
        ),
        event_update_interval_seconds=(
            config.inference.event_update_interval_seconds
        ),
        min_track_observations=(
            config.inference.min_track_observations
        ),
    )

    def on_discontinuity():
        logger.warning(
            "[%s] Monotonic PTS loop cut detected — resetting ByteTrack & TrackStateManager",
            camera.id,
        )
        tracker.reset()
        state_manager.reset()

    # --------------------------------------------------------
    # Camera
    # --------------------------------------------------------

    stream = CameraStream(
        source=camera.source,
        camera_id=camera.id,
        buffer_size=1,
        loop_video=True,
        on_pts_reset=on_discontinuity,
    )
    stream.open()

    # --------------------------------------------------------
    # Behavior Engine
    # --------------------------------------------------------

    behavior_enabled = (
        getattr(config, "behavior", None) is not None
        and config.behavior.enabled
    )

    behavior_engine = None

    behavior_deduplicator = None

    if behavior_enabled:

        behavior_config = build_behavior_config(
            config
        )

        behavior_engine = BehaviorEngine(
            config=behavior_config
        )

        behavior_deduplicator = (
            BehaviorEventDeduplicator(
                cooldown_seconds=10.0
            )
        )

        logger.info(
            "[%s] Behavior Engine enabled",
            camera.id,
        )

    else:

        logger.info(
            "[%s] Behavior Engine disabled",
            camera.id,
        )

    # --------------------------------------------------------
    # Decision Engine
    # --------------------------------------------------------

    decision_enabled = (
        getattr(config, "decision", None) is not None
        and config.decision.enabled
    )

    decision_engine = None

    if decision_enabled:

        decision_config = build_decision_config(
            config
        )

        decision_engine = DecisionEngine(
            config=decision_config
        )

        logger.info(
            "[%s] Decision Engine enabled | "
            "periodic=%ss | "
            "new_tracks=%s | "
            "high_confidence=%.2f",
            camera.id,
            decision_config.periodic_inference_seconds,
            decision_config.analyze_new_tracks,
            decision_config.high_confidence_threshold,
        )

    else:

        logger.info(
            "[%s] Decision Engine disabled",
            camera.id,
        )

    # --------------------------------------------------------
    # ALPR Engine
    # --------------------------------------------------------

    alpr_engine = build_alpr_engine(config)

    threat_intel_engine = ThreatIntelEngine()
    context_fusion_engine = ContextFusionEngine()

    # Prevent duplicate ALPR events for the same track + plate.
    emitted_plates = set()
    emitted_threats = set()

    # --------------------------------------------------------
        # Execution Registry + Router
        # --------------------------------------------------------

    execution_registry = ExecutionRegistry()

    if alpr_engine is not None:
        execution_registry.register(
                EdgeExecutor(
                    executor_id=f"{config.node.id}-edge-executor",
                    alpr_engine=alpr_engine,
                )
            )

        execution_registry.register(
                LocalExecutor(
                    executor_id="local-executor-01",
                    alpr_engine=alpr_engine,
                )
            )

        execution_router = ExecutionRouter(
            registry=execution_registry,
        )

        logger.info(
            "[%s] Execution Router initialized | executors=%s",
            camera.id,
            [
                executor.executor_id
                for executor in execution_registry.all()
            ],
        )

    # --------------------------------------------------------
    # Counters
    # --------------------------------------------------------

    frame_number = 0

    events_sent = 0

    behavior_events_sent = 0

    alpr_analyzed = 0
    alpr_events_sent = 0

    threat_checks = 0
    threat_events_sent = 0

    decision_counts = {
        "evaluated": 0,
        "skip": 0,
        "local_ai": 0,
        "cloud_ai": 0,
    }
    offload_counts = {
    "edge": 0,
    "local": 0,
    "cloud": 0,
    "rejected": 0,
    "fallback": 0,
    }

    execution_counts = {
    "successful": 0,
    "failed": 0,
}

    # ========================================================
    # CAMERA LOOP
    # ========================================================

    try:

        while True:

            # ------------------------------------------------
            # Read frame with monotonic PTS timing
            # ------------------------------------------------

            success, frame, pts_ms = stream.read(with_pts=True)

            if not success:

                logger.info(
                    "[%s] Stream ended",
                    camera.id,
                )

                break

            frame_number += 1

            # ------------------------------------------------
            # Frame sampling
            # ------------------------------------------------

            if (
                frame_number
                % config.inference.track_every_n_frames
                != 0
            ):
                continue

            # ------------------------------------------------
            # YOLO + ByteTrack
            # ------------------------------------------------

            detections, latency_ms = tracker.track(
                frame
            )

            # Strict Monotonic PTS Frame Presentation Timing (zero wall-clock drift)
            timestamp = (
                datetime.fromtimestamp(pts_ms / 1000.0, tz=timezone.utc)
                if pts_ms > 0
                else datetime.now(timezone.utc)
            )

            # ------------------------------------------------
            # Update TrackState
            # ------------------------------------------------

            enriched_detections = (
                state_manager.update(
                    detections,
                    timestamp,
                )
            )

            if not enriched_detections:
                continue

            # =================================================
            # CONFIDENCE MAP
            # =================================================

            confidence_by_track = {}

            for detection in enriched_detections:

                track_id = detection.get(
                    "track_id"
                )

                if track_id is None:
                    continue

                confidence_by_track[int(track_id)] = (
                    float(
                        detection.get(
                            "confidence",
                            0.0,
                        )
                    )
                )

            # =================================================
            # BEHAVIOR ANALYSIS
            # =================================================

            behavior_events_by_track = {}

            if (
                behavior_enabled
                and behavior_engine is not None
                and behavior_deduplicator is not None
            ):

                (
                    behavior_sent,
                    behavior_events_by_track,
                ) = analyze_behaviors(

                    camera=camera,

                    config=config,

                    behavior_engine=(
                        behavior_engine
                    ),

                    behavior_deduplicator=(
                        behavior_deduplicator
                    ),

                    state_manager=(
                        state_manager
                    ),

                    event_client=(
                        event_client
                    ),

                    frame_number=(
                        frame_number
                    ),

                    latency_ms=(
                        latency_ms
                    ),
                )

                behavior_events_sent += (
                    behavior_sent
                )

            # =================================================
            # DECISION ENGINE
            # =================================================

            if (
                decision_enabled
                and decision_engine is not None
            ):

                decisions_by_track = process_decisions(
                    camera=camera,
                    state_manager=state_manager,
                    decision_engine=decision_engine,
                    behavior_events_by_track=behavior_events_by_track,
                    confidence_by_track=confidence_by_track,
                )

                # --------------------------------------------
                # Decision metrics
                # --------------------------------------------

                for decision in decisions_by_track.values():

                    decision_counts[
                        "evaluated"
                    ] += 1

                    action = (
                        decision.action.value
                    )

                    if action == "SKIP":

                        decision_counts[
                            "skip"
                        ] += 1

                    elif action == "LOCAL_AI":

                        decision_counts[
                            "local_ai"
                        ] += 1

                    elif action == "CLOUD_AI":

                        decision_counts[
                            "cloud_ai"
                        ] += 1

            else:
                decisions_by_track = {}

            

            # =================================================
            # ALPR
            # =================================================
            # =========================================================
# DYNAMIC OFFLOADING
# =========================================================

            offload_decisions_by_track = (
    process_offload_decisions(
        camera=camera,
        config=config,
        enriched_detections=enriched_detections,
        decisions_by_track=decisions_by_track,
        offload_scheduler=offload_scheduler,
    )
)
            for offload_decision in (
    offload_decisions_by_track.values()
):

                if not offload_decision.accepted:
                    offload_counts["rejected"] += 1
                    continue

                target = offload_decision.target.value.lower()

                if target in offload_counts:
                    offload_counts[target] += 1

                if offload_decision.fallback_used:
                    offload_counts["fallback"] += 1
            (
    analyzed,
    sent,
    checks,
    threat_sent,
) = process_alpr(
    camera=camera,
    config=config,
    frame=frame,
    enriched_detections=enriched_detections,
    decisions_by_track=decisions_by_track,
    offload_decisions_by_track=offload_decisions_by_track,
    execution_router=execution_router,
    execution_counts=execution_counts,
    behavior_events_by_track=behavior_events_by_track,
    alpr_engine=alpr_engine,
    threat_intel_engine=threat_intel_engine,
    context_fusion_engine=context_fusion_engine,
    event_client=event_client,
    frame_number=frame_number,
    latency_ms=latency_ms,
    emitted_plates=emitted_plates,
    emitted_threats=emitted_threats,
)



            alpr_analyzed += analyzed
            alpr_events_sent += sent

            threat_checks += checks
            threat_events_sent += threat_sent

            # =================================================
            # OBJECT TRACKING EVENT
            # =================================================

            emit_detections = []

            for detection in enriched_detections:

                track_id = detection.get(
                    "track_id"
                )

                if track_id is None:
                    continue

                if state_manager.should_emit_update(
                    track_id,
                    timestamp,
                ):

                    emit_detections.append(
                        detection
                    )

            if not emit_detections:
                continue

            # ------------------------------------------------
            # Build object event
            # ------------------------------------------------

            event = build_event(

                camera=camera,

                config=config,

                event_type="OBJECT_TRACKED",

                detections=(
                    emit_detections
                ),

                frame_number=(
                    frame_number
                ),

                latency_ms=(
                    latency_ms
                ),
            )

            # ------------------------------------------------
            # Send
            # ------------------------------------------------

            sent = event_client.send(event)

            if sent:

                events_sent += 1

                logger.info(
                    "[%s] Track event sent | "
                    "tracks=%d | "
                    "active=%d | "
                    "latency=%.2fms",
                    camera.id,
                    len(emit_detections),
                    state_manager.active_count(),
                    latency_ms,
                )

    except KeyboardInterrupt:

        logger.info(
            "[%s] Camera processing interrupted",
            camera.id,
        )

    except Exception:

        logger.exception(
            "[%s] Camera processing failed",
            camera.id,
        )

    finally:

        # ----------------------------------------------------
        # Cleanup
        # ----------------------------------------------------

        stream.release()

        state_manager.reset()

        tracker.reset()

        if alpr_engine is not None:
            alpr_engine.reset()

        emitted_plates.clear()
        emitted_threats.clear()

        if behavior_deduplicator is not None:
            behavior_deduplicator.clear()

        logger.info(
            "[%s] Camera stopped | "
            "frames=%d | object_events=%d | behavior_events=%d | "
            "decisions=%d | skip=%d | local_ai=%d | cloud_ai=%d | "
            "alpr_analyzed=%d | alpr_events=%d | "
            "threat_checks=%d | threat_events=%d | "
            "offload_edge=%d | offload_local=%d | offload_cloud=%d | "
            "offload_rejected=%d | offload_fallback=%d | "
            "execution_success=%d | execution_failed=%d",
            camera.id,
            frame_number,
            events_sent,
            behavior_events_sent,
            decision_counts["evaluated"],
            decision_counts["skip"],
            decision_counts["local_ai"],
            decision_counts["cloud_ai"],
            alpr_analyzed,
            alpr_events_sent,
            threat_checks,
            threat_events_sent,
            offload_counts["edge"],
            offload_counts["local"],
            offload_counts["cloud"],
            offload_counts["rejected"],
            offload_counts["fallback"],
            execution_counts["successful"],
            execution_counts["failed"],
        )

# ============================================================
# MAIN
# ============================================================

def main():

    setup_logging()

    config = load_config()

    logger.info(
        "===================================="
    )

    logger.info(
        "Sentinel Edge Node Starting"
    )

    logger.info(
        "Node: %s",
        config.node.id,
    )

    logger.info(
        "City: %s",
        config.node.city,
    )

    logger.info(
        "Tracker: %s",
        config.inference.tracker,
    )

    # --------------------------------------------------------
    # Behavior status
    # --------------------------------------------------------

    behavior_enabled = (
        getattr(config, "behavior", None) is not None
        and config.behavior.enabled
    )

    logger.info(
        "Behavior Engine: %s",
        (
            "ENABLED"
            if behavior_enabled
            else "DISABLED"
        ),
    )

    # --------------------------------------------------------
    # Decision status
    # --------------------------------------------------------

    decision_enabled = (
        getattr(config, "decision", None) is not None
        and config.decision.enabled
    )

    logger.info(
        "Decision Engine: %s",
        (
            "ENABLED"
            if decision_enabled
            else "DISABLED"
        ),
    )

    alpr_enabled = (
        getattr(config, "alpr", None) is not None
        and config.alpr.enabled
    )

    logger.info(
        "ALPR: %s",
        "ENABLED" if alpr_enabled else "DISABLED",
    )

    logger.info(
        "===================================="
    )

    # --------------------------------------------------------
    # Event Client
    # --------------------------------------------------------

    event_client = EventClient(
        config.api.base_url
    )
    offload_scheduler = build_offload_scheduler(
        config
)

    try:

        enabled_cameras = [
            camera for camera in config.cameras if camera.enabled
        ]

        if len(enabled_cameras) <= 1:
            for camera in enabled_cameras:
                tracker = VehicleTracker(
                    model_path=config.inference.model_path,
                    confidence=config.inference.confidence,
                    classes=config.inference.classes,
                    tracker=config.inference.tracker,
                    image_size=config.inference.image_size,
                )
                process_camera(
                    camera=camera,
                    config=config,
                    tracker=tracker,
                    event_client=event_client,
                    offload_scheduler=offload_scheduler,
                )
        else:
            logger.info(
                "Launching %d cameras concurrently...",
                len(enabled_cameras),
            )
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(32, len(enabled_cameras)),
                thread_name_prefix="CamWorker",
            ) as executor:
                futures = []
                for camera in enabled_cameras:
                    tracker = VehicleTracker(
                        model_path=config.inference.model_path,
                        confidence=config.inference.confidence,
                        classes=config.inference.classes,
                        tracker=config.inference.tracker,
                        image_size=config.inference.image_size,
                    )
                    futures.append(
                        executor.submit(
                            process_camera,
                            camera=camera,
                            config=config,
                            tracker=tracker,
                            event_client=event_client,
                            offload_scheduler=offload_scheduler,
                        )
                    )
                concurrent.futures.wait(futures)

    finally:

        event_client.close()

        logger.info(
            "Sentinel Edge Node stopped"
        )
        logger.info(
            "Dynamic Offload Scheduler: ENABLED"
        )

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()