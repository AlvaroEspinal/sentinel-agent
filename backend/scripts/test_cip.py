#!/usr/bin/env python3
"""CLI test for the CIP Extractor.

Processes a sample chunk of text resembling a Massachusetts town Capital
Improvement Plan and prints structured JSON to stdout.

Usage:
    python scripts/test_cip.py                    # embedded sample, Wellesley
    python scripts/test_cip.py --town Newton      # change town context
    python scripts/test_cip.py --file plan.txt    # read from a file instead
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from scrapers.connectors.cip_extractor import CIPExtractor

# ── Sample CIP text ──────────────────────────────────────────────────────
SAMPLE_CIP_TEXT = """
TOWN OF WELLESLEY
CAPITAL IMPROVEMENT PLAN — FISCAL YEARS 2027–2031
Approved by the Advisory Committee, March 2026

ARTICLE 14 — DEPARTMENT OF PUBLIC WORKS

Item 1: Cedar Street Reconstruction
The Department of Public Works requests $1,200,000 for the full-depth
reconstruction of Cedar Street from Washington Street to Route 9.  Work
includes new drainage infrastructure, ADA-compliant sidewalks, and LED
streetlights.  Funding source: General Fund / Free Cash.
Proposed fiscal year: FY2027.

Item 2: Water Main Replacement — Weston Road
$875,000 is requested to replace the aging 8-inch cast-iron water main on
Weston Road (approx. 3,200 linear feet).  The existing main dates to 1954
and has experienced three breaks in the last two years.
Funding: Water Enterprise Fund.  Proposed fiscal year: FY2027.

ARTICLE 15 — SCHOOL COMMITTEE

Item 3: Wellesley High School HVAC Modernization (Phase II)
The School Committee requests $3,400,000 for the second phase of HVAC
upgrades at Wellesley High School, 50 Rice Street.  Scope includes
replacement of rooftop units serving the B-Wing and gymnasium,
installation of building automation controls, and asbestos abatement.
Funding: Bond authorization.  Proposed fiscal year: FY2028.

ARTICLE 16 — PARKS & RECREATION

Item 4: Hunnewell Field Synthetic Turf Replacement
$950,000 to remove and replace the synthetic turf surface at Hunnewell
Field, Cameron Street.  The current surface has exceeded its 10-year
useful life.  Includes shock-pad replacement and perimeter drainage
improvements.  Funding: Community Preservation Act (CPA).
Proposed fiscal year: FY2027.

ARTICLE 17 — FIRE DEPARTMENT

Item 5: Engine 2 Replacement
The Fire Department requests $785,000 for the purchase of a new Class-A
pumper to replace Engine 2, a 2008 Pierce Dash currently stationed at
the Wellesley Hills Fire Station, 457 Washington Street.  The current
apparatus has 148,000 miles and recurring pump-test failures.
Funding: General Fund.  Proposed fiscal year: FY2028.
"""


async def main(args: argparse.Namespace) -> None:
    print("═" * 60)
    print("  CIP Extractor — Test Run")
    print("═" * 60)

    extractor = CIPExtractor()

    # Determine input text
    if args.file:
        filepath = Path(args.file)
        if not filepath.exists():
            print(f"Error: file not found — {filepath}")
            sys.exit(1)
        text = filepath.read_text(encoding="utf-8")
        print(f"  Source : {filepath}")
    else:
        text = SAMPLE_CIP_TEXT
        print("  Source : embedded sample CIP text")

    town = args.town
    doc_type = args.doc_type
    print(f"  Town   : {town}")
    print(f"  Type   : {doc_type}")
    print(f"  Chars  : {len(text):,}")
    print("─" * 60)
    print("Sending to Claude for extraction …\n")

    result = await extractor.extract_cip_projects(text, town, doc_type)

    print(json.dumps(result, indent=2))

    print("─" * 60)
    count = result.get("project_count", 0)
    if count:
        print(f"✅  Extracted {count} project(s) successfully.")
    else:
        print("⚠️   No projects extracted — check API key / input text.")
    print("═" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test the CIP Extractor")
    parser.add_argument("--town", default="Wellesley", help="Town context (default: Wellesley)")
    parser.add_argument("--file", default=None, help="Path to a text file to extract from")
    parser.add_argument("--doc-type", default="capital_plan",
                        choices=["capital_plan", "warrant"],
                        help="Document type (default: capital_plan)")
    args = parser.parse_args()
    asyncio.run(main(args))
