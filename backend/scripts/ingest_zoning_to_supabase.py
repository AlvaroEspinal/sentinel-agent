#!/usr/bin/env python3
"""
Ingest all zoning bylaw JSON files from data_cache/zoning_bylaws/ into Supabase.

Stores one row per town in municipal_documents with:
  - doc_type = "zoning_bylaw"
  - mentions = {"districts": [...], "sections": [...]}
  - content_text = flattened district summary for full-text search
"""
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
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

CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "zoning_bylaws"


def build_content_text(data: dict) -> str:
    """Flatten districts + sections into searchable text."""
    parts = []
    town = data.get("town", "")
    parts.append(f"Zoning Bylaw: {town}")

    for d in data.get("districts", []):
        code = d.get("code", "")
        name = d.get("name", "")
        allowed = ", ".join(d.get("allowed_uses", []))
        special = ", ".join(d.get("special_permit_uses", []))
        line = f"District {code} ({name})"
        if allowed:
            line += f" — Allowed: {allowed}"
        if special:
            line += f" | Special Permit: {special}"
        parts.append(line)

    for s in data.get("sections", []):
        title = s.get("title", "")
        summary = s.get("summary", "")
        if title:
            parts.append(f"{title}: {summary}")

    return "\n".join(parts)


async def ingest_zoning(db: SupabaseRestClient):
    files = sorted(CACHE_DIR.glob("*_zoning.json"))
    logger.info(f"Found {len(files)} zoning JSON files in {CACHE_DIR}")

    inserted = 0
    updated = 0
    skipped = 0
    errors = 0

    for fpath in files:
        try:
            data = json.loads(fpath.read_text())
        except Exception as e:
            logger.error(f"Failed to read {fpath.name}: {e}")
            errors += 1
            continue

        status = data.get("status", "")
        if status != "success":
            logger.warning(f"Skipping {fpath.name} — status={status!r}")
            skipped += 1
            continue

        town_id = data.get("town_id", "")
        town = data.get("town", town_id.title())
        source_url = data.get("source_url", "")
        districts = data.get("districts", [])
        sections = data.get("sections", [])

        if not town_id:
            logger.warning(f"Skipping {fpath.name} — missing town_id")
            skipped += 1
            continue

        title = f"{town} Zoning Bylaw"
        content_text = build_content_text(data)
        mentions = {
            "districts": districts,
            "sections": sections,
            "district_count": len(districts),
        }

        # Check for existing row
        existing = await db.fetch(
            "municipal_documents",
            select="id",
            filters={"town_id": f"eq.{town_id}", "doc_type": "eq.zoning_bylaw"},
            limit=1,
        )

        record = {
            "town_id": town_id,
            "doc_type": "zoning_bylaw",
            "title": title,
            "source_url": source_url,
            "content_text": content_text,
            "mentions": mentions,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            if existing:
                await db.update(
                    "municipal_documents",
                    {"town_id": f"eq.{town_id}", "doc_type": "eq.zoning_bylaw"},
                    record,
                )
                logger.info(f"  UPDATED  {town_id}: {len(districts)} districts")
                updated += 1
            else:
                await db.insert("municipal_documents", record)
                logger.info(f"  INSERTED {town_id}: {len(districts)} districts")
                inserted += 1
        except Exception as e:
            logger.error(f"  ERROR    {town_id}: {e}")
            errors += 1

    logger.info(
        f"\n--- Done: {inserted} inserted, {updated} updated, "
        f"{skipped} skipped, {errors} errors ---"
    )


async def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")
        return

    db = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    connected = await db.connect()
    if not connected:
        logger.error("Could not connect to Supabase.")
        return

    logger.info("Connected to Supabase.")
    await ingest_zoning(db)


if __name__ == "__main__":
    asyncio.run(main())
