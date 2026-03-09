#!/usr/bin/env python3
"""
Ingest Municipal Overlay records to Supabase.

Reads overlay JSON files from data_cache/overlays/ (one per town) and inserts
summary records into the `municipal_documents` table.

Each overlay file contains:
  - use_code_summary: list of use-code categories with parcel counts + acreage
  - zoning_features: list of parcel-level features
  - bbox, source, source_url, etc.
"""
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from database.supabase_client import SupabaseRestClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

OVERLAYS_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "overlays"


def build_content_text(data: dict) -> str:
    """Flatten overlay use-code summary into searchable text."""
    parts = []
    town = data.get("display_name", data.get("town_id", "Unknown"))
    parts.append(f"Municipal Overlay Data: {town}")
    parts.append(f"Source: {data.get('source', 'MassGIS')}")
    parts.append(f"BBox: {data.get('bbox', '')}")

    for entry in data.get("use_code_summary", []):
        code = entry.get("use_code", "")
        label = entry.get("label", "")
        count = entry.get("parcel_count", 0)
        acres = entry.get("total_acres", 0)
        parts.append(f"  {code} ({label}): {count} parcels, {acres:.1f} acres")

    return "\n".join(parts)


async def ingest_overlays(db: SupabaseRestClient):
    """Read overlay JSONs and insert into Supabase."""
    logger.info("--- Starting Overlays Ingestion ---")

    if not OVERLAYS_DIR.exists():
        logger.error(f"Overlays directory not found: {OVERLAYS_DIR}")
        return

    files = sorted(OVERLAYS_DIR.glob("*_overlays.json"))
    logger.info(f"Found {len(files)} overlay files in {OVERLAYS_DIR}")

    inserted = 0
    updated = 0
    errors = 0

    for fpath in files:
        town_id = fpath.stem.replace("_overlays", "")
        logger.info(f"Processing overlays for: {town_id}")

        try:
            data = json.loads(fpath.read_text())
        except Exception as e:
            logger.error(f"Failed to read {fpath.name}: {e}")
            errors += 1
            continue

        if data.get("error"):
            logger.warning(f"Skipping {town_id} — has error: {data['error']}")
            errors += 1
            continue

        use_codes = data.get("use_code_summary", [])
        feature_count = data.get("feature_count", 0)
        display_name = data.get("display_name", town_id.title())

        title = f"{display_name} Municipal Overlay Data"
        content_text = build_content_text(data)
        mentions = {
            "use_code_summary": use_codes,
            "summary_count": data.get("summary_count", len(use_codes)),
            "feature_count": feature_count,
            "bbox": data.get("bbox", ""),
            "source": data.get("source", ""),
        }

        # Check for existing row
        existing = await db.fetch(
            "municipal_documents",
            select="id",
            filters={"town_id": f"eq.{town_id}", "doc_type": "eq.municipal_overlay"},
            limit=1,
        )

        record = {
            "town_id": town_id,
            "doc_type": "municipal_overlay",
            "title": title,
            "source_url": data.get("source_url", ""),
            "content_text": content_text[:10000],
            "mentions": mentions,
            "scraped_at": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        }

        try:
            if existing:
                await db.update(
                    "municipal_documents",
                    {"town_id": f"eq.{town_id}", "doc_type": "eq.municipal_overlay"},
                    record,
                )
                logger.info(f"  UPDATED  {town_id}: {len(use_codes)} use codes, {feature_count} features")
                updated += 1
            else:
                await db.insert("municipal_documents", record)
                logger.info(f"  INSERTED {town_id}: {len(use_codes)} use codes, {feature_count} features")
                inserted += 1
        except Exception as e:
            logger.error(f"  ERROR    {town_id}: {e}")
            errors += 1

    logger.info(
        f"\n--- Done: {inserted} inserted, {updated} updated, {errors} errors ---"
    )


async def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Supabase credentials missing in .env")
        return

    db = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    connected = await db.connect()
    if not connected:
        logger.error("Could not connect to Supabase.")
        return

    logger.info("Connected to Supabase.")
    await ingest_overlays(db)
    await db.disconnect()
    logger.info("Done! Overlays ingestion complete.")


if __name__ == "__main__":
    asyncio.run(main())
