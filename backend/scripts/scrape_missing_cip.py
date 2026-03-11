"""
scrape_missing_cip.py — CIP scraper for 4 towns that failed in prior runs.

These towns failed in the automated scrape_all_cip.py runs (status: not_found /
timeout) because the original URL guesses were wrong or the sites required
special handling (JS rendering, WAF blocks, etc.).

This script uses RESEARCHED, VERIFIED URLs found through web search in March 2026.

Target towns:
  1. Dover     — Uses "Bluebook" (Warrant Committee Report), not a separate CIP page
  2. Lincoln   — Uses Finance Committee Report & Capital Planning Committee docs
  3. Newton    — Has a proper CIP page at newtonma.gov/government/finance/capital-improvement-plan
  4. Wayland   — Uses Capital Improvement Planning Committee reports on wayland.ma.us

Usage:
    python3 -m backend.scripts.scrape_missing_cip          # run all 4
    python3 -m backend.scripts.scrape_missing_cip --town newton  # single town

Notes:
    - Requires FIRECRAWL_API_KEY and OPENROUTER_API_KEY in .env
    - Newton & Wayland pages use JavaScript rendering → uses scrape_with_actions
    - Dover's Bluebook is a direct PDF → Firecrawl PDF scrape
    - Lincoln's capital info is split across Capital Planning Committee + FinCom report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Path bootstrap ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]   # sentinel-agent/
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

# ── Load .env BEFORE any module that calls os.getenv at import time ────────────
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(ROOT / "backend" / ".env", override=True)
except ImportError:
    pass

from backend.scrapers.connectors.firecrawl_client import FirecrawlClient
from backend.scrapers.connectors.cip_extractor import CIPExtractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scrape_missing_cip")

# ── Output directory ────────────────────────────────────────────────────────────
CIP_DIR = ROOT / "backend" / "data_cache" / "cip"
CIP_DIR.mkdir(parents=True, exist_ok=True)

# ── CIP keyword detection ──────────────────────────────────────────────────────
CIP_KEYWORDS = re.compile(
    r"capital\s+improvement|capital\s+program|CIP\b|capital\s+plan|"
    r"capital\s+budget|five[- ]year\s+plan|infrastructure\s+plan|"
    r"capital\s+project|warrant\s+committee|capital\s+request",
    re.IGNORECASE,
)

PDF_CIP_PATTERN = re.compile(
    r"(?:capital[_\-\s]*improvement|capital[_\-\s]*program|capital[_\-\s]*plan|"
    r"\bcip\b|five[_\-\s]*year|capital[_\-\s]*budget|bluebook|warrant[_\-\s]*committee|"
    r"capital[_\-\s]*request|financial[_\-\s]*plan)",
    re.IGNORECASE,
)

# ══════════════════════════════════════════════════════════════════════════════
# TOWN CONFIGURATIONS — Researched & verified URLs (March 2026)
# ══════════════════════════════════════════════════════════════════════════════

TOWNS: List[Dict[str, Any]] = [
    {
        "id": "dover",
        "name": "Dover",
        "notes": (
            "Dover does NOT have a standalone CIP document. Capital budget info "
            "is in the annual 'Bluebook' (Warrant Committee Report) published "
            "before May Town Meeting. The Capital Budget Committee reviews and "
            "recommends the annual capital budget. Direct PDF links to the "
            "Bluebook are on the Document Center."
        ),
        # Strategy: Try the Capital Budget Committee page first (it links to
        # the Bluebook PDF), then fallback to direct Bluebook PDF URLs and
        # the Town Budget & Finances page.
        "urls": [
            # Capital Budget Committee page — has links to Bluebook + agendas
            "https://www.doverma.gov/290/Capital-Budget-Committee",
            # 2025 Bluebook PDF (confirmed working from prior extraction)
            "https://www.doverma.gov/documentcenter/view/4554",
            # Town Budget & Finances landing page
            "https://www.doverma.gov/530/Town-Budget-Finances",
            # Warrant Committee page — publishes the Bluebook
            "https://www.doverma.gov/338/Warrant-Committee",
            # Agenda Center for Capital Budget Committee
            "https://www.doverma.gov/AgendaCenter/Capital-Budget-Committee-8",
        ],
        "use_actions": False,
    },
    {
        "id": "lincoln",
        "name": "Lincoln",
        "notes": (
            "Lincoln has a Capital Planning Committee (CPC) that produces a "
            "rolling 5-year capital forecast. Capital project info also appears "
            "in the Finance Committee's annual report and Town Meeting warrant. "
            "The FY2026 FinCom report has the most structured capital data. "
            "The Capital Planning Committee page at lincolntown.org/119 has "
            "committee info but may not directly link to the latest PDF report."
        ),
        "urls": [
            # Capital Planning Committee page
            "https://www.lincolntown.org/119/Capital-Planning-Committee",
            # Finance Committee Documents (links to FinCom reports with capital)
            "https://www.lincolntown.org/416/Finance-Committee-Documents",
            # 2025 Annual Town Meeting page (has warrant + FinCom report)
            "https://www.lincolntown.org/1538/2025-Annual-Town-Meeting",
            # Budget Information page
            "https://www.lincolntown.org/1487/Budget-Information",
            # Finance Committee main page
            "https://www.lincolntown.org/135/Finance-Committee",
            # FY2026 FinCom Report PDF (confirmed working from prior extraction)
            "https://www.lincolntown.org/DocumentCenter/View/98197/20250329-Fincom-Report-FY26--FINAL-",
        ],
        "use_actions": False,
    },
    {
        "id": "newton",
        "name": "Newton",
        "notes": (
            "Newton has a proper Capital Improvement Plan (CIP) program run by "
            "the Finance Department. The CIP page uses JavaScript rendering "
            "(requires wait_for_actions). Newton also has a CIP Archives page. "
            "The FY2027-FY2031 CIP is the latest document. The direct PDF link "
            "was confirmed working from prior manual extraction."
        ),
        "urls": [
            # Main CIP page (CORRECT URL — previous scraper had wrong path)
            "https://www.newtonma.gov/government/finance/capital-improvement-plan",
            # CIP Archives page
            "https://www.newtonma.gov/government/finance/cip-archives",
            # Finance department main page
            "https://www.newtonma.gov/government/finance",
            # Capital Projects page (DPW/Public Buildings perspective)
            "https://www.newtonma.gov/government/public-buildings/current-upcoming-projects",
        ],
        # Newton's site uses heavy JavaScript rendering
        "use_actions": True,
    },
    {
        "id": "wayland",
        "name": "Wayland",
        "notes": (
            "Wayland has a Capital Improvement Planning Committee (CIPC) that "
            "produces a 5-year capital plan. The FY2025-FY2029 CIP PDF was "
            "confirmed working. A newer FY2026-FY2030 plan may exist but the "
            "direct URL is on a meeting cloud blob (less reliable). The CIPC "
            "page, Annual Town Meeting warrant, and FY25 Budget page all have "
            "capital budget information."
        ),
        "urls": [
            # Capital Improvement Planning Committee page
            "https://www.wayland.ma.us/capital-improvement-planning-committee",
            # FY25 Budget Information (has capital budget details)
            "https://www.wayland.ma.us/select-board/pages/fy25-budget-information",
            # Annual Budgets page
            "https://www.wayland.ma.us/select-board/pages/annual-budgets",
            # FY2025-FY2029 Capital Plan PDF (confirmed working)
            "https://www.wayland.ma.us/sites/g/files/vyhlif9231/f/uploads/capital_report_fy25-fy29-v3-112023.pdf",
            # FY25 Town Capital Write-up for Warrant
            "https://www.wayland.ma.us/sites/g/files/vyhlif9231/f/uploads/fy25_town_capital_write-up_for_warrant_final_revised_5.12.2024.pdf",
            # 2025 Annual Town Meeting Warrant (contains FY26 capital budget)
            "https://www.wayland.ma.us/sites/g/files/vyhlif9231/f/uploads/atm_warrant_2025_final_0.pdf",
        ],
        # Wayland's site can be slow with JS
        "use_actions": True,
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_pdf_links(data: Dict[str, Any]) -> List[str]:
    """Pull PDF URLs out of Firecrawl response data."""
    pdfs: List[str] = []
    for link in data.get("links", []):
        if isinstance(link, str) and link.lower().endswith(".pdf"):
            pdfs.append(link)
        elif isinstance(link, dict):
            href = link.get("href") or link.get("url") or ""
            if href.lower().endswith(".pdf"):
                pdfs.append(href)
    markdown = data.get("markdown", "") or ""
    for href in re.findall(r'\]\(([^)]+\.pdf[^)]*)\)', markdown, re.IGNORECASE):
        pdfs.append(href)
    seen: set = set()
    unique = []
    for p in pdfs:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _is_cip_pdf(url: str) -> bool:
    return bool(PDF_CIP_PATTERN.search(url))


def _score_pdf(url: str) -> int:
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
    if "bluebook" in url_lower or "blue-book" in url_lower:
        score += 4
    if "warrant" in url_lower:
        score += 2
    if "fincom" in url_lower or "finance" in url_lower:
        score += 1
    for yr in ["2027", "2026", "2025", "2028"]:
        if yr in url_lower:
            score += 2
            break
    return score


def _page_mentions_cip(data: Dict[str, Any]) -> bool:
    text = (data.get("markdown") or "") + " " + (data.get("html") or "")
    return bool(CIP_KEYWORDS.search(text))


def _save_result(town_id: str, result: Dict[str, Any]) -> Path:
    out_path = CIP_DIR / f"{town_id}_cip.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    return out_path


# ── Per-town scrape logic ───────────────────────────────────────────────────

async def scrape_town(
    town: Dict[str, Any],
    fc: FirecrawlClient,
    extractor: CIPExtractor,
    timeout_s: float = 120.0,
) -> Dict[str, Any]:
    """Scrape CIP data for a single town. Returns structured result dict."""

    town_id = town["id"]
    town_name = town["name"]
    urls_to_try: List[str] = town["urls"]
    use_actions: bool = town.get("use_actions", False)

    searched_urls: List[str] = []
    cip_page_url: Optional[str] = None
    cip_pdfs: List[str] = []
    page_data: Optional[Dict[str, Any]] = None

    logger.info("[%s] Starting scrape — %d URLs to try", town_name, len(urls_to_try))
    if town.get("notes"):
        logger.info("[%s] Notes: %s", town_name, town["notes"][:200])

    # ── Step 1: Find a page that mentions CIP ────────────────────────────
    for url in urls_to_try:
        searched_urls.append(url)
        logger.info("[%s] Trying: %s", town_name, url)

        try:
            # Use actions (JS wait) for sites that need rendering
            if use_actions or url.lower().endswith(".pdf"):
                data = await asyncio.wait_for(
                    fc.scrape_with_actions(
                        url,
                        actions=[{"type": "wait", "milliseconds": 5000}],
                        formats=["markdown", "links"],
                        only_main_content=True,
                    ),
                    timeout=60.0,
                )
            else:
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

        pdfs = _extract_pdf_links(data)
        cip_pdf_candidates = [p for p in pdfs if _is_cip_pdf(p)]

        # Also check if the URL itself is a PDF (direct PDF link)
        if url.lower().endswith(".pdf") and _is_cip_pdf(url):
            if url not in cip_pdf_candidates:
                cip_pdf_candidates.insert(0, url)

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

    # ── Step 2: Not found? ────────────────────────────────────────────────
    if cip_page_url is None:
        logger.warning("[%s] No CIP page found across %d URLs", town_name, len(urls_to_try))
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
            "notes": town.get("notes", ""),
        }
        _save_result(town_id, result)
        return result

    # ── Step 3: Try to scrape the best PDF ────────────────────────────────
    extraction_text: str = ""
    extraction_source: str = "page_markdown"
    pdf_used: Optional[str] = None

    if cip_pdfs:
        best_pdf = cip_pdfs[0]
        logger.info("[%s] Attempting to scrape CIP PDF: %s", town_name, best_pdf)
        try:
            pdf_data = await asyncio.wait_for(
                fc.scrape(best_pdf, formats=["markdown"], only_main_content=False),
                timeout=60.0,
            )
            if pdf_data and pdf_data.get("markdown"):
                extraction_text = pdf_data["markdown"]
                extraction_source = "pdf"
                pdf_used = best_pdf
                logger.info("[%s] PDF scraped: %d chars", town_name, len(extraction_text))
        except asyncio.TimeoutError:
            logger.warning("[%s] PDF scrape timeout for %s", town_name, best_pdf)
        except Exception as exc:
            logger.warning("[%s] PDF scrape error: %s", town_name, exc)

    # Fall back to page markdown
    if not extraction_text and page_data:
        extraction_text = page_data.get("markdown") or ""
        extraction_source = "page_markdown"
        logger.info("[%s] Falling back to page markdown (%d chars)", town_name, len(extraction_text))

    # ── Step 4: LLM extraction ────────────────────────────────────────────
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
                timeout=90.0,
            )
            projects = extraction_result.get("projects", [])
            logger.info("[%s] Extracted %d projects", town_name, len(projects))
        except asyncio.TimeoutError:
            logger.error("[%s] LLM extraction timed out", town_name)
        except Exception as exc:
            logger.error("[%s] LLM extraction error: %s", town_name, exc)
    else:
        logger.warning("[%s] No text available for LLM extraction", town_name)

    # ── Step 5: Build + save result ───────────────────────────────────────
    if projects:
        status = "found"
    elif extraction_text:
        status = "found_no_projects"
    else:
        status = "not_found"

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
        "notes": town.get("notes", ""),
    }

    out_path = _save_result(town_id, result)
    logger.info("[%s] Saved to %s (%d projects)", town_name, out_path, len(projects))
    return result


# ── Main ────────────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape CIP for missing towns")
    parser.add_argument(
        "--town",
        type=str,
        help="Scrape only this town (dover, lincoln, newton, wayland)",
    )
    args = parser.parse_args()

    towns_to_scrape = TOWNS
    if args.town:
        towns_to_scrape = [t for t in TOWNS if t["id"] == args.town.lower()]
        if not towns_to_scrape:
            logger.error("Unknown town: %s (available: dover, lincoln, newton, wayland)", args.town)
            sys.exit(1)

    logger.info("=" * 70)
    logger.info("Missing CIP Scraper — %d towns", len(towns_to_scrape))
    logger.info("Output: %s", CIP_DIR)
    logger.info("Firecrawl key present: %s", bool(os.getenv("FIRECRAWL_API_KEY")))
    logger.info("OpenRouter key present: %s", bool(os.getenv("OPENROUTER_API_KEY")))
    logger.info("=" * 70)

    fc = FirecrawlClient(api_key=os.getenv("FIRECRAWL_API_KEY", ""))
    extractor = CIPExtractor(api_key=os.getenv("OPENROUTER_API_KEY", ""))

    summary: List[Dict[str, Any]] = []
    start_total = time.perf_counter()

    for i, town in enumerate(towns_to_scrape):
        if i > 0:
            logger.info("Sleeping 3s before next town...")
            await asyncio.sleep(3)

        town_start = time.perf_counter()
        logger.info("")
        logger.info("── [%d/%d] %s ─────────────────────────", i + 1, len(towns_to_scrape), town["name"])

        try:
            result = await asyncio.wait_for(
                scrape_town(town, fc, extractor),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            logger.error("[%s] Town-level timeout (120s)", town["name"])
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

    await fc.close()

    # ── Summary table ────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - start_total
    logger.info("")
    logger.info("=" * 70)
    logger.info("SUMMARY — %.1fs total", total_elapsed)
    logger.info("=" * 70)
    logger.info("%-14s  %-20s  %8s  %s", "Town", "Status", "Projects", "Elapsed")
    logger.info("-" * 70)
    total_projects = 0
    for row in summary:
        total_projects += row["project_count"]
        pdf_note = " [PDF]" if row["pdf_used"] else ""
        logger.info(
            "%-14s  %-20s  %8d  %.1fs%s",
            row["town"],
            row["status"],
            row["project_count"],
            row["elapsed_s"],
            pdf_note,
        )
    logger.info("-" * 70)
    logger.info("Total projects extracted: %d", total_projects)
    logger.info("Output directory: %s", CIP_DIR)

    # Save summary
    summary_path = CIP_DIR / "_missing_cip_summary.json"
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
