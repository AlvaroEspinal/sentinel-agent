#!/usr/bin/env python3
"""
Real Estate Intelligence Data Ingestion Script for ALL MEPA Records.

Paginates through the MEPA Environmental Monitor API until all records are fetched
and inserts them into the Supabase database.
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

def parser_date(date_str: str):
    """Best effort date parser to ISO 8601"""
    if not date_str:
        return None
    try:
        from dateutil import parser
        dt = parser.parse(date_str)
        return dt.isoformat() + "Z"
    except Exception:
        return None

async def ingest_all_mepa(db: SupabaseRestClient):
    """Fetch all MEPA filings historically and insert into the Supabase documents table."""
    logger.info("--- Starting ALL MEPA Ingestion ---")
    scraper = MEPAScraper()
    
    page = 1
    page_size = 500
    total_inserted = 0
    total_skipped = 0
    
    while True:
        logger.info(f"Fetching MEPA page {page}...")
        # Search from a very early date just in case
        filings = await scraper.search_projects(
            date_from="01/01/2000",
            date_to=datetime.now().strftime("%m/%d/%Y"),
            page=page,
            page_size=page_size
        )
        
        if not filings:
            logger.info("No more filings found. Finishing.")
            break
            
        logger.info(f"Retrieved {len(filings)} filings on page {page}. Ingesting...")
        
        for f in filings:
            if not f.get("eea_number"):
                # Missing essential ID, skip
                continue

            # Check if this EEA number is already in the database
            # We'll assume the URL or eea_number itself is unique enough,
            # but to be fast, let's just insert with conflict tracking if we could.
            # Supabase POST doesn't natively do UPSERT without primary key matching or ON CONFLICT.
            # We can run a small query or just insert and catch duplicates if we had a constraint.
            # The municipal_documents table might not have a UNIQUE constraint on url or eea_number,
            # so we'll do our best. Actually, we'll just insert everything and if we want deduplication,
            # we can look for existing url.
            
            project_url = f.get("project_url", "")
            existing = await db.fetch("municipal_documents", select="id", filters={"source_url": f"eq.{project_url}"}, limit=1)
            if existing:
                total_skipped += 1
                continue

            # Construct a document record matching the existing schema
            pub_date = parser_date(f.get("publish_date", ""))
            if not pub_date:
                pub_date = datetime.utcnow().isoformat() + "Z"
                
            record = {
                "town_id": None, # State level
                "doc_type": "MEPA Environmental Monitor",
                "title": f.get("project_name", "Unknown Project"),
                "source_url": project_url,
                "meeting_date": pub_date,
                "content_text": f"EEA Number: {f.get('eea_number')} | Proponent: {f.get('proponent')} | Location: {f.get('location')} | Filing Type: {f.get('filing_type')} | Analyst: {f.get('mepa_analyst')} | Comment Deadline: {f.get('public_comment_deadline')}",
                "mentions": {
                    "municipality": f.get("municipality", ""),
                    "eea_number": f.get("eea_number", ""),
                    "proponent": f.get("proponent", ""),
                    "status": f.get("filing_type", "Pending"),
                    "address": f.get("location", "")
                }
            }
            
            # Insert
            try:
                await db.insert("municipal_documents", record)
                total_inserted += 1
            except Exception as e:
                logger.error(f"Failed to insert MEPA filing: {e}")
                
        # If we got less than page_size, it's the last page
        if len(filings) < page_size:
            logger.info("Reached the end of the results.")
            break
            
        page += 1
            
    logger.info(f"--- Successfully ingested {total_inserted} MEPA records (skipped {total_skipped} duplicates) ---")

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

    # 1. Run ALL MEPA ingest
    await ingest_all_mepa(db)
    
    # Disconnect
    await db.disconnect()
    logger.info("Done! Batch ingestion complete.")

if __name__ == "__main__":
    asyncio.run(main())
