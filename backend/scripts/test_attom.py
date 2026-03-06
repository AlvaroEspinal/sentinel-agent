#!/usr/bin/env python3
"""
CLI smoke-test for the ATTOM Property API client.

Usage:
    cd backend
    python scripts/test_attom.py                          # default sample address
    python scripts/test_attom.py "10 Main St" "Wellesley, MA"  # custom address
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — ensure we can import from the backend package
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")  # project root .env
load_dotenv()  # local override

from scrapers.connectors.attom_client import AttomClient  # noqa: E402


def _pp(label: str, data: dict) -> None:
    """Pretty-print a section."""
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  {label}")
    print(sep)
    print(json.dumps(data, indent=2, default=str))


async def main() -> None:
    api_key = os.getenv("ATTOM_API_KEY", "")
    if not api_key:
        print(
            "\n⚠️  ATTOM_API_KEY is not set in .env — skipping live API calls.\n"
            "   Set ATTOM_API_KEY in your .env file and re-run.\n"
        )
        sys.exit(0)

    # Allow custom address from CLI args
    if len(sys.argv) >= 3:
        address1, address2 = sys.argv[1], sys.argv[2]
    else:
        address1 = "83 Longfellow Rd"
        address2 = "Wellesley, MA"

    print(f"\n🏠  ATTOM Property API — Testing with: {address1}, {address2}\n")

    client = AttomClient(api_key=api_key)

    # 1. Property detail
    print("→ Fetching property detail …")
    detail = await client.get_property_detail(address1, address2)
    _pp("PROPERTY DETAIL", detail)

    # 2. Sales / deed history
    print("\n→ Fetching sales / deed history …")
    sales = await client.get_sales_history(address1, address2)
    _pp("SALES HISTORY", sales)

    # 3. Mortgage / lien detail
    print("\n→ Fetching mortgage / lien detail …")
    mortgage = await client.get_mortgage_detail(address1, address2)
    _pp("MORTGAGE / LIEN DETAIL", mortgage)

    # 4. Full profile (convenience)
    print("\n→ Fetching full profile (combined) …")
    profile = await client.get_full_profile(address1, address2)
    _pp("FULL PROFILE", profile)

    print("\n✅  All ATTOM tests completed.\n")


if __name__ == "__main__":
    asyncio.run(main())
