import asyncio
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add the backend root to python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from database.supabase_client import SupabaseRestClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Supabase credentials missing in .env")
        return

    db = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    connected = await db.connect()
    if not connected:
        logger.error("Could not connect to Supabase.")
        return

    data_dir = Path("data/tax_delinquency")
    if not data_dir.exists():
        logger.info("No tax delinquency JSON files found.")
        return

    total_inserted = 0
    for file_path in data_dir.glob("*_tax_titles.json"):
        town_id_str = file_path.stem.replace("_tax_titles", "")
        town_name = town_id_str.replace("_", " ").title()
        
        with open(file_path, "r") as f:
            records = json.load(f)
            
        logger.info(f"Uploading {len(records)} records for {town_name}...")
        
        # Try finding town in DB
        town_uuid = None
        try:
            town_resp = await db.fetch_towns() # fetch all or fetch by name
            for t in town_resp:
                if t.get("name", "").lower() == town_name.lower() or t.get("id") == town_id_str:
                    town_uuid = t.get("id")
                    break
        except Exception as e:
            logger.warning(f"Could not fetch town_id for {town_name}: {e}")

        for rec in records:
            address = rec.get("address", "")
            owner = rec.get("owner", "")
            amount_owed = rec.get("amount_owed", "")
            doc = {
                "town_id": town_uuid,
                "doc_type": "Tax Delinquency",
                "title": f"Tax Delinquent Property: {address}",
                "source_url": "Direct PDF Scrape",
                "content_text": f"Address: {address} | Owner: {owner} | Amount Owed: {amount_owed} | Year: {rec.get('year')} | Tax Type: {rec.get('tax_type')}",
                "meeting_date": datetime.utcnow().isoformat() + "Z", # Required for municipal docs typically, or we can leave it out
                "mentions": {
                    "owner": owner,
                    "amount_owed": amount_owed,
                    "tax_type": rec.get("tax_type", ""),
                    "address": address,
                    "status": "Delinquent",
                    "parcel_id": rec.get("parcel_id", "")
                }
            }
            try:
                # Upsert or insert depending on your DB. For now, simple insert
                await db.insert("municipal_documents", doc)
                total_inserted += 1
            except Exception as e:
                logger.warning(f"Failed to insert record for {town_name}: {e}")

    logger.info(f"Successfully pushed {total_inserted} tax delinquency records to Supabase.")
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
