"""
Sentinel Video Intelligence Platform — Gujarat Police CCTV Infrastructure
Module: edge/reid_engine.py
Description: Production-grade Vehicle Re-Identification (Re-ID) Engine.

Components:
1. NightGlarePreprocessor:
   - Converts frame to CIE LAB color space.
   - Identifies pixels where L > 230 (glare regions).
   - Applies localized Gaussian attenuation to soften glare in those regions without
     flattening the rest of the image.
   - Applies CLAHE (clipLimit=2.5) on the L channel for contrast recovery.
   - Applies bilateral filtering (edge-preserving smoothing) as a final denoise pass.
   - Returns the reconstructed BGR frame.
2. Deep Feature Extraction:
   - Supports two backbone options behind a common interface: OSNet and ResNet-18
     (torchvision baseline with hook for loading fine-tuned weights).
   - Generates 512-dimensional embeddings.
   - Strictly enforces unit L2 normalization (||v||_2 == 1.0 within floating tolerance).
3. Matching Engine:
   - Cosine similarity and Euclidean distance functions.
   - match_against_watchlist(embedding, threshold=0.75): queries public.egujcop_watchlist
     (PostGIS, asyncpg) and returns candidates above the similarity threshold, ranked descending.

NOTE ON ASYNC USAGE:
VehicleReIDEngine.match_crop_against_watchlist is a coroutine and must be awaited
from within an existing event loop (e.g. a FastAPI request handler or the async
event worker). Do not wrap it in asyncio.run() from an already-async context --
that raises RuntimeError('asyncio.run() cannot be called from a running event
loop'). The only place asyncio.run() belongs in this module is the synchronous
CLI entrypoint in main().
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger("sentinel.edge.reid_engine")


# ==============================================================================
# 1. NIGHT GLARE PREPROCESSOR CLASS
# ==============================================================================

class NightGlarePreprocessor:
    """
    Adaptive low-light and night operations pre-processing:
    - Converts frame to CIE LAB color space.
    - Identifies pixels where L > 230 (glare regions).
    - Applies localized Gaussian attenuation to soften glare in those regions without
      flattening the rest of the image.
    - Applies CLAHE (clipLimit=2.5) on the L channel for contrast recovery.
    - Applies bilateral filtering (edge-preserving smoothing) as a final denoise pass.
    - Returns the reconstructed BGR frame.
    """

    def __init__(
        self,
        glare_threshold: int = 230,
        glare_attenuation_factor: float = 0.45,
        clahe_clip_limit: float = 2.5,
        clahe_tile_grid: Tuple[int, int] = (8, 8),
        bilateral_d: int = 5,
        bilateral_sigma_color: float = 35.0,
        bilateral_sigma_space: float = 35.0,
    ) -> None:
        self.glare_threshold = glare_threshold
        self.glare_attenuation_factor = glare_attenuation_factor
        self.clahe_clip_limit = clahe_clip_limit
        self.clahe_tile_grid = clahe_tile_grid
        self.bilateral_d = bilateral_d
        self.bilateral_sigma_color = bilateral_sigma_color
        self.bilateral_sigma_space = bilateral_sigma_space

        self._clahe = cv2.createCLAHE(
            clipLimit=self.clahe_clip_limit,
            tileGridSize=self.clahe_tile_grid,
        )

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        """
        Executes the full 5-stage night pre-processing pipeline on input BGR frame.
        """
        if frame is None or frame.size == 0:
            raise ValueError("Input frame is None or empty.")

        # Stage 1: Convert frame to CIE LAB color space
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)

        # Stage 2: Identify pixels where L > 230 (glare regions)
        glare_mask = (l_channel > self.glare_threshold).astype(np.uint8) * 255

        # Stage 3: Apply localized Gaussian attenuation to soften glare
        if np.any(glare_mask):
            # Compute adaptive kernel size based on frame dimensions (odd integer >= 5)
            ksize = max(5, int(min(frame.shape[:2]) * 0.05) | 1)
            # Soft continuous attenuation weight map
            soft_glare_mask = cv2.GaussianBlur(
                glare_mask.astype(np.float32) / 255.0,
                (ksize, ksize),
                0,
            )
            # Localized attenuation: compress lightness only in glare regions
            l_float = l_channel.astype(np.float32)
            attenuated_l = l_float * (1.0 - self.glare_attenuation_factor * soft_glare_mask)
            l_channel = np.clip(attenuated_l, 0, 255).astype(np.uint8)

        # Stage 4: Apply CLAHE (clipLimit=2.5) on the L channel for contrast recovery
        l_enhanced = self._clahe.apply(l_channel)

        # Recombine LAB channels
        lab_enhanced = cv2.merge([l_enhanced, a_channel, b_channel])

        # Stage 5: Apply bilateral filtering (edge-preserving smoothing) as final denoise pass
        denoised_lab = cv2.bilateralFilter(
            lab_enhanced,
            d=self.bilateral_d,
            sigmaColor=self.bilateral_sigma_color,
            sigmaSpace=self.bilateral_sigma_space,
        )

        # Stage 6: Return reconstructed BGR frame
        reconstructed_bgr = cv2.cvtColor(denoised_lab, cv2.COLOR_LAB2BGR)
        return reconstructed_bgr


# ==============================================================================
# 2. DEEP FEATURE EXTRACTION BACKBONES (OSNet & ResNet-18)
# ==============================================================================

class ConvBlock(nn.Module):
    """Convolution + BatchNorm + ReLU building block."""

    def __init__(self, in_c: int, out_c: int, k: int, s: int = 1, p: int = 0):
        super().__init__()
        self.conv = nn.Conv2d(in_c, out_c, k, stride=s, padding=p, bias=False)
        self.bn = nn.BatchNorm2d(out_c)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.relu(self.bn(self.conv(x)))


class OSBlock(nn.Module):
    """Omni-Scale Learning Block with dynamic Aggregation Gate (AG)."""

    def __init__(self, in_c: int, out_c: int):
        super().__init__()
        mid_c = out_c // 4

        self.stream1 = ConvBlock(in_c, mid_c, k=1)
        self.stream2 = nn.Sequential(
            ConvBlock(in_c, mid_c, k=1),
            ConvBlock(mid_c, mid_c, k=3, p=1),
        )
        self.stream3 = nn.Sequential(
            ConvBlock(in_c, mid_c, k=1),
            ConvBlock(mid_c, mid_c, k=3, p=1),
            ConvBlock(mid_c, mid_c, k=3, p=1),
        )
        self.stream4 = nn.Sequential(
            ConvBlock(in_c, mid_c, k=1),
            ConvBlock(mid_c, mid_c, k=3, p=1),
            ConvBlock(mid_c, mid_c, k=3, p=1),
            ConvBlock(mid_c, mid_c, k=3, p=1),
        )

        self.gate = nn.Sequential(
            nn.Conv2d(mid_c, mid_c, kernel_size=1, bias=False),
            nn.BatchNorm2d(mid_c),
            nn.Sigmoid(),
        )
        self.conv1x1 = ConvBlock(mid_c, out_c, k=1)
        self.shortcut = nn.Identity() if in_c == out_c else ConvBlock(in_c, out_c, k=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        s1 = self.stream1(x)
        s2 = self.stream2(x)
        s3 = self.stream3(x)
        s4 = self.stream4(x)
        stream_sum = s1 + s2 + s3 + s4
        gated = stream_sum * self.gate(stream_sum)
        return self.conv1x1(gated) + self.shortcut(x)


class OSNetReID(nn.Module):
    """
    Lightweight OSNet architecture outputting 512-dimensional embeddings.
    """

    def __init__(self, embedding_dim: int = 512):
        super().__init__()
        self.embedding_dim = embedding_dim

        self.stem = nn.Sequential(
            ConvBlock(3, 64, k=7, s=2, p=3),
            nn.MaxPool2d(kernel_size=3, stride=2, padding=1),
        )
        self.stage1 = nn.Sequential(OSBlock(64, 128), OSBlock(128, 128))
        self.down1 = ConvBlock(128, 128, k=3, s=2, p=1)
        self.stage2 = nn.Sequential(OSBlock(128, 256), OSBlock(256, 256))
        self.down2 = ConvBlock(256, 256, k=3, s=2, p=1)
        self.stage3 = nn.Sequential(OSBlock(256, 384), OSBlock(384, 384))

        self.global_pool = nn.AdaptiveAvgPool2d((1, 1))
        self.head = nn.Sequential(
            nn.Linear(384, embedding_dim, bias=False),
            nn.BatchNorm1d(embedding_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.stem(x)
        feat = self.stage1(feat)
        feat = self.down1(feat)
        feat = self.stage2(feat)
        feat = self.down2(feat)
        feat = self.stage3(feat)
        pooled = self.global_pool(feat).flatten(1)
        raw_embed = self.head(pooled)
        return F.normalize(raw_embed, p=2, dim=-1)


class ResNet18ReID(nn.Module):
    """
    ResNet-18 Backbone modified for Re-ID with a 512-d bottleneck head.
    Supports ImageNet pretrained weights baseline and fine-tuned weight loading hook.
    """

    def __init__(self, embedding_dim: int = 512, pretrained: bool = True, weights_path: Optional[str] = None):
        super().__init__()
        self.embedding_dim = embedding_dim
        import torchvision.models as models

        weights = None
        if pretrained and weights_path is None:
            try:
                weights = models.ResNet18_Weights.DEFAULT
            except Exception:
                weights = None

        base = models.resnet18(weights=weights)
        self.conv1 = base.conv1
        self.bn1 = base.bn1
        self.relu = base.relu
        self.maxpool = base.maxpool
        self.layer1 = base.layer1
        self.layer2 = base.layer2
        self.layer3 = base.layer3
        self.layer4 = base.layer4
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))

        # 512-d embedding head
        self.head = nn.Sequential(
            nn.Linear(base.fc.in_features, embedding_dim, bias=False),
            nn.BatchNorm1d(embedding_dim),
        )

        # Hook for loading fine-tuned Re-ID weights
        if weights_path and Path(weights_path).exists():
            logger.info("Loading fine-tuned Re-ID weights from %s", weights_path)
            state = torch.load(weights_path, map_location="cpu")
            self.load_state_dict(state, strict=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)
        pooled = self.avgpool(x).flatten(1)
        raw_embed = self.head(pooled)
        return F.normalize(raw_embed, p=2, dim=-1)


# ==============================================================================
# 3. VECTOR SIMILARITY & DISTANCE METRICS
# ==============================================================================

def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """
    Computes Cosine Similarity between two feature vectors:
    cos_sim(u, v) = (u . v) / (||u|| * ||v||)
    For unit L2-normalized vectors, this equals the dot product dot(u, v).
    """
    u = v1.flatten().astype(np.float64)
    v = v2.flatten().astype(np.float64)
    norm_u = np.linalg.norm(u)
    norm_v = np.linalg.norm(v)
    if norm_u == 0.0 or norm_v == 0.0:
        return 0.0
    return float(np.dot(u, v) / (norm_u * norm_v))


def euclidean_distance(v1: np.ndarray, v2: np.ndarray) -> float:
    """
    Computes Euclidean (L2) Distance: ||u - v||_2.
    """
    u = v1.flatten().astype(np.float64)
    v = v2.flatten().astype(np.float64)
    return float(np.linalg.norm(u - v))


def cosine_distance(v1: np.ndarray, v2: np.ndarray) -> float:
    """Computes Cosine Distance: 1.0 - cosine_similarity(u, v)."""
    return float(1.0 - cosine_similarity(v1, v2))


# ==============================================================================
# 4. WATCHLIST MATCHING ENGINE (PostGIS & asyncpg)
# ==============================================================================

async def match_against_watchlist(
    embedding: np.ndarray,
    threshold: float = 0.75,
    db_url: Optional[str] = None,
    conn: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    Queries public.egujcop_watchlist (PostGIS, asyncpg) and returns candidates
    above the similarity threshold, ranked descending by similarity score.
    """
    target_vector = embedding.flatten().astype(np.float32)
    norm = np.linalg.norm(target_vector)
    if norm > 0:
        target_vector /= norm

    url = db_url or os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@127.0.0.1:5433/sentinel",
    )

    should_close = False
    if conn is None:
        import asyncpg
        conn = await asyncpg.connect(url)
        should_close = True

    try:
        rows = await conn.fetch("""
            SELECT id, license_plate, vehicle_make, vehicle_model, vehicle_color,
                   owner_name, category, severity, notes, embedding
            FROM public.egujcop_watchlist
            WHERE embedding IS NOT NULL;
        """)

        candidates: List[Dict[str, Any]] = []
        for r in rows:
            raw_emb = r["embedding"]
            if raw_emb is None:
                continue
            cand_vector = np.array(raw_emb, dtype=np.float32)
            sim = cosine_similarity(target_vector, cand_vector)
            dist_euc = euclidean_distance(target_vector, cand_vector)

            if sim >= threshold:
                candidates.append({
                    "id": r["id"],
                    "license_plate": r["license_plate"],
                    "vehicle_make": r["vehicle_make"],
                    "vehicle_model": r["vehicle_model"],
                    "vehicle_color": r["vehicle_color"],
                    "owner_name": r["owner_name"],
                    "category": r["category"],
                    "severity": r["severity"],
                    "notes": r["notes"],
                    "similarity": round(sim, 4),
                    "euclidean_distance": round(dist_euc, 4),
                })

        # Rank descending by cosine similarity
        candidates.sort(key=lambda x: x["similarity"], reverse=True)
        return candidates

    finally:
        if should_close:
            await conn.close()


# ==============================================================================
# 5. VEHICLE RE-ID ENGINE UNIFIED INTERFACE
# ==============================================================================

class VehicleReIDEngine:
    """
    Unified Vehicle Re-Identification Engine managing:
    - NightGlarePreprocessor
    - OSNet and ResNet-18 backbones
    - Unit L2-normalized 512-d embeddings
    - Watchlist candidate matching
    """

    def __init__(
        self,
        architecture: str = "osnet",
        embedding_dim: int = 512,
        device: Optional[str] = None,
        weights_path: Optional[str] = None,
        pretrained: bool = True,
        threshold: float = 0.75,
        db_url: Optional[str] = None,
    ) -> None:
        self.embedding_dim = embedding_dim
        self.threshold = threshold
        self.architecture_name = architecture.lower()
        self.db_url = db_url or os.getenv("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5433/sentinel")

        # Resolve compute device
        self.device = torch.device(device if device else ("cuda" if torch.cuda.is_available() else "cpu"))

        # Initialize requested backbone
        if self.architecture_name == "resnet18":
            self.model: nn.Module = ResNet18ReID(
                embedding_dim=self.embedding_dim,
                pretrained=pretrained,
                weights_path=weights_path,
            )
        else:
            self.model = OSNetReID(embedding_dim=self.embedding_dim)

        self.model.to(self.device)
        self.model.eval()

        self.preprocessor = NightGlarePreprocessor()

        # ImageNet normalization constants
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device).view(1, 3, 1, 1)

        logger.info(
            "VehicleReIDEngine active | Backbone: %s | Device: %s | Embedding Dim: %d",
            self.architecture_name.upper(),
            self.device,
            self.embedding_dim,
        )

    def extract_embedding(self, vehicle_crop: np.ndarray, apply_preprocessor: bool = True) -> np.ndarray:
        """
        Extracts an L2-normalized 512-d feature vector from vehicle crop.
        Strictly enforces unit norm: ||v||_2 == 1.0 within floating tolerance.

        This method is CPU/GPU-bound (torch inference) rather than I/O-bound,
        so it intentionally remains synchronous. It is safe to call from both
        sync and async contexts; if called from a hot async path at high
        throughput, consider offloading via loop.run_in_executor(...) to
        avoid blocking the event loop during inference.
        """
        if vehicle_crop is None or vehicle_crop.size == 0:
            raise ValueError("Vehicle crop is empty or None")

        # Stage 1: Night/Glare Pre-processing
        img = self.preprocessor.preprocess(vehicle_crop) if apply_preprocessor else vehicle_crop

        # Stage 2: Resize to standard (256x128)
        resized = cv2.resize(img, (128, 256), interpolation=cv2.INTER_LINEAR)

        # Stage 3: Tensor formatting & normalization
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        tensor = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).float().to(self.device) / 255.0
        tensor = (tensor - self.mean) / self.std

        # Stage 4: Neural inference
        with torch.no_grad():
            feat = self.model(tensor)
            feat = F.normalize(feat, p=2, dim=-1)

        embedding = feat.squeeze(0).cpu().numpy().astype(np.float32)

        # Enforce unit L2-normalization invariant
        norm = float(np.linalg.norm(embedding))
        if norm > 0:
            embedding /= norm
        assert abs(np.linalg.norm(embedding) - 1.0) < 1e-4, f"L2 normalization invariant violated: {norm}"

        return embedding

    async def match_crop_against_watchlist(
        self,
        vehicle_crop: np.ndarray,
        threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Async wrapper for match_against_watchlist.

        IMPORTANT: This is a coroutine and must be awaited from within an
        existing event loop (e.g. a FastAPI route handler, or the async
        event worker in the ingest pipeline). Do NOT call asyncio.run() on
        this from code that is already running inside an event loop --
        that raises:
            RuntimeError: asyncio.run() cannot be called from a running event loop

        For synchronous call sites (scripts, the CLI in this module),
        wrap the call in asyncio.run(...) at the outermost sync boundary
        only -- see main() below for the correct pattern.
        """
        emb = self.extract_embedding(vehicle_crop)
        t = threshold if threshold is not None else self.threshold
        try:
            return await match_against_watchlist(emb, threshold=t, db_url=self.db_url)
        except Exception as exc:
            logger.warning("Database watchlist query failed (%s); returning empty candidates.", exc)
            return []


# ==============================================================================
# 6. COMMAND-LINE INTERFACE
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinel Vehicle Re-ID Engine")
    parser.add_argument("--image", type=str, default=None, help="Vehicle crop image path")
    parser.add_argument("--compare", type=str, default=None, help="Second vehicle crop image path for pairwise metric")
    parser.add_argument("--architecture", type=str, default="osnet", choices=["osnet", "resnet18"])
    parser.add_argument("--threshold", type=float, default=0.75, help="Similarity threshold")
    parser.add_argument("--device", type=str, default=None, help="cpu or cuda")
    args = parser.parse_args()

    engine = VehicleReIDEngine(
        architecture=args.architecture,
        threshold=args.threshold,
        device=args.device,
    )

    if args.image and args.compare:
        im1 = cv2.imread(args.image)
        im2 = cv2.imread(args.compare)
        if im1 is None or im2 is None:
            print(f"Error reading comparison images: {args.image}, {args.compare}")
            sys.exit(1)

        e1 = engine.extract_embedding(im1)
        e2 = engine.extract_embedding(im2)
        sim = cosine_similarity(e1, e2)
        dist = euclidean_distance(e1, e2)

        print("=" * 65)
        print("SENTINEL RE-ID PAIRWISE COMPARISON")
        print(f"  Target 1:           {args.image}")
        print(f"  Target 2:           {args.compare}")
        print(f"  Cosine Similarity:  {sim:.4f} (Threshold: {args.threshold:.2f})")
        print(f"  Euclidean Distance: {dist:.4f}")
        print(f"  Decision:           {'MATCH' if sim >= args.threshold else 'NO MATCH'}")
        print("=" * 65)
        return

    if args.image:
        im = cv2.imread(args.image)
        if im is None:
            print(f"Error reading image: {args.image}")
            sys.exit(1)

        # main() is a synchronous entrypoint, so asyncio.run() is the correct
        # (and only) place in this module to drive the coroutine to completion.
        matches = asyncio.run(engine.match_crop_against_watchlist(im, threshold=args.threshold))
        print("=" * 65)
        print(f"SENTINEL WATCHLIST QUERY RESULT ({len(matches)} matches >= {args.threshold:.2f})")
        for m in matches:
            print(f"  - [{m['license_plate']}] {m['vehicle_make']} {m['vehicle_model']} ({m['vehicle_color']}) | Sim: {m['similarity']:.4f}")
        print("=" * 65)
        return

    # Self-test if invoked with no arguments
    synthetic = np.random.randint(20, 200, (256, 128, 3), dtype=np.uint8)
    emb = engine.extract_embedding(synthetic)
    print(f"Self-test successful | Extracted 512-d embedding with norm: {np.linalg.norm(emb):.6f}")


if __name__ == "__main__":
    main()