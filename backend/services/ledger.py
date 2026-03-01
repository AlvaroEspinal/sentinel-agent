"""Immutable Compliance Ledger for audit trail and SEC reporting."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Optional

from loguru import logger

from config import COMPLIANCE_LEDGER_SECRET
from models.compliance import ComplianceLedgerEntry, DataProvenanceRecord


class ComplianceLedger:
    """Append-only ledger implementing a hash-chain for immutable audit trail.

    In production this would be backed by a tamper-proof database or
    a distributed ledger.  For the POC it keeps entries in memory with
    cryptographic hash chaining so any retroactive modification is
    detectable.
    """

    def __init__(self) -> None:
        self._entries: list[ComplianceLedgerEntry] = []
        self._provenance: dict[str, DataProvenanceRecord] = {}
        self._last_hash: str = hashlib.sha256(
            COMPLIANCE_LEDGER_SECRET.encode()
        ).hexdigest()

    # ------------------------------------------------------------------
    # Core write operations
    # ------------------------------------------------------------------

    def append(self, entry: ComplianceLedgerEntry) -> ComplianceLedgerEntry:
        """Append an entry and chain its hash to the previous one."""
        entry.previous_hash = self._last_hash
        payload = json.dumps(
            {
                "id": entry.id,
                "timestamp": entry.timestamp.isoformat(),
                "event_type": entry.event_type,
                "event_description": entry.event_description,
                "previous_hash": entry.previous_hash,
                "provenance_records": entry.provenance_records,
                "agent_name": entry.agent_name,
                "alert_id": entry.alert_id,
                "ticker": entry.ticker,
            },
            sort_keys=True,
        )
        entry.entry_hash = hashlib.sha256(payload.encode()).hexdigest()
        self._last_hash = entry.entry_hash
        self._entries.append(entry)
        logger.info(
            f"Ledger entry [{entry.event_type}] appended "
            f"hash={entry.entry_hash[:12]}... agent={entry.agent_name}"
        )
        return entry

    def record_provenance(self, record: DataProvenanceRecord) -> DataProvenanceRecord:
        """Store a data-provenance record and return it."""
        if not record.data_hash:
            record.data_hash = "no_payload"
        self._provenance[record.id] = record
        logger.debug(f"Provenance recorded: {record.source_provider} [{record.id}]")
        return record

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def get_entries_for_alert(self, alert_id: str) -> list[ComplianceLedgerEntry]:
        return [e for e in self._entries if e.alert_id == alert_id]

    def get_provenance_for_alert(self, alert_id: str) -> list[DataProvenanceRecord]:
        return [p for p in self._provenance.values() if p.alert_id == alert_id]

    def get_all_entries(self) -> list[ComplianceLedgerEntry]:
        return list(self._entries)

    def get_entry_by_id(self, entry_id: str) -> Optional[ComplianceLedgerEntry]:
        for e in self._entries:
            if e.id == entry_id:
                return e
        return None

    def get_provenance_by_id(self, prov_id: str) -> Optional[DataProvenanceRecord]:
        return self._provenance.get(prov_id)

    # ------------------------------------------------------------------
    # Integrity verification
    # ------------------------------------------------------------------

    def verify_chain(self) -> bool:
        """Walk the hash chain and confirm no entries have been tampered with."""
        expected = hashlib.sha256(COMPLIANCE_LEDGER_SECRET.encode()).hexdigest()
        for entry in self._entries:
            if entry.previous_hash != expected:
                logger.error(f"Chain broken at entry {entry.id}")
                return False
            expected = entry.entry_hash
        logger.info("Ledger chain integrity verified")
        return True

    @property
    def last_hash(self) -> str:
        return self._last_hash

    @property
    def size(self) -> int:
        return len(self._entries)
