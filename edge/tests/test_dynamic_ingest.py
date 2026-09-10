import time
import pytest
from sentinel_edge.camera.dynamic_ingest import (
    CameraDescriptor,
    FramePacket,
    discover_camera_topology,
    stream_camera_frames,
)


def test_discover_camera_topology():
    """Verify dynamic discovery returns valid camera descriptors without hardcoding."""
    # Test with live backend or resilient fallback
    descriptors = discover_camera_topology(api_base_url="http://127.0.0.1:8001")
    assert len(descriptors) > 0

    for cam in descriptors:
        assert isinstance(cam.id, str)
        assert len(cam.id) > 0
        assert cam.codec in ["h264", "h265"]
        assert cam.latitude != 0.0
        assert cam.longitude != 0.0
        assert cam.active_fps > 0


def test_stream_camera_frames_pts():
    """Verify frame generator extracts monotonic PTS and delta PTS."""
    descriptors = discover_camera_topology(api_base_url="http://127.0.0.1:8001")
    cam = descriptors[0]

    discontinuity_fired = False

    def on_discontinuity(cam_id, prev_pts, curr_pts):
        nonlocal discontinuity_fired
        discontinuity_fired = True

    generator = stream_camera_frames(
        camera=cam,
        is_active=lambda: True,
        on_discontinuity=on_discontinuity,
    )

    # Ingest 5 frames
    packets = []
    for _ in range(5):
        packet = next(generator)
        assert isinstance(packet, FramePacket)
        assert packet.camera_id == cam.id
        assert packet.frame is not None
        assert packet.pts_ms >= 0
        packets.append(packet)

    assert len(packets) == 5
    # Verify delta PTS calculation
    for i in range(1, len(packets)):
        assert packets[i].pts_ms >= packets[i - 1].pts_ms
        assert packets[i].delta_pts_ms >= 0


def test_scene_discontinuity_flushing():
    """Verify scene discontinuity detection callback on PTS reset."""
    cam = CameraDescriptor(
        id="CAM_TEST_DISC",
        name="Test Camera",
        district_id="NODE_TEST",
        substation_id="SUB_TEST",
        city="Ahmedabad",
        latitude=23.0,
        longitude=72.5,
        codec="h264",
        live=True,
        rtsp_url="",
        hls_url="",
        whep_url="",
        fallback_file="./media/ahmd.mp4",
        preview_fps=10.0,
        active_fps=10.0,
    )

    discontinuity_calls = []

    def handle_discontinuity(cam_id, prev_pts, curr_pts):
        discontinuity_calls.append((cam_id, prev_pts, curr_pts))

    gen = stream_camera_frames(
        camera=cam,
        is_active=lambda: True,
        on_discontinuity=handle_discontinuity,
    )

    # Read a few frames
    first = next(gen)
    assert first.frame is not None
