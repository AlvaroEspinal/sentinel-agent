"""PermitEyes (Full Circle Technologies) scraper connector.

Works with towns using the PermitEyes public view portal at permiteyes.us.
Uses DataTables server-side AJAX POST to paginate through all permits.

Supported towns:
- Concord: permiteyes.us/concord/publicview.php (12-column layout)
- Lincoln: permiteyes.us/lincoln/publicview.php (9-column layout)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx


@dataclass(frozen=True)
class ColumnMap:
    """Maps logical field names to DataTables column indices.

    Set to -1 if the field is not present in the response.
    """
    description: int = -1
    app_number: int = -1
    app_date: int = -1
    issue_date: int = -1
    address: int = -1
    applicant: int = -1
    app_type: int = -1
    permit_number: int = -1
    status: int = -1
    num_columns: int = 12
    sort_column: int = 0  # Column to sort by (desc)


# Concord: 12 columns
# col[0]=Description, col[4]=AppNumber, col[5]=AppDate, col[6]=IssueDate,
# col[7]=Address, col[8]=Applicant, col[9]=AppType, col[10]=PermitNumber, col[11]=Status
CONCORD_COLUMNS = ColumnMap(
    description=0, app_number=4, app_date=5, issue_date=6,
    address=7, applicant=8, app_type=9, permit_number=10, status=11,
    num_columns=12, sort_column=4,
)

# Lincoln: 9 columns
# col[0]=Description(empty), col[1]=InternalID, col[2]=AppDate, col[3]=IssueDate,
# col[4]=Address, col[5]=Applicant, col[6]=AppType, col[7]=PermitNumber, col[8]=Status
LINCOLN_COLUMNS = ColumnMap(
    description=0, app_number=1, app_date=2, issue_date=3,
    address=4, applicant=5, app_type=6, permit_number=7, status=8,
    num_columns=9, sort_column=1,
)

# Chicopee: 17 columns
# col[6]=AppNumber, col[7]=AppDate, col[9]=Address, col[11]=Applicant,
# col[13]=AppType, col[15]=Status
CHICOPEE_COLUMNS = ColumnMap(
    app_number=6, app_date=7, address=9, applicant=11,
    app_type=13, status=15,
    num_columns=17, sort_column=6,
)

# Easthampton: 19 columns
# col[6]=AppNumber, col[7]=AppDate, col[10..11]=Address(number+street),
# col[12]=Applicant, col[14]=Description, col[15]=AppType, col[17]=Status
EASTHAMPTON_COLUMNS = ColumnMap(
    app_number=6, app_date=7, address=11, applicant=12,
    description=14, app_type=15, status=17,
    num_columns=19, sort_column=6,
)

# Taunton: 14 columns
# col[3]=AppNumber, col[4]=AppDate, col[5]=IssueDate, col[6]=Address,
# col[7]=Applicant, col[8]=Contractor, col[10]=Description, col[11]=AppType,
# col[12]=PermitNumber, col[13]=Status
TAUNTON_COLUMNS = ColumnMap(
    app_number=3, app_date=4, issue_date=5, address=6,
    applicant=7, description=10, app_type=11,
    permit_number=12, status=13,
    num_columns=14, sort_column=3,
)

# West Bridgewater: 17 columns
# col[4]=AppNumber, col[5]=AppDate, col[6]=IssueDate,
# col[8..9]=Address(number+street), col[10]=Contractor, col[11]=Owner,
# col[12]=Description, col[13]=AppType, col[14]=PermitNumber, col[15]=Status
WEST_BRIDGEWATER_COLUMNS = ColumnMap(
    app_number=4, app_date=5, issue_date=6, address=9,
    applicant=10, description=12, app_type=13,
    permit_number=14, status=15,
    num_columns=17, sort_column=4,
)


@dataclass(frozen=True)
class PermitEyesConfig:
    """Configuration for a PermitEyes town."""
    town_slug: str  # e.g. "concord", "lincoln"
    # List of (endpoint_path, department_label) tuples
    endpoints: List[Tuple[str, str]]
    columns: ColumnMap = field(default_factory=lambda: CONCORD_COLUMNS)

    @property
    def base_url(self) -> str:
        return f"https://permiteyes.us/{self.town_slug}"


# Known PermitEyes town configurations
PERMITEYES_TOWNS: Dict[str, PermitEyesConfig] = {
    "concord": PermitEyesConfig(
        town_slug="concord",
        endpoints=[
            ("ajax/getbuildingpublichome.php", "Building"),
            ("ajax/getfirepublichome.php", "Fire"),
        ],
        columns=CONCORD_COLUMNS,
    ),
    "lincoln": PermitEyesConfig(
        town_slug="lincoln",
        endpoints=[
            ("ajax/getpublichome.php", "Building"),
        ],
        columns=LINCOLN_COLUMNS,
    ),
    "chicopee": PermitEyesConfig(
        town_slug="chicopee",
        endpoints=[
            ("ajax/getpublichome.php", "Building"),
        ],
        columns=CHICOPEE_COLUMNS,
    ),
    "easthampton": PermitEyesConfig(
        town_slug="easthampton",
        endpoints=[
            ("ajax/getpublichome.php", "Building"),
        ],
        columns=EASTHAMPTON_COLUMNS,
    ),
    "taunton": PermitEyesConfig(
        town_slug="taunton",
        endpoints=[
            ("ajax/getpublicview.php", "Building"),
        ],
        columns=TAUNTON_COLUMNS,
    ),
    "west_bridgewater": PermitEyesConfig(
        town_slug="westbridgewater",
        endpoints=[
            ("ajax/getbuildingpublichome.php", "Building"),
        ],
        columns=WEST_BRIDGEWATER_COLUMNS,
    ),
}


def _extract_text(html_cell: str) -> str:
    """Extract plain text from an HTML span cell."""
    text = re.sub(r"<[^>]+>", "", html_cell).strip()
    return text


def _extract_data_attr(html_cell: str, attr: str) -> Optional[str]:
    """Extract a data-* attribute value from an HTML cell."""
    match = re.search(rf"data-{attr}=['\"]([^'\"]+)['\"]", html_cell)
    return match.group(1) if match else None


def _extract_title(html_cell: str) -> Optional[str]:
    """Extract title attribute (used for full permit type name)."""
    match = re.search(r"title='([^']+)'", html_cell)
    if not match:
        match = re.search(r'title="([^"]+)"', html_cell)
    return match.group(1).strip() if match else None


def _safe_col(row: List[str], idx: int) -> str:
    """Safely get a column value, returning empty string if index is invalid."""
    if idx < 0 or idx >= len(row):
        return ""
    return row[idx]


def _build_datatables_params(
    start: int, length: int, columns: ColumnMap,
) -> Dict[str, str]:
    """Build DataTables server-side POST parameters."""
    params: Dict[str, str] = {
        "draw": "1",
        "start": str(start),
        "length": str(length),
        "search[value]": "",
        "search[regex]": "false",
        "order[0][column]": str(columns.sort_column),
        "order[0][dir]": "desc",
    }
    for i in range(columns.num_columns):
        params[f"columns[{i}][data]"] = str(i)
        params[f"columns[{i}][name]"] = ""
        params[f"columns[{i}][searchable]"] = "true"
        params[f"columns[{i}][orderable]"] = "true"
        params[f"columns[{i}][search][value]"] = ""
        params[f"columns[{i}][search][regex]"] = "false"
    return params


def parse_permit_row(
    row: List[str], department: str, columns: ColumnMap,
) -> Dict[str, Any]:
    """Parse a single DataTables row into a structured permit dict."""
    description = _extract_text(_safe_col(row, columns.description))
    app_number = _extract_text(_safe_col(row, columns.app_number))
    app_date = _extract_text(_safe_col(row, columns.app_date))
    issue_date = _extract_text(_safe_col(row, columns.issue_date))
    address = _extract_text(_safe_col(row, columns.address))
    applicant = _extract_text(_safe_col(row, columns.applicant))
    permit_number = _extract_text(_safe_col(row, columns.permit_number))
    status = _extract_text(_safe_col(row, columns.status))

    # Get full type name from title attribute, fallback to text
    app_type = ""
    raw_type_cell = _safe_col(row, columns.app_type)
    if raw_type_cell:
        app_type = _extract_title(raw_type_cell) or _extract_text(raw_type_cell)
    app_type = app_type.strip().rstrip(".")

    # Extract unique IDs from data attributes (Concord uses these)
    application_id = ""
    internal_id = ""
    raw_app_cell = _safe_col(row, columns.app_number)
    if raw_app_cell:
        application_id = _extract_data_attr(raw_app_cell, "application-id") or ""
        internal_id = _extract_data_attr(raw_app_cell, "id") or ""

    return {
        "source_id": internal_id or app_number,
        "application_id": application_id,
        "app_number": app_number,
        "description": description,
        "app_date": app_date,
        "issue_date": issue_date,
        "address": address,
        "applicant": applicant,
        "app_type": app_type or department,
        "permit_number": permit_number or app_number,
        "status": status,
        "department": department,
    }


async def fetch_permits_page(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    endpoint: str,
    columns: ColumnMap,
    start: int,
    length: int = 100,
    timeout_s: float = 30.0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Fetch a single page of permits from a PermitEyes DataTables endpoint.

    Returns (rows_as_dicts_list, total_records).
    """
    url = f"{base_url}/{endpoint}"
    params = _build_datatables_params(start=start, length=length, columns=columns)

    resp = await client.post(
        url,
        data=params,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout_s,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"PermitEyes request failed: status={resp.status_code}")

    payload = resp.json()
    total = int(payload.get("recordsTotal", 0))
    rows = payload.get("data", [])
    return rows, total


async def scrape_all_permits(
    *,
    config: PermitEyesConfig,
    client: httpx.AsyncClient,
    page_size: int = 200,
    max_records: int = 50_000,
    partition: Optional[int] = None,
    num_partitions: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Scrape all permits from a PermitEyes town across all department endpoints.

    Supports partitioning: split endpoints across partitions if num_partitions > 1.
    """
    endpoints = list(config.endpoints)

    # Partition support: split endpoints across partitions
    if partition is not None and num_partitions is not None and num_partitions > 1:
        chunk_size = max(1, (len(endpoints) + num_partitions - 1) // num_partitions)
        start_idx = partition * chunk_size
        end_idx = min(start_idx + chunk_size, len(endpoints))
        endpoints = endpoints[start_idx:end_idx]
        if not endpoints:
            return []

    all_permits: List[Dict[str, Any]] = []

    for endpoint_path, department in endpoints:
        offset = 0
        total = None

        while len(all_permits) < max_records:
            rows, records_total = await fetch_permits_page(
                client=client,
                base_url=config.base_url,
                endpoint=endpoint_path,
                columns=config.columns,
                start=offset,
                length=page_size,
            )

            if total is None:
                total = records_total

            if not rows:
                break

            for row in rows:
                if not isinstance(row, list):
                    continue
                permit = parse_permit_row(row, department, config.columns)
                if permit.get("source_id"):
                    all_permits.append(permit)

            offset += len(rows)
            if offset >= (total or 0):
                break

    return all_permits[:max_records]
