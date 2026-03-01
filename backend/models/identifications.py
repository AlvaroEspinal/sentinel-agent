"""Vision Intelligence Data Models - LPR & Face Detection"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class DetectionSource(str, Enum):
    CAMERA_FEED = "CAMERA_FEED"
    UPLOADED_FRAME = "UPLOADED_FRAME"
    PROXY_SNAPSHOT = "PROXY_SNAPSHOT"


class VehicleInfo(BaseModel):
    """Vehicle metadata returned by Plate Recognizer or similar lookup API."""
    make: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    year: Optional[int] = None
    vehicle_type: Optional[str] = None   # car, truck, motorcycle, bus
    region: Optional[str] = None          # state/region code
    vin: Optional[str] = None
    raw: dict = Field(default_factory=dict)


class PlateDetection(BaseModel):
    """A single license plate detection event from a camera frame."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    detected_at: datetime = Field(default_factory=datetime.utcnow)

    # Plate text
    plate_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    bounding_box: Optional[dict] = None    # {x, y, width, height} in pixels

    # Source
    camera_id: Optional[str] = None
    camera_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: DetectionSource = DetectionSource.CAMERA_FEED

    # Vehicle info (from lookup API)
    vehicle: Optional[VehicleInfo] = None
    lookup_provider: Optional[str] = None  # "plate_recognizer", "mock"

    # Flags
    is_on_watchlist: bool = False
    human_review_required: bool = False
    alert_generated: bool = False

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.85

    @property
    def display_label(self) -> str:
        parts = [self.plate_text]
        if self.vehicle and self.vehicle.make:
            parts.append(f"{self.vehicle.year or ''} {self.vehicle.make} {self.vehicle.model or ''}".strip())
        return " | ".join(parts)


class FaceDetection(BaseModel):
    """A single face detection event from a camera frame."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    detected_at: datetime = Field(default_factory=datetime.utcnow)

    # Detection
    confidence: float = Field(ge=0.0, le=1.0)
    bounding_box: Optional[dict] = None    # {x, y, width, height}
    embedding: Optional[list[float]] = None  # 512-dim ArcFace embedding
    quality_score: Optional[float] = None    # pixel gap between eyes

    # Source
    camera_id: Optional[str] = None
    camera_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: DetectionSource = DetectionSource.CAMERA_FEED

    # Match result
    matched_subject_id: Optional[str] = None
    match_confidence: Optional[float] = None
    match_provider: Optional[str] = None    # "compreface", "faiss", "mock"

    # Compliance
    is_on_watchlist: bool = False
    human_review_required: bool = True      # Always true per compliance policy
    jurisdiction_compliant: bool = True

    @property
    def meets_quality_threshold(self) -> bool:
        """Reject frames with <32 pixels between eyes."""
        return self.quality_score is not None and self.quality_score >= 32.0


class FrameAnalysisRequest(BaseModel):
    """Request to analyze a single camera frame for LPR and/or face detection."""
    image_url: Optional[str] = None         # URL to fetch
    image_base64: Optional[str] = None      # Base64-encoded JPEG/PNG
    camera_id: Optional[str] = None
    camera_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    run_lpr: bool = True
    run_face_detection: bool = False         # Off by default (compliance)


class FrameAnalysisResult(BaseModel):
    """Result of analyzing a single camera frame."""
    camera_id: Optional[str] = None
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    plates: list[PlateDetection] = Field(default_factory=list)
    faces: list[FaceDetection] = Field(default_factory=list)
    processing_ms: Optional[float] = None
    error: Optional[str] = None

    @property
    def total_detections(self) -> int:
        return len(self.plates) + len(self.faces)
