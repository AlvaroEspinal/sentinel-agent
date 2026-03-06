#!/usr/view/env python3
"""Run LLM extraction for existing meeting minutes.

Reads the local JSON files in data/scraped/minutes/*.json and runs
LLMExtractor.extract_from_minutes for documents missing summaries/keywords.
Updates the local JSON and Supabase.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.connectors.llm_extractor import LLMExtractor
from database.supabase_client import SupabaseRestClient
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

LOCAL_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "scraped" / "minutes"

async def process_file(filepath: Path, llm: LLMExtractor, supabase: SupabaseRestClient):
    logger.info(f"Processing {filepath.name}...")
    try:
        with open(filepath, "r") as f:
            docs = json.load(f)
    except Exception as e:
        logger.error(f"Error reading {filepath}: {e}")
        return
        
    updated = False
    for doc in docs:
        # Check if already extracted
        if doc.get("content_summary") and doc.get("keywords"):
            continue
            
        text = doc.get("content_text")
        if not text or len(text) < 100:
            continue
            
        town = doc.get("town_id", "Unknown Town").title()
        board = doc.get("board", "Unknown Board").replace("_", " ").title()
        
        try:
            extraction = await llm.extract_from_minutes(text[:20000], town, board)
            doc["content_summary"] = extraction.get("summary")
            doc["keywords"] = extraction.get("keywords", [])
            doc["mentions"] = extraction.get("mentions", [])
            updated = True
            logger.info(f"    Extracted: {doc.get('title', 'Unknown')} ({len(doc['keywords'])} keywords)")
            
            # Upsert partial to Supabase if we have hash
            content_hash = doc.get("content_hash")
            if content_hash and supabase:
                try:
                    await supabase.insert(
                        "municipal_documents", 
                        [{
                            "content_hash": content_hash,
                            "content_summary": doc["content_summary"],
                            "keywords": doc["keywords"],
                            "mentions": doc["mentions"]
                        }],
                        upsert=True,
                        on_conflict="content_hash"
                    )
                except Exception as db_e:
                    logger.warning(f"Failed to update Supabase: {db_e}")
                    
            # Rate limit backoff for Anthropic
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Error extracting {doc.get('title')}: {e}")
            await asyncio.sleep(5) # longer backoff on error
            
    if updated:
        with open(filepath, "w") as f:
            json.dump(docs, f, indent=2)
            logger.info(f"Saved updates to {filepath.name}")

async def main(args: argparse.Namespace):
    llm = LLMExtractor()
    supabase = None
    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        supabase = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
        connected = await supabase.connect()
        if not connected:
            supabase = None
    
    files = list(LOCAL_DATA_DIR.glob("*.json"))
    if args.town:
        files = [f for f in files if f.stem == args.town]
        
    for f in files:
        await process_file(f, llm, supabase)
        
    if supabase:
        await supabase.disconnect()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract insights from existing minutes")
    parser.add_argument("--town", help="Specific town to process")
    args = parser.parse_args()
    asyncio.run(main(args))
