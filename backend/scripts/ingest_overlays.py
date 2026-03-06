#!/usr/bin/env python3
"""
Ingest Municipal Overlay records to Supabase.

Reads the GeoJSON files saved in data_cache resulting from scraping overlays
and inserts them into the `municipal_documents` table.
"""
import asyncio
import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Add the backend root to python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from database.supabase_client import SupabaseRestClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def ingest_overlays(db: SupabaseRestClient):
    """Read overlay GeoJSON from data_cache and insert into Supabase."""
    logger.info("--- Starting Overlays Ingestion ---")
    
    data_cache = Path(__file__).resolve().parent.parent / "data_cache"
    
    try:
        town_resp = await db.fetch("towns", filters={"name": "eq.Boston"})
        town_id = town_resp[0]["id"] if town_resp else None
    except Exception as e:
        logger.warning(f"Failed to fetch town id for Boston: {e}")
        town_id = None

    geojson_files = list(data_cache.glob("*.geojson"))
    if not geojson_files:
        logger.info("No GeoJSON files found in data_cache/")
        return
        
    for p in geojson_files:
        layer_name = p.stem
        logger.info(f"Processing overlay layer: {layer_name}")
        
        with open(p, "r") as f:
            data = json.load(f)
            
        features = data.get("features", [])
        success_count = 0
        
        for feat in features:
            props = feat.get("properties", {})
            title = props.get("PDA_NAME") or props.get("DISTRICT") or props.get("HISTORIC_N") or props.get("Neighborho") or f"Overlay Feature in {layer_name}"
            
            record = {
                "town_id": town_id, 
                "doc_type": "overlay_district",
                "title": f"Overlay: {title}",
                "source_url": layer_name,
                "meeting_date": datetime.utcnow().isoformat() + "Z",
                "content_text": json.dumps(props),
                "mentions": props
            }
            try:
                await db.insert("municipal_documents", record)
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to insert overlay feature {title}: {e}")
        
        logger.info(f"Ingested {success_count} features for layer {layer_name}")

async def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Supabase credentials missing in .env")
        return

    db = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    connected = await db.connect()
    if not connected:
        logger.error("Could not connect to Supabase.")
        return
        
    logger.info("Successfully connected to Supabase.")

    # Run ingest
    await ingest_overlays(db)
    
    # Disconnect
    await db.disconnect()
    logger.info("Done! Overlays ingestion complete.")

if __name__ == "__main__":
    asyncio.run(main())
