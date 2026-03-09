"""
Phase 3a: Scrape remaining permits for Weston and Sherborn
using the SimpliCITY / MapsOnline connector.

Usage:
    python3 -m backend.scripts.scrape_remaining_permits
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Load .env so FIRECRAWL_API_KEY is available ───────────────────────────────
_env_path = Path(__file__).resolve().parents[2] / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    logger.info("Loaded .env from %s", _env_path)

from backend.scrapers.connectors.simplicity_client import (
    SIMPLICITY_TOWNS,
    get_session_id,
    scrape_town_permits,
)

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data_cache" / "permits"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TOWNS_TO_SCRAPE = ["weston", "sherborn"]

# httpx client settings
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def scrape_town(town_key: str, client: httpx.AsyncClient) -> list[dict]:
    """Scrape all permits for a single town. Returns list of permit dicts."""
    config = SIMPLICITY_TOWNS[town_key]
    logger.info("=" * 60)
    logger.info("Scraping %s  (client=%s, config=%s)", town_key.upper(), config.client_name, config.config_id)
    logger.info("Forms: %s", [f"{f.department}({f.form_id})" for f in config.forms])

    # ── Step 1: Obtain session ID ──────────────────────────────────────────
    logger.info("[%s] Getting session ID ...", town_key)
    ssid = await get_session_id(client=client, client_name=config.client_name)

    if not ssid:
        logger.error("[%s] Could not obtain session ID — aborting this town", town_key)
        return []

    logger.info("[%s] Session ID obtained: %s...%s", town_key, ssid[:8], ssid[-4:])

    # ── Step 2: Scrape all permit forms ────────────────────────────────────
    try:
        permits = await scrape_town_permits(
            config=config,
            client=client,
            ssid=ssid,
            page_size=100,
            max_records=50_000,
        )
    except Exception as exc:
        logger.error("[%s] scrape_town_permits raised: %s", town_key, exc)
        return []

    logger.info("[%s] Total permits scraped: %d", town_key, len(permits))
    return permits


async def save_results(town_key: str, permits: list[dict]) -> Path:
    """Write permits to JSON, return the output path."""
    out_path = OUTPUT_DIR / f"{town_key}_permits.json"
    payload = {
        "town": town_key,
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "total": len(permits),
        "permits": permits,
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("[%s] Saved %d permits → %s", town_key, len(permits), out_path)
    return out_path


def print_summary(results: dict[str, list[dict]]) -> None:
    """Print a final summary table."""
    print("\n" + "=" * 60)
    print("  SCRAPE SUMMARY")
    print("=" * 60)
    grand_total = 0
    for town, permits in results.items():
        print(f"  {town.upper():<12}  {len(permits):>6} permits")
        grand_total += len(permits)
        # Show per-department breakdown
        dept_counts: dict[str, int] = {}
        for p in permits:
            dept = p.get("department", "Unknown")
            dept_counts[dept] = dept_counts.get(dept, 0) + 1
        for dept, cnt in sorted(dept_counts.items(), key=lambda x: -x[1]):
            print(f"    {dept:<20}  {cnt:>6}")
    print("-" * 60)
    print(f"  {'TOTAL':<12}  {grand_total:>6} permits")
    print("=" * 60)


async def main() -> None:
    results: dict[str, list[dict]] = {}

    async with httpx.AsyncClient(
        headers=HTTP_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, connect=15.0),
    ) as client:
        for town_key in TOWNS_TO_SCRAPE:
            if town_key not in SIMPLICITY_TOWNS:
                logger.error("Unknown town key: %s  (available: %s)", town_key, list(SIMPLICITY_TOWNS.keys()))
                continue

            permits = await scrape_town(town_key, client)
            results[town_key] = permits

            # Always save even if empty (so we know it ran)
            await save_results(town_key, permits)

            # Brief pause between towns
            if town_key != TOWNS_TO_SCRAPE[-1]:
                logger.info("Pausing 3s before next town...")
                await asyncio.sleep(3)

    print_summary(results)

    # Exit with error if nothing was scraped
    total = sum(len(v) for v in results.values())
    if total == 0:
        logger.error("No permits scraped from any town. Check session ID / network.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
