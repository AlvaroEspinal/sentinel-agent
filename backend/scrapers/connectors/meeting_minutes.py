"""
Meeting Minutes Scraper — Municipal board minutes extraction.

Scrapes meeting minutes from town websites using Firecrawl,
then extracts structured intelligence using LLM (Claude).

Pipeline:
1. Firecrawl crawls the town's agenda center / meeting minutes pages
2. Extracts links to individual meeting documents (HTML or PDF)
3. Scrapes/downloads each document
4. Extracts text from PDFs using pdfplumber
5. Sends text to LLM for structured extraction
6. Stores in municipal_documents table

Boards covered:
- Select Board / Board of Selectmen / City Council
- Planning Board
- Zoning Board of Appeals (ZBA)
- Conservation Commission
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
from datetime import date, datetime
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

from .firecrawl_client import FirecrawlClient
from .town_config import BoardConfig, TownConfig


class MeetingMinutesScraper:
    """Scrapes and processes meeting minutes for a town."""

    def __init__(
        self,
        firecrawl: FirecrawlClient,
        llm_extractor: Optional[Any] = None,
        max_pages_per_board: int = 20,
    ):
        self.firecrawl = firecrawl
        self.llm_extractor = llm_extractor
        self.max_pages_per_board = max_pages_per_board
        self._http: Optional[Any] = None

    async def _ensure_http(self) -> Any:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                limits=httpx.Limits(max_connections=5),
                follow_redirects=True,
            )
        return self._http

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None

    # ── Main Entry Point ──────────────────────────────────────────────────

    async def scrape_town(
        self,
        town: TownConfig,
        boards: Optional[List[str]] = None,
        since_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Scrape meeting minutes for all boards in a town.

        Args:
            town: Town configuration
            boards: Optional list of board slugs to scrape (default: all)
            since_date: Only include documents after this date

        Returns:
            List of document dicts ready for database insertion
        """
        documents: List[Dict[str, Any]] = []

        for board in town.boards:
            if boards and board.slug not in boards:
                continue
            if not board.minutes_url:
                logger.info("[Minutes] Skipping %s/%s — no minutes URL configured",
                           town.name, board.name)
                continue

            try:
                board_docs = await self._scrape_board(town, board, since_date)
                documents.extend(board_docs)
                logger.info(
                    "[Minutes] %s/%s: %d documents found",
                    town.name, board.name, len(board_docs),
                )
            except Exception as exc:
                logger.error(
                    "[Minutes] Error scraping %s/%s: %s",
                    town.name, board.name, exc,
                )

        return documents

    # ── Board-Level Scraping ──────────────────────────────────────────────

    async def _scrape_board(
        self,
        town: TownConfig,
        board: BoardConfig,
        since_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Scrape meeting minutes for a single board."""
        logger.info("[Minutes] Scraping %s / %s from %s",
                    town.name, board.name, board.minutes_url)

        # Step 1: Crawl the agenda center page to find meeting links
        pages = await self.firecrawl.crawl(
            board.minutes_url,
            max_pages=self.max_pages_per_board,
            include_paths=[".*minutes.*", ".*agenda.*", ".*meeting.*"],
        )

        if not pages:
            # Fallback: scrape the main page for PDF links
            logger.info("[Minutes] No crawl results, trying direct scrape for PDFs")
            pdf_links = await self.firecrawl.extract_links(
                board.minutes_url, link_pattern=".pdf"
            )
            pages = [{"metadata": {"sourceURL": board.minutes_url}, "links": pdf_links}]

        documents = []

        for page in pages:
            metadata = page.get("metadata", {})
            page_url = metadata.get("sourceURL", "")
            markdown = page.get("markdown", "")
            links = page.get("links", [])

            # Extract PDF links from the page
            pdf_links = [l for l in links if ".pdf" in l.lower()]

            # Also look for PDF links in the markdown
            md_pdf_links = re.findall(r'\[([^\]]*)\]\((https?://[^\)]*\.pdf[^\)]*)\)', markdown)
            for link_text, link_url in md_pdf_links:
                if link_url not in pdf_links:
                    pdf_links.append(link_url)

            # Process each PDF
            for pdf_url in pdf_links:
                try:
                    doc = await self._process_document(
                        town=town,
                        board=board,
                        source_url=page_url,
                        file_url=pdf_url,
                        since_date=since_date,
                    )
                    if doc:
                        documents.append(doc)
                except Exception as exc:
                    logger.warning("[Minutes] Error processing %s: %s", pdf_url, exc)

            # Also process the HTML page itself if it has substantial content
            if markdown and len(markdown) > 500:
                meeting_date = self._extract_date_from_text(
                    metadata.get("title", "") + " " + markdown[:500]
                )
                if since_date and meeting_date and meeting_date < since_date:
                    continue

                content_hash = hashlib.sha256(markdown.encode()).hexdigest()
                doc = {
                    "town_id": town.id,
                    "doc_type": "meeting_minutes",
                    "board": board.slug,
                    "title": metadata.get("title", f"{board.name} Minutes"),
                    "meeting_date": meeting_date.isoformat() if meeting_date else None,
                    "source_url": page_url,
                    "file_url": None,
                    "content_text": markdown[:50000],  # Cap at 50K chars
                    "content_hash": content_hash,
                }

                # LLM extraction if available
                if self.llm_extractor and doc["content_text"]:
                    try:
                        extraction = await self.llm_extractor.extract_from_minutes(
                            doc["content_text"], town.name, board.name
                        )
                        doc["content_summary"] = extraction.get("summary")
                        doc["keywords"] = extraction.get("keywords", [])
                        doc["mentions"] = extraction.get("mentions", [])
                    except Exception as exc:
                        logger.warning("[Minutes] LLM extraction failed: %s", exc)

                documents.append(doc)

        return documents

    # ── Document Processing ───────────────────────────────────────────────

    async def _process_document(
        self,
        town: TownConfig,
        board: BoardConfig,
        source_url: str,
        file_url: str,
        since_date: Optional[date] = None,
    ) -> Optional[Dict[str, Any]]:
        """Download and extract text from a PDF document."""

        # Try to extract date from filename/URL
        meeting_date = self._extract_date_from_text(file_url)
        if since_date and meeting_date and meeting_date < since_date:
            return None

        # Download the PDF
        client = await self._ensure_http()
        try:
            resp = await client.get(file_url, timeout=30.0)
            if resp.status_code != 200:
                logger.warning("[Minutes] HTTP %d downloading %s", resp.status_code, file_url)
                return None

            pdf_bytes = resp.content
            if len(pdf_bytes) < 100:
                return None

        except Exception as exc:
            logger.warning("[Minutes] Download error for %s: %s", file_url, exc)
            return None

        # Extract text from PDF
        text = self._extract_pdf_text(pdf_bytes)
        if not text or len(text) < 100:
            logger.debug("[Minutes] No meaningful text extracted from %s", file_url)
            return None

        # If we didn't get a date from the URL, try from the content
        if not meeting_date:
            meeting_date = self._extract_date_from_text(text[:1000])

        content_hash = hashlib.sha256(text.encode()).hexdigest()

        # Infer title from filename
        filename = file_url.split("/")[-1].split("?")[0]
        title = filename.replace(".pdf", "").replace("-", " ").replace("_", " ").strip()
        if not title:
            title = f"{board.name} Minutes"

        doc = {
            "town_id": town.id,
            "doc_type": "meeting_minutes",
            "board": board.slug,
            "title": title,
            "meeting_date": meeting_date.isoformat() if meeting_date else None,
            "source_url": source_url,
            "file_url": file_url,
            "content_text": text[:50000],
            "page_count": None,  # Could count PDF pages if needed
            "file_size_bytes": len(pdf_bytes),
            "content_hash": content_hash,
        }

        # LLM extraction
        if self.llm_extractor and text:
            try:
                extraction = await self.llm_extractor.extract_from_minutes(
                    text[:20000], town.name, board.name
                )
                doc["content_summary"] = extraction.get("summary")
                doc["keywords"] = extraction.get("keywords", [])
                doc["mentions"] = extraction.get("mentions", [])
            except Exception as exc:
                logger.warning("[Minutes] LLM extraction failed for %s: %s", file_url, exc)

        return doc

    # ── PDF Text Extraction ───────────────────────────────────────────────

    @staticmethod
    def _extract_pdf_text(pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes using pdfplumber."""
        if pdfplumber is None:
            logger.warning("[Minutes] pdfplumber not installed — cannot extract PDF text")
            return ""

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)
                return "\n\n".join(pages_text)
        except Exception as exc:
            logger.warning("[Minutes] PDF extraction error: %s", exc)
            return ""

    # ── Date Extraction ───────────────────────────────────────────────────

    @staticmethod
    def _extract_date_from_text(text: str) -> Optional[date]:
        """Try to extract a meeting date from text/filename."""
        if not text:
            return None

        # Pattern 1: YYYY-MM-DD
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass

        # Pattern 2: MM/DD/YYYY or MM-DD-YYYY
        match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', text)
        if match:
            try:
                return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
            except ValueError:
                pass

        # Pattern 3: Month DD, YYYY (e.g. "January 15, 2025")
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
        }
        match = re.search(
            r'(january|february|march|april|may|june|july|august|'
            r'september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})',
            text.lower(),
        )
        if match:
            try:
                month = months[match.group(1)]
                return date(int(match.group(3)), month, int(match.group(2)))
            except (ValueError, KeyError):
                pass

        # Pattern 4: YYYYMMDD in filename
        match = re.search(r'(\d{4})(\d{2})(\d{2})', text)
        if match:
            try:
                d = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                if 2000 <= d.year <= 2030:
                    return d
            except ValueError:
                pass

        return None
