"""
CivicClerk Scraper — CivicClerk OData API for meeting minutes.

Used for towns like Brookline that migrated from AgendaCenter to CivicClerk.

API base: https://{tenant}.api.civicclerk.com/v1/
Endpoints:
  GET /Events?$orderby=eventDate desc&$top=100&$filter=...
  GET /EventCategories  (lists boards)

Usage:
    client = CivicClerkClient(tenant="BrooklineMA")
    categories = await client.list_categories()
    meetings = await client.list_events(category_id=26)
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime
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


class CivicClerkClient:
    """OData API client for CivicClerk meeting management systems."""

    def __init__(self, tenant: str, timeout: float = 30.0):
        self.tenant = tenant
        self.api_base = f"https://{tenant}.api.civicclerk.com/v1"
        self.portal_base = f"https://{tenant.lower()}.portal.civicclerk.com"
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
                    "Accept": "application/json",
                },
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_categories(self) -> List[Dict[str, Any]]:
        """List all event categories (boards).

        Returns list of dicts with id, categoryDesc, etc.
        """
        client = await self._ensure_client()
        try:
            resp = await client.get(f"{self.api_base}/EventCategories")
            if resp.status_code != 200:
                logger.warning("[CivicClerk] HTTP %d listing categories", resp.status_code)
                return []
            data = resp.json()
            categories = data.get("value", data) if isinstance(data, dict) else data
            logger.info("[CivicClerk] Found %d categories", len(categories))
            return categories
        except Exception as exc:
            logger.error("[CivicClerk] Error listing categories: %s", exc)
            return []

    def find_category_id(self, categories: List[Dict[str, Any]], search_name: str) -> Optional[int]:
        """Find a category ID by name (fuzzy match on categoryDesc)."""
        search_lower = search_name.lower()
        for cat in categories:
            desc = (cat.get("categoryDesc") or cat.get("name") or "").lower()
            if search_lower in desc or desc in search_lower:
                return cat.get("id")
        return None

    async def list_events(
        self,
        category_id: Optional[int] = None,
        top: int = 200,
        min_year: int = 2024,
    ) -> List[Dict[str, Any]]:
        """List events (meetings) from CivicClerk OData API.

        Args:
            category_id: Filter by event category (board) ID
            top: Max results to return
            min_year: Only include events from this year onwards

        Returns:
            List of event dicts with meeting info and file URLs
        """
        client = await self._ensure_client()
        params = {
            "$orderby": "eventDate desc",
            "$top": str(top),
        }

        filters = []
        if category_id is not None:
            filters.append(f"eventCategoryId eq {category_id}")
        if min_year:
            filters.append(f"year(eventDate) ge {min_year}")

        if filters:
            params["$filter"] = " and ".join(filters)

        try:
            resp = await client.get(f"{self.api_base}/Events", params=params)
            if resp.status_code != 200:
                logger.warning("[CivicClerk] HTTP %d listing events", resp.status_code)
                return []
            data = resp.json()
            events = data.get("value", data) if isinstance(data, dict) else data
            logger.info("[CivicClerk] Found %d events (category=%s)", len(events), category_id)
            return events
        except Exception as exc:
            logger.error("[CivicClerk] Error listing events: %s", exc)
            return []

    def extract_meetings_from_events(
        self,
        events: List[Dict[str, Any]],
        board_name: str = "",
    ) -> List[Dict[str, Any]]:
        """Convert CivicClerk events to our standard meeting format.

        Extracts meetings that have minutes files available.
        """
        meetings = []
        for event in events:
            # Check for minutes file
            minutes_file = event.get("minutesFile") or event.get("minutesFileUrl")
            file_url_found = None
            
            if isinstance(minutes_file, dict):
                if minutes_file.get("minutesId") != 0:
                    file_url_found = minutes_file.get("fileUrl") or minutes_file.get("url")
            elif isinstance(minutes_file, str):
                file_url_found = minutes_file

            if not file_url_found:
                # Check publishedFiles for minutes
                published = event.get("publishedFiles", [])
                if isinstance(published, list):
                    for f in published:
                        name = (f.get("name") or f.get("fileName") or "").lower()
                        if "minute" in name:
                            file_id_val = f.get("fileId")
                            if file_id_val:
                                file_url_found = f"{self.api_base}/Meetings/GetMeetingFileStream(fileId={file_id_val},plainText=false)"
                            else:
                                file_url_found = f.get("streamUrl") or f.get("fileUrl") or f.get("url")
                            break

            if not file_url_found:
                continue

            # Parse date
            event_date = event.get("eventDate")
            meeting_date = None
            if event_date:
                try:
                    if isinstance(event_date, str):
                        # OData date format: "2025-01-15T00:00:00Z"
                        meeting_date = datetime.fromisoformat(
                            event_date.replace("Z", "+00:00")
                        ).date()
                    elif isinstance(event_date, datetime):
                        meeting_date = event_date.date()
                except (ValueError, TypeError):
                    pass

            title = event.get("eventCategoryName") or event.get("name") or board_name
            event_title = event.get("name") or event.get("title") or ""
            if event_title and event_title != title:
                title = f"{title} — {event_title}"

            # Build PDF URL if it's a relative path
            if isinstance(file_url_found, str):
                if not file_url_found.startswith("http"):
                    if not file_url_found.startswith("/"):
                        file_url_found = f"/{file_url_found}"
                    file_url_found = f"{self.portal_base}{file_url_found}"

            meetings.append({
                "event_id": event.get("id"),
                "title": title.strip(" —"),
                "meeting_date": meeting_date,
                "minutes_url": file_url_found,
                "agenda_url": event.get("agendaFile") or event.get("agendaFileUrl"),
            })

        meetings.sort(key=lambda m: m.get("meeting_date") or date.min, reverse=True)
        return meetings

    async def download_pdf(self, url: str) -> Optional[bytes]:
        """Download a PDF from a CivicClerk file URL."""
        client = await self._ensure_client()
        try:
            resp = await client.get(
                url, 
                timeout=60.0,
                headers={"Accept": "application/pdf, application/octet-stream, */*"}
            )
            if resp.status_code != 200:
                logger.warning("[CivicClerk] HTTP %d downloading %s", resp.status_code, url)
                return None
            content = resp.content
            if len(content) < 200:
                return None
            return content
        except Exception as exc:
            logger.warning("[CivicClerk] Download error %s: %s", url, exc)
            return None

    @staticmethod
    def extract_pdf_text(pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes using pdfplumber."""
        if pdfplumber is None:
            logger.warning("[CivicClerk] pdfplumber not installed")
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
            logger.warning("[CivicClerk] PDF extraction error: %s", exc)
            return ""
