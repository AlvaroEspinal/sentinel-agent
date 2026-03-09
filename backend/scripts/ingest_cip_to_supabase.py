#!/usr/bin/env python3
"""
Ingest Capital Improvement Plan (CIP) records to Supabase.

Reads CIP JSON files from data_cache/cip/ (one per town) and inserts
summary records into the `municipal_documents` table.

Each CIP file contains:
  - town, name, status, source_url, pdf_used, scraped_at
  - project_count: number of CIP projects
  - projects: list of {project_name, department, total_cost, fy_year, description, category}
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

CIP_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "cip"


def build_content_text(data: dict) -> str:
    """Flatten CIP projects into searchable text."""
    parts = []
    town = data.get("town", data.get("name", "Unknown"))
    parts.append(f"Capital Improvement Plan: {town}")
    parts.append(f"Projects: {data.get('project_count', 0)}")

    if data.get("pdf_used"):
        parts.append(f"Source PDF: {data['pdf_used']}")

    for proj in data.get("projects", []):
        name = proj.get("project_name", "")
        dept = proj.get("department", "")
        cost = proj.get("total_cost", "")
        fy = proj.get("fy_year", "")
        desc = proj.get("description", "")
        cat = proj.get("category", "")

        line = f"  {name}"
        if dept:
            line += f" | Dept: {dept}"
        if cat:
            line += f" | Category: {cat}"
        if cost:
            line += f" | Cost: {cost}"
        if fy:
            line += f" | FY: {fy}"
        parts.append(line)
        if desc:
            parts.append(f"    {desc[:200]}")

    return "\n".join(parts)


async def ingest_cip(db: SupabaseRestClient):
    """Read CIP JSONs and insert into Supabase."""
    logger.info("--- Starting CIP Ingestion ---")

    if not CIP_DIR.exists():
        logger.error(f"CIP directory not found: {CIP_DIR}")
        return

    files = sorted(CIP_DIR.glob("*_cip.json"))
    logger.info(f"Found {len(files)} CIP files in {CIP_DIR}")

    inserted = 0
    updated = 0
    skipped = 0
    errors = 0

    for fpath in files:
        town_id = fpath.stem.replace("_cip", "")
        logger.info(f"Processing CIP for: {town_id}")

        try:
            data = json.loads(fpath.read_text())
        except Exception as e:
            logger.error(f"Failed to read {fpath.name}: {e}")
            errors += 1
            continue

        status = data.get("status", "")
        if status not in ("success", "partial", "extracted"):
            logger.warning(f"Skipping {town_id} — status={status!r}")
            skipped += 1
            continue

        projects = data.get("projects", [])
        project_count = data.get("project_count", len(projects))
        town_name = data.get("town", data.get("name", town_id.title()))

        if project_count == 0 and not projects:
            logger.warning(f"Skipping {town_id} — no projects found")
            skipped += 1
            continue

        title = f"{town_name} Capital Improvement Plan"
        content_text = build_content_text(data)
        mentions = {
            "projects": projects,
            "project_count": project_count,
            "pdf_used": data.get("pdf_used", ""),
        }

        # Check for existing row
        existing = await db.fetch(
            "municipal_documents",
            select="id",
            filters={"town_id": f"eq.{town_id}", "doc_type": "eq.capital_improvement"},
            limit=1,
        )

        record = {
            "town_id": town_id,
            "doc_type": "capital_improvement",
            "title": title,
            "source_url": data.get("source_url", ""),
            "content_text": content_text[:10000],
            "mentions": mentions,
            "scraped_at": data.get("scraped_at", datetime.now(timezone.utc).isoformat()),
        }

        try:
            if existing:
                await db.update(
                    "municipal_documents",
                    {"town_id": f"eq.{town_id}", "doc_type": "eq.capital_improvement"},
                    record,
                )
                logger.info(f"  UPDATED  {town_id}: {project_count} projects")
                updated += 1
            else:
                await db.insert("municipal_documents", record)
                logger.info(f"  INSERTED {town_id}: {project_count} projects")
                inserted += 1
        except Exception as e:
            logger.error(f"  ERROR    {town_id}: {e}")
            errors += 1

    logger.info(
        f"\n--- Done: {inserted} inserted, {updated} updated, "
        f"{skipped} skipped, {errors} errors ---"
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
    await ingest_cip(db)
    await db.disconnect()
    logger.info("Done! CIP ingestion complete.")


if __name__ == "__main__":
    asyncio.run(main())
