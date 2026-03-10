#!/usr/bin/env python3
"""
Test with CORRECT label text for criteria dropdown.

KEY DISCOVERY: The criteria dropdown has:
  value="Recorded Land Document Search"  =>  label="Document Search"

Previous tests used the VALUE text, not the LABEL text!
FireCrawl's write() on <select> matches by label (visible text).
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


async def test_correct_criteria_label():
    """
    Test 1: Use correct label text 'Document Search' for criteria switch.
    Then just search with dates — no doc type or town filter.
    If we get results, the criteria switch finally works!
    """
    print("\n=== TEST 1: Correct label 'Document Search' + date range ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Use LABEL TEXT not VALUE for write on <select>
        FC.action_write(
            "select#SearchCriteriaName1_DDL_SearchName",
            "Document Search"
        ),
        FC.action_wait(5000),  # Wait for ASP.NET postback
        # Set narrow date range
        FC.action_write("#SearchFormEx1_ACSTextBox_DateFrom", "01/01/2024"),
        FC.action_write("#SearchFormEx1_ACSTextBox_DateTo", "03/09/2026"),
        # Click search
        FC.action_click("#SearchFormEx1_btnSearch"),
        FC.action_wait(8000),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["rawHtml"])
    if result:
        html = result.get("rawHtml", "") or result.get("html", "") or result.get("markdown", "")
        print(f"  Got {len(html)} chars")

        # Check which criteria is selected
        crit = re.findall(r'<option[^>]*selected[^>]*>([^<]*)</option>', html)
        print(f"  Selected options: {crit}")

        # Check for hits
        hits = re.search(r'(\d+)\s+hits', html)
        if hits:
            print(f"  Hits: {hits.group(1)}")

        if "0 hits" in html:
            print("  ❌ 0 hits")
        elif "hits" in html.lower() and hits and int(hits.group(1)) > 0:
            print(f"  ✅ Got {hits.group(1)} hits!")
        elif "GR" in html or "GT" in html:
            print("  ✅ Got result rows!")

        # Check for name search fields (shouldn't be present if criteria switched)
        if "SearchFormEx1_ACSTextBox_LastName" in html:
            print("  ⚠️  LastName field present — might still be Name Search")
        if "SearchFormEx1_ACSDropDownList_DocumentType" in html:
            print("  ✅ DocType dropdown present — criteria DID switch!")

        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_correct_label_1.html"
        path.write_text(html)
        print(f"  Saved to {path.name}")
        return True
    else:
        print("  ❌ FireCrawl returned None")
        return False


async def test_write_multiselect():
    """
    Test 2: Use correct criteria label THEN try write on multi-select listbox.
    Try writing with the OPTION TEXT for doc type and town.
    """
    print("\n=== TEST 2: Correct label + write TAKING/NEWTON on multi-selects ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        FC.action_write("select#SearchCriteriaName1_DDL_SearchName", "Document Search"),
        FC.action_wait(5000),
        # Try write with option TEXT on multi-select listbox
        FC.action_write("select#SearchFormEx1_ACSDropDownList_DocumentType", "TAKING"),
        FC.action_write("select#SearchFormEx1_ACSDropDownList_Towns", "NEWTON"),
        # Click search
        FC.action_click("#SearchFormEx1_btnSearch"),
        FC.action_wait(8000),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["rawHtml"])
    if result:
        html = result.get("rawHtml", "") or result.get("html", "") or result.get("markdown", "")
        print(f"  Got {len(html)} chars")

        hits = re.search(r'(\d+)\s+hits', html)
        if hits:
            print(f"  Hits: {hits.group(1)}")
        if "0 hits" in html:
            print("  ❌ 0 hits — write on multi-select probably didn't work")
        elif hits and int(hits.group(1)) > 0:
            print(f"  ✅ Got {hits.group(1)} hits with TAKING + NEWTON!")

        # Check if TAKING was selected
        taking_sel = re.search(r'option[^>]*value="100103"[^>]*selected', html)
        newton_sel = re.search(r'option[^>]*value="115"[^>]*selected', html)
        print(f"  TAKING selected in HTML: {bool(taking_sel)}")
        print(f"  NEWTON selected in HTML: {bool(newton_sel)}")

        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_correct_label_2.html"
        path.write_text(html)
        print(f"  Saved to {path.name}")
        return True
    else:
        print("  ❌ FireCrawl returned None")
        return False


async def test_write_multiselect_by_value():
    """
    Test 3: Try write with OPTION VALUE instead of text on multi-selects.
    """
    print("\n=== TEST 3: Correct label + write by VALUE (100103/115) ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        FC.action_write("select#SearchCriteriaName1_DDL_SearchName", "Document Search"),
        FC.action_wait(5000),
        # Try write with option VALUE
        FC.action_write("select#SearchFormEx1_ACSDropDownList_DocumentType", "100103"),
        FC.action_write("select#SearchFormEx1_ACSDropDownList_Towns", "115"),
        # Set dates
        FC.action_write("#SearchFormEx1_ACSTextBox_DateFrom", "01/01/2020"),
        FC.action_write("#SearchFormEx1_ACSTextBox_DateTo", "03/09/2026"),
        # Search
        FC.action_click("#SearchFormEx1_btnSearch"),
        FC.action_wait(8000),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["rawHtml"])
    if result:
        html = result.get("rawHtml", "") or result.get("html", "") or result.get("markdown", "")
        print(f"  Got {len(html)} chars")

        hits = re.search(r'(\d+)\s+hits', html)
        if hits:
            print(f"  Hits: {hits.group(1)}")
        if "0 hits" in html:
            print("  ❌ 0 hits")
        elif hits and int(hits.group(1)) > 0:
            print(f"  ✅ Got {hits.group(1)} hits with VALUE-based write!")

        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_correct_label_3.html"
        path.write_text(html)
        print(f"  Saved to {path.name}")
        return True
    else:
        print("  ❌ FireCrawl returned None")
        return False


async def main():
    print("=" * 60)
    print("Testing with CORRECT label text for criteria dropdown")
    print("=" * 60)

    # Test 1: Just criteria switch + dates (prove it works)
    await test_correct_criteria_label()

    # Test 2: + write text on multi-selects
    await test_write_multiselect()

    # Test 3: + write value on multi-selects
    await test_write_multiselect_by_value()

    print("\n" + "=" * 60)
    print("Tests complete")


if __name__ == "__main__":
    asyncio.run(main())
