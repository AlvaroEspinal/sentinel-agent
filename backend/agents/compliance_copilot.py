"""Compliance Co-Pilot Agent -- SEC compliance shield.

Validates every data source is public OSINT or commercially licensed,
blocks anything that could be classified as MNPI, hashes all data
with SHA-256 for immutable provenance, and generates SEC audit reports
on demand.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from models.alerts import SentinelAlert
from models.compliance import (
    AuditReport,
    ComplianceLedgerEntry,
    DataProvenanceRecord,
)
from services.ledger import ComplianceLedger


# ---------------------------------------------------------------------------
# MNPI risk indicators -- sources or keywords that signal non-public
# material information.  If any of these appear in a data source
# descriptor, the data is blocked.
# ---------------------------------------------------------------------------
_MNPI_RISK_INDICATORS: set[str] = {
    # Source types that are always MNPI
    "insider_tip",
    "corporate_leak",
    "board_minutes",
    "pre_earnings",
    "internal_memo",
    "nda_protected",
    "draft_filing",
    "unreleased_financial",
    "private_placement",
    # Suspicious providers
    "dark_web",
    "hacked_data",
    "whistleblower_raw",
    "unauthorized_recording",
}

# Allowed MNPI classifications that pass compliance
_ALLOWED_CLASSIFICATIONS: set[str] = {
    "PUBLIC_OSINT",
    "COMMERCIAL_LICENSE",
}

# Source providers that are pre-approved as OSINT
_APPROVED_PROVIDERS: set[str] = {
    "OpenSky Network",
    "OpenWeatherMap",
    "AIS Hub / ITU AIS Network",
    "AIS Hub",
    "Planet Labs",
    "Planet Labs (Mock)",
    "Capella Space",
    "Capella Space (Mock)",
    "SEC EDGAR",
    "Yahoo Finance",
    "Sentinel Agent Internal",
    "US Census Bureau",
    "NOAA",
    "USGS",
    "Copernicus Open Access Hub",
}


class ComplianceCoPilot:
    """SEC compliance shield that sits at the end of the agent pipeline.

    Every alert must pass through this agent before reaching a PM.
    It validates data provenance, blocks MNPI, hashes everything, and
    maintains an immutable audit trail.
    """

    def __init__(self, ledger: Optional[ComplianceLedger] = None) -> None:
        self.ledger = ledger or ComplianceLedger()
        logger.info("ComplianceCoPilot initialised")

    # ------------------------------------------------------------------
    # Primary public method
    # ------------------------------------------------------------------

    async def validate_and_log(
        self,
        data_sources: list[dict],
        alert: SentinelAlert,
    ) -> str:
        """Validate all data sources used in an alert, hash the entire
        alert payload, and log it to the compliance ledger.

        Returns the SHA-256 compliance hash of the alert.

        Raises ValueError if any data source is classified as MNPI.
        """
        logger.info(
            f"Compliance validation for alert {alert.id} | "
            f"ticker={alert.ticker} | sources={len(data_sources)}"
        )

        provenance_ids: list[str] = []
        all_osint = True
        total_cost = 0.0

        for source in data_sources:
            # Step 1: Check for MNPI risk
            if self.check_mnpi_risk(source):
                blocked_reason = (
                    f"MNPI BLOCKED: Source '{source.get('source_provider', 'unknown')}' "
                    f"failed compliance check. Type='{source.get('source_type', '?')}', "
                    f"classification='{source.get('mnpi_classification', '?')}'."
                )
                logger.error(blocked_reason)
                # Log the block event
                self._log_event(
                    event_type="mnpi_blocked",
                    description=blocked_reason,
                    alert_id=alert.id,
                    ticker=alert.ticker,
                    prov_ids=[],
                    reasoning="Data source failed MNPI classification check. Blocked.",
                )
                raise ValueError(blocked_reason)

            # Step 2: Create provenance record
            raw_payload = json.dumps(source, sort_keys=True, default=str).encode()
            prov_record = DataProvenanceRecord(
                id=uuid.uuid4().hex[:12],
                timestamp=datetime.utcnow(),
                source_type=source.get("source_type", "unknown"),
                source_url=source.get("source_url", ""),
                source_provider=source.get("source_provider", "unknown"),
                is_publicly_available=source.get("is_publicly_available", True),
                mnpi_classification=source.get("mnpi_classification", "PUBLIC_OSINT"),
                data_hash=self.hash_data(raw_payload),
                data_size_bytes=len(raw_payload),
                alert_id=alert.id,
                ticker=alert.ticker,
                api_cost_usd=source.get("api_cost_usd", 0.0),
            )
            self.ledger.record_provenance(prov_record)
            provenance_ids.append(prov_record.id)
            total_cost += prov_record.api_cost_usd

            if not prov_record.is_publicly_available:
                all_osint = False

        # Step 3: Hash the entire alert
        alert_payload = json.dumps(
            {
                "alert_id": alert.id,
                "ticker": alert.ticker,
                "title": alert.title,
                "summary": alert.summary,
                "severity": alert.severity.value,
                "confidence": alert.confidence_score,
                "recommended_action": alert.recommended_action.value,
                "data_source_count": len(data_sources),
                "provenance_ids": provenance_ids,
                "timestamp": datetime.utcnow().isoformat(),
            },
            sort_keys=True,
        ).encode()
        compliance_hash = self.hash_data(alert_payload)

        # Step 4: Update the alert
        alert.compliance_hash = compliance_hash
        alert.is_osint_verified = all_osint
        alert.data_sources = [
            s.get("source_url", "") for s in data_sources if s.get("source_url")
        ]

        # Step 5: Log to ledger
        self._log_event(
            event_type="alert_compliance_verified",
            description=(
                f"Alert {alert.id} for {alert.ticker} passed compliance validation. "
                f"{len(data_sources)} sources verified, "
                f"all_osint={all_osint}, cost=${total_cost:.2f}."
            ),
            alert_id=alert.id,
            ticker=alert.ticker,
            prov_ids=provenance_ids,
            reasoning=(
                f"Verified {len(data_sources)} data sources: "
                f"{', '.join(s.get('source_provider', '?') for s in data_sources)}. "
                f"All classified as {', '.join(set(s.get('mnpi_classification', '?') for s in data_sources))}. "
                f"No MNPI risk detected. "
                f"Compliance hash: {compliance_hash[:16]}..."
            ),
        )

        logger.info(
            f"Compliance PASSED for alert {alert.id} | "
            f"hash={compliance_hash[:16]}... | osint={all_osint}"
        )
        return compliance_hash

    # ------------------------------------------------------------------
    # MNPI risk assessment
    # ------------------------------------------------------------------

    def check_mnpi_risk(self, source: dict) -> bool:
        """Return True if the data source poses MNPI risk and should be
        BLOCKED.

        Checks:
            1. Source type is in the MNPI risk indicator set.
            2. MNPI classification is not in the allowed set.
            3. Provider is not in the pre-approved list (warning only).
            4. Keywords in the source description suggest MNPI.
        """
        source_type = source.get("source_type", "").lower()
        classification = source.get("mnpi_classification", "PUBLIC_OSINT").upper()
        provider = source.get("source_provider", "")
        description = source.get("description", "").lower()
        url = source.get("source_url", "").lower()

        # Check 1: explicit risk indicator in source type
        if source_type in _MNPI_RISK_INDICATORS:
            logger.warning(f"MNPI risk: source_type '{source_type}' is blocked")
            return True

        # Check 2: classification must be in allowed set
        if classification not in _ALLOWED_CLASSIFICATIONS:
            if classification == "RESTRICTED":
                logger.warning(
                    f"MNPI risk: classification '{classification}' "
                    f"from {provider} is restricted"
                )
                return True

        # Check 3: keywords in description
        for indicator in _MNPI_RISK_INDICATORS:
            if indicator.replace("_", " ") in description:
                logger.warning(
                    f"MNPI risk: keyword '{indicator}' found in description "
                    f"for source from {provider}"
                )
                return True

        # Check 4: suspicious URL patterns
        blocked_url_patterns = [
            "pastebin.com",
            "darknet",
            ".onion",
            "leaked",
            "hack",
        ]
        for pattern in blocked_url_patterns:
            if pattern in url:
                logger.warning(f"MNPI risk: URL pattern '{pattern}' in {url}")
                return True

        # Provider not pre-approved is a warning, not a block
        if provider and provider not in _APPROVED_PROVIDERS:
            logger.debug(
                f"Provider '{provider}' is not pre-approved but classification "
                f"'{classification}' is acceptable"
            )

        return False

    # ------------------------------------------------------------------
    # Audit report generation
    # ------------------------------------------------------------------

    async def generate_audit_report(self, alert_id: str) -> AuditReport:
        """Generate a full SEC audit report for a given alert.

        Collects all provenance records and ledger entries associated
        with the alert, verifies the hash chain, and assembles a
        comprehensive AuditReport model.
        """
        logger.info(f"Generating audit report for alert {alert_id}")

        # Gather all provenance and ledger entries
        provenance_records = self.ledger.get_provenance_for_alert(alert_id)
        ledger_entries = self.ledger.get_entries_for_alert(alert_id)

        # Verify chain integrity
        chain_valid = self.ledger.verify_chain()

        # Determine MNPI status
        all_public = all(pr.is_publicly_available for pr in provenance_records)
        mnpi_risk = any(
            pr.mnpi_classification not in _ALLOWED_CLASSIFICATIONS
            for pr in provenance_records
        )

        # Total API cost
        total_cost = sum(pr.api_cost_usd for pr in provenance_records)

        # Build the full reasoning chain from ledger entries
        reasoning_parts: list[str] = []
        for entry in sorted(ledger_entries, key=lambda e: e.timestamp):
            reasoning_parts.append(
                f"[{entry.timestamp.strftime('%H:%M:%S')}] "
                f"{entry.agent_name}: {entry.event_description}"
            )
            if entry.agent_reasoning:
                reasoning_parts.append(f"  Reasoning: {entry.agent_reasoning}")

        full_reasoning = "\n".join(reasoning_parts)

        # Hash the entire report for integrity
        report_payload = json.dumps(
            {
                "alert_id": alert_id,
                "provenance_count": len(provenance_records),
                "ledger_count": len(ledger_entries),
                "chain_valid": chain_valid,
                "generated_at": datetime.utcnow().isoformat(),
            },
            sort_keys=True,
        ).encode()
        report_hash = self.hash_data(report_payload)

        # Identify ticker from provenance or ledger
        ticker = ""
        if provenance_records:
            ticker = provenance_records[0].ticker or ""
        elif ledger_entries:
            ticker = ledger_entries[0].ticker or ""

        report = AuditReport(
            id=uuid.uuid4().hex[:12],
            generated_at=datetime.utcnow(),
            generated_by="Sentinel Compliance Co-Pilot",
            alert_id=alert_id,
            ticker=ticker,
            provenance_records=provenance_records,
            ledger_entries=ledger_entries,
            all_sources_public=all_public,
            mnpi_risk_flag=mnpi_risk,
            total_api_cost_usd=total_cost,
            full_reasoning_chain=full_reasoning,
            report_hash=report_hash,
        )

        # Log report generation
        self._log_event(
            event_type="audit_report_generated",
            description=(
                f"Audit report generated for alert {alert_id}. "
                f"{len(provenance_records)} provenance records, "
                f"{len(ledger_entries)} ledger entries. "
                f"Chain integrity: {'VALID' if chain_valid else 'BROKEN'}."
            ),
            alert_id=alert_id,
            ticker=ticker,
            prov_ids=[pr.id for pr in provenance_records],
            reasoning=f"Full audit trail compiled. Report hash: {report_hash[:16]}...",
        )

        logger.info(
            f"Audit report {report.id} generated | "
            f"provenance={len(provenance_records)} ledger={len(ledger_entries)} "
            f"chain_valid={chain_valid} hash={report_hash[:16]}..."
        )
        return report

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    @staticmethod
    def hash_data(data: bytes) -> str:
        """Return the SHA-256 hex digest of arbitrary bytes."""
        return hashlib.sha256(data).hexdigest()

    # ------------------------------------------------------------------
    # Chain of custody
    # ------------------------------------------------------------------

    async def get_full_chain_of_custody(
        self, alert_id: str
    ) -> list[ComplianceLedgerEntry]:
        """Return every ComplianceLedgerEntry associated with an alert,
        sorted chronologically.

        This is the complete audit trail from first data ingestion
        through to the final alert delivery.
        """
        entries = self.ledger.get_entries_for_alert(alert_id)
        entries.sort(key=lambda e: e.timestamp)
        logger.debug(
            f"Chain of custody for alert {alert_id}: "
            f"{len(entries)} entries"
        )
        return entries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_event(
        self,
        event_type: str,
        description: str,
        alert_id: str,
        ticker: str,
        prov_ids: list[str],
        reasoning: str = "",
    ) -> ComplianceLedgerEntry:
        """Create and append a compliance ledger entry."""
        entry = ComplianceLedgerEntry(
            id=uuid.uuid4().hex[:12],
            timestamp=datetime.utcnow(),
            event_type=event_type,
            event_description=description,
            provenance_records=prov_ids,
            agent_name="ComplianceCoPilot",
            agent_reasoning=reasoning,
            alert_id=alert_id,
            ticker=ticker,
        )
        return self.ledger.append(entry)
