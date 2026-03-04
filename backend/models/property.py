"""Property & Real Estate Data Models for Parcl Intelligence"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, date
from enum import Enum


class PropertyType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    MULTI_FAMILY = "MULTI_FAMILY"
    CONDO = "CONDO"
    TOWNHOUSE = "TOWNHOUSE"
    LAND = "LAND"
    COMMERCIAL = "COMMERCIAL"
    MIXED_USE = "MIXED_USE"
    OTHER = "OTHER"


class PermitStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    COMING_SOON = "COMING_SOON"


class AgentType(str, Enum):
    LISTING = "listing"
    NEIGHBORHOOD = "neighborhood"
    PORTFOLIO = "portfolio"
    DEVELOPMENT_SCOUT = "development_scout"
    CLIMATE_RISK = "climate_risk"
    MARKET_PULSE = "market_pulse"
    COMMUNITY_INTEL = "community_intel"


class AgentStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class FindingType(str, Enum):
    PERMIT_ACTIVITY = "PERMIT_ACTIVITY"
    PRICE_CHANGE = "PRICE_CHANGE"
    RISK_UPDATE = "RISK_UPDATE"
    CONSTRUCTION = "CONSTRUCTION"
    ZONING_CHANGE = "ZONING_CHANGE"
    LISTING_CHANGE = "LISTING_CHANGE"
    MARKET_SHIFT = "MARKET_SHIFT"
    MEETING_MENTION = "MEETING_MENTION"
    SATELLITE_CHANGE = "SATELLITE_CHANGE"
    CAMERA_ANOMALY = "CAMERA_ANOMALY"


class FindingSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ─── Risk Scores ──────────────────────────────────────────────────────────────
class RiskScores(BaseModel):
    """Climate and environmental risk scores for a property."""
    flood_risk: Optional[int] = None  # 1-10 scale
    fire_risk: Optional[int] = None
    heat_risk: Optional[int] = None
    wind_risk: Optional[int] = None
    environmental_risk: Optional[int] = None  # contamination proximity
    overall_risk: Optional[int] = None
    source: Optional[str] = None  # "first_street", "fema", etc.
    assessed_at: Optional[datetime] = None


# ─── Neighborhood Scores ──────────────────────────────────────────────────────
class NeighborhoodScores(BaseModel):
    """Walkability, transit, school, and demographic scores."""
    walk_score: Optional[int] = None
    transit_score: Optional[int] = None
    bike_score: Optional[int] = None
    school_rating: Optional[float] = None  # 1-10
    median_income: Optional[int] = None
    population_growth_pct: Optional[float] = None
    source: Optional[str] = None


# ─── Property ─────────────────────────────────────────────────────────────────
class Property(BaseModel):
    """Central entity: a physical real estate property."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    address: str
    normalized_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    latitude: float = 0.0
    longitude: float = 0.0
    parcel_id: Optional[str] = None

    # Physical attributes
    property_type: PropertyType = PropertyType.OTHER
    year_built: Optional[int] = None
    lot_size_sqft: Optional[float] = None
    living_area_sqft: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    zoning: Optional[str] = None

    # Valuation
    tax_assessment: Optional[float] = None
    last_sale_price: Optional[float] = None
    last_sale_date: Optional[date] = None
    estimated_value: Optional[float] = None

    # Enrichment
    risk_scores: Optional[RiskScores] = None
    neighborhood_scores: Optional[NeighborhoodScores] = None
    data_sources: list[str] = Field(default_factory=list)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Agents monitoring this property
    active_agents_count: int = 0
    nearby_permits_count: int = 0


# ─── Permit ───────────────────────────────────────────────────────────────────
class Permit(BaseModel):
    """A building/construction permit filed with a municipality."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    property_id: Optional[str] = None
    town_id: Optional[str] = None
    permit_number: Optional[str] = None
    permit_type: Optional[str] = None
    status: PermitStatus = PermitStatus.FILED
    estimated_value: Optional[float] = None
    description: Optional[str] = None
    applicant_name: Optional[str] = None
    contractor_name: Optional[str] = None
    address: Optional[str] = None
    latitude: float = 0.0
    longitude: float = 0.0
    filed_date: Optional[date] = None
    issued_date: Optional[date] = None
    completed_date: Optional[date] = None
    source_system: Optional[str] = None  # 'accela', 'opengov', 'boston'
    source_id: Optional[str] = None
    raw_data: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Listing ──────────────────────────────────────────────────────────────────
class Listing(BaseModel):
    """A property listing from MLS, Zillow, Realtor.com, etc."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    property_id: Optional[str] = None
    source: Optional[str] = None  # 'realtor', 'zillow', 'mls'
    mls_id: Optional[str] = None
    list_price: Optional[float] = None
    status: ListingStatus = ListingStatus.ACTIVE
    days_on_market: Optional[int] = None
    price_per_sqft: Optional[float] = None
    listing_url: Optional[str] = None
    agent_name: Optional[str] = None
    brokerage: Optional[str] = None
    listed_at: Optional[datetime] = None
    sold_at: Optional[datetime] = None
    sold_price: Optional[float] = None
    raw_data: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Property Agent ───────────────────────────────────────────────────────────
class PropertyAgent(BaseModel):
    """An AI monitoring agent bound to a property, neighborhood, or portfolio."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    entity_type: str = "property"  # 'property', 'neighborhood', 'portfolio'
    entity_id: Optional[str] = None  # property_id, area polygon hash, portfolio_id
    agent_type: AgentType = AgentType.LISTING
    name: str = ""
    config: dict = Field(default_factory=dict)  # monitoring radius, data sources, thresholds
    status: AgentStatus = AgentStatus.ACTIVE
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_interval_seconds: int = 300  # 5 minutes default
    findings_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Agent Finding ────────────────────────────────────────────────────────────
class AgentFinding(BaseModel):
    """A finding/alert generated by a monitoring agent."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    agent_id: str
    property_id: Optional[str] = None
    finding_type: FindingType = FindingType.PERMIT_ACTIVITY
    severity: FindingSeverity = FindingSeverity.INFO
    title: str
    summary: str = ""
    data: dict = Field(default_factory=dict)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    acknowledged: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_actionable(self) -> bool:
        return self.severity in [FindingSeverity.HIGH, FindingSeverity.CRITICAL]


# ─── Portfolio ────────────────────────────────────────────────────────────────
class Portfolio(BaseModel):
    """A collection of properties being monitored together."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    name: str
    description: Optional[str] = None
    properties: list[Property] = Field(default_factory=list)
    total_estimated_value: Optional[float] = None
    average_risk_score: Optional[float] = None
    active_agents_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Search / Query Models ───────────────────────────────────────────────────
class PropertySearchRequest(BaseModel):
    """Request to search for properties."""
    query: Optional[str] = None  # free text search
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_km: float = 1.0
    property_type: Optional[PropertyType] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    limit: int = 20


class PermitSearchRequest(BaseModel):
    """Request to search for permits."""
    query: Optional[str] = None
    address: Optional[str] = None
    town_id: Optional[str] = None
    permit_type: Optional[str] = None
    status: Optional[PermitStatus] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_km: float = 1.0
    filed_after: Optional[date] = None
    filed_before: Optional[date] = None
    min_value: Optional[float] = None
    limit: int = 20


class ChatRequest(BaseModel):
    """Request for RAG chat."""
    message: str
    property_id: Optional[str] = None
    context: Optional[str] = None  # additional context like selected area


class ChatResponse(BaseModel):
    """Response from RAG chat."""
    content: str
    sources: list[dict] = Field(default_factory=list)
    permits_found: int = 0
    properties_referenced: int = 0
    suggested_questions: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class AgentCreateRequest(BaseModel):
    """Request to create a new monitoring agent."""
    entity_type: str = "property"  # 'property', 'neighborhood', 'portfolio'
    entity_id: str  # property_id, area hash, portfolio_id
    agent_type: AgentType
    name: Optional[str] = None
    config: dict = Field(default_factory=dict)
    run_interval_seconds: int = 300
