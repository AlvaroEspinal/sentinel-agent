#!/usr/bin/env python3
"""
Test keyboard-based approach for <select> elements.

FireCrawl's `write` action calls Playwright's fill(), which does NOT work
on <select> elements. We need to use keyboard navigation instead:
  1. Click select to focus it
  2. Use ArrowDown/type-ahead to pick the option
  3. For criteria: "Document Search" is 2nd option → 1 ArrowDown from default

Multi-select listboxes: type first few chars to jump to option, then Space to select.
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


async def test_keyboard_criteria():
    """
    Test A: Use keyboard to switch criteria dropdown.
    Click select → ArrowDown (to move from 'Name Search' to 'Document Search')
    The postback should fire on change.
    """
    print("\n=== TEST A: Keyboard ArrowDown to switch criteria ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Focus the criteria dropdown
        FC.action_click("select#SearchCriteriaName1_DDL_SearchName"),
        FC.action_wait(500),
        # ArrowDown once: Name Search → Document Search
        FC.action_press("ArrowDown"),
        FC.action_wait(6000),  # Wait for ASP.NET postback
        # Scrape to see if form changed
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["rawHtml"])
    if result:
        html = result.get("rawHtml", "") or result.get("html", "")
        print(f"  Got {len(html)} chars")

        # Check which criteria is selected
        crit_selected = re.findall(r'<option[^>]*selected[^>]*>([^<]*)</option>', html)
        print(f"  Selected options: {crit_selected}")

        # Check if Name Search fields are gone (would indicate switch worked)
        has_lastname = "ACSTextBox_LastName" in html
        has_doctype = "ACSDropDownList_DocumentType" in html
        print(f"  LastName field: {has_lastname}")
        print(f"  DocType listbox: {has_doctype}")

        # Look for Document Search specific fields
        if "ACSTextBox_DateFrom" in html and not has_lastname:
            print("  ✅ Criteria switched! Date fields present, name fields gone")
        elif has_lastname:
            print("  ❌ Still on Name Search")

        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_keyboard_A.html"
        path.write_text(html)
        print(f"  Saved to {path.name}")
        return True
    else:
        print("  ❌ FireCrawl returned None")
        return False


async def test_keyboard_full_search():
    """
    Test B: Full search with keyboard navigation.
    1. Click criteria → ArrowDown → wait for postback
    2. Set date fields with write (text inputs work fine)
    3. Click search

    Skip doc type/town for now — search ALL to see if we get any results.
    """
    print("\n=== TEST B: Keyboard criteria switch + date range search ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Switch criteria with keyboard
        FC.action_click("select#SearchCriteriaName1_DDL_SearchName"),
        FC.action_wait(300),
        FC.action_press("ArrowDown"),  # → Document Search
        FC.action_wait(6000),  # Wait for postback reload
        # Set date range (write works on text inputs)
        FC.action_write("#SearchFormEx1_ACSTextBox_DateFrom", "01/01/2024"),
        FC.action_write("#SearchFormEx1_ACSTextBox_DateTo", "03/09/2026"),
        # Search
        FC.action_click("#SearchFormEx1_btnSearch"),
        FC.action_wait(8000),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["rawHtml"])
    if result:
        html = result.get("rawHtml", "") or result.get("html", "")
        print(f"  Got {len(html)} chars")

        hits = re.search(r'(\d+)\s+hits', html)
        if hits:
            h = int(hits.group(1))
            print(f"  Hits: {h}")
            if h > 0:
                print(f"  ✅ Got {h} results! Criteria switch WORKS!")
            else:
                print("  ❌ 0 hits")

        if "0 hits" in html:
            print("  ❌ 0 hits message found")

        # Check selected criteria
        crit_selected = re.findall(r'<option[^>]*selected[^>]*>([^<]*)</option>', html)
        print(f"  Selected options: {crit_selected}")

        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_keyboard_B.html"
        path.write_text(html)
        print(f"  Saved to {path.name}")
        return True
    else:
        print("  ❌ FireCrawl returned None")
        return False


async def test_keyboard_with_doctype():
    """
    Test C: Full search with keyboard for criteria AND doc type.
    After criteria switch, Tab to doc type listbox, type 'TAK' to jump to TAKING.
    """
    print("\n=== TEST C: Keyboard criteria + type-ahead for doc type ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Switch criteria
        FC.action_click("select#SearchCriteriaName1_DDL_SearchName"),
        FC.action_wait(300),
        FC.action_press("ArrowDown"),  # → Document Search
        FC.action_wait(6000),
        # Click the doc type listbox to focus it
        FC.action_click("select#SearchFormEx1_ACSDropDownList_DocumentType"),
        FC.action_wait(300),
        # Type-ahead: T-A-K should jump to TAKING
        FC.action_press("t"),
        FC.action_press("a"),
        FC.action_press("k"),
        FC.action_wait(500),
        # Set dates
        FC.action_write("#SearchFormEx1_ACSTextBox_DateFrom", "01/01/2020"),
        FC.action_write("#SearchFormEx1_ACSTextBox_DateTo", "03/09/2026"),
        # Search (13 actions total — at the limit)
        FC.action_click("#SearchFormEx1_btnSearch"),
        FC.action_wait(8000),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["rawHtml"])
    if result:
        html = result.get("rawHtml", "") or result.get("html", "")
        print(f"  Got {len(html)} chars")

        hits = re.search(r'(\d+)\s+hits', html)
        if hits:
            h = int(hits.group(1))
            print(f"  Hits: {h}")
            if h > 0:
                print(f"  ✅ Got {h} results!")
        if "0 hits" in html:
            print("  ❌ 0 hits")
        if "TAKING" in html:
            print("  ✅ TAKING found in results!")

        # Check what's selected
        taking_sel = re.search(r'TAKING[^<]*</option>', html)
        if taking_sel:
            ctx = html[max(0, taking_sel.start()-100):taking_sel.end()]
            print(f"  TAKING option context: ...{ctx}")

        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_keyboard_C.html"
        path.write_text(html)
        print(f"  Saved to {path.name}")
        return True
    else:
        print("  ❌ FireCrawl returned None (too many actions?)")
        return False


async def main():
    print("=" * 60)
    print("Testing keyboard-based select navigation")
    print("=" * 60)

    # Test A first: just criteria switch
    await test_keyboard_criteria()

    # Test B: criteria + dates + search
    await test_keyboard_full_search()

    # Test C: criteria + doc type + dates + search (if A/B work)
    await test_keyboard_with_doctype()

    print("\n" + "=" * 60)
    print("Tests complete")


if __name__ == "__main__":
    asyncio.run(main())
