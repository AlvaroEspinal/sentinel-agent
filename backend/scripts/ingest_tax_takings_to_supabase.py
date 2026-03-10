#!/usr/bin/env python3
"""
Ingest tax taking records from Registry of Deeds JSON files into Supabase.

Reads from: data_cache/tax_delinquency/{town}_tax_takings.json
Inserts to: municipal_documents table with doc_type="Tax Taking"

Each record becomes a municipal_documents row with structured `mentions` JSONB.
Uses content_hash-based deduplication to avoid duplicates on re-runs.
"""

import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Setup path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir.parent / ".env", override=True)

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from database.supabase_client import SupabaseRestClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_tax_takings")


def make_content_hash(town: str, book: str, page: str, file_date: str) -> str:
    """Create a deterministic hash for deduplication."""
    key = f"{town}|{book}|{page}|{file_date}"
    return hashlib.sha256(key.encode()).hexdigest()


def record_to_document(record: dict, town_id: str) -> dict:
    """Convert a tax taking record to a municipal_documents row."""
    address = record.get("address", "").strip()
    grantor = record.get("grantor", "").strip()
    grantee = record.get("grantee", "").strip()
    book = record.get("book", "").strip()
    page = record.get("page", "").strip()
    file_date = record.get("file_date", "").strip()
    prop_desc = record.get("property_description", "").strip()
    registry = record.get("registry", "").strip()

    # Build title
    if address:
        title = f"Tax Taking: {address}"
    elif grantee:
        title = f"Tax Taking: {grantee}"
    else:
        title = f"Tax Taking: Book {book}, Page {page}"

    # Build content_text (pipe-delimited for consistency with permit format)
    content_parts = [
        f"Type: Tax Taking",
        f"Address: {address}" if address else "",
        f"Owner/Grantee: {grantee}" if grantee else "",
        f"Grantor: {grantor}" if grantor else "",
        f"File Date: {file_date}" if file_date else "",
        f"Book: {book}" if book else "",
        f"Page: {page}" if page else "",
        f"Registry: {registry}" if registry else "",
        f"Description: {prop_desc}" if prop_desc else "",
    ]
    content_text = " | ".join([p for p in content_parts if p])

    # Parse file_date to a proper date (if possible)
    meeting_date = None
    if file_date:
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(file_date, fmt)
                meeting_date = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    # Source URL
    if registry == "norfolk":
        source_url = "https://www.norfolkresearch.org/ALIS/"
    elif registry == "middlesex_south":
        source_url = "https://www.masslandrecords.com/MiddlesexSouth/"
    else:
        source_url = record.get("source_url", "Registry of Deeds")

    # Content hash for deduplication
    content_hash = make_content_hash(town_id, book, page, file_date)

    return {
        "town_id": town_id,
        "doc_type": "Tax Taking",
        "title": title,
        "source_url": source_url,
        "content_text": content_text,
        "meeting_date": meeting_date,
        "content_hash": content_hash,
        "mentions": json.dumps({
            "address": address,
            "owner": grantee,
            "grantor": grantor,
            "book": book,
            "page": page,
            "file_date": file_date,
            "registry": registry,
            "property_description": prop_desc,
            "status": "Tax Taking Recorded",
            "legal_basis": "MGL Chapter 60",
        }),
    }


async def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("❌ Supabase credentials missing in .env")
        return

    db = SupabaseRestClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)
    connected = await db.connect()
    if not connected:
        logger.error("❌ Could not connect to Supabase")
        return

    data_dir = backend_dir / "data_cache" / "tax_delinquency"
    if not data_dir.exists():
        logger.error(f"❌ Data directory not found: {data_dir}")
        await db.disconnect()
        return

    # Find all tax taking JSON files
    json_files = sorted(data_dir.glob("*_tax_takings.json"))
    if not json_files:
        logger.warning("⚠️ No *_tax_takings.json files found. Run scrape_tax_takings_from_registry.py first.")
        await db.disconnect()
        return

    logger.info(f"📦 Found {len(json_files)} tax taking files to ingest")
    logger.info("=" * 60)

    total_inserted = 0
    total_skipped = 0

    for file_path in json_files:
        with open(file_path, "r") as f:
            data = json.load(f)

        town_id = data.get("town", file_path.stem.replace("_tax_takings", ""))
        town_name = data.get("name", town_id.title())
        records = data.get("records", [])
        status = data.get("status", "unknown")

        if status == "no_records_found" or not records:
            logger.info(f"  ⏭️ {town_name}: no records to ingest")
            continue

        logger.info(f"  📍 {town_name}: {len(records)} records...")

        # Check for existing records to avoid duplicates
        existing_count = await db.count(
            "municipal_documents",
            filters={"town_id": f"eq.{town_id}", "doc_type": "eq.Tax Taking"},
        )

        if existing_count > 0:
            logger.info(f"     ℹ️ {existing_count} existing Tax Taking records for {town_name}")

        # Convert records to documents
        docs = []
        for rec in records:
            doc = record_to_document(rec, town_id)
            docs.append(doc)

        # Batch insert with upsert on content_hash
        inserted = 0
        skipped = 0

        for doc in docs:
            try:
                await db.insert(
                    "municipal_documents",
                    doc,
                    upsert=True,
                    on_conflict="content_hash",
                    minimal=True,
                )
                inserted += 1
            except Exception as e:
                error_msg = str(e)
                if "duplicate" in error_msg.lower() or "conflict" in error_msg.lower():
                    skipped += 1
                else:
                    logger.warning(f"     ⚠️ Insert failed for {doc.get('title', '?')}: {e}")
                    skipped += 1

        total_inserted += inserted
        total_skipped += skipped
        logger.info(f"     ✅ Inserted: {inserted}, Skipped: {skipped}")

    logger.info("=" * 60)
    logger.info(f"🏁 Done! Inserted: {total_inserted}, Skipped: {total_skipped}")

    # Verify final counts
    final_count = await db.count(
        "municipal_documents",
        filters={"doc_type": "eq.Tax Taking"},
    )
    logger.info(f"📊 Total Tax Taking records in Supabase: {final_count}")

    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
