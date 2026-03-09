"""
scrape_all_cip.py — Capital Improvement Plan scraper for 12 MA towns.

Runs sequentially, 2s delay between towns, 90s timeout per town.
Output: backend/data_cache/cip/{town_id}_cip.json

Usage:
    python3 -m backend.scripts.scrape_all_cip
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Path bootstrap so we can import backend modules ──────────────────────────
ROOT = Path(__file__).resolve().parents[2]   # sentinel-agent/
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

# ── Load .env BEFORE any module that calls os.getenv at import time ──────────
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(ROOT / "backend" / ".env", override=True)
except ImportError:
    pass  # dotenv not installed — rely on shell env

from backend.scrapers.connectors.firecrawl_client import FirecrawlClient
from backend.scrapers.connectors.cip_extractor import CIPExtractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scrape_all_cip")

# ── Output directory ──────────────────────────────────────────────────────────
CIP_DIR = ROOT / "backend" / "data_cache" / "cip"
CIP_DIR.mkdir(parents=True, exist_ok=True)

# ── Per-town config ───────────────────────────────────────────────────────────
TOWNS: List[Dict[str, Any]] = [
    {
        "id": "newton",
        "name": "Newton",
        "urls": [
            "https://www.newtonma.gov/city-hall/finance/capital-improvement-program",
            "https://www.newtonma.gov/government/finance/capital-improvement-program",
            "https://www.newtonma.gov/city-hall/finance",
        ],
    },
    {
        "id": "wellesley",
        "name": "Wellesley",
        "urls": [
            "https://www.wellesleyma.gov/departments/finance",
            "https://www.wellesleyma.gov/800/Capital-Improvement-Plan",
            "https://www.wellesleyma.gov/finance/capital-improvement",
        ],
    },
    {
        "id": "weston",
        "name": "Weston",
        "urls": [
            "https://www.weston.org/departments/finance",
            "https://www.weston.org/384/Capital-Improvement-Plan",
            "https://westonma.gov/finance/capital-improvement",
        ],
    },
    {
        "id": "brookline",
        "name": "Brookline",
        "urls": [
            "https://www.brooklinema.gov/finance",
            "https://www.brooklinema.gov/170/Capital-Improvement-Plan",
            "https://www.brooklinema.gov/departments/finance/capital-improvement",
        ],
    },
    {
        "id": "needham",
        "name": "Needham",
        "urls": [
            "https://www.needhamma.gov/finance",
            "https://www.needhamma.gov/349/Capital-Improvement-Plan",
            "https://needhamma.gov/departments/finance",
        ],
    },
    {
        "id": "dover",
        "name": "Dover",
        "urls": [
            "https://www.doverma.org/finance",
            "https://www.doverma.org/139/Capital-Improvement",
            "https://www.doverma.org/departments/finance",
        ],
    },
    {
        "id": "sherborn",
        "name": "Sherborn",
        "urls": [
            "https://www.townof.sherborn.ma.us/finance",
            "https://www.townof.sherborn.ma.us/capital-improvement",
            "https://www.sherbornma.org/finance",
        ],
    },
    {
        "id": "natick",
        "name": "Natick",
        "urls": [
            "https://www.natickma.gov/finance",
            "https://www.natickma.gov/261/Capital-Improvement-Plan",
            "https://www.natickma.gov/departments/finance",
        ],
    },
    {
        "id": "wayland",
        "name": "Wayland",
        "urls": [
            "https://www.wayland.ma.us/finance",
            "https://www.wayland.ma.us/256/Capital-Improvement-Plan",
            "https://wayland.ma.us/departments/finance",
        ],
    },
    {
        "id": "lincoln",
        "name": "Lincoln",
        "urls": [
            "https://www.lincolntown.org/finance",
            "https://www.lincolntown.org/259/Capital-Improvement-Plan",
            "https://lincolntown.org/departments/finance",
        ],
    },
    {
        "id": "concord",
        "name": "Concord",
        "urls": [
            "https://www.concordma.gov/finance",
            "https://www.concordma.gov/365/Capital-Improvement-Plan",
            "https://concordma.gov/departments/finance",
        ],
    },
    {
        "id": "lexington",
        "name": "Lexington",
        "urls": [
            "https://www.lexingtonma.gov/finance/capital-improvement-program",
            "https://www.lexingtonma.gov/departments/finance",
            "https://www.lexingtonma.gov/276/Capital-Improvement-Program",
        ],
    },
]

# ── Keyword patterns for CIP content detection ───────────────────────────────
CIP_KEYWORDS = re.compile(
    r"capital\s+improvement|capital\s+program|CIP\b|capital\s+plan|"
    r"capital\s+budget|five[- ]year\s+plan|infrastructure\s+plan",
    re.IGNORECASE,
)

PDF_CIP_PATTERN = re.compile(
    r"(?:capital[_\-\s]*improvement|capital[_\-\s]*program|capital[_\-\s]*plan|"
    r"\bcip\b|five[_\-\s]*year)",
    re.IGNORECASE,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_pdf_links(data: Dict[str, Any]) -> List[str]:
    """Pull PDF URLs out of Firecrawl response data (links + markdown hrefs)."""
    pdfs: List[str] = []

    # 1. From explicit links array
    for link in data.get("links", []):
        if isinstance(link, str) and link.lower().endswith(".pdf"):
            pdfs.append(link)
        elif isinstance(link, dict):
            href = link.get("href") or link.get("url") or ""
            if href.lower().endswith(".pdf"):
                pdfs.append(href)

    # 2. From markdown — [text](url.pdf) patterns
    markdown = data.get("markdown", "") or ""
    for href in re.findall(r'\]\(([^)]+\.pdf[^)]*)\)', markdown, re.IGNORECASE):
        pdfs.append(href)

    # Deduplicate while preserving order
    seen: set = set()
    unique = []
    for p in pdfs:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _is_cip_pdf(url: str) -> bool:
    """Return True if the PDF URL looks like a Capital Improvement Plan."""
    return bool(PDF_CIP_PATTERN.search(url))


def _score_pdf(url: str) -> int:
    """Higher score = more likely to be THE CIP document."""
    url_lower = url.lower()
    score = 0
    if "capital" in url_lower:
        score += 3
    if "cip" in url_lower:
        score += 4
    if "improvement" in url_lower:
        score += 2
    if "program" in url_lower or "plan" in url_lower:
        score += 1
    # Prefer recent years
    for yr in ["2026", "2025", "2024", "2027"]:
        if yr in url_lower:
            score += 2
            break
    return score


def _page_mentions_cip(data: Dict[str, Any]) -> bool:
    """Return True if page content mentions capital improvement topics."""
    text = (data.get("markdown") or "") + " " + (data.get("html") or "")
    return bool(CIP_KEYWORDS.search(text))


def _save_result(town_id: str, result: Dict[str, Any]) -> Path:
    out_path = CIP_DIR / f"{town_id}_cip.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    return out_path


# ── Per-town scrape logic ─────────────────────────────────────────────────────

async def scrape_town(
    town: Dict[str, Any],
    fc: FirecrawlClient,
    extractor: CIPExtractor,
    timeout_s: float = 90.0,
) -> Dict[str, Any]:
    """Scrape CIP data for a single town. Returns structured result dict."""

    town_id = town["id"]
    town_name = town["name"]
    urls_to_try: List[str] = town["urls"]

    searched_urls: List[str] = []
    cip_page_url: Optional[str] = None
    cip_pdfs: List[str] = []
    page_data: Optional[Dict[str, Any]] = None

    logger.info("[%s] Starting scrape — %d URLs to try", town_name, len(urls_to_try))

    # ── Step 1: Find a page that mentions CIP ──────────────────────────────
    for url in urls_to_try:
        searched_urls.append(url)
        logger.info("[%s] Trying: %s", town_name, url)

        try:
            data = await asyncio.wait_for(
                fc.scrape(url, formats=["markdown", "links"], only_main_content=True),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning("[%s] Timeout on %s", town_name, url)
            continue
        except Exception as exc:
            logger.warning("[%s] Error on %s: %s", town_name, url, exc)
            continue

        if data is None:
            logger.info("[%s] No data returned for %s", town_name, url)
            continue

        # Check if the page or its links reference CIP
        pdfs = _extract_pdf_links(data)
        cip_pdf_candidates = [p for p in pdfs if _is_cip_pdf(p)]

        if cip_pdf_candidates or _page_mentions_cip(data):
            logger.info(
                "[%s] CIP content found at %s (%d CIP PDFs, page mentions CIP: %s)",
                town_name, url, len(cip_pdf_candidates), _page_mentions_cip(data),
            )
            cip_page_url = url
            page_data = data
            cip_pdfs = sorted(
                cip_pdf_candidates,
                key=lambda u: _score_pdf(u),
                reverse=True,
            )
            break

        logger.info("[%s] No CIP content at %s — moving on", town_name, url)

    # ── Step 2: If no dedicated CIP page found, return not_found ───────────
    if cip_page_url is None:
        logger.warning("[%s] No CIP page found", town_name)
        result = {
            "town": town_name,
            "town_id": town_id,
            "status": "not_found",
            "searched_urls": searched_urls,
            "scraped_at": datetime.utcnow().isoformat() + "Z",
            "cip_page_url": None,
            "cip_pdf_urls": [],
            "projects": [],
            "project_count": 0,
        }
        _save_result(town_id, result)
        return result

    # ── Step 3: Try to scrape the best PDF or fall back to page text ────────
    extraction_text: str = ""
    extraction_source: str = "page_markdown"
    pdf_used: Optional[str] = None

    if cip_pdfs:
        best_pdf = cip_pdfs[0]
        logger.info("[%s] Attempting to scrape CIP PDF: %s", town_name, best_pdf)
        try:
            pdf_data = await asyncio.wait_for(
                fc.scrape(best_pdf, formats=["markdown"], only_main_content=False),
                timeout=45.0,
            )
            if pdf_data and pdf_data.get("markdown"):
                extraction_text = pdf_data["markdown"]
                extraction_source = "pdf"
                pdf_used = best_pdf
                logger.info(
                    "[%s] PDF scraped: %d chars", town_name, len(extraction_text)
                )
        except asyncio.TimeoutError:
            logger.warning("[%s] PDF scrape timeout for %s", town_name, best_pdf)
        except Exception as exc:
            logger.warning("[%s] PDF scrape error: %s", town_name, exc)

    # Fall back to page markdown if no PDF text
    if not extraction_text and page_data:
        extraction_text = page_data.get("markdown") or ""
        extraction_source = "page_markdown"
        logger.info(
            "[%s] Falling back to page markdown (%d chars)", town_name, len(extraction_text)
        )

    # ── Step 4: LLM extraction ─────────────────────────────────────────────
    projects: List[Dict[str, Any]] = []
    extraction_result: Dict[str, Any] = {}

    if extraction_text.strip():
        logger.info(
            "[%s] Running LLM extraction on %d chars from '%s'",
            town_name, len(extraction_text), extraction_source,
        )
        try:
            extraction_result = await asyncio.wait_for(
                extractor.extract_cip_projects(
                    text=extraction_text,
                    town_name=town_name,
                    doc_type="capital_plan",
                ),
                timeout=60.0,
            )
            projects = extraction_result.get("projects", [])
            logger.info("[%s] Extracted %d projects", town_name, len(projects))
        except asyncio.TimeoutError:
            logger.error("[%s] LLM extraction timed out", town_name)
        except Exception as exc:
            logger.error("[%s] LLM extraction error: %s", town_name, exc)
    else:
        logger.warning("[%s] No text available for LLM extraction", town_name)

    # ── Step 5: Build + save result ────────────────────────────────────────
    status = "found" if projects else ("found_no_projects" if extraction_text else "not_found")

    result: Dict[str, Any] = {
        "town": town_name,
        "town_id": town_id,
        "status": status,
        "searched_urls": searched_urls,
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "cip_page_url": cip_page_url,
        "cip_pdf_urls": cip_pdfs,
        "pdf_used_for_extraction": pdf_used,
        "extraction_source": extraction_source,
        "llm_provider": extraction_result.get("provider"),
        "llm_model": extraction_result.get("model"),
        "projects": projects,
        "project_count": len(projects),
    }

    out_path = _save_result(town_id, result)
    logger.info("[%s] Saved to %s", town_name, out_path)
    return result


# ── Main entrypoint ───────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("=" * 60)
    logger.info("CIP Scraper — %d towns", len(TOWNS))
    logger.info("Output: %s", CIP_DIR)
    logger.info("Firecrawl key present: %s", bool(os.getenv("FIRECRAWL_API_KEY")))
    logger.info("OpenRouter key present: %s", bool(os.getenv("OPENROUTER_API_KEY")))
    logger.info("=" * 60)

    # Pass keys explicitly so they resolve after dotenv load
    fc = FirecrawlClient(api_key=os.getenv("FIRECRAWL_API_KEY", ""))
    extractor = CIPExtractor(api_key=os.getenv("OPENROUTER_API_KEY", ""))

    summary: List[Dict[str, Any]] = []
    start_total = time.perf_counter()

    for i, town in enumerate(TOWNS):
        if i > 0:
            logger.info("Sleeping 2s before next town...")
            await asyncio.sleep(2)

        town_start = time.perf_counter()
        logger.info("")
        logger.info("── [%d/%d] %s ─────────────────────────", i + 1, len(TOWNS), town["name"])

        try:
            result = await asyncio.wait_for(
                scrape_town(town, fc, extractor),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            logger.error("[%s] Town-level timeout (90s)", town["name"])
            result = {
                "town": town["name"],
                "town_id": town["id"],
                "status": "timeout",
                "scraped_at": datetime.utcnow().isoformat() + "Z",
                "projects": [],
                "project_count": 0,
                "searched_urls": town["urls"],
            }
            _save_result(town["id"], result)
        except Exception as exc:
            logger.error("[%s] Unexpected error: %s", town["name"], exc, exc_info=True)
            result = {
                "town": town["name"],
                "town_id": town["id"],
                "status": "error",
                "error": str(exc),
                "scraped_at": datetime.utcnow().isoformat() + "Z",
                "projects": [],
                "project_count": 0,
                "searched_urls": town["urls"],
            }
            _save_result(town["id"], result)

        elapsed = time.perf_counter() - town_start
        summary.append({
            "town": town["name"],
            "status": result.get("status"),
            "project_count": result.get("project_count", 0),
            "pdf_used": result.get("pdf_used_for_extraction"),
            "elapsed_s": round(elapsed, 1),
        })

    # Close Firecrawl HTTP client
    await fc.close()

    # ── Print summary table ────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - start_total
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY — %.1fs total", total_elapsed)
    logger.info("=" * 60)
    logger.info("%-14s  %-18s  %8s  %s", "Town", "Status", "Projects", "Elapsed")
    logger.info("-" * 60)
    total_projects = 0
    for row in summary:
        total_projects += row["project_count"]
        pdf_note = " [PDF]" if row["pdf_used"] else ""
        logger.info(
            "%-14s  %-18s  %8d  %.1fs%s",
            row["town"],
            row["status"],
            row["project_count"],
            row["elapsed_s"],
            pdf_note,
        )
    logger.info("-" * 60)
    logger.info("Total projects extracted: %d", total_projects)
    logger.info("Output directory: %s", CIP_DIR)

    # Save combined summary JSON
    summary_path = CIP_DIR / "_summary.json"
    with open(summary_path, "w") as f:
        json.dump(
            {
                "run_at": datetime.utcnow().isoformat() + "Z",
                "total_elapsed_s": round(total_elapsed, 1),
                "total_projects": total_projects,
                "towns": summary,
            },
            f,
            indent=2,
        )
    logger.info("Summary saved: %s", summary_path)


if __name__ == "__main__":
    asyncio.run(main())
