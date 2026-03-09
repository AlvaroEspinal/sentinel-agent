"""
scrape_all_zoning.py — Run ZoningBylawScraper for all 12 MVP towns.

Saves results to backend/data_cache/zoning_bylaws/{town_id}_zoning.json

Uses direct municipal website URLs instead of ecode360.com (which requires auth).
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scrape_all_zoning")

OUTPUT_DIR = PROJECT_ROOT / "backend" / "data_cache" / "zoning_bylaws"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Town registry ─────────────────────────────────────────────────────────────
# Direct PDF URLs verified working as of March 2026.
# Newton/Wayland WAF-blocked — using direct showpublisheddocument PDF for Newton.
TOWN_ZONING_URLS: Dict[str, Tuple[str, str]] = {
    # Newton: WAF blocks page but direct PDF URL may work (showpublisheddocument)
    "newton":    ("Newton",    "https://www.newtonma.gov/home/showpublisheddocument/132596/638956220862881519"),
    # Wellesley: verified PDF, amended through 2025 ATM
    "wellesley": ("Wellesley", "https://www.wellesleyma.gov/DocumentCenter/View/12119/Full-Zoning-Bylaw-as-of-2025-ATM"),
    # Weston: verified PDF (June 2022 + May 2021 amendments)
    "weston":    ("Weston",    "https://www.westonma.gov/DocumentCenter/View/35384/Zoning-By-Law-June-2022-with-amendments-may-15--2021"),
    # Brookline: verified PDF (2021/2023 bylaw)
    "brookline": ("Brookline", "https://www.brooklinema.gov/DocumentCenter/View/39415/ZoningBylaw_12162021-VP_02222023-MM"),
    # Needham: verified PDF (full zoning bylaw)
    "needham":   ("Needham",   "https://www.needhamma.gov/DocumentCenter/View/16644"),
    # Dover: zoning only on ecode360 (requires auth) — no public PDF available; will fail
    "dover":     ("Dover",     "https://ecode360.com/10427235"),
    # Sherborn: verified PDF (2023 Zoning Bylaws)
    "sherborn":  ("Sherborn",  "https://www.sherbornma.org/DocumentCenter/View/1981/2023-Zoning-Bylaws-pdf"),
    # Natick: verified PDF (June 2025 — most current)
    "natick":    ("Natick",    "https://www.natickma.gov/DocumentCenter/View/19928/2025-June-Zoning-Bylaws"),
    # Wayland: WAF blocks town site; use zoning bylaws page URL
    "wayland":   ("Wayland",   "https://www.wayland.ma.us/planning-department-board/pages/development-information-zoning-bylaws-regulations-fees-forms"),
    # Lincoln: correct domain is lincolntown.org; verified PDF (2025 ATM, 116 pages)
    "lincoln":   ("Lincoln",   "https://www.lincolntown.org/DocumentCenter/View/104918/Zoning-Bylaw-ATM-3292025"),
    # Concord: verified PDF (106 pages, Dec 2025 final)
    "concord":   ("Concord",   "https://concordma.gov/DocumentCenter/View/1394/Zoning-Bylaw---Full-Document-PDF"),
    # Lexington: verified PDF (2025 ATM)
    "lexington": ("Lexington", "https://www.lexingtonma.gov/DocumentCenter/View/16044"),
}

SINGLE_TOWN_TIMEOUT = 180  # seconds per town (PDF download can be slow)


async def scrape_town(town_id: str, town_name: str, url: str) -> bool:
    """Scrape one town; return True on success, False on failure."""
    from backend.scrapers.connectors.zoning_bylaw_scraper import ZoningBylawScraper

    output_path = OUTPUT_DIR / f"{town_id}_zoning.json"

    # Skip if already done
    if output_path.exists():
        logger.info("[%s] Already scraped — skipping (delete file to re-run)", town_id)
        return True

    logger.info("=" * 60)
    logger.info("[%s] Starting scrape from %s", town_id, url)

    scraper = ZoningBylawScraper()

    try:
        result = await asyncio.wait_for(
            scraper.scrape(town_id, town_name, url),
            timeout=SINGLE_TOWN_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error("[%s] TIMEOUT after %ds — skipping", town_id, SINGLE_TOWN_TIMEOUT)
        return False
    except Exception as exc:
        logger.error("[%s] Unexpected error: %s", town_id, exc, exc_info=True)
        return False

    if result.get("status") == "failed":
        logger.error("[%s] Scraper returned failure — no data extracted", town_id)
        return False

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    districts = result.get("districts", [])
    sections = result.get("sections", [])
    logger.info(
        "[%s] SUCCESS — %d districts, %d sections written to %s",
        town_id, len(districts), len(sections), output_path,
    )
    return True


async def main() -> None:
    results: Dict[str, str] = {}
    total = len(TOWN_ZONING_URLS)

    for idx, (town_id, (town_name, url)) in enumerate(TOWN_ZONING_URLS.items(), 1):
        print(f"\n[{idx}/{total}] {town_name} ({town_id})")
        print(f"       URL: {url}")

        start = time.time()
        ok = await scrape_town(town_id, town_name, url)
        elapsed = time.time() - start

        status = "SUCCESS" if ok else "FAILED"
        results[town_id] = status
        print(f"       Result: {status}  ({elapsed:.1f}s)")

        # Brief pause between towns to be polite to servers
        if idx < total:
            logger.info("Sleeping 5s before next town...")
            await asyncio.sleep(5)

    # ── Final report ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    successes = [t for t, s in results.items() if s == "SUCCESS"]
    failures  = [t for t, s in results.items() if s == "FAILED"]

    print(f"  Succeeded ({len(successes)}): {', '.join(successes) or 'none'}")
    print(f"  Failed    ({len(failures)}):  {', '.join(failures) or 'none'}")
    print(f"  Output dir: {OUTPUT_DIR}")

    # List saved files
    saved = sorted(OUTPUT_DIR.glob("*_zoning.json"))
    if saved:
        print(f"\nSaved files ({len(saved)}):")
        for f in saved:
            size_kb = f.stat().st_size / 1024
            print(f"  {f.name}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    asyncio.run(main())
