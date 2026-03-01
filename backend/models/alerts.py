"""Alert & Anomaly Data Models"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class AlertSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertCategory(str, Enum):
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    PRODUCTION = "PRODUCTION"
    FOOT_TRAFFIC = "FOOT_TRAFFIC"
    LOGISTICS = "LOGISTICS"
    CORPORATE_ACTIVITY = "CORPORATE_ACTIVITY"
    GEOPOLITICAL = "GEOPOLITICAL"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    THESIS_RISK = "THESIS_RISK"


class RecommendedAction(str, Enum):
    HOLD = "HOLD"
    SIZE_UP = "SIZE_UP"
    SIZE_DOWN = "SIZE_DOWN"
    EXIT = "EXIT"
    MONITOR = "MONITOR"
    HEDGE = "HEDGE"


class AnomalyDetection(BaseModel):
    """Raw anomaly detected by the Consensus Vision Agent."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    geo_target_id: str
    sensor_type: str
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    anomaly_type: str  # e.g., "vehicle_count_drop", "thermal_reduction", "ship_backlog"
    magnitude: float  # percentage change
    raw_values: dict = Field(default_factory=dict)  # e.g., {"model_a": 400, "model_b": 410, "model_c": 395}
    consensus_score: float = 0.0  # 0 to 1
    models_agreed: int = 0
    models_total: int = 3
    human_review_required: bool = False


class QuantBacktest(BaseModel):
    """Financial materiality analysis from the Quant Regression Agent."""
    anomaly_id: str
    ticker: str
    r_squared: float = 0.0
    historical_correlation: float = 0.0
    predicted_price_impact_pct: float = 0.0
    prediction_window_days: int = 14
    sample_size: int = 0
    is_material: bool = False  # True if r_squared > threshold
    backtest_details: dict = Field(default_factory=dict)


class OmnichannelAdjustment(BaseModel):
    """E-commerce / digital revenue adjustment from RAG Agent."""
    ticker: str
    physical_revenue_pct: float = 100.0
    digital_revenue_pct: float = 0.0
    digital_trend: Optional[str] = None  # "growing", "stable", "declining"
    adjusted_severity: Optional[AlertSeverity] = None
    adjustment_rationale: str = ""
    sec_filing_source: Optional[str] = None  # Which 10-K was referenced


class SentinelAlert(BaseModel):
    """The final alert delivered to the PM. Fully enriched and compliance-logged."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Position context
    ticker: str
    position_side: str
    shares: int = 0

    # Alert content
    title: str
    summary: str  # Natural language memo
    severity: AlertSeverity = AlertSeverity.MEDIUM
    category: AlertCategory = AlertCategory.PRODUCTION
    confidence_score: float = 0.0  # 0 to 1

    # Geo context
    latitude: float = 0.0
    longitude: float = 0.0
    location_name: str = ""

    # Agent outputs
    anomaly: Optional[AnomalyDetection] = None
    backtest: Optional[QuantBacktest] = None
    omnichannel: Optional[OmnichannelAdjustment] = None

    # Recommendation
    recommended_action: RecommendedAction = RecommendedAction.MONITOR
    action_rationale: str = ""

    # Compliance
    compliance_hash: Optional[str] = None
    data_sources: list[str] = Field(default_factory=list)  # URLs/API receipts
    is_osint_verified: bool = True

    # UI
    camera_target: Optional[dict] = None  # {lat, lon, altitude, heading, pitch}
    visualization_mode: str = "default"  # default, flir, nvg, crt

    @property
    def is_actionable(self) -> bool:
        return self.confidence_score >= 0.75 and self.severity in [
            AlertSeverity.HIGH, AlertSeverity.CRITICAL
        ]
