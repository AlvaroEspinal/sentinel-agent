"""
AgendaCenter Direct Scraper — CivicPlus AgendaCenter meeting minutes.

Scrapes meeting minutes PDFs directly from CivicPlus AgendaCenter sites
using their internal AJAX endpoint. No Firecrawl or API keys needed.

10 of our 12 MVP towns use AgendaCenter:
  Wellesley, Weston, Brookline, Needham, Dover, Natick,
  Concord, Lexington, Sherborn, Lincoln

Usage:
    client = AgendaCenterClient()
    meetings = await client.list_meetings("https://www.wellesleyma.gov", cat_id=12, years=[2024, 2025])
    pdf_bytes = await client.download_pdf("https://www.wellesleyma.gov/AgendaCenter/ViewFile/Minutes/_01152025-8700")
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # type: ignore


class AgendaCenterClient:
    """Direct HTTP scraper for CivicPlus AgendaCenter sites."""

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        self._client: Optional[Any] = None

    async def _ensure_client(self) -> Any:
        if self._client is None:
            if httpx is None:
                raise RuntimeError("httpx required: pip install httpx")
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10),
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; MunicipalIntel/1.0)",
                },
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Core: List meetings via AJAX POST ──────────────────────────────

    async def list_meetings(
        self,
        base_url: str,
        cat_id: int,
        years: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch all meetings for a board across specified years.

        Args:
            base_url: Town website base URL (e.g. "https://www.wellesleyma.gov")
            cat_id:   AgendaCenter category ID (from URL slug, e.g. 12 from Planning-Board-12)
            years:    Years to scrape (default: [2024, 2025, 2026])

        Returns:
            List of meeting dicts with: title, meeting_date, minutes_url, agenda_url
        """
        if years is None:
            years = [2024, 2025, 2026]

        client = await self._ensure_client()
        base = base_url.rstrip("/")
        all_meetings: List[Dict[str, Any]] = []

        for year in years:
            try:
                resp = await client.post(
                    f"{base}/AgendaCenter/UpdateCategoryList",
                    data={"year": str(year), "catID": str(cat_id)},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "[AgendaCenter] HTTP %d for %s catID=%d year=%d",
                        resp.status_code, base, cat_id, year,
                    )
                    continue

                html = resp.text
                meetings = self._parse_meetings(html, base)
                all_meetings.extend(meetings)
                logger.info(
                    "[AgendaCenter] %s catID=%d year=%d: %d meetings",
                    base, cat_id, year, len(meetings),
                )

            except Exception as exc:
                logger.error(
                    "[AgendaCenter] Error fetching %s catID=%d year=%d: %s",
                    base, cat_id, year, exc,
                )

        return all_meetings

    # ── Download PDF ───────────────────────────────────────────────────

    async def download_pdf(self, url: str) -> Optional[bytes]:
        """Download a PDF from an AgendaCenter ViewFile URL."""
        client = await self._ensure_client()
        try:
            resp = await client.get(url, timeout=60.0)
            if resp.status_code != 200:
                logger.warning("[AgendaCenter] HTTP %d downloading %s", resp.status_code, url)
                return None
            content = resp.content
            if len(content) < 200:
                return None
            return content
        except Exception as exc:
            logger.warning("[AgendaCenter] Download error %s: %s", url, exc)
            return None

    # ── Extract text from PDF bytes ────────────────────────────────────

    @staticmethod
    def extract_pdf_text(pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes using pdfplumber."""
        if pdfplumber is None:
            logger.warning("[AgendaCenter] pdfplumber not installed")
            return ""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
                return "\n\n".join(pages)
        except Exception as exc:
            logger.warning("[AgendaCenter] PDF extraction error: %s", exc)
            return ""

    # ── HTML Parsing ───────────────────────────────────────────────────

    @staticmethod
    def _parse_meetings(html: str, base_url: str) -> List[Dict[str, Any]]:
        """Parse the AJAX HTML fragment for meeting rows."""
        meetings = []

        # Find all ViewFile links for minutes and agendas
        # Pattern: /AgendaCenter/ViewFile/Minutes/_MMDDYYYY-NNNN
        # Pattern: /AgendaCenter/ViewFile/Agenda/_MMDDYYYY-NNNN
        minutes_pattern = re.compile(
            r'href="(/AgendaCenter/ViewFile/Minutes/_(\d{8})-(\d+))"',
            re.IGNORECASE,
        )
        agenda_pattern = re.compile(
            r'href="(/AgendaCenter/ViewFile/Agenda/_(\d{8})-(\d+))"',
            re.IGNORECASE,
        )

        # Build a map of agenda_id → {minutes_url, agenda_url, date}
        agenda_map: Dict[str, Dict[str, Any]] = {}

        for match in minutes_pattern.finditer(html):
            path, date_str, agenda_id = match.groups()
            if agenda_id not in agenda_map:
                agenda_map[agenda_id] = {}
            agenda_map[agenda_id]["minutes_url"] = f"{base_url}{path}"
            agenda_map[agenda_id]["date_str"] = date_str

        for match in agenda_pattern.finditer(html):
            path, date_str, agenda_id = match.groups()
            if agenda_id not in agenda_map:
                agenda_map[agenda_id] = {}
            agenda_map[agenda_id]["agenda_url"] = f"{base_url}{path}"
            if "date_str" not in agenda_map[agenda_id]:
                agenda_map[agenda_id]["date_str"] = date_str

        # Extract meeting titles from nearby <a> or <p> tags
        # Pattern: <a href="/AgendaCenter/ViewFile/Agenda/...">Meeting Title</a>
        title_pattern = re.compile(
            r'<a\s+href="/AgendaCenter/ViewFile/Agenda/_\d{8}-(\d+)"[^>]*>\s*([^<]+?)\s*</a>',
            re.IGNORECASE,
        )
        for match in title_pattern.finditer(html):
            agenda_id, title = match.groups()
            if agenda_id in agenda_map:
                agenda_map[agenda_id]["title"] = title.strip()

        # Convert to meeting list
        for agenda_id, info in agenda_map.items():
            date_str = info.get("date_str", "")
            meeting_date = None
            if date_str and len(date_str) == 8:
                try:
                    # MMDDYYYY format
                    meeting_date = date(
                        int(date_str[4:8]),
                        int(date_str[0:2]),
                        int(date_str[2:4]),
                    )
                except ValueError:
                    pass

            # Only include meetings that have minutes PDFs
            if "minutes_url" not in info:
                continue

            meetings.append({
                "agenda_id": agenda_id,
                "title": info.get("title", "Meeting Minutes"),
                "meeting_date": meeting_date,
                "minutes_url": info.get("minutes_url"),
                "agenda_url": info.get("agenda_url"),
            })

        # Sort by date descending
        meetings.sort(key=lambda m: m.get("meeting_date") or date.min, reverse=True)
        return meetings

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def extract_cat_id(agenda_center_url: str) -> Optional[int]:
        """Extract the category ID from an AgendaCenter board URL.

        e.g. "https://www.wellesleyma.gov/AgendaCenter/Planning-Board-12" → 12
        """
        match = re.search(r'-(\d+)\s*$', agenda_center_url)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def extract_base_url(agenda_center_url: str) -> str:
        """Extract the base URL from an AgendaCenter board URL.

        e.g. "https://www.wellesleyma.gov/AgendaCenter/Planning-Board-12"
             → "https://www.wellesleyma.gov"
        """
        match = re.match(r'(https?://[^/]+)', agenda_center_url)
        return match.group(1) if match else agenda_center_url
