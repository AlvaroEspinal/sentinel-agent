"""
ArchiveCenter Scraper — CivicPlus ArchiveCenter meeting minutes.

Used for towns like Needham that store minutes in the ArchiveCenter
module instead of AgendaCenter.

URL patterns:
  List:     /Archive.aspx?AMID={amid}
  Download: /ArchiveCenter/ViewFile/Item/{adid}

Usage:
    client = ArchiveCenterClient()
    meetings = await client.list_meetings("https://www.needhamma.gov", amid=33)
    pdf_bytes = await client.download_pdf("https://www.needhamma.gov/ArchiveCenter/ViewFile/Item/14918")
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # type: ignore


class ArchiveCenterClient:
    """Direct HTTP scraper for CivicPlus ArchiveCenter sites."""

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

    async def list_meetings(
        self,
        base_url: str,
        amid: int,
        max_pages: int = 5,
    ) -> List[Dict[str, Any]]:
        """Fetch all archive entries for a board's minutes.

        Args:
            base_url: Town website base URL (e.g. "https://www.needhamma.gov")
            amid:     ArchiveCenter module ID for minutes
            max_pages: Maximum pagination pages to fetch

        Returns:
            List of meeting dicts with: title, meeting_date, minutes_url, adid
        """
        client = await self._ensure_client()
        base = base_url.rstrip("/")
        all_meetings: List[Dict[str, Any]] = []

        for page in range(1, max_pages + 1):
            try:
                url = f"{base}/Archive.aspx?AMID={amid}"
                if page > 1:
                    url += f"&page={page}"

                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(
                        "[ArchiveCenter] HTTP %d for %s AMID=%d page=%d",
                        resp.status_code, base, amid, page,
                    )
                    break

                html = resp.text
                meetings = self._parse_archive_entries(html, base)

                if not meetings:
                    break

                all_meetings.extend(meetings)
                logger.info(
                    "[ArchiveCenter] %s AMID=%d page=%d: %d entries",
                    base, amid, page, len(meetings),
                )

                # Check if there's a next page
                if f'page={page + 1}' not in html and 'class="next"' not in html.lower():
                    break

            except Exception as exc:
                logger.error(
                    "[ArchiveCenter] Error fetching %s AMID=%d page=%d: %s",
                    base, amid, page, exc,
                )
                break

        return all_meetings

    async def download_pdf(self, url: str) -> Optional[bytes]:
        """Download a PDF from an ArchiveCenter ViewFile URL."""
        client = await self._ensure_client()
        try:
            resp = await client.get(url, timeout=60.0)
            if resp.status_code != 200:
                logger.warning("[ArchiveCenter] HTTP %d downloading %s", resp.status_code, url)
                return None
            content = resp.content
            if len(content) < 200:
                return None
            return content
        except Exception as exc:
            logger.warning("[ArchiveCenter] Download error %s: %s", url, exc)
            return None

    @staticmethod
    def extract_pdf_text(pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes using pdfplumber."""
        if pdfplumber is None:
            logger.warning("[ArchiveCenter] pdfplumber not installed")
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
            logger.warning("[ArchiveCenter] PDF extraction error: %s", exc)
            return ""

    @staticmethod
    def _parse_archive_entries(html: str, base_url: str) -> List[Dict[str, Any]]:
        """Parse the ArchiveCenter HTML for document entries."""
        meetings = []

        # Pattern 1: Links to Archive.aspx?ADID=NNNNN (with or without leading slash)
        # HTML structure: <a href="Archive.aspx?ADID=14918"><span>Title - Date</span></a>
        # or: <a href="/Archive.aspx?ADID=14918">Title</a>
        entry_pattern = re.compile(
            r'<a\s+href="/?Archive\.aspx\?ADID=(\d+)"[^>]*>\s*(.+?)\s*</a>',
            re.IGNORECASE | re.DOTALL,
        )

        for match in entry_pattern.finditer(html):
            adid, raw_title = match.groups()
            # Strip HTML tags (title may be inside <span>)
            title = re.sub(r'<[^>]+>', '', raw_title).strip()
            if not title or title == "All Archives":
                continue

            meeting_date = ArchiveCenterClient._extract_date_from_title(title)
            pdf_url = f"{base_url}/ArchiveCenter/ViewFile/Item/{adid}"

            meetings.append({
                "adid": adid,
                "title": title,
                "meeting_date": meeting_date,
                "minutes_url": pdf_url,
            })

        # Pattern 2: Direct links to ArchiveCenter/ViewFile/Item/NNNNN
        viewfile_pattern = re.compile(
            r'<a\s+href="/?ArchiveCenter/ViewFile/Item/(\d+)"[^>]*>\s*(.+?)\s*</a>',
            re.IGNORECASE | re.DOTALL,
        )

        seen_adids = {m["adid"] for m in meetings}
        for match in viewfile_pattern.finditer(html):
            adid, raw_title = match.groups()
            if adid in seen_adids:
                continue
            title = re.sub(r'<[^>]+>', '', raw_title).strip()
            if not title:
                continue

            meeting_date = ArchiveCenterClient._extract_date_from_title(title)
            meetings.append({
                "adid": adid,
                "title": title,
                "meeting_date": meeting_date,
                "minutes_url": f"{base_url}/ArchiveCenter/ViewFile/Item/{adid}",
            })

        # Sort by date descending
        meetings.sort(key=lambda m: m.get("meeting_date") or date.min, reverse=True)
        return meetings

    @staticmethod
    def _extract_date_from_title(title: str) -> Optional[date]:
        """Try to extract a date from an archive entry title."""
        # "January 15, 2025" or "Jan 15, 2025"
        month_names = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12,
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
            'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9,
            'oct': 10, 'nov': 11, 'dec': 12,
        }

        # "Month DD, YYYY"
        m = re.search(
            r'(\w+)\s+(\d{1,2}),?\s+(\d{4})',
            title,
        )
        if m:
            month_str, day_str, year_str = m.groups()
            month_num = month_names.get(month_str.lower())
            if month_num:
                try:
                    return date(int(year_str), month_num, int(day_str))
                except ValueError:
                    pass

        # "MM/DD/YYYY" or "M/D/YYYY"
        m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', title)
        if m:
            try:
                return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            except ValueError:
                pass

        # "YYYY-MM-DD"
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', title)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

        return None
