#!/usr/bin/env python3
"""
CLI test script for the Tax Delinquency / Tax Title scraper.

Usage:
    # From a URL (downloads the PDF automatically):
    python scripts/test_tax_delinquency.py --url "https://example.com/tax-title-list.pdf"

    # From a local file:
    python scripts/test_tax_delinquency.py --file path/to/delinquent_taxes.pdf

    # Default: uses a sample Town of Brookline MA tax title PDF
    python scripts/test_tax_delinquency.py
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure backend/ is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from scrapers.connectors.tax_delinquency_scraper import TaxDelinquencyScraper


# ── Default sample URLs ──────────────────────────────────────────────────
# Several MA towns publish tax-title / delinquency lists as PDFs.
# We try a few known URLs and fall back gracefully.

SAMPLE_URLS = [
    # Brookline MA – Treasurer's Tax Title list
    "https://www.brooklinema.gov/DocumentCenter/View/26078/Tax-Title-Accounts-List",
    # Weston MA
    "https://www.westonma.gov/DocumentCenter/View/29283/Tax-Title-List-as-of-033124",
]


async def main():
    parser = argparse.ArgumentParser(
        description="Test the Tax Delinquency / Tax Title PDF scraper",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--url", help="URL of a tax delinquency PDF to scrape")
    group.add_argument("--file", help="Local path to a tax delinquency PDF")
    parser.add_argument(
        "--town", default=None, help="Town name (for logging context only)",
    )
    args = parser.parse_args()

    scraper = TaxDelinquencyScraper()

    try:
        if args.file:
            print(f"📄 Extracting from local file: {args.file}")
            records = await scraper.extract_from_pdf(args.file)

        elif args.url:
            print(f"🌐 Extracting from URL: {args.url}")
            records = await scraper.extract_from_url(args.url)

        else:
            # Try sample URLs
            records = []
            for url in SAMPLE_URLS:
                print(f"🌐 Trying sample URL: {url}")
                try:
                    records = await scraper.extract_from_url(url)
                    if records:
                        break
                except Exception as e:
                    print(f"   ⚠️  Failed: {e}")
                    continue

            if not records:
                # Last resort: check for test_lexington.pdf in backend/
                local_fallback = Path(__file__).parent.parent / "test_lexington.pdf"
                if local_fallback.exists():
                    print(f"📄 Falling back to local file: {local_fallback}")
                    records = await scraper.extract_from_pdf(local_fallback)
                else:
                    print(
                        "❌ No sample URL worked and no local PDF found. "
                        "Provide --url or --file."
                    )
                    sys.exit(1)

        # ── Output ────────────────────────────────────────────────────────
        print(f"\n{'=' * 60}")
        print(f"✅ Extracted {len(records)} tax delinquency records")
        print(f"{'=' * 60}\n")

        if records:
            print(json.dumps(records, indent=2, ensure_ascii=False))

            # Quick summary
            print(f"\n{'─' * 60}")
            print("📊 Summary:")
            print(f"   Total records: {len(records)}")
            owners = {r.get("owner", "?") for r in records}
            print(f"   Unique owners: {len(owners)}")

            tax_types = {r.get("tax_type") for r in records if r.get("tax_type")}
            if tax_types:
                print(f"   Tax types:     {', '.join(sorted(tax_types))}")
        else:
            print("No records extracted. The PDF may not contain tabular tax data,")
            print("or the content may not be a tax delinquency / tax title list.")

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
