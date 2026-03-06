#!/usr/bin/env python3
"""
CLI test script for the MEPA Environmental Monitor scraper.

Usage:
    python scripts/test_mepa.py              # latest 20 filings
    python scripts/test_mepa.py --count 10   # latest 10 filings
    python scripts/test_mepa.py --type ENF   # only ENF filings
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure backend root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.connectors.mepa_scraper import MEPAScraper  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch the latest MEPA Environmental Monitor filings."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of filings to retrieve (default: 20)",
    )
    parser.add_argument(
        "--type",
        dest="doc_type",
        type=str,
        default=None,
        help="Filter by document type (ENF, EIR, FEIR, NPC, …)",
    )
    args = parser.parse_args()

    scraper = MEPAScraper()

    print(f"\n{'='*60}")
    print("  MEPA Environmental Monitor — Latest Filings")
    print(f"{'='*60}\n")

    if args.doc_type:
        print(f"  Filter: document type = {args.doc_type.upper()}\n")
        filings = await scraper.search_projects(
            document_type=args.doc_type,
            page_size=args.count,
        )
        filings = filings[: args.count]
    else:
        filings = await scraper.get_latest_filings(count=args.count)

    if not filings:
        print("  ⚠  No filings returned. The API may be temporarily unavailable.")
        sys.exit(1)

    print(f"  Retrieved {len(filings)} filing(s).\n")
    print(json.dumps(filings, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
