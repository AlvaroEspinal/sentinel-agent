#!/usr/bin/env python3
"""
Ingest Wetlands & Open Space records to Supabase.

Reads wetland JSON files from data_cache/wetlands/ (one per town) and inserts
summary records into the `municipal_documents` table.

Each wetland file contains:
  - wetlands: GeoJSON FeatureCollection of DEP wetland polygons
  - wetlands_count: number of wetland features
  - openspace: GeoJSON FeatureCollection of open space parcels
  - openspace_count: number of open space features
  - bbox, display_name, etc.
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

WETLANDS_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "wetlands"


def build_content_text(data: dict) -> str:
    """Flatten wetlands summary into searchable text."""
    parts = []
    town = data.get("display_name", data.get("town", "Unknown"))
    parts.append(f"Wetlands & Open Space: {town}")
    parts.append(f"Wetland areas: {data.get('wetlands_count', 0)} features")
    parts.append(f"Open space parcels: {data.get('openspace_count', 0)} features")

    bbox = data.get("bbox", "")
    if bbox:
        parts.append(f"BBox: {bbox}")

    # Summarize wetland types if available
    wetlands_fc = data.get("wetlands", {})
    if isinstance(wetlands_fc, dict):
        features = wetlands_fc.get("features", [])
        # Count by wetland type
        type_counts: dict[str, int] = {}
        for f in features:
            props = f.get("properties", {})
            wtype = props.get("IT_VALDESC", props.get("WETCODE", "Unknown"))
            type_counts[wtype] = type_counts.get(wtype, 0) + 1
        for wtype, count in sorted(type_counts.items(), key=lambda x: -x[1])[:20]:
            parts.append(f"  {wtype}: {count} areas")

    return "\n".join(parts)


async def ingest_wetlands(db: SupabaseRestClient):
    """Read wetland JSONs and insert into Supabase."""
    logger.info("--- Starting Wetlands Ingestion ---")

    if not WETLANDS_DIR.exists():
        logger.error(f"Wetlands directory not found: {WETLANDS_DIR}")
        return

    files = sorted(WETLANDS_DIR.glob("*_wetlands.json"))
    logger.info(f"Found {len(files)} wetland files in {WETLANDS_DIR}")

    inserted = 0
    updated = 0
    errors = 0

    for fpath in files:
        town_id = fpath.stem.replace("_wetlands", "")
        logger.info(f"Processing wetlands for: {town_id}")

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

        wetlands_count = data.get("wetlands_count", 0)
        openspace_count = data.get("openspace_count", 0)
        display_name = data.get("display_name", data.get("town", town_id.title()))

        title = f"{display_name} Wetlands & Open Space Data"
        content_text = build_content_text(data)

        # Store counts and summary (not full GeoJSON — too large)
        mentions = {
            "wetlands_count": wetlands_count,
            "openspace_count": openspace_count,
            "bbox": data.get("bbox", ""),
            "source": "MassGIS DEP Wetlands + Open Space",
        }

        # Check for existing row
        existing = await db.fetch(
            "municipal_documents",
            select="id",
            filters={"town_id": f"eq.{town_id}", "doc_type": "eq.wetland_area"},
            limit=1,
        )

        record = {
            "town_id": town_id,
            "doc_type": "wetland_area",
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
                    {"town_id": f"eq.{town_id}", "doc_type": "eq.wetland_area"},
                    record,
                )
                logger.info(f"  UPDATED  {town_id}: {wetlands_count} wetlands, {openspace_count} open space")
                updated += 1
            else:
                await db.insert("municipal_documents", record)
                logger.info(f"  INSERTED {town_id}: {wetlands_count} wetlands, {openspace_count} open space")
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
    await ingest_wetlands(db)
    await db.disconnect()
    logger.info("Done! Wetlands ingestion complete.")


if __name__ == "__main__":
    asyncio.run(main())
