#!/usr/bin/env python3
"""
Fix MEPA filing town assignments in the municipal_documents table.

Problem:
  5,314 MEPA Environmental Monitor records have town_id=NULL (they were
  ingested without municipality information from the MEPA API).

Strategy (two-phase):
  Phase 1: Text-based matching — search content_text Location field for
           MVP town names with word-boundary checks to reduce false positives.
  Phase 2: MEPA API re-query — for each MVP town, query the MEPA eMonitor API
           with the municipality filter and match by EEA number to update town_id.
  Phase 3: Report — show final distribution of MEPA filings by town_id.

Usage:
  python fix_mepa_towns.py                  # Run both phases
  python fix_mepa_towns.py --phase 1        # Text matching only
  python fix_mepa_towns.py --phase 2        # API re-query only
  python fix_mepa_towns.py --dry-run        # Preview changes without writing
  python fix_mepa_towns.py --phase 1 --dry-run
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Add the backend root to python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

MEPA_SEARCH_URL = (
    "https://t7i6mic1h4.execute-api.us-east-1.amazonaws.com"
    "/PROD/V1.0.0/api/Project/search"
)
MEPA_API_KEY = "ZyygCR4t0y8gKbqSbbuUO6g4GrfcGRMF9QRplY4m"
MEPA_ORIGIN = "https://eeaonline.eea.state.ma.us"

# The 12 MVP municipalities
MVP_TOWNS = [
    "newton",
    "wellesley",
    "weston",
    "brookline",
    "needham",
    "dover",
    "sherborn",
    "natick",
    "wayland",
    "lincoln",
    "concord",
    "lexington",
]

# Both doc_type values used for MEPA records
MEPA_DOC_TYPES = ["MEPA Environmental Monitor", "mepa_filing"]

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("fix_mepa_towns")


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def _supa_headers(extra: Optional[dict] = None) -> dict:
    h = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


async def supa_count(
    client: httpx.AsyncClient,
    filters: dict,
) -> int:
    """Count rows in municipal_documents matching filters."""
    params = {"select": "id", **filters}
    r = await client.get(
        f"{SUPABASE_URL}/rest/v1/municipal_documents",
        headers=_supa_headers({"Prefer": "count=exact", "Range": "0-0"}),
        params=params,
    )
    cr = r.headers.get("content-range", "")
    if "/" in cr:
        total = cr.split("/")[-1]
        if total not in ("*", ""):
            return int(total)
    return 0


async def supa_fetch(
    client: httpx.AsyncClient,
    select: str,
    filters: dict,
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    """Fetch rows from municipal_documents."""
    params = {"select": select, "limit": str(limit), "offset": str(offset), **filters}
    r = await client.get(
        f"{SUPABASE_URL}/rest/v1/municipal_documents",
        headers=_supa_headers(),
        params=params,
    )
    r.raise_for_status()
    return r.json()


async def supa_fetch_all(
    client: httpx.AsyncClient,
    select: str,
    filters: dict,
    page_size: int = 1000,
) -> list[dict]:
    """Paginate through all matching rows."""
    all_rows: list[dict] = []
    offset = 0
    while True:
        batch = await supa_fetch(client, select, filters, limit=page_size, offset=offset)
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return all_rows


async def supa_patch(
    client: httpx.AsyncClient,
    filters: dict,
    data: dict,
) -> int:
    """PATCH (update) rows matching filters. Returns HTTP status."""
    params = {**filters}
    r = await client.patch(
        f"{SUPABASE_URL}/rest/v1/municipal_documents",
        headers=_supa_headers({"Prefer": "return=minimal"}),
        params=params,
        json=data,
    )
    r.raise_for_status()
    return r.status_code


async def supa_patch_by_ids(
    client: httpx.AsyncClient,
    ids: list[str],
    data: dict,
    batch_size: int = 50,
) -> int:
    """Update rows by list of IDs, in batches. Returns count updated."""
    updated = 0
    for i in range(0, len(ids), batch_size):
        chunk = ids[i : i + batch_size]
        # PostgREST: id=in.(uuid1,uuid2,...)
        id_list = ",".join(chunk)
        r = await client.patch(
            f"{SUPABASE_URL}/rest/v1/municipal_documents",
            headers=_supa_headers({"Prefer": "return=minimal"}),
            params={"id": f"in.({id_list})"},
            json=data,
        )
        r.raise_for_status()
        updated += len(chunk)
    return updated


# ---------------------------------------------------------------------------
# Phase 1: Text-based matching
# ---------------------------------------------------------------------------

def _extract_location(content_text: str) -> str:
    """Extract the Location field from pipe-delimited content_text."""
    if "Location:" in content_text:
        after = content_text.split("Location:", 1)[1]
        loc = after.split("|")[0].strip()
        return loc
    return ""


def _is_strong_town_match(town: str, title: str, location: str) -> bool:
    """
    Determine if the record strongly belongs to a town based on title/location.

    Rules to reduce false positives:
    - Town name as a standalone word in Location (not as part of a street name)
    - For ambiguous towns (lincoln, dover, concord, weston), require stronger signals:
      only match on Location field, never on title alone
    - 'Newton Street' or 'Newton Road' are NOT Newton-the-city
    - Location like 'NEWTON' or 'CITY OF NEWTON' is valid
    """
    town_lower = town.lower()
    title_lower = title.lower()
    loc_lower = location.lower()

    # Towns whose names are also common street/place names — require Location-only match
    AMBIGUOUS_TOWNS = {"lincoln", "dover", "concord", "weston"}

    # Patterns that indicate a street name, not a city
    # NOTE: Order matters — check longer forms before shorter abbreviations.
    # Include bare abbreviations (e.g., "st", "rd", "ave") for end-of-string cases
    # like "CONCORD ST" where no trailing punctuation follows.
    STREET_SUFFIXES = [
        "street", "st.", "st,", "st ", "st/", "st",
        "road", "rd.", "rd,", "rd ", "rd",
        "avenue", "ave.", "ave,", "ave ", "ave",
        "lane", "ln.", "ln,", "ln",
        "drive", "dr.", "dr,", "dr",
        "way", "place", "pl.", "pl,",
        "circle", "court", "ct.", "ct,",
        "boulevard", "blvd.", "terrace",
        "pike", "turnpike", "highway", "hwy",
        "path", "trail", "parkway", "pkwy",
    ]

    def _is_town_as_city_in_location(text: str) -> bool:
        """
        Check if town name appears as a city reference in a Location field.
        More permissive than title matching since Location is a structured field.
        """
        pattern = r'\b' + re.escape(town_lower) + r'\b'
        matches = list(re.finditer(pattern, text))
        if not matches:
            return False

        for m in matches:
            end_pos = m.end()
            after_text = text[end_pos:].strip().lower()

            # If followed by a street suffix, it's a street name
            # Use regex word boundary for short suffixes to avoid false matches
            is_street = False
            for sfx in STREET_SUFFIXES:
                if after_text.startswith(sfx):
                    # For bare abbreviations (no trailing punct), verify word boundary
                    rest_after_sfx = after_text[len(sfx):]
                    if rest_after_sfx == "" or not rest_after_sfx[0].isalpha():
                        is_street = True
                        break
            if is_street:
                continue

            # If followed by "&" or "and" it's likely a cross-street
            # e.g., "LINCOLN & DANIELS STREET"
            if after_text.startswith("&") or after_text.startswith("and "):
                continue

            # If preceded by "&" or "/" it's likely a cross-street reference
            before_text = text[: m.start()].rstrip()
            if before_text and before_text[-1] in ("&", "/"):
                continue

            # If preceded by a number, it's likely a street address ("282 LINCOLN ...")
            before_word = before_text.split()[-1] if before_text.split() else ""
            if before_word.isdigit():
                # But "282 LINCOLN" could be an address ON Lincoln, check what follows
                # If nothing meaningful follows or it's followed by a comma, could be city
                if after_text and after_text[0] not in (",", " ", ""):
                    continue

            return True

        return False

    # === Exact Location matches (highest confidence) ===
    if loc_lower == town_lower:
        return True
    if loc_lower.startswith(town_lower + ","):
        return True
    if f"city of {town_lower}" in loc_lower:
        return True
    if f"town of {town_lower}" in loc_lower:
        return True

    # === Word boundary match in Location (with street exclusion) ===
    if _is_town_as_city_in_location(loc_lower):
        return True

    # === Title matches (only for non-ambiguous towns) ===
    if town_lower not in AMBIGUOUS_TOWNS:
        # For titles, require stronger evidence: town name as a standalone word
        # that is NOT followed by common suffixes like "Plaza", "Park", etc.
        TITLE_EXCLUSION_SUFFIXES = STREET_SUFFIXES + [
            "plaza", "park", "woods", "hill", "hills", "heights",
            "center", "centre", "mall", "square",
        ]
        pattern = r'\b' + re.escape(town_lower) + r'\b'
        title_matches = list(re.finditer(pattern, title_lower))
        for m in title_matches:
            after_text = title_lower[m.end():].strip()
            is_place = any(after_text.startswith(s) for s in TITLE_EXCLUSION_SUFFIXES)
            if is_place:
                continue

            # Also exclude if preceded by number (e.g., "one lincoln street")
            before_text = title_lower[: m.start()].rstrip()
            before_word = before_text.split()[-1] if before_text.split() else ""
            if before_word.isdigit() or before_word in ("one", "two"):
                continue

            # Also exclude town-name as a prefix with hyphen (e.g., "lincoln-sudbury")
            if m.end() < len(title_lower) and title_lower[m.end()] == "-":
                continue

            return True

    return False


async def phase1_text_matching(
    client: httpx.AsyncClient,
    dry_run: bool = False,
) -> Dict[str, int]:
    """
    Phase 1: Match MEPA records to MVP towns using text content.

    Examines the content_text Location field and title for town name references.
    Uses word boundary matching and street-name exclusion to reduce false positives.

    Returns dict of town -> count of records matched.
    """
    logger.info("=" * 60)
    logger.info("PHASE 1: Text-Based Town Matching")
    logger.info("=" * 60)

    # Fetch all MEPA records with NULL town_id
    logger.info("Fetching MEPA records with NULL town_id...")
    records = await supa_fetch_all(
        client,
        select="id,title,content_text",
        filters={
            "doc_type": "eq.MEPA Environmental Monitor",
            "town_id": "is.null",
        },
    )
    logger.info(f"Found {len(records)} MEPA records with NULL town_id")

    if not records:
        logger.info("No unassigned records to process.")
        return {}

    # Track matches per town
    matches: Dict[str, List[str]] = {town: [] for town in MVP_TOWNS}
    matched_ids: Set[str] = set()

    for record in records:
        rid = record["id"]
        title = record.get("title") or ""
        content_text = record.get("content_text") or ""
        location = _extract_location(content_text)

        for town in MVP_TOWNS:
            if rid in matched_ids:
                break  # Already matched to a town
            if _is_strong_town_match(town, title, location):
                matches[town].append(rid)
                matched_ids.add(rid)

    # Report and apply
    results: Dict[str, int] = {}
    total_matched = 0

    for town in MVP_TOWNS:
        count = len(matches[town])
        if count == 0:
            continue
        results[town] = count
        total_matched += count
        logger.info(f"  {town}: {count} records matched")

        if not dry_run:
            updated = await supa_patch_by_ids(
                client, matches[town], {"town_id": town}
            )
            logger.info(f"    -> Updated {updated} records to town_id='{town}'")

    logger.info(f"\nPhase 1 total: {total_matched} records matched to MVP towns")
    if dry_run:
        logger.info("  (DRY RUN — no changes written)")

    return results


# ---------------------------------------------------------------------------
# Phase 2: MEPA API re-query
# ---------------------------------------------------------------------------

async def _query_mepa_api(
    client: httpx.AsyncClient,
    municipality: str,
    page: int = 1,
    page_size: int = 500,
) -> List[Dict[str, Any]]:
    """Query the MEPA API for projects in a specific municipality."""
    params = {
        "Municipality": municipality,
        "Page": page,
        "PageSize": page_size,
    }
    headers = {
        "x-api-key": MEPA_API_KEY,
        "origin": MEPA_ORIGIN,
        "Accept": "application/json",
    }
    try:
        r = await client.get(
            MEPA_SEARCH_URL, params=params, headers=headers, timeout=30.0
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return data.get("list", data.get("results", []))
    except Exception as exc:
        logger.error(f"MEPA API error for {municipality}: {exc}")
        return []


def _extract_eea_number_from_content(content_text: str) -> str:
    """Extract EEA Number UUID from pipe-delimited content_text."""
    if "EEA Number:" in content_text:
        after = content_text.split("EEA Number:", 1)[1]
        eea = after.split("|")[0].strip()
        return eea.lower()
    return ""


def _extract_eea_number_from_url(source_url: str) -> str:
    """Extract EEA number from the source_url (last path segment)."""
    if source_url and "/project/" in source_url:
        return source_url.split("/project/")[-1].strip().lower()
    return ""


async def phase2_api_requery(
    client: httpx.AsyncClient,
    dry_run: bool = False,
) -> Dict[str, int]:
    """
    Phase 2: Re-query the MEPA API with municipality filter and match
    results to existing records by EEA number.
    """
    logger.info("=" * 60)
    logger.info("PHASE 2: MEPA API Re-Query by Municipality")
    logger.info("=" * 60)

    # Build a lookup of all unassigned MEPA records by EEA number
    logger.info("Fetching remaining unassigned MEPA records...")
    records = await supa_fetch_all(
        client,
        select="id,title,content_text,source_url",
        filters={
            "doc_type": "eq.MEPA Environmental Monitor",
            "town_id": "is.null",
        },
    )
    logger.info(f"Found {len(records)} unassigned MEPA records")

    if not records:
        logger.info("No unassigned records remaining.")
        return {}

    # Index by EEA number (from content_text and source_url)
    eea_to_ids: Dict[str, str] = {}
    title_to_ids: Dict[str, str] = {}

    for rec in records:
        rid = rec["id"]
        ct = rec.get("content_text") or ""
        url = rec.get("source_url") or ""
        title = (rec.get("title") or "").strip().upper()

        eea_from_ct = _extract_eea_number_from_content(ct)
        eea_from_url = _extract_eea_number_from_url(url)

        if eea_from_ct:
            eea_to_ids[eea_from_ct] = rid
        if eea_from_url:
            eea_to_ids[eea_from_url] = rid
        if title:
            title_to_ids[title] = rid

    logger.info(f"Indexed {len(eea_to_ids)} EEA numbers, {len(title_to_ids)} titles")

    # Query MEPA API for each MVP town
    results: Dict[str, int] = {}
    total_matched = 0

    # Use a separate client for MEPA API to avoid header conflicts
    async with httpx.AsyncClient(timeout=30.0) as mepa_client:
        for town in MVP_TOWNS:
            # The API expects proper casing (e.g., "Newton" not "newton")
            municipality = town.capitalize()
            logger.info(f"\nQuerying MEPA API for municipality='{municipality}'...")

            all_projects: list = []
            page = 1
            while True:
                projects = await _query_mepa_api(
                    mepa_client, municipality, page=page, page_size=500
                )
                if not projects:
                    break
                all_projects.extend(projects)
                if len(projects) < 500:
                    break
                page += 1
                await asyncio.sleep(0.5)  # Rate limiting

            logger.info(f"  API returned {len(all_projects)} projects for {municipality}")

            matched_ids: list[str] = []
            for proj in all_projects:
                eea = (proj.get("eeaNumber") or proj.get("projectId") or "").lower()
                proj_name = (proj.get("projectName") or proj.get("name") or "").strip().upper()

                # Match by EEA number
                rid = eea_to_ids.get(eea)
                if not rid and proj_name:
                    rid = title_to_ids.get(proj_name)

                if rid:
                    matched_ids.append(rid)

            if matched_ids:
                # Deduplicate
                matched_ids = list(set(matched_ids))
                results[town] = len(matched_ids)
                total_matched += len(matched_ids)
                logger.info(f"  {town}: {len(matched_ids)} records matched via API")

                if not dry_run:
                    updated = await supa_patch_by_ids(
                        client, matched_ids, {"town_id": town}
                    )
                    logger.info(f"    -> Updated {updated} records")
            else:
                logger.info(f"  {town}: no new matches from API")

            # Be polite to the API
            await asyncio.sleep(1.0)

    logger.info(f"\nPhase 2 total: {total_matched} records matched via MEPA API")
    if dry_run:
        logger.info("  (DRY RUN — no changes written)")

    return results


# ---------------------------------------------------------------------------
# Phase 3: Verification report
# ---------------------------------------------------------------------------

async def phase3_report(client: httpx.AsyncClient) -> None:
    """Print a summary of MEPA filing distribution by town_id."""
    logger.info("=" * 60)
    logger.info("PHASE 3: Verification Report")
    logger.info("=" * 60)

    # Count by doc_type
    for doc_type in MEPA_DOC_TYPES:
        total = await supa_count(client, {"doc_type": f"eq.{doc_type}"})
        logger.info(f"\n  doc_type='{doc_type}': {total} total records")

        # Count NULL town_id
        null_count = await supa_count(
            client, {"doc_type": f"eq.{doc_type}", "town_id": "is.null"}
        )
        logger.info(f"    town_id=NULL: {null_count}")

        # Count per MVP town
        for town in MVP_TOWNS:
            count = await supa_count(
                client, {"doc_type": f"eq.{doc_type}", "town_id": f"eq.{town}"}
            )
            if count > 0:
                logger.info(f"    {town}: {count}")

        # Count non-MVP, non-NULL
        non_null_total = total - null_count
        mvp_total = 0
        for t in MVP_TOWNS:
            c = await supa_count(
                client, {"doc_type": f"eq.{doc_type}", "town_id": f"eq.{t}"}
            )
            mvp_total += c
        other = non_null_total - mvp_total
        if other > 0:
            logger.info(f"    (other towns): {other}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Fix MEPA filing town assignments")
    parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2],
        default=None,
        help="Run only phase 1 (text) or phase 2 (API). Default: both.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to database.",
    )
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Before counts
        logger.info("=" * 60)
        logger.info("BEFORE: MEPA record distribution")
        logger.info("=" * 60)
        for doc_type in MEPA_DOC_TYPES:
            total = await supa_count(client, {"doc_type": f"eq.{doc_type}"})
            null_count = await supa_count(
                client, {"doc_type": f"eq.{doc_type}", "town_id": "is.null"}
            )
            assigned = total - null_count
            logger.info(
                f"  {doc_type}: {total} total, {null_count} unassigned (NULL), "
                f"{assigned} assigned"
            )

        # Run phases
        run_phase1 = args.phase is None or args.phase == 1
        run_phase2 = args.phase is None or args.phase == 2

        phase1_results = {}
        phase2_results = {}

        if run_phase1:
            phase1_results = await phase1_text_matching(client, dry_run=args.dry_run)

        if run_phase2:
            phase2_results = await phase2_api_requery(client, dry_run=args.dry_run)

        # Final report
        await phase3_report(client)

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        if phase1_results:
            p1_total = sum(phase1_results.values())
            logger.info(f"Phase 1 (text matching): {p1_total} records assigned")
            for town, count in sorted(phase1_results.items()):
                logger.info(f"  {town}: {count}")
        if phase2_results:
            p2_total = sum(phase2_results.values())
            logger.info(f"Phase 2 (API re-query): {p2_total} records assigned")
            for town, count in sorted(phase2_results.items()):
                logger.info(f"  {town}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
