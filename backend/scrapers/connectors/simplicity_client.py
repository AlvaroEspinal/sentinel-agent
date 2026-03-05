"""SimpliCITY / MapsOnline (PeopleGIS / Schneider Geospatial) connector.

Works with towns using the MapsOnline permit portal at mapsonline.net.
Uses the pf-ng JSON search API with session-based public access.

Supported towns:
- Weston: mapsonline.net/westonma/
- Sherborn: mapsonline.net/sherbornma/

The API returns positional arrays with a schema definition.
Dates are Unix timestamps in milliseconds.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.mapsonline.net"


@dataclass(frozen=True)
class SimplicityFormConfig:
    """Configuration for a single permit form (e.g. Building, Electrical)."""
    form_id: str
    department: str  # "Building", "Electrical", "Gas", "Plumbing", "Sheet Metal"


@dataclass(frozen=True)
class SimplicityTownConfig:
    """Configuration for a SimpliCITY/MapsOnline town."""
    client_name: str  # e.g. "westonma", "sherbornma"
    config_id: str  # e.g. "permit-63", "permit-62"
    forms: List[SimplicityFormConfig] = field(default_factory=list)

    @property
    def public_reports_url(self) -> str:
        return f"{BASE_URL}/{self.client_name}/public_permit_reports.html.php"


# Known SimpliCITY town configurations
SIMPLICITY_TOWNS: Dict[str, SimplicityTownConfig] = {
    "weston": SimplicityTownConfig(
        client_name="westonma",
        config_id="permit-63",
        forms=[
            SimplicityFormConfig("131616041", "Building"),
            SimplicityFormConfig("705190362", "Electrical"),
            SimplicityFormConfig("316110055", "Gas"),
            SimplicityFormConfig("592110861", "Plumbing"),
            SimplicityFormConfig("317755858", "Sheet Metal"),
        ],
    ),
    "sherborn": SimplicityTownConfig(
        client_name="sherbornma",
        config_id="permit-62",
        forms=[
            SimplicityFormConfig("932028839", "Building"),
            SimplicityFormConfig("41232828", "Electrical"),
            SimplicityFormConfig("394345104", "Gas"),
            SimplicityFormConfig("944470520", "Plumbing"),
            SimplicityFormConfig("705726072", "Sheet Metal"),
        ],
    ),
}


def _ms_to_date(ms_str: str) -> Optional[str]:
    """Convert millisecond timestamp string to YYYY-MM-DD date string."""
    if not ms_str or ms_str in ("", "null", "None"):
        return None
    try:
        ts = int(ms_str) / 1000.0
        if ts <= 0:
            return None
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return None


def _safe_str(val: Any) -> str:
    """Safely convert a value to string, handling None and various types."""
    if val is None or val == "null":
        return ""
    return str(val).strip()


async def get_session_id(
    *,
    client: httpx.AsyncClient,
    client_name: str,
    timeout_s: float = 20.0,
) -> Optional[str]:
    """Get a public session ID (ssid) from the MapsOnline portal.

    Fetches the public permit reports page and extracts the session ID
    from the embedded iframe's check_auth_ssid call.
    """
    url = f"{BASE_URL}/{client_name}/public_permit_reports.html.php"
    try:
        resp = await client.get(url, timeout=timeout_s, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning("SimpliCITY session page failed: status=%d", resp.status_code)
            return None

        html = resp.text

        # Look for ssid in check_auth_ssid URL or JavaScript
        match = re.search(r'ssid=([a-f0-9]{32})', html)
        if match:
            return match.group(1)

        # Try alternate pattern: embedded in form_server URL
        match = re.search(r'check_auth_ssid[^"]*ssid=([a-f0-9]{32})', html)
        if match:
            return match.group(1)

        # Try extracting from iframe src
        match = re.search(r'src="([^"]*transaction\.php[^"]*)"', html)
        if match:
            iframe_url = match.group(1)
            if not iframe_url.startswith("http"):
                iframe_url = f"{BASE_URL}{iframe_url}" if iframe_url.startswith("/") else f"{BASE_URL}/{iframe_url}"

            iframe_resp = await client.get(iframe_url, timeout=timeout_s, follow_redirects=True)
            if iframe_resp.status_code == 200:
                iframe_match = re.search(r'"ssid"\s*:\s*"([a-f0-9]{32})"', iframe_resp.text)
                if iframe_match:
                    return iframe_match.group(1)

        # Last resort: call check_auth_ssid directly with a dummy ID
        auth_url = f"{BASE_URL}/form_server/htdocs/transaction.php"
        auth_resp = await client.get(
            auth_url,
            params={
                "request": "check_auth_ssid",
                "id": "46598141",
                "ssid": "",
                "format": "json",
            },
            timeout=timeout_s,
        )
        if auth_resp.status_code == 200:
            try:
                data = auth_resp.json()
                if data.get("auth") and data.get("ssid"):
                    return data["ssid"]
            except Exception:
                pass

        logger.warning("SimpliCITY: could not extract ssid from %s", url)
        return None

    except Exception as exc:
        logger.warning("SimpliCITY session error for %s: %s", client_name, exc)
        return None


def _build_schema_map(schema: List[Dict[str, str]]) -> Dict[str, int]:
    """Build a mapping from field title to column index."""
    return {item.get("title", ""): i for i, item in enumerate(schema) if item.get("title")}


def parse_permit_record(
    row: List[Any],
    schema_map: Dict[str, int],
    department: str,
) -> Dict[str, Any]:
    """Parse a single SimpliCITY result row into a structured permit dict."""

    def get(field: str) -> str:
        idx = schema_map.get(field, -1)
        if idx < 0 or idx >= len(row):
            return ""
        return _safe_str(row[idx])

    # Address components
    addr_num = get("addr_num")
    addr_name = get("addr_name")
    addr_unit = get("addr_unit")
    address = f"{addr_num} {addr_name}".strip()
    if addr_unit:
        address = f"{address} #{addr_unit}"

    # Permit number — try several field names
    permit_no = get("permit_no") or get("app_no") or get("perm_no") or ""

    # Status — try several field names
    status = get("status") or get("perm_status") or ""

    # Dates (millisecond timestamps)
    app_date = _ms_to_date(get("app_date"))
    draft_date = _ms_to_date(get("draft_date"))
    issued_date = _ms_to_date(get("issue_date")) or _ms_to_date(get("issued_date"))

    # Cost
    estimated_value = None
    cost_str = get("total_cost") or get("bldg_cost") or ""
    if cost_str:
        try:
            val = float(cost_str.replace(",", "").replace("$", ""))
            if val > 0:
                estimated_value = val
        except (ValueError, TypeError):
            pass

    # Description
    description = get("work_desc") or get("staff_desc") or get("perm_cat") or ""

    # Applicant / owner
    owner = get("owner1") or ""
    applicant = get("applicant") or get("con_fname") or ""
    if not applicant and get("con_lname"):
        applicant = f"{get('con_fname')} {get('con_lname')}".strip()

    # Contractor
    contractor = get("company") or ""
    if not contractor:
        con_first = get("con_fname") or ""
        con_last = get("con_lname") or ""
        if con_first or con_last:
            contractor = f"{con_first} {con_last}".strip()

    # Permit category / type
    perm_cat = get("perm_cat") or department
    use_type = get("use") or ""

    # Internal ID (last two values in row are typically id and jump_id)
    internal_id = ""
    if len(row) >= 2:
        # Second-to-last is usually numeric internal ID
        try:
            internal_id = str(int(row[-2]))
        except (ValueError, TypeError):
            pass

    source_id = internal_id or permit_no

    return {
        "source_id": source_id,
        "permit_number": permit_no,
        "description": description[:500],
        "app_date": app_date or draft_date,
        "issue_date": issued_date,
        "address": address,
        "applicant": owner or applicant,
        "contractor": contractor,
        "app_type": f"{department} - {perm_cat}" if perm_cat != department else department,
        "permit_type": department,
        "status": status,
        "estimated_value": estimated_value,
        "use_type": use_type,
        "department": department,
    }


async def search_permits(
    *,
    client: httpx.AsyncClient,
    ssid: str,
    form_id: str,
    offset: int = 0,
    limit: int = 100,
    where: str = "1=1",
    timeout_s: float = 30.0,
) -> Tuple[List[Any], List[Dict[str, str]], int]:
    """Search permits using the pf-ng search API.

    Returns (results_rows, schema, total_count).
    """
    url = f"{BASE_URL}/pf-ng/s/search"
    payload = {
        "search": {
            "form_id": form_id,
            "where": where,
            "limit": str(limit),
            "offset": str(offset),
        },
        "debug": "no",
        "unique": "no",
    }

    resp = await client.post(
        url,
        params={"sid": ssid},
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=timeout_s,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"SimpliCITY search failed: status={resp.status_code} body={resp.text[:200]}"
        )

    data = resp.json()
    schema = data.get("schema", [])
    results = data.get("results", [])
    total = int(data.get("total", 0))

    return results, schema, total


async def scrape_town_permits(
    *,
    config: SimplicityTownConfig,
    client: httpx.AsyncClient,
    ssid: str,
    page_size: int = 100,
    max_records: int = 50_000,
    partition: Optional[int] = None,
    num_partitions: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Scrape all permits for a SimpliCITY town.

    Supports partitioning across permit form types.
    """
    forms = list(config.forms)

    # Partition support: split forms across partitions
    if partition is not None and num_partitions is not None and num_partitions > 1:
        chunk_size = max(1, (len(forms) + num_partitions - 1) // num_partitions)
        start_idx = partition * chunk_size
        end_idx = min(start_idx + chunk_size, len(forms))
        forms = forms[start_idx:end_idx]
        if not forms:
            return []

    all_permits: List[Dict[str, Any]] = []

    for form_config in forms:
        offset = 0
        total = None
        schema_map: Optional[Dict[str, int]] = None

        while len(all_permits) < max_records:
            try:
                results, schema, records_total = await search_permits(
                    client=client,
                    ssid=ssid,
                    form_id=form_config.form_id,
                    offset=offset,
                    limit=page_size,
                )
            except Exception as exc:
                logger.warning(
                    "SimpliCITY search failed %s/%s offset=%d: %s",
                    config.client_name, form_config.department, offset, exc,
                )
                break

            if total is None:
                total = records_total
                logger.info(
                    "SimpliCITY %s %s: %d total records",
                    config.client_name, form_config.department, records_total,
                )

            if schema_map is None and schema:
                schema_map = _build_schema_map(schema)

            if not results or schema_map is None:
                break

            for row in results:
                if not isinstance(row, list):
                    continue
                permit = parse_permit_record(row, schema_map, form_config.department)
                if permit.get("source_id"):
                    all_permits.append(permit)

            offset += len(results)
            if offset >= (total or 0):
                break

        if total is not None and total > 0:
            logger.info(
                "SimpliCITY %s %s: scraped %d/%d",
                config.client_name, form_config.department,
                min(offset, total), total,
            )

    return all_permits[:max_records]
