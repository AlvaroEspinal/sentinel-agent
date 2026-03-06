#!/usr/bin/env python3
"""
Real Estate Intelligence Data Ingestion Script

Orchestrates the new scrapers (MEPA Environmental Monitor, Tax Delinquency, CIPs)
and inserts the resulting intelligence into the Supabase database.
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
load_dotenv()

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from database.supabase_client import SupabaseRestClient
from scrapers.connectors.mepa_scraper import MEPAScraper
from scrapers.connectors.tax_delinquency_scraper import TaxDelinquencyScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# List of target pilot towns
TARGET_TOWNS = [
    "Lexington", "Wellesley", "Natick", "Weston", 
    "Concord", "Wayland", "Needham", "Dover", "Sherborn", "Brookline"
]

async def ingest_mepa(db: SupabaseRestClient):
    """Fetch latest MEPA filings and insert into the Supabase documents table."""
    logger.info("--- Starting MEPA Ingestion ---")
    scraper = MEPAScraper()
    # Fetch latest 100 filings to get good coverage
    filings = await scraper.get_latest_filings(count=100)
    logger.info(f"Retrieved {len(filings)} recent MEPA filings.")
    
    success_count = 0
    for f in filings:
        # Construct a document record matching the existing schema
        record = {
            "town_id": None, # State level, but we could try to map municipality to town_id if needed
            "source_type": "MEPA Environmental Monitor",
            "title": f.get("project_name", "Unknown Project"),
            "url": f.get("project_url", ""),
            "published_at": parser_date(f.get("publish_date", "")),
            "content_text": f"EEA Number: {f.get('eea_number')} | Proponent: {f.get('proponent')} | Location: {f.get('location')} | Filing Type: {f.get('filing_type')} | Analyst: {f.get('mepa_analyst')} | Comment Deadline: {f.get('public_comment_deadline')}",
            "permit_type": "Environmental Filing",
            "status": f.get("filing_type", "Pending"),
            "address": f.get("location", ""),
            "mentions": {
                "municipality": f.get("municipality", ""),
                "eea_number": f.get("eea_number", ""),
                "proponent": f.get("proponent", "")
            }
        }
        
        # Insert
        try:
            resp = await db.insert("municipal_documents", record)
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to insert MEPA filing: {e}")
            
    logger.info(f"--- Successfully ingested {success_count}/{len(filings)} MEPA records ---")

def parser_date(date_str: str):
    """Best effort date parser to ISO 8601"""
    if not date_str:
        return datetime.utcnow().isoformat() + "Z"
    try:
        from dateutil import parser
        # Usually MEPA dates look like "8/8/2025 12:00:00 AM"
        dt = parser.parse(date_str)
        return dt.isoformat() + "Z"
    except Exception:
        return datetime.utcnow().isoformat() + "Z"

async def ingest_tax_delinquency(db: SupabaseRestClient):
    """Fetch tax delinquency lists for known towns and insert into documents table."""
    logger.info("--- Starting Tax Delinquency Ingestion ---")
    scraper = TaxDelinquencyScraper()
    
    # We will use extract_from_url with explicitly found Tax Title URLs
    # Using Concord's Tax Title PDF as an example
    pilot_sources = {
        "Lexington": "https://www.lexingtonma.gov/DocumentCenter/View/11568/Tax-Title-List-PDF", # Example placeholder
        "Concord": "https://www.concordma.gov/DocumentCenter/View/45535/Tax-Title-Properties" # Example placeholder
    }
    
    total_inserted = 0
    for town, url in pilot_sources.items():
        logger.info(f"Processing Tax Delinquency for {town} from {url}...")
        try:
            records = await scraper.extract_from_url(url)
            logger.info(f"Found {len(records)} delinquent properties for {town}.")
        except Exception as e:
            logger.warning(f"Could not extract from {url}: {e}")
            continue
        
        # Fetch town ID from Supabase
        town_id = None
        try:
            town_resp = await db.fetch_town_by_name(town.title())
            if town_resp:
                town_id = town_resp.get("id")
        except Exception as e:
            logger.error(f"Could not find town_id for {town}: {e}")
            
        for rec in records:
            doc = {
                "town_id": town_id,
                "doc_type": "Tax Collector",
                "title": f"Tax Delinquent Property: {rec.get('address')}",
                "source_url": rec.get("source_url", ""),
                "content_text": f"Address: {rec.get('address')} | Owner: {rec.get('owner')} | Amount Owed: {rec.get('amount_owed')} | Status: {rec.get('status')}",
                "meeting_date": datetime.utcnow().isoformat() + "Z",
                "mentions": {
                    "owner": rec.get("owner", ""),
                    "amount_owed": rec.get("amount_owed", ""),
                    "tax_type": rec.get("tax_type", ""),
                    "address": rec.get("address", ""),
                    "status": "Delinquent"
                }
            }
            try:
                await db.insert("municipal_documents", doc)
                total_inserted += 1
            except Exception as e:
                logger.warning(f"Failed to insert tax record: {e}")
                
    logger.info(f"--- Successfully ingested {total_inserted} total Tax Delinquency records ---")


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

    # 1. Run MEPA
    await ingest_mepa(db)
    
    # 2. Run Tax Delinquency
    await ingest_tax_delinquency(db)
    
    # Disconnect
    await db.disconnect()
    logger.info("Done! Batch ingestion complete.")


if __name__ == "__main__":
    asyncio.run(main())
