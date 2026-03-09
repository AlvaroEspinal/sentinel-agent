#!/usr/bin/env python3
"""
Migrate data from municipal_documents staging table into domain-specific tables:
  - Tax Delinquency         -> tax_delinquent_parcels
  - overlay_district        -> municipal_overlays  (+ geometry from GeoJSON files)
  - MEPA Environmental Monitor + mepa_filing -> mepa_filings
"""
import asyncio
import json
import sys
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from database.supabase_client import SupabaseRestClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

DATA_CACHE = Path(__file__).resolve().parent.parent / "data_cache"
PAGE_SIZE = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def fetch_all_paged(db: SupabaseRestClient, table: str, filters: dict) -> list:
    """Fetch all rows with pagination to avoid PostgREST limits."""
    return await db.fetch_all(table, filters=filters, page_size=PAGE_SIZE)


def parse_amount(val):
    """Parse dollar strings like '$1,234.56' or '1234.56' into float."""
    if val is None:
        return None
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def overlay_type_from_layer(layer_name: str) -> str:
    """Infer overlay_type from GeoJSON layer filename."""
    name = layer_name.lower()
    if "historic" in name:
        return "historic_district"
    if "flood" in name or "coastal" in name:
        return "flood_overlay"
    if "planned" in name or "pda" in name:
        return "planned_development"
    if "neighborhood" in name:
        return "neighborhood_district"
    if "institutional" in name:
        return "institutional_overlay"
    if "zoning" in name:
        return "zoning_district"
    return "overlay_district"


# ---------------------------------------------------------------------------
# Build geometry lookup from GeoJSON files
# {layer_stem: {props_fingerprint: geometry_dict}}
# ---------------------------------------------------------------------------

def build_geometry_lookup() -> dict[str, list[dict]]:
    """
    Returns {layer_stem: [{"geometry": ..., "properties": ...}, ...]}
    """
    lookup: dict[str, list[dict]] = {}
    for geojson_path in DATA_CACHE.glob("*.geojson"):
        with open(geojson_path) as f:
            data = json.load(f)
        features = data.get("features", [])
        lookup[geojson_path.stem] = [
            {"geometry": feat.get("geometry"), "properties": feat.get("properties", {})}
            for feat in features
        ]
        logger.info(f"Loaded {len(features)} features from {geojson_path.name}")
    return lookup


def find_geometry(layer_name: str, props: dict, geo_lookup: dict):
    """
    Match a municipal_documents overlay record back to its GeoJSON geometry.
    Matches on the 'objectid' or 'OBJECTID' field, falling back to full props equality.
    """
    candidates = geo_lookup.get(layer_name, [])
    if not candidates:
        return None

    # Try matching by OBJECTID
    obj_id = props.get("OBJECTID") or props.get("objectid")
    if obj_id is not None:
        for c in candidates:
            c_id = c["properties"].get("OBJECTID") or c["properties"].get("objectid")
            if str(c_id) == str(obj_id):
                return c["geometry"]

    # Fallback: full props equality
    for c in candidates:
        if c["properties"] == props:
            return c["geometry"]

    return None


# ---------------------------------------------------------------------------
# Migration functions
# ---------------------------------------------------------------------------

async def migrate_tax_delinquent(db: SupabaseRestClient, town_id):
    logger.info("--- Migrating Tax Delinquency records ---")

    rows = await fetch_all_paged(db, "municipal_documents", {"doc_type": "eq.Tax Delinquency"})
    logger.info(f"Found {len(rows)} Tax Delinquency rows")

    success = 0
    for row in rows:
        mentions = row.get("mentions") or {}
        if isinstance(mentions, str):
            try:
                mentions = json.loads(mentions)
            except Exception:
                mentions = {}

        record = {
            "town_id": town_id,
            "parcel_id": mentions.get("parcel_id"),
            "owner": mentions.get("owner"),
            "address": mentions.get("address") or row.get("title"),
            "tax_type": mentions.get("tax_type"),
            "amount_owed": parse_amount(mentions.get("amount_owed")),
            "status": mentions.get("status"),
            "source_url": row.get("source_url"),
            "raw_mentions": mentions,
            "scraped_at": row.get("meeting_date") or row.get("created_at"),
        }
        try:
            await db.insert("tax_delinquent_parcels", record)
            success += 1
        except Exception as e:
            logger.error(f"Failed to insert tax record '{record.get('address')}': {e}")

    logger.info(f"Tax Delinquency: inserted {success}/{len(rows)}")


async def migrate_overlays(db: SupabaseRestClient, town_id):
    logger.info("--- Migrating overlay_district records ---")

    geo_lookup = build_geometry_lookup()
    rows = await fetch_all_paged(db, "municipal_documents", {"doc_type": "eq.overlay_district"})
    logger.info(f"Found {len(rows)} overlay_district rows")

    success = 0
    for row in rows:
        mentions = row.get("mentions") or {}
        if isinstance(mentions, str):
            try:
                mentions = json.loads(mentions)
            except Exception:
                mentions = {}

        layer_name = row.get("source_url") or ""
        geometry = find_geometry(layer_name, mentions, geo_lookup)

        # Derive a human title
        title = (
            mentions.get("PDA_NAME")
            or mentions.get("DISTRICT")
            or mentions.get("HISTORIC_N")
            or mentions.get("Neighborho")
            or mentions.get("name")
            or row.get("title", "")
        )

        record = {
            "town_id": town_id,
            "layer_name": layer_name,
            "overlay_type": overlay_type_from_layer(layer_name),
            "title": title,
            "geometry": geometry,
            "properties": mentions,
            "source_url": layer_name,
            "scraped_at": row.get("meeting_date") or row.get("created_at"),
        }
        try:
            await db.insert("municipal_overlays", record)
            success += 1
        except Exception as e:
            logger.error(f"Failed to insert overlay '{title}': {e}")

    geo_matched = sum(
        1 for row in rows
        if find_geometry(
            row.get("source_url") or "",
            row.get("mentions") or {},
            geo_lookup
        )
    )
    logger.info(f"Overlays: inserted {success}/{len(rows)} | geometry matched: {geo_matched}")


async def migrate_mepa(db: SupabaseRestClient, town_id):
    logger.info("--- Migrating MEPA records ---")

    monitor_rows = await fetch_all_paged(
        db, "municipal_documents", {"doc_type": "eq.MEPA Environmental Monitor"}
    )
    filing_rows = await fetch_all_paged(
        db, "municipal_documents", {"doc_type": "eq.mepa_filing"}
    )
    all_rows = monitor_rows + filing_rows
    logger.info(f"Found {len(monitor_rows)} MEPA Monitor + {len(filing_rows)} mepa_filing rows")

    success = 0
    for row in all_rows:
        mentions = row.get("mentions") or {}
        if isinstance(mentions, str):
            try:
                mentions = json.loads(mentions)
            except Exception:
                mentions = {}
        # mentions may be a list for mepa_filing rows (empty [])
        if isinstance(mentions, list):
            mentions = {}

        record = {
            "town_id": town_id,
            "eea_number": mentions.get("eea_number"),
            "title": mentions.get("title") or row.get("title"),
            "status": mentions.get("status"),
            "address": mentions.get("address"),
            "proponent": mentions.get("proponent"),
            "municipality": mentions.get("municipality"),
            "source_url": row.get("source_url"),
            "doc_type": row.get("doc_type"),
            "raw_mentions": mentions,
            "scraped_at": row.get("meeting_date") or row.get("created_at"),
        }
        try:
            await db.insert("mepa_filings", record)
            success += 1
        except Exception as e:
            logger.error(f"Failed to insert MEPA record '{record.get('title')}': {e}")

    logger.info(f"MEPA: inserted {success}/{len(all_rows)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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

    # Look up Boston town_id
    town_id = None
    try:
        resp = await db.fetch("towns", filters={"name": "eq.Boston"})
        town_id = resp[0]["id"] if resp else None
        logger.info(f"Boston town_id: {town_id}")
    except Exception as e:
        logger.warning(f"Could not fetch Boston town_id: {e}")

    # Tax delinquency already migrated (71/71) — skip
    await migrate_overlays(db, town_id)
    await migrate_mepa(db, town_id)

    await db.disconnect()
    logger.info("=== Migration complete ===")


if __name__ == "__main__":
    asyncio.run(main())
