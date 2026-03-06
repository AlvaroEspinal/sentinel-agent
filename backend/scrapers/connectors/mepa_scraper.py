"""
MEPA Environmental Monitor Scraper.

Queries the Massachusetts Environmental Policy Act (MEPA) eMonitor database
for new real estate development filings (ENFs, EIRs, NPCs, etc.).

Primary method uses the AWS API Gateway backing the Angular SPA at:
  https://eeaonline.eea.state.ma.us/EEA/MEPA-eMonitor/search

Fallback method scrapes the HTML search results page with BeautifulSoup.

No existing FastAPI routes or global state files are modified.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = (
    "https://t7i6mic1h4.execute-api.us-east-1.amazonaws.com"
    "/PROD/V1.0.0/api/Project"
)
SEARCH_ENDPOINT = f"{API_BASE}/search"

API_KEY = "ZyygCR4t0y8gKbqSbbuUO6g4GrfcGRMF9QRplY4m"

EMONITOR_ORIGIN = "https://eeaonline.eea.state.ma.us"
PROJECT_DETAIL_URL = (
    "https://eeaonline.eea.state.ma.us/EEA/MEPA-eMonitor/project/{eea_number}"
)

# HTML fallback URL (the Angular SPA search page)
HTML_SEARCH_URL = (
    "https://eeaonline.eea.state.ma.us/EEA/MEPA-eMonitor/search"
)

# Document types recognised by the API
VALID_DOC_TYPES = {
    "ENF",   # Environmental Notification Form
    "EIR",   # Environmental Impact Report
    "DEIR",  # Draft EIR
    "FEIR",  # Final EIR
    "SEIR",  # Supplemental EIR
    "NPC",   # Notice of Project Change
    "SA",    # Secretary's Advisory
    "SC",    # Scope
}


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class MEPAScraper:
    """Async scraper for the MEPA Environmental Monitor."""

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self._headers = {
            "x-api-key": API_KEY,
            "origin": EMONITOR_ORIGIN,
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_projects(
        self,
        *,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        document_type: Optional[str] = None,
        municipality: Optional[str] = None,
        project_name: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Search MEPA project filings via the eMonitor API.

        Args:
            date_from:      Start date filter (MM/DD/YYYY).
            date_to:        End date filter (MM/DD/YYYY).
            document_type:  Filter by type (ENF, EIR, FEIR, NPC …).
            municipality:   Filter by municipality name.
            project_name:   Filter by project name substring.
            page:           Page number (1-indexed).
            page_size:      Number of results per page.

        Returns:
            A list of normalised filing dicts.
        """
        params: Dict[str, Any] = {
            "Page": page,
            "PageSize": page_size,
        }

        if date_from:
            params["SubmittalDateFrom"] = date_from
        if date_to:
            params["SubmittalDateTo"] = date_to
        if document_type:
            doc = document_type.upper()
            if doc in VALID_DOC_TYPES:
                params["DocumentType"] = doc
        if municipality:
            params["Municipality"] = municipality
        if project_name:
            params["ProjectName"] = project_name

        try:
            return await self._fetch_from_api(params)
        except Exception as exc:
            logger.warning("API request failed (%s); trying HTML fallback.", exc)
            return await self._parse_html_fallback(params)

    async def get_latest_filings(self, count: int = 20) -> List[Dict[str, Any]]:
        """
        Convenience method: return the *count* most recent filings.

        Uses a 90-day look-back window so the result set is reasonably fresh.
        """
        today = datetime.now()
        date_from = (today - timedelta(days=90)).strftime("%m/%d/%Y")
        date_to = today.strftime("%m/%d/%Y")

        filings = await self.search_projects(
            date_from=date_from,
            date_to=date_to,
            page_size=max(count, 50),
        )

        # Sort by publish_date descending, then trim
        filings.sort(
            key=lambda f: f.get("publish_date") or "",
            reverse=True,
        )
        return filings[:count]

    # ------------------------------------------------------------------
    # Internal: API path
    # ------------------------------------------------------------------

    async def _fetch_from_api(
        self, params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Call the AWS API Gateway and normalise the response."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                SEARCH_ENDPOINT,
                params=params,
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()

        raw_projects = data if isinstance(data, list) else data.get("list", data.get("results", []))
        return [self._normalise_project(p) for p in raw_projects]

    @staticmethod
    def _normalise_project(raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Flatten a raw API project object into a clean filing dict.

        The API returns a project with a nested ``submittals`` list.
        We surface the most recent submittal's metadata at the top level.
        """
        submittals = raw.get("submittals") or []
        latest = submittals[0] if submittals else {}

        eea_number = raw.get("eeaNumber") or raw.get("projectId") or ""

        return {
            "eea_number": eea_number,
            "project_name": raw.get("projectName") or raw.get("name", ""),
            "municipality": raw.get("municipality", ""),
            "location": raw.get("location") or raw.get("address", ""),
            "proponent": raw.get("proponent", ""),
            "filing_type": latest.get("submittalType") or latest.get("documentType", ""),
            "publish_date": latest.get("publishDate") or latest.get("monitorDate", ""),
            "public_comment_deadline": latest.get("commentsDueDate", ""),
            "mepa_analyst": raw.get("mepaAnalyst", ""),
            "project_url": PROJECT_DETAIL_URL.format(eea_number=eea_number),
            "source": "MEPA eMonitor",
        }

    # ------------------------------------------------------------------
    # Internal: HTML fallback (BeautifulSoup)
    # ------------------------------------------------------------------

    async def _parse_html_fallback(
        self, params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Fallback scraper: fetch the eMonitor search page's HTML and
        extract project rows with BeautifulSoup.

        This is a best-effort fallback — the Angular SPA may not render
        data in the initial HTML payload, in which case an empty list is
        returned.
        """
        try:
            from bs4 import BeautifulSoup  # noqa: F811
        except ImportError:
            logger.error(
                "beautifulsoup4 is not installed — cannot use HTML fallback. "
                "Install it with:  pip install beautifulsoup4"
            )
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(HTML_SEARCH_URL)
                resp.raise_for_status()
                html = resp.text

            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("table tbody tr")

            filings: List[Dict[str, Any]] = []
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 5:
                    continue

                link = cells[0].find("a")
                eea_number = link.get_text(strip=True) if link else cells[0].get_text(strip=True)

                filings.append({
                    "eea_number": eea_number,
                    "project_name": cells[1].get_text(strip=True),
                    "municipality": cells[2].get_text(strip=True),
                    "location": cells[3].get_text(strip=True) if len(cells) > 3 else "",
                    "proponent": "",
                    "filing_type": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                    "publish_date": "",
                    "public_comment_deadline": "",
                    "mepa_analyst": cells[5].get_text(strip=True) if len(cells) > 5 else "",
                    "project_url": PROJECT_DETAIL_URL.format(eea_number=eea_number),
                    "source": "MEPA eMonitor (HTML fallback)",
                })

            return filings

        except Exception as exc:
            logger.error("HTML fallback failed: %s", exc)
            return []
