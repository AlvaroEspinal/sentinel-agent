#!/usr/bin/env python3
"""
Daily scrape orchestrator with per-source scheduling logic.

Run this script on a cron schedule (e.g., every 6 hours) or manually.
Each source has its own interval; scraping is skipped if last_scraped is recent enough.

Intervals (from plan):
  - permits       → weekly    (7 days)
  - meeting_mins  → weekly    (7 days)
  - zoning_bylaw  → monthly   (30 days)
  - cip           → annually  (365 days)
  - overlays      → monthly   (30 days)
  - wetlands      → monthly   (30 days)
  - mepa          → weekly    (7 days)

Usage:
  python3 backend/scripts/daily_scrape.py
  python3 backend/scripts/daily_scrape.py --source permits
  python3 backend/scripts/daily_scrape.py --force        # ignore intervals
  python3 backend/scripts/daily_scrape.py --dry-run      # show what would run
"""
import argparse
import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from database.supabase_client import SupabaseRestClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent

# ─── Source definitions ────────────────────────────────────────────────────────
# Each entry:
#   key         — unique source id used in scrape_schedule tracking
#   label       — human description
#   interval    — timedelta between runs
#   script      — script path relative to SCRIPTS_DIR (None = built-in handler)
#   enabled     — set False to skip permanently

SOURCES = [
    {
        "key": "permits",
        "label": "Building Permits (all towns)",
        "interval": timedelta(days=7),
        "script": "scrape_remaining_permits.py",
        "enabled": True,
    },
    {
        "key": "meeting_minutes",
        "label": "Meeting Minutes (remaining towns)",
        "interval": timedelta(days=7),
        "script": "scrape_remaining_minutes.py",
        "enabled": True,
    },
    {
        "key": "mepa",
        "label": "MEPA Environmental Monitor",
        "interval": timedelta(days=7),
        "script": "ingest_all_mepa.py",
        "enabled": True,
    },
    {
        "key": "zoning_bylaw",
        "label": "Zoning Bylaws (all towns)",
        "interval": timedelta(days=30),
        "script": "scrape_all_zoning.py",
        "enabled": True,
    },
    {
        "key": "zoning_ingest",
        "label": "Ingest Zoning JSON → Supabase",
        "interval": timedelta(days=30),
        "script": "ingest_zoning_to_supabase.py",
        "enabled": True,
    },
    {
        "key": "overlays",
        "label": "Municipal Overlays (MassGIS)",
        "interval": timedelta(days=30),
        "script": "scrape_all_overlays.py",
        "enabled": True,
    },
    {
        "key": "wetlands",
        "label": "Wetlands & Conservation (MassGIS)",
        "interval": timedelta(days=30),
        "script": "scrape_all_wetlands.py",
        "enabled": True,
    },
    {
        "key": "cip",
        "label": "Capital Improvement Plans",
        "interval": timedelta(days=365),
        "script": "scrape_all_cip_v2.py",
        "enabled": True,
    },
]

# ─── Schedule state file (local JSON) ─────────────────────────────────────────
STATE_FILE = Path(__file__).resolve().parent.parent / "data_cache" / "scrape_schedule.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def last_ran(state: dict, key: str) -> datetime | None:
    ts = state.get(key)
    if ts:
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            pass
    return None


def due(state: dict, source: dict, force: bool) -> bool:
    if not source["enabled"]:
        return False
    if force:
        return True
    prev = last_ran(state, source["key"])
    if prev is None:
        return True  # never ran
    now = datetime.now(timezone.utc)
    if prev.tzinfo is None:
        prev = prev.replace(tzinfo=timezone.utc)
    return (now - prev) >= source["interval"]


def run_script(script_name: str) -> bool:
    """Run a script as a subprocess. Returns True on success."""
    path = SCRIPTS_DIR / script_name
    if not path.exists():
        logger.warning(f"  Script not found: {path} — skipping")
        return False

    logger.info(f"  Running: python3 {script_name}")
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(SCRIPTS_DIR.parent.parent),  # project root
    )
    if result.returncode != 0:
        logger.error(f"  FAILED (exit {result.returncode}): {script_name}")
        return False

    logger.info(f"  OK: {script_name}")
    return True


async def main():
    parser = argparse.ArgumentParser(description="Daily scrape orchestrator")
    parser.add_argument("--source", help="Run only this source key")
    parser.add_argument("--force", action="store_true", help="Ignore intervals, run everything")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without running")
    args = parser.parse_args()

    state = load_state()
    now = datetime.now(timezone.utc)

    logger.info(f"=== Daily Scrape — {now.strftime('%Y-%m-%d %H:%M UTC')} ===")

    ran = 0
    skipped = 0
    failed = 0

    for source in SOURCES:
        key = source["key"]

        # Filter by --source flag
        if args.source and key != args.source:
            continue

        if not source["enabled"]:
            logger.info(f"  DISABLED  [{key}] {source['label']}")
            skipped += 1
            continue

        if not due(state, source, args.force):
            prev = last_ran(state, key)
            next_run = prev + source["interval"]
            logger.info(
                f"  SKIP      [{key}] {source['label']} "
                f"(next: {next_run.strftime('%Y-%m-%d')})"
            )
            skipped += 1
            continue

        logger.info(f"  DUE       [{key}] {source['label']}")

        if args.dry_run:
            logger.info(f"  [DRY RUN] Would run: {source['script']}")
            ran += 1
            continue

        success = run_script(source["script"])

        if success:
            state[key] = now.isoformat()
            save_state(state)
            ran += 1
        else:
            failed += 1

    logger.info(
        f"\n=== Done: {ran} ran, {skipped} skipped, {failed} failed ==="
    )

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
