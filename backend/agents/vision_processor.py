"""Vision Processor Agent - LPR and face detection pipeline.

Processes camera frames on-demand (not continuous streaming - too expensive).
Uses fast-alpr when installed, falls back to mock detections for demo.

Usage:
    processor = VisionProcessorAgent()
    result = await processor.analyze_frame(request)
"""
from __future__ import annotations
import asyncio
import base64
import time
import random
import httpx
from typing import Optional
from datetime import datetime

# Try importing fast-alpr (optional dependency)
try:
    from fast_alpr import ALPR
    _HAS_ALPR = True
except ImportError:
    _HAS_ALPR = False

# Try importing PIL for image handling
try:
    from PIL import Image
    import io
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from models.identifications import (
    PlateDetection, FaceDetection, FrameAnalysisRequest,
    FrameAnalysisResult, VehicleInfo, DetectionSource,
)
from data.plate_lookup import PlateLookupClient


# ── Mock detection helpers ────────────────────────────────────────────────────
_MOCK_PLATES = [
    "ABC1234", "XYZ9876", "7ABC234", "CAL8M95", "NY12345",
    "TX55678", "FLA3927", "WA10293", "CO48291", "IL76543",
]


def _mock_plate_detections(camera_id: Optional[str], lat: Optional[float], lon: Optional[float]) -> list[PlateDetection]:
    """Generate 0-2 mock plate detections seeded by camera_id."""
    seed = sum(ord(c) for c in (camera_id or "default"))
    rng = random.Random(seed + int(time.time() / 30))  # Changes every 30s
    n = rng.randint(0, 2)
    detections = []
    for i in range(n):
        plate = rng.choice(_MOCK_PLATES)
        detections.append(PlateDetection(
            plate_text=plate,
            confidence=round(rng.uniform(0.72, 0.98), 3),
            bounding_box={
                "x": rng.randint(50, 400),
                "y": rng.randint(50, 300),
                "width": rng.randint(80, 180),
                "height": rng.randint(25, 50),
            },
            camera_id=camera_id,
            latitude=lat,
            longitude=lon,
            source=DetectionSource.CAMERA_FEED,
            lookup_provider="mock",
        ))
    return detections


def _mock_face_detections(camera_id: Optional[str]) -> list[FaceDetection]:
    """Generate 0-1 mock face detections - intentionally rare."""
    seed = sum(ord(c) for c in (camera_id or "default"))
    rng = random.Random(seed + int(time.time() / 60))
    if rng.random() > 0.15:   # Only 15% of frames have a face
        return []
    return [FaceDetection(
        confidence=round(rng.uniform(0.55, 0.82), 3),
        bounding_box={"x": rng.randint(100, 500), "y": rng.randint(50, 200), "width": 64, "height": 80},
        quality_score=round(rng.uniform(18.0, 45.0), 1),
        camera_id=camera_id,
        source=DetectionSource.CAMERA_FEED,
        human_review_required=True,
        match_provider="mock",
    )]


class VisionProcessorAgent:
    """
    On-demand vision processing agent for LPR and face detection.

    Architecture:
      1. Fetch frame (URL or base64)
      2. Run LPR pipeline -> PlateDetection list
      3. Run face detection pipeline (if enabled) -> FaceDetection list
      4. Enrich plates with vehicle lookup
      5. Return FrameAnalysisResult
    """

    def __init__(self):
        self._alpr = None
        self._plate_client = PlateLookupClient()
        self._mock_mode = not _HAS_ALPR

        if _HAS_ALPR:
            try:
                self._alpr = ALPR()
            except Exception:
                self._mock_mode = True

    async def analyze_frame(self, request: FrameAnalysisRequest) -> FrameAnalysisResult:
        """Main entry point. Analyze a single frame for plates and/or faces."""
        start = time.monotonic()

        try:
            # Fetch image bytes if URL provided
            image_bytes: Optional[bytes] = None
            if request.image_url:
                image_bytes = await self._fetch_image(request.image_url)
            elif request.image_base64:
                image_bytes = base64.b64decode(request.image_base64)

            # Run LPR
            plates: list[PlateDetection] = []
            if request.run_lpr:
                plates = await self._run_lpr(image_bytes, request)
                # Enrich with vehicle info
                if plates:
                    plates = await self._enrich_plates(plates)

            # Run face detection
            faces: list[FaceDetection] = []
            if request.run_face_detection:
                faces = await self._run_face_detection(image_bytes, request)

            elapsed_ms = round((time.monotonic() - start) * 1000, 1)
            return FrameAnalysisResult(
                camera_id=request.camera_id,
                plates=plates,
                faces=faces,
                processing_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = round((time.monotonic() - start) * 1000, 1)
            return FrameAnalysisResult(
                camera_id=request.camera_id,
                error=str(e),
                processing_ms=elapsed_ms,
            )

    async def _fetch_image(self, url: str) -> Optional[bytes]:
        """Fetch image bytes from URL."""
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            return resp.content

    async def _run_lpr(self, image_bytes: Optional[bytes], request: FrameAnalysisRequest) -> list[PlateDetection]:
        """Run license plate recognition."""
        if self._mock_mode or image_bytes is None:
            return _mock_plate_detections(request.camera_id, request.latitude, request.longitude)

        # Real ALPR path (fast-alpr installed)
        try:
            import numpy as np
            if _HAS_PIL:
                img = Image.open(io.BytesIO(image_bytes))
                img_array = np.array(img)
            else:
                # Can't decode without PIL - fall back to mock
                return _mock_plate_detections(request.camera_id, request.latitude, request.longitude)

            # Run in thread pool (CPU-bound)
            loop = asyncio.get_event_loop()
            raw_results = await loop.run_in_executor(None, self._alpr.run, img_array)

            plates = []
            for r in (raw_results or []):
                plate_text = r.get("plate", "")
                confidence = r.get("score", 0.0)
                if plate_text and confidence >= 0.5:
                    plates.append(PlateDetection(
                        plate_text=plate_text.upper(),
                        confidence=confidence,
                        bounding_box=r.get("box"),
                        camera_id=request.camera_id,
                        camera_name=request.camera_name,
                        latitude=request.latitude,
                        longitude=request.longitude,
                        source=DetectionSource.CAMERA_FEED,
                    ))
            return plates

        except Exception:
            return _mock_plate_detections(request.camera_id, request.latitude, request.longitude)

    async def _run_face_detection(self, image_bytes: Optional[bytes], request: FrameAnalysisRequest) -> list[FaceDetection]:
        """Run face detection. Always mock in current implementation."""
        # CompreFace integration would go here (Phase 4)
        return _mock_face_detections(request.camera_id)

    async def _enrich_plates(self, plates: list[PlateDetection]) -> list[PlateDetection]:
        """Enrich plates with vehicle info via lookup API."""
        enriched = []
        for plate in plates:
            vehicle_data = await self._plate_client.lookup(plate.plate_text)
            plate.vehicle = VehicleInfo(
                make=vehicle_data.get("make"),
                model=vehicle_data.get("model"),
                color=vehicle_data.get("color"),
                year=vehicle_data.get("year"),
                vehicle_type=vehicle_data.get("vehicle_type"),
                region=vehicle_data.get("region"),
                raw=vehicle_data.get("raw", {}),
            )
            plate.lookup_provider = vehicle_data.get("provider", "unknown")
            enriched.append(plate)
        return enriched

    @property
    def is_mock(self) -> bool:
        return self._mock_mode

    def status(self) -> dict:
        return {
            "alpr_available": _HAS_ALPR,
            "mock_mode": self._mock_mode,
            "plate_lookup_mock": self._plate_client.is_mock,
            "pil_available": _HAS_PIL,
        }
