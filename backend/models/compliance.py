"""Compliance & Audit Trail Models"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DataProvenanceRecord(BaseModel):
    """Immutable record of every data point ingested."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Source identification
    source_type: str  # "api", "satellite", "adsb", "ais", "cctv", "sec_filing"
    source_url: str  # The exact public URL or API endpoint
    source_provider: str  # e.g., "OpenSky Network", "Planet Labs", "SEC EDGAR"

    # Data classification
    is_publicly_available: bool = True
    mnpi_classification: str = "PUBLIC_OSINT"  # PUBLIC_OSINT, COMMERCIAL_LICENSE, RESTRICTED
    commercial_license_id: Optional[str] = None

    # Content hash
    data_hash: str = ""  # SHA-256 of the raw data payload
    data_size_bytes: int = 0

    # Linking
    alert_id: Optional[str] = None
    geo_target_id: Optional[str] = None
    ticker: Optional[str] = None

    # API receipt
    api_request_id: Optional[str] = None
    api_cost_usd: float = 0.0


class ComplianceLedgerEntry(BaseModel):
    """An entry in the immutable compliance ledger."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Event
    event_type: str  # "data_ingestion", "alert_generated", "trade_recommendation", "audit_export"
    event_description: str

    # Chain of custody
    previous_hash: str = ""
    entry_hash: str = ""

    # Data provenance
    provenance_records: list[str] = Field(default_factory=list)  # IDs of DataProvenanceRecords

    # Agent chain of thought
    agent_reasoning: str = ""  # The LLM's chain-of-thought that led to the conclusion
    agent_name: str = ""  # Which agent generated this

    # Alert reference
    alert_id: Optional[str] = None
    ticker: Optional[str] = None


class AuditReport(BaseModel):
    """SEC Audit Report generated on demand."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generated_by: str = "Sentinel Compliance Co-Pilot"

    # Scope
    alert_id: str
    ticker: str
    trade_date: Optional[datetime] = None
    trade_action: Optional[str] = None  # "BUY", "SELL", "SHORT"

    # Data provenance chain
    provenance_records: list[DataProvenanceRecord] = Field(default_factory=list)
    ledger_entries: list[ComplianceLedgerEntry] = Field(default_factory=list)

    # Verification
    all_sources_public: bool = True
    mnpi_risk_flag: bool = False
    total_api_cost_usd: float = 0.0

    # Agent reasoning chain
    full_reasoning_chain: str = ""

    # Output
    pdf_path: Optional[str] = None
    report_hash: str = ""  # SHA-256 of the full report
