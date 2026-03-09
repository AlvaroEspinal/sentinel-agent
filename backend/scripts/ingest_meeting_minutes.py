#!/usr/bin/env python3
"""
Ingest Meeting Minutes records to Supabase.

Reads meeting minutes JSON files from data_cache/meeting_minutes/ (one per town)
and inserts individual document records into the `municipal_documents` table.

Each minutes file contains:
  - town, name, scraped_at, total_documents, year_range
  - boards: list of board names
  - documents: list of {board, title, date, url, content}

Creates one municipal_documents row per board (aggregated), so agents can
search across a town's meeting minutes efficiently.
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

MINUTES_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "meeting_minutes"


def build_content_text(data: dict) -> str:
    """Build searchable text from meeting minutes."""
    parts = []
    town = data.get("town", data.get("name", "Unknown"))
    parts.append(f"Meeting Minutes: {town}")
    parts.append(f"Total documents: {data.get('total_documents', 0)}")
    parts.append(f"Year range: {data.get('year_range', 'N/A')}")

    boards = data.get("boards", [])
    if boards:
        parts.append(f"Boards: {', '.join(boards)}")

    # Include recent document titles (most recent first)
    docs = data.get("documents", [])
    docs_sorted = sorted(docs, key=lambda d: d.get("date") or "", reverse=True)

    for doc in docs_sorted[:50]:  # Cap at 50 most recent
        board = doc.get("board", "")
        title = doc.get("title", "")
        date = doc.get("date", "")
        line = f"  [{date}] {board}: {title}"
        parts.append(line)

        # Include content snippet if available
        content = doc.get("content", "")
        if content:
            snippet = content[:300].replace("\n", " ").strip()
            parts.append(f"    {snippet}")

    return "\n".join(parts)


async def ingest_minutes(db: SupabaseRestClient):
    """Read meeting minutes JSONs and insert into Supabase."""
    logger.info("--- Starting Meeting Minutes Ingestion ---")

    if not MINUTES_DIR.exists():
        logger.error(f"Meeting minutes directory not found: {MINUTES_DIR}")
        return

    files = sorted(MINUTES_DIR.glob("*_minutes.json"))
    logger.info(f"Found {len(files)} minutes files in {MINUTES_DIR}")

    inserted = 0
    updated = 0
    errors = 0

    for fpath in files:
        town_id = fpath.stem.replace("_minutes", "")
        logger.info(f"Processing minutes for: {town_id}")

        try:
            data = json.loads(fpath.read_text())
        except Exception as e:
            logger.error(f"Failed to read {fpath.name}: {e}")
            errors += 1
            continue

        # Handle two formats:
        # Format A (Newton): dict with {town, documents, boards, ...}
        # Format B (Lexington, Wayland): list of individual doc records
        if isinstance(data, list):
            # Convert list format to dict format
            documents = data
            boards_set = set()
            for doc in documents:
                b = doc.get("board", "")
                if b:
                    boards_set.add(b)
            boards = sorted(boards_set)
            town_name = town_id.replace("_", " ").title()
            total_docs = len(documents)
            year_range = ""
            source_url = documents[0].get("source_url", "") if documents else ""
            scraped_at = datetime.now(timezone.utc).isoformat()
            # Rebuild as dict for build_content_text
            data = {
                "town": town_name,
                "total_documents": total_docs,
                "year_range": year_range,
                "boards": boards,
                "documents": [
                    {
                        "board": d.get("board", ""),
                        "title": d.get("title", ""),
                        "date": d.get("meeting_date", ""),
                        "url": d.get("file_url", d.get("source_url", "")),
                        "content": d.get("content_text", ""),
                    }
                    for d in documents
                ],
            }
        else:
            if data.get("error"):
                logger.warning(f"Skipping {town_id} — has error: {data['error']}")
                errors += 1
                continue
            source_url = data.get("source_url", "")
            scraped_at = data.get("scraped_at", datetime.now(timezone.utc).isoformat())

        total_docs = data.get("total_documents", 0)
        boards = data.get("boards", [])
        documents = data.get("documents", [])
        town_name = data.get("town", data.get("name", town_id.title()))

        title = f"{town_name} Meeting Minutes"
        content_text = build_content_text(data)

        mentions = {
            "total_documents": total_docs,
            "year_range": data.get("year_range", ""),
            "boards": boards,
            "board_count": len(boards),
            "document_count": len(documents),
        }

        # Check for existing row
        existing = await db.fetch(
            "municipal_documents",
            select="id",
            filters={"town_id": f"eq.{town_id}", "doc_type": "eq.meeting_minutes"},
            limit=1,
        )

        record = {
            "town_id": town_id,
            "doc_type": "meeting_minutes",
            "title": title,
            "source_url": source_url,
            "content_text": content_text[:10000],
            "mentions": mentions,
            "scraped_at": scraped_at,
        }

        try:
            if existing:
                await db.update(
                    "municipal_documents",
                    {"town_id": f"eq.{town_id}", "doc_type": "eq.meeting_minutes"},
                    record,
                )
                logger.info(f"  UPDATED  {town_id}: {total_docs} docs across {len(boards)} boards")
                updated += 1
            else:
                await db.insert("municipal_documents", record)
                logger.info(f"  INSERTED {town_id}: {total_docs} docs across {len(boards)} boards")
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
    await ingest_minutes(db)
    await db.disconnect()
    logger.info("Done! Meeting minutes ingestion complete.")


if __name__ == "__main__":
    asyncio.run(main())
