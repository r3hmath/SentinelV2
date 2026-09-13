"""
Sentinel Video Intelligence Platform — Unit Test Suite
Module: tests/test_reid.py
Description: Unit tests for Vehicle Re-ID Engine (edge/reid_engine.py).
             Covers:
             1. Glare attenuation on a synthetic high-L test image
             2. Embedding shape and unit L2-normalization invariants
             3. Matching threshold behavior with synthetic fixtures
"""

import math
from unittest.mock import AsyncMock, MagicMock

import cv2
import numpy as np
import pytest
import torch

from edge.reid_engine import (
    NightGlarePreprocessor,
    OSNetReID,
    ResNet18ReID,
    VehicleReIDEngine,
    cosine_distance,
    cosine_similarity,
    euclidean_distance,
    match_against_watchlist,
)


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def synthetic_high_l_glare_image():
    """
    Creates a synthetic image with dark ambient background (L ~40)
    and an intense specular glare hotspot where L > 230 (L = 255).
    """
    # 200x200 BGR image with dark background
    img = np.full((200, 200, 3), 40, dtype=np.uint8)

    # Insert headlight bloom circle where intensity is 255 (L = 255 in LAB)
    cv2.circle(img, (100, 100), 30, (255, 255, 255), -1)
    return img


@pytest.fixture
def synthetic_watchlist_rows():
    """
    Mock database rows simulating public.egujcop_watchlist table
    with unit L2-normalized 512-d embeddings.
    """
    rng = np.random.RandomState(42)
    rows = []
    plates = ["GJ01AB1234", "GJ05CD5678", "GJ06EF9012", "GJ27XY9999"]
    makes = ["Maruti Suzuki", "Mahindra", "Hyundai", "Toyota"]
    models = ["Swift Dzire", "Scorpio-N", "Creta", "Fortuner"]
    colors = ["White", "Black", "Red", "Blue"]

    for i, (p, m, mod, c) in enumerate(zip(plates, makes, models, colors), 1):
        raw_vec = rng.randn(512).astype(np.float32)
        norm_vec = raw_vec / np.linalg.norm(raw_vec)
        rows.append({
            "id": i,
            "license_plate": p,
            "vehicle_make": m,
            "vehicle_model": mod,
            "vehicle_color": c,
            "owner_name": f"Owner {i}",
            "category": "STOLEN" if i <= 2 else "WANTED",
            "severity": "CRITICAL" if i == 1 else "HIGH",
            "notes": f"FIR Ref {100 + i}",
            "embedding": norm_vec.tolist(),
        })
    return rows


# ==============================================================================
# 1. GLARE ATTENUATION ON SYNTHETIC HIGH-L TEST IMAGE
# ==============================================================================

def test_glare_attenuation_on_synthetic_high_l_image(synthetic_high_l_glare_image):
    """
    Verify NightGlarePreprocessor detects pixels where L > 230 and applies
    localized Gaussian attenuation to soften glare without flattening the rest of the image.
    """
    preprocessor = NightGlarePreprocessor(glare_threshold=230, glare_attenuation_factor=0.45)

    # Check initial L value at the glare center (100, 100)
    initial_lab = cv2.cvtColor(synthetic_high_l_glare_image, cv2.COLOR_BGR2LAB)
    initial_l_center = initial_lab[100, 100, 0]
    initial_l_bg = initial_lab[20, 20, 0]
    assert initial_l_center > 230, f"Expected initial L > 230, got {initial_l_center}"

    # Run preprocessor
    processed_bgr = preprocessor.preprocess(synthetic_high_l_glare_image)

    # Check processed L values
    processed_lab = cv2.cvtColor(processed_bgr, cv2.COLOR_BGR2LAB)
    processed_l_center = processed_lab[100, 100, 0]
    processed_l_bg = processed_lab[20, 20, 0]

    # 1. Glare center must be attenuated
    assert processed_l_center < initial_l_center, "Specular glare was not attenuated"
    # 2. Glare center should be compressed significantly below saturation (255)
    assert processed_l_center < 220
    # 3. Ambient background must not be flattened (CLAHE recovers local shadow contrast)
    assert processed_l_bg >= initial_l_bg


# ==============================================================================
# 2. EMBEDDING SHAPE & UNIT L2-NORMALIZATION INVARIANTS
# ==============================================================================

def test_osnet_embedding_shape_and_l2_normalization():
    """Verify OSNet backbone outputs 512-d embeddings with ||v||_2 == 1.0."""
    model = OSNetReID(embedding_dim=512)
    model.eval()

    dummy_batch = torch.randn(2, 3, 256, 128)
    with torch.no_grad():
        embeddings = model(dummy_batch)

    assert embeddings.shape == (2, 512)
    for row in embeddings:
        l2_norm = torch.norm(row, p=2).item()
        assert abs(l2_norm - 1.0) < 1e-4, f"L2 norm invariant failed: {l2_norm}"


def test_resnet18_embedding_shape_and_l2_normalization():
    """Verify ResNet-18 backbone outputs 512-d embeddings with ||v||_2 == 1.0."""
    model = ResNet18ReID(embedding_dim=512, pretrained=False)
    model.eval()

    dummy_batch = torch.randn(2, 3, 256, 128)
    with torch.no_grad():
        embeddings = model(dummy_batch)

    assert embeddings.shape == (2, 512)
    for row in embeddings:
        l2_norm = torch.norm(row, p=2).item()
        assert abs(l2_norm - 1.0) < 1e-4, f"L2 norm invariant failed: {l2_norm}"


def test_vehicle_reid_engine_extract_embedding_invariant():
    """Verify VehicleReIDEngine.extract_embedding enforces 512-d unit vector invariant."""
    engine = VehicleReIDEngine(architecture="osnet", device="cpu")
    crop = np.random.randint(30, 200, (180, 120, 3), dtype=np.uint8)

    emb = engine.extract_embedding(crop)
    assert isinstance(emb, np.ndarray)
    assert emb.shape == (512,)
    assert emb.dtype == np.float32
    norm = float(np.linalg.norm(emb))
    assert abs(norm - 1.0) < 1e-4, f"Unit norm failed: {norm}"


# ==============================================================================
# 3. VECTOR SIMILARITY & DISTANCE METRICS
# ==============================================================================

def test_similarity_metric_invariants():
    """Verify Cosine and Euclidean mathematical relationships on unit vectors."""
    v1 = np.zeros(512, dtype=np.float32)
    v2 = np.zeros(512, dtype=np.float32)
    v1[0] = 1.0
    v2[0] = 1.0

    # Identical vectors
    assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-5
    assert abs(euclidean_distance(v1, v2) - 0.0) < 1e-5

    # Orthogonal vectors
    v2[0] = 0.0
    v2[1] = 1.0
    assert abs(cosine_similarity(v1, v2) - 0.0) < 1e-5
    assert abs(euclidean_distance(v1, v2) - math.sqrt(2.0)) < 1e-4


# ==============================================================================
# 4. MATCHING THRESHOLD BEHAVIOR WITH SYNTHETIC FIXTURES
# ==============================================================================

@pytest.mark.asyncio
async def test_match_against_watchlist_threshold_and_ranking(synthetic_watchlist_rows):
    """
    Verify match_against_watchlist filters out candidates below threshold (0.75),
    retains candidates above threshold, and ranks them descending by similarity.
    Uses mocked database connection with synthetic fixtures (no real DB required).
    """
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = synthetic_watchlist_rows

    # Candidate 0 vector
    cand_0_vec = np.array(synthetic_watchlist_rows[0]["embedding"], dtype=np.float32)
    # Candidate 1 vector
    cand_1_vec = np.array(synthetic_watchlist_rows[1]["embedding"], dtype=np.float32)

    # Construct query vector:
    # Blend 85% of cand_0 + 15% of cand_1 -> will have ~0.85 similarity to cand_0
    query_vec = 0.85 * cand_0_vec + 0.15 * cand_1_vec
    query_vec /= np.linalg.norm(query_vec)

    # 1. Query with default threshold 0.75
    results = await match_against_watchlist(
        embedding=query_vec,
        threshold=0.75,
        conn=mock_conn,
    )

    # Must return matched candidate(s)
    assert len(results) >= 1
    # Candidate 0 must be the top ranked match
    top = results[0]
    assert top["license_plate"] == synthetic_watchlist_rows[0]["license_plate"]
    assert top["similarity"] >= 0.75
    assert top["severity"] == "CRITICAL"

    # Verify descending sort order
    for i in range(1, len(results)):
        assert results[i - 1]["similarity"] >= results[i]["similarity"]


@pytest.mark.asyncio
async def test_match_against_watchlist_rejects_below_threshold(synthetic_watchlist_rows):
    """
    Verify match_against_watchlist returns empty list when no candidate
    reaches the similarity threshold.
    """
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = synthetic_watchlist_rows

    # Create a random orthogonal query vector
    rng = np.random.RandomState(999)
    random_vec = rng.randn(512).astype(np.float32)
    random_vec /= np.linalg.norm(random_vec)

    # High threshold (0.80) should reject random unrelated vectors
    results = await match_against_watchlist(
        embedding=random_vec,
        threshold=0.80,
        conn=mock_conn,
    )

    assert len(results) == 0
