#!/usr/bin/env python3
import asyncio
import logging
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir.parent / ".env", override=True)

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
import httpx

# Hardcoded towns to avoid import issues
TOWNS = {
    "newton": "Newton", "lexington": "Lexington", "needham": "Needham",
    "natick": "Natick", "wellesley": "Wellesley", "wayland": "Wayland",
    "dover": "Dover", "weston": "Weston", "sherborn": "Sherborn",
    "lincoln": "Lincoln", "brookline": "Brookline", "concord": "Concord"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("repair_tax")

async def main():
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    async with httpx.AsyncClient(headers=headers) as client:
        # Fetch records with null town_id
        url = f"{SUPABASE_URL}/rest/v1/municipal_documents"
        params = {
            "doc_type": "eq.Tax Delinquency",
            "town_id": "is.null",
            "select": "id,title,content_text"
        }
        res = await client.get(url, params=params)
        records = res.json()
        
        if not records:
            logger.info("No records found with null town_id. Already fixed!")
            return
            
        logger.info(f"Found {len(records)} records to fix.")
        
        fixed = 0
        for rec in records:
            text_to_search = (rec.get('title', '') + " " + rec.get('content_text', '')).lower()
            found_town = None
            
            for part in rec.get('content_text', '').split('|'):
                if 'Address:' in part:
                    for tid, name in TOWNS.items():
                        if name.lower() in part.lower():
                            found_town = tid
                            break
                    break
                    
            if not found_town:
                import re
                for tid, name in TOWNS.items():
                    if re.search(rf"\b{name.lower()}\b", text_to_search):
                        found_town = tid
                        break
                        
            if found_town:
                update_url = f"{SUPABASE_URL}/rest/v1/municipal_documents?id=eq.{rec['id']}"
                upd_res = await client.patch(update_url, json={"town_id": found_town})
                if upd_res.status_code in (200, 204):
                    fixed += 1
                else:
                    logger.error(f"Failed to update {rec['id']}: {upd_res.status_code} {upd_res.text}")
            else:
                logger.warning(f"Defaulting to 'boston' for: {rec['title']}")
                update_url = f"{SUPABASE_URL}/rest/v1/municipal_documents?id=eq.{rec['id']}"
                upd_res = await client.patch(update_url, json={"town_id": "boston"})
                if upd_res.status_code in (200, 204):
                    fixed += 1
                
        logger.info(f"Fixed {fixed} out of {len(records)} records!")

if __name__ == "__main__":
    asyncio.run(main())
