#!/usr/bin/env python3
"""
Focused test: Click option elements directly in multi-select listboxes.

The doc type and town fields are <select multiple="multiple" size="4"> —
they're LISTBOXES where options are always visible.
Clicking an <option> should select it.
"""

import asyncio
import re
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir.parent / ".env", override=True)

from scrapers.connectors.firecrawl_client import FirecrawlClient

FC = FirecrawlClient
BASE_URL = "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"


async def test_click_options():
    """
    Test A: Switch criteria, then click option elements in listboxes.
    8 actions total (within safe limit).
    """
    print("\n=== TEST A: Switch criteria + click TAKING option + click NEWTON option ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Step 1: Switch to Document Search mode
        FC.action_write(
            "select#SearchCriteriaName1_DDL_SearchName",
            "Recorded Land Document Search"
        ),
        FC.action_wait(5000),  # Wait for ASP.NET postback
        # Step 2: Click TAKING option in the multi-select listbox
        FC.action_click(
            "#SearchFormEx1_ACSDropDownList_DocumentType option[value='100103']"
        ),
        FC.action_wait(500),
        # Step 3: Click NEWTON option in the town multi-select listbox
        FC.action_click(
            "#SearchFormEx1_ACSDropDownList_Towns option[value='115']"
        ),
        FC.action_wait(500),
        # Step 4: Click the search button
        FC.action_click("#SearchFormEx1_btnSearch"),
        FC.action_wait(8000),  # Wait for results
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["rawHtml"])
    if result:
        html = result.get("rawHtml", "") or result.get("html", "") or result.get("markdown", "")
        print(f"  Got {len(html)} chars")

        # Check for results
        if "0 hits" in html or "Search criteria resulted in 0" in html:
            print("  ❌ 0 hits — doc type/town NOT selected")
        elif "GR" in html and ("TAKING" in html or "TAK" in html):
            print("  ✅ Got TAKING results!")
        elif "results found" in html.lower():
            print("  ✅ Results found!")

        # Save full output
        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_click_option_result.html"
        path.write_text(html)
        print(f"  Saved to {path.name}")

        # Show snippet of results area
        # Look for the results section
        snippet_start = html.find("hits")
        if snippet_start == -1:
            snippet_start = html.find("result")
        if snippet_start == -1:
            snippet_start = html.find("Search")
        if snippet_start > 0:
            print(f"  Snippet: ...{html[max(0,snippet_start-50):snippet_start+200]}...")

        return True
    else:
        print("  ❌ FireCrawl returned None (HTTP error)")
        return False


async def test_click_options_no_criteria():
    """
    Test B: Skip criteria switch. Just click options directly on initial page.
    The listboxes are visible on the initial Name Search page too.
    5 actions total.
    """
    print("\n=== TEST B: Click options WITHOUT criteria switch (fewer actions) ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Click TAKING option directly
        FC.action_click(
            "#SearchFormEx1_ACSDropDownList_DocumentType option[value='100103']"
        ),
        # Click NEWTON option directly
        FC.action_click(
            "#SearchFormEx1_ACSDropDownList_Towns option[value='115']"
        ),
        FC.action_wait(500),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["rawHtml"])
    if result:
        html = result.get("rawHtml", "") or result.get("html", "") or result.get("markdown", "")
        print(f"  Got {len(html)} chars")

        # Check if TAKING is now selected in the listbox
        taking_selected = re.search(
            r'option[^>]*value="100103"[^>]*selected', html
        )
        newton_selected = re.search(
            r'option[^>]*value="115"[^>]*selected', html
        )

        print(f"  TAKING selected: {bool(taking_selected)}")
        print(f"  NEWTON selected: {bool(newton_selected)}")

        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_click_option_B.html"
        path.write_text(html[:5000])
        print(f"  Saved first 5K to {path.name}")
        return True
    else:
        print("  ❌ FireCrawl returned None")
        return False


async def test_minimal_search():
    """
    Test C: Most minimal possible - just switch criteria and search.
    Let the default "Search All" remain. If we get results, it proves
    the criteria switch works and we just need date filtering + town.

    Uses write for date fields + click search.
    """
    print("\n=== TEST C: Document Search with date range only (no doc type filter) ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Switch to Document Search
        FC.action_write(
            "select#SearchCriteriaName1_DDL_SearchName",
            "Recorded Land Document Search"
        ),
        FC.action_wait(5000),
        # Set date range to narrow results
        FC.action_write("#SearchFormEx1_ACSTextBox_DateFrom", "01/01/2024"),
        FC.action_write("#SearchFormEx1_ACSTextBox_DateTo", "03/09/2026"),
        # Search with defaults (all types, all towns)
        FC.action_click("#SearchFormEx1_btnSearch"),
        FC.action_wait(8000),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["rawHtml"])
    if result:
        html = result.get("rawHtml", "") or result.get("html", "") or result.get("markdown", "")
        print(f"  Got {len(html)} chars")

        if "0 hits" in html:
            print("  ❌ 0 hits")
        elif "GR" in html or "GT" in html:
            print("  ✅ Got results with GR/GT rows!")
            # Count them
            gr_count = html.count(">GR<") + html.count(">GR </")
            gt_count = html.count(">GT<") + html.count(">GT </")
            print(f"  GR rows: {gr_count}, GT rows: {gt_count}")

        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_click_option_C.html"
        path.write_text(html)
        print(f"  Saved {len(html)} chars to {path.name}")

        # Check for result count
        hits_match = re.search(r'(\d+)\s+hits', html)
        if hits_match:
            print(f"  Total hits: {hits_match.group(1)}")

        return True
    else:
        print("  ❌ FireCrawl returned None")
        return False


async def main():
    print("=" * 60)
    print("Testing click-option approach for multi-select listboxes")
    print("=" * 60)

    # Test B first (fewest actions, most likely to not HTTP 500)
    await test_click_options_no_criteria()

    # Test C: search without doc type to see if criteria switch works
    await test_minimal_search()

    # Test A: full approach
    await test_click_options()

    print("\n" + "=" * 60)
    print("Tests complete")


if __name__ == "__main__":
    asyncio.run(main())
