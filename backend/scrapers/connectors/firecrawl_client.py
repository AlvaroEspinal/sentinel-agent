"""
Firecrawl API Client — Web scraping for town websites.

Used to crawl and extract structured content from:
- Town meeting minutes pages (HTML + linked PDFs)
- Permit portal pages without APIs
- Zoning bylaw pages
- Town budget/capital improvement documents

Firecrawl handles JavaScript rendering, anti-bot detection, and
converts HTML to clean markdown with metadata.

Supports Browser Actions mode for sites that require interaction
(clicking through Cloudflare, filling forms, navigating SPAs).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v1"


class FirecrawlClient:
    """Async client for the Firecrawl web scraping API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = FIRECRAWL_BASE_URL,
        timeout_s: float = 120.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client: Optional[Any] = None

        if not self.api_key:
            logger.warning("FIRECRAWL_API_KEY not set — Firecrawl client will fail")

    async def _ensure_client(self) -> Any:
        if self._client is None:
            if httpx is None:
                raise RuntimeError("httpx is required: pip install httpx")
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s, connect=15.0),
                limits=httpx.Limits(max_connections=5),
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ── Single Page Scrape ────────────────────────────────────────────────

    async def scrape(
        self,
        url: str,
        formats: Optional[List[str]] = None,
        only_main_content: bool = True,
        wait_for: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """Scrape a single URL and return structured content.

        Args:
            url: The URL to scrape
            formats: Output formats — ["markdown"], ["html"], ["markdown", "links"], etc.
            only_main_content: Strip nav/footer/sidebar (recommended)
            wait_for: Milliseconds to wait for JS rendering

        Returns:
            Dict with keys: markdown, html, metadata, links (depending on formats)
            None on failure
        """
        client = await self._ensure_client()

        payload: Dict[str, Any] = {
            "url": url,
            "formats": formats or ["markdown", "links"],
            "onlyMainContent": only_main_content,
        }
        if wait_for > 0:
            payload["waitFor"] = wait_for

        for attempt in range(self.max_retries):
            try:
                resp = await client.post(
                    f"{self.base_url}/scrape",
                    json=payload,
                    headers=self._headers(),
                )

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success"):
                        return data.get("data", {})
                    logger.warning("[Firecrawl] Scrape returned success=false for %s", url)
                    return None

                if resp.status_code == 429:
                    wait_time = 10 * (attempt + 1)
                    logger.warning("[Firecrawl] Rate limited, waiting %ds...", wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                logger.warning(
                    "[Firecrawl] Scrape HTTP %d for %s (attempt %d/%d)",
                    resp.status_code, url, attempt + 1, self.max_retries,
                )
                await asyncio.sleep(3 * (attempt + 1))

            except Exception as exc:
                logger.warning(
                    "[Firecrawl] Scrape error for %s: %s (attempt %d/%d)",
                    url, exc, attempt + 1, self.max_retries,
                )
                await asyncio.sleep(3 * (attempt + 1))

        logger.error("[Firecrawl] Failed to scrape %s after %d attempts", url, self.max_retries)
        return None

    # ── Browser Actions Scrape ─────────────────────────────────────────────

    async def scrape_with_actions(
        self,
        url: str,
        actions: List[Dict[str, Any]],
        formats: Optional[List[str]] = None,
        only_main_content: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Scrape a URL with browser actions (click, type, scroll, wait, etc.).

        This replaces local Playwright for sites that need interaction —
        Cloudflare challenges, form submissions, SPA navigation, etc.
        Firecrawl runs the browser remotely, so no local display needed.

        Args:
            url: The URL to navigate to
            actions: List of action dicts. Each action has a "type" key plus
                type-specific params. Supported types:
                - {"type": "wait", "milliseconds": 2000}
                - {"type": "click", "selector": "#button"}
                - {"type": "write", "text": "hello", "selector": "#input"}
                - {"type": "press", "key": "Enter"}
                - {"type": "scroll", "direction": "down", "amount": 3}
                - {"type": "screenshot"}  (returns screenshot in response)
                - {"type": "scrape"}  (captures page state mid-sequence)
                - {"type": "executeJavascript", "script": "return document.title"}
            formats: Output formats — ["markdown"], ["html"], etc.
            only_main_content: Strip nav/footer/sidebar

        Returns:
            Dict with keys: markdown, html, metadata, actions_results, etc.
            None on failure

        Limits:
            - Max 50 actions per request
            - Max 60 seconds combined wait time
            - Not supported for PDF URLs
        """
        if len(actions) > 50:
            logger.warning("[Firecrawl] Truncating actions to 50 (limit)")
            actions = actions[:50]

        client = await self._ensure_client()

        payload: Dict[str, Any] = {
            "url": url,
            "formats": formats or ["markdown"],
            "onlyMainContent": only_main_content,
            "actions": actions,
        }

        for attempt in range(self.max_retries):
            try:
                resp = await client.post(
                    f"{self.base_url}/scrape",
                    json=payload,
                    headers=self._headers(),
                )

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success"):
                        return data.get("data", {})
                    logger.warning(
                        "[Firecrawl] Browser scrape returned success=false for %s", url
                    )
                    return None

                if resp.status_code == 429:
                    wait_time = 10 * (attempt + 1)
                    logger.warning("[Firecrawl] Rate limited, waiting %ds...", wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                logger.warning(
                    "[Firecrawl] Browser scrape HTTP %d for %s (attempt %d/%d)",
                    resp.status_code, url, attempt + 1, self.max_retries,
                )
                await asyncio.sleep(3 * (attempt + 1))

            except Exception as exc:
                logger.warning(
                    "[Firecrawl] Browser scrape error for %s: %s (attempt %d/%d)",
                    url, exc, attempt + 1, self.max_retries,
                )
                await asyncio.sleep(3 * (attempt + 1))

        logger.error(
            "[Firecrawl] Failed browser scrape %s after %d attempts",
            url, self.max_retries,
        )
        return None

    # ── Action Builders (convenience) ────────────────────────────────────

    @staticmethod
    def action_wait(ms: int = 2000) -> Dict[str, Any]:
        """Wait for JS rendering / Cloudflare challenge."""
        return {"type": "wait", "milliseconds": ms}

    @staticmethod
    def action_click(selector: str) -> Dict[str, Any]:
        """Click an element by CSS selector."""
        return {"type": "click", "selector": selector}

    @staticmethod
    def action_write(selector: str, text: str) -> Dict[str, Any]:
        """Type text into an input field."""
        return {"type": "write", "text": text, "selector": selector}

    @staticmethod
    def action_press(key: str) -> Dict[str, Any]:
        """Press a keyboard key (e.g. 'Enter', 'Tab')."""
        return {"type": "press", "key": key}

    @staticmethod
    def action_scroll(direction: str = "down", amount: int = 3) -> Dict[str, Any]:
        """Scroll the page."""
        return {"type": "scroll", "direction": direction, "amount": amount}

    @staticmethod
    def action_screenshot() -> Dict[str, Any]:
        """Take a screenshot (returned in response)."""
        return {"type": "screenshot"}

    @staticmethod
    def action_scrape() -> Dict[str, Any]:
        """Capture current page state mid-action-sequence."""
        return {"type": "scrape"}

    @staticmethod
    def action_execute_js(script: str) -> Dict[str, Any]:
        """Execute JavaScript and return result."""
        return {"type": "executeJavascript", "script": script}

    # ── Multi-Page Crawl ──────────────────────────────────────────────────

    async def crawl(
        self,
        url: str,
        max_pages: int = 50,
        include_paths: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
        poll_interval_s: float = 5.0,
        max_wait_s: float = 300.0,
        wait_for: int = 0,
    ) -> List[Dict[str, Any]]:
        """Crawl a website starting from URL, return all discovered pages.

        Args:
            url: Starting URL to crawl
            max_pages: Maximum pages to crawl
            include_paths: URL path patterns to include (glob-style)
            exclude_paths: URL path patterns to exclude
            poll_interval_s: How often to poll for job completion
            max_wait_s: Maximum time to wait for crawl to complete
            wait_for: Milliseconds to wait for JS rendering on each page

        Returns:
            List of page dicts with markdown, metadata, links
        """
        client = await self._ensure_client()

        scrape_opts: Dict[str, Any] = {
            "formats": ["markdown", "links"],
            "onlyMainContent": True,
        }
        if wait_for > 0:
            scrape_opts["waitFor"] = wait_for

        payload: Dict[str, Any] = {
            "url": url,
            "limit": max_pages,
            "scrapeOptions": scrape_opts,
        }
        if include_paths:
            payload["includePaths"] = include_paths
        if exclude_paths:
            payload["excludePaths"] = exclude_paths

        # Start crawl job
        try:
            resp = await client.post(
                f"{self.base_url}/crawl",
                json=payload,
                headers=self._headers(),
            )

            if resp.status_code not in (200, 201):
                logger.error("[Firecrawl] Crawl start failed: HTTP %d", resp.status_code)
                return []

            job_data = resp.json()
            if not job_data.get("success"):
                logger.error("[Firecrawl] Crawl start returned success=false")
                return []

            job_id = job_data.get("id")
            if not job_id:
                logger.error("[Firecrawl] Crawl start returned no job ID")
                return []

            logger.info("[Firecrawl] Crawl started: job=%s for %s", job_id, url)

        except Exception as exc:
            logger.error("[Firecrawl] Crawl start error: %s", exc)
            return []

        # Poll for completion
        start_time = time.monotonic()
        all_pages: List[Dict[str, Any]] = []

        while (time.monotonic() - start_time) < max_wait_s:
            await asyncio.sleep(poll_interval_s)

            try:
                status_resp = await client.get(
                    f"{self.base_url}/crawl/{job_id}",
                    headers=self._headers(),
                )

                if status_resp.status_code != 200:
                    logger.warning("[Firecrawl] Crawl poll HTTP %d", status_resp.status_code)
                    continue

                status_data = status_resp.json()
                status = status_data.get("status", "unknown")

                if status == "completed":
                    pages = status_data.get("data", [])
                    all_pages.extend(pages)

                    # Handle pagination (Firecrawl returns paginated results)
                    next_url = status_data.get("next")
                    while next_url:
                        try:
                            next_resp = await client.get(
                                next_url, headers=self._headers()
                            )
                            if next_resp.status_code == 200:
                                next_data = next_resp.json()
                                more_pages = next_data.get("data", [])
                                if more_pages:
                                    all_pages.extend(more_pages)
                                next_url = next_data.get("next")
                            else:
                                break
                        except Exception:
                            break

                    logger.info(
                        "[Firecrawl] Crawl completed: %d pages from %s",
                        len(all_pages), url,
                    )
                    return all_pages

                elif status == "failed":
                    logger.error("[Firecrawl] Crawl failed for %s", url)
                    return []

                else:
                    # Still running
                    total = status_data.get("total", "?")
                    completed = status_data.get("completed", "?")
                    logger.debug(
                        "[Firecrawl] Crawl in progress: %s/%s pages", completed, total
                    )

            except Exception as exc:
                logger.warning("[Firecrawl] Crawl poll error: %s", exc)

        logger.error("[Firecrawl] Crawl timed out after %.0fs for %s", max_wait_s, url)
        return all_pages  # Return whatever we got

    # ── Extract Links (convenience) ───────────────────────────────────────

    async def extract_links(
        self,
        url: str,
        link_pattern: Optional[str] = None,
    ) -> List[str]:
        """Scrape a page and extract all links, optionally filtered by pattern.

        Args:
            url: Page to scrape
            link_pattern: Substring filter for links (e.g. ".pdf", "minutes")

        Returns:
            List of URLs found on the page
        """
        result = await self.scrape(url, formats=["links"])
        if not result:
            return []

        links = result.get("links", [])
        if not links:
            # Try extracting from markdown
            metadata = result.get("metadata", {})
            links = metadata.get("links", [])

        if link_pattern:
            pattern_lower = link_pattern.lower()
            links = [l for l in links if pattern_lower in l.lower()]

        return links

    # ── Scrape Multiple Pages ─────────────────────────────────────────────

    async def scrape_batch(
        self,
        urls: List[str],
        concurrency: int = 3,
        delay_s: float = 1.0,
    ) -> List[Optional[Dict[str, Any]]]:
        """Scrape multiple URLs with concurrency control.

        Args:
            urls: List of URLs to scrape
            concurrency: Max concurrent scrapes
            delay_s: Delay between starting each scrape

        Returns:
            List of results (None for failed pages)
        """
        semaphore = asyncio.Semaphore(concurrency)
        results: List[Optional[Dict[str, Any]]] = [None] * len(urls)

        async def _scrape_one(idx: int, url: str):
            async with semaphore:
                if idx > 0:
                    await asyncio.sleep(delay_s)
                results[idx] = await self.scrape(url)

        tasks = [_scrape_one(i, url) for i, url in enumerate(urls)]
        await asyncio.gather(*tasks, return_exceptions=True)
        return results
