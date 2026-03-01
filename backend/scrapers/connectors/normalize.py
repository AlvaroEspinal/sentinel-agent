"""
Normalize permit data from multiple MA municipalities into the Parcl unified schema.

Ported from municipal-intel for Parcl Intelligence.

Unified Schema (maps to the documents + document_metadata + document_locations structure):
- permit_number: Unique permit ID
- town: Municipality name (lowercase slug)
- address: Full address
- latitude / longitude: Coordinates
- permit_type: Type of permit (Building, Electrical, Plumbing, etc.)
- status: Permit status
- description: Work description
- filed_date: Date applied/filed
- issued_date: Date issued
- estimated_value: Total cost (if available)
- source_system: Data source (socrata, ckan, opengov)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Date parsing ────────────────────────────────────────────────────────────

def parse_date(date_str: Optional[str]) -> Optional[str]:
    """Convert various date formats to ISO date (YYYY-MM-DD)."""
    if not date_str:
        return None

    date_str = str(date_str).strip()
    if not date_str:
        return None

    # Handle Socrata format: "2014-11-07T00:00:00.000"
    if "T" in date_str:
        try:
            return date_str.split("T")[0]
        except Exception:
            return None

    # Handle MM/DD/YYYY
    try:
        dt = datetime.strptime(date_str, "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    # Handle YYYY-MM-DD (already ISO)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str

    return date_str


# ─── Town-specific normalizers ───────────────────────────────────────────────

def _normalize_boston(permit: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Boston CKAN permit data."""
    metadata = permit.get("metadata", {})
    content = permit.get("content", "")

    # Infer permit type from content
    permit_type = "Building"
    if "electrical" in content.lower():
        permit_type = "Electrical"
    elif "plumbing" in content.lower():
        permit_type = "Plumbing"
    elif "gas" in content.lower():
        permit_type = "Gas"

    return {
        "permit_number": permit.get("source_id", ""),
        "town": "boston",
        "address": permit.get("address", ""),
        "latitude": _safe_float(metadata.get("latitude")),
        "longitude": _safe_float(metadata.get("longitude")),
        "permit_type": permit_type,
        "status": metadata.get("status", ""),
        "description": content[:500] if content else "",
        "filed_date": parse_date(metadata.get("application_date")),
        "issued_date": parse_date(metadata.get("issue_date")),
        "estimated_value": _safe_float(metadata.get("declared_valuation")),
        "source_system": "ckan",
    }


def _normalize_cambridge(permit: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Cambridge Socrata permit data."""
    source = permit.get("_source_dataset", "")

    type_map = {
        "electrical": "Electrical",
        "plumbing": "Plumbing",
        "gas": "Gas",
        "mechanical": "Mechanical",
        "demolition": "Demolition",
        "solar": "Solar",
        "roof": "Roofing",
        "siding": "Siding",
        "new_construction": "New Construction",
        "addition_alteration": "Addition/Alteration",
    }

    permit_type = "Building"
    for key, val in type_map.items():
        if key in source.lower():
            permit_type = val
            break

    return {
        "permit_number": permit.get("id", ""),
        "town": "cambridge",
        "address": permit.get("full_address", ""),
        "latitude": _safe_float(permit.get("latitude")),
        "longitude": _safe_float(permit.get("longitude")),
        "permit_type": permit_type,
        "status": permit.get("status", ""),
        "description": (permit.get("description_of_work") or "")[:500],
        "filed_date": parse_date(permit.get("applicant_submit_date")),
        "issued_date": parse_date(permit.get("issue_date")),
        "estimated_value": _safe_float(permit.get("total_cost_of_construction")),
        "source_system": "socrata",
    }


def _normalize_somerville(permit: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Somerville Socrata permit data."""
    permit_id = permit.get("id", "")

    # Infer type from permit ID prefix
    permit_type = permit.get("type", "Building")
    prefix_map = {
        "E": "Electrical",
        "P": "Plumbing",
        "G": "Gas",
        "B": "Building",
        "D": "Demolition",
        "SM": "Mechanical",
        "CI": "Certificate of Inspection",
    }
    for prefix, ptype in prefix_map.items():
        if permit_id.startswith(prefix):
            permit_type = ptype
            break

    return {
        "permit_number": permit_id,
        "town": "somerville",
        "address": permit.get("address", ""),
        "latitude": _safe_float(permit.get("latitude")),
        "longitude": _safe_float(permit.get("longitude")),
        "permit_type": permit_type,
        "status": permit.get("status", ""),
        "description": (permit.get("work") or "")[:500],
        "filed_date": parse_date(permit.get("application_date")),
        "issued_date": parse_date(permit.get("issue_date")),
        "estimated_value": _safe_float(permit.get("amount")),
        "source_system": "socrata",
    }


# ─── Registry ───────────────────────────────────────────────────────────────

_NORMALIZERS = {
    "boston": _normalize_boston,
    "cambridge": _normalize_cambridge,
    "somerville": _normalize_somerville,
}


# ─── Public API ──────────────────────────────────────────────────────────────

def normalize_permit(permit: Dict[str, Any], town: str) -> Optional[Dict[str, Any]]:
    """Normalize a single permit record from raw source format.

    Args:
        permit: Raw permit dict from the source (Socrata, CKAN, etc.)
        town: Municipality slug (e.g. "cambridge", "somerville")

    Returns:
        Normalized permit dict, or None if normalization fails.
    """
    normalizer = _NORMALIZERS.get(town.lower())
    if not normalizer:
        logger.warning("No normalizer for town: %s", town)
        return None

    try:
        return normalizer(permit)
    except Exception as exc:
        logger.debug("Failed to normalize permit for %s: %s", town, exc)
        return None


def normalize_batch(
    permits: List[Dict[str, Any]], town: str
) -> List[Dict[str, Any]]:
    """Normalize a batch of permits, skipping failures.

    Returns:
        List of successfully normalized permit dicts.
    """
    results: List[Dict[str, Any]] = []
    for permit in permits:
        normalized = normalize_permit(permit, town)
        if normalized:
            results.append(normalized)
    logger.info(
        "Normalized %d/%d permits for %s", len(results), len(permits), town
    )
    return results


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _safe_float(value: Any) -> Optional[float]:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
