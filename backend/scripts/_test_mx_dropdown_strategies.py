#!/usr/bin/env python3
"""
Test multiple strategies to set dropdown values on Middlesex South Registry.

Problem: FireCrawl `write` on <select> doesn't work after ASP.NET postback.
         `executeJavascript` causes HTTP 500 on this site.

Strategies to test:
1. Click select → click option element
2. Click select → type option text (keyboard search in dropdown)
3. Use `select` action type (may be supported by FireCrawl but undocumented)
4. Pre-build the search URL with form data encoded
5. Two-phase: separate calls for criteria switch and search
"""

import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir.parent / ".env", override=True)

from scrapers.connectors.firecrawl_client import FirecrawlClient

FC = FirecrawlClient
BASE_URL = "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"


async def strategy_1_click_option():
    """Strategy 1: Click the select to open dropdown, then click the option element."""
    print("\n=== STRATEGY 1: Click select → Click option ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Step 1: Switch to Document Search
        FC.action_write("select#SearchCriteriaName1_DDL_SearchName", "Recorded Land Document Search"),
        FC.action_wait(4000),  # Wait for postback
        # Step 2: Click the doc type select to open it
        FC.action_click("select#SearchFormEx1_ACSDropDownList_DocumentType"),
        FC.action_wait(500),
        # Step 3: Click the TAKING option directly
        FC.action_click("select#SearchFormEx1_ACSDropDownList_DocumentType option[value='100103']"),
        FC.action_wait(500),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["html"])
    if result:
        html = result.get("html", "")
        print(f"  Got {len(html)} chars HTML")
        # Check if TAKING was selected
        if 'selected' in html and 'TAKING' in html:
            print("  ✅ TAKING appears selected!")
        if 'Search All Document Types' in html:
            print("  ❌ Still at 'Search All Document Types'")
        # Save for analysis
        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_strat1.html"
        path.write_text(html[:5000])
        print(f"  Saved first 5K to {path.name}")
        return True
    else:
        print("  ❌ FireCrawl returned None")
        return False


async def strategy_2_keyboard_nav():
    """Strategy 2: Click select, then use keyboard to type 'TAKING' to jump to option."""
    print("\n=== STRATEGY 2: Click select → Type to search ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Switch to Document Search
        FC.action_write("select#SearchCriteriaName1_DDL_SearchName", "Recorded Land Document Search"),
        FC.action_wait(4000),
        # Click doc type select to focus it
        FC.action_click("select#SearchFormEx1_ACSDropDownList_DocumentType"),
        FC.action_wait(500),
        # Type "TAK" to jump to TAKING in the dropdown
        FC.action_press("t"),
        FC.action_press("a"),
        FC.action_press("k"),
        FC.action_wait(500),
        # Press Enter or Tab to confirm selection
        FC.action_press("Enter"),
        FC.action_wait(500),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["html"])
    if result:
        html = result.get("html", "")
        print(f"  Got {len(html)} chars HTML")
        if 'Search All Document Types' in html:
            print("  ❌ Still at 'Search All Document Types'")
        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_strat2.html"
        path.write_text(html[:5000])
        print(f"  Saved first 5K to {path.name}")
        return True
    else:
        print("  ❌ FireCrawl returned None")
        return False


async def strategy_3_select_action():
    """Strategy 3: Try using a 'select' action type with selectOption (Playwright-style)."""
    print("\n=== STRATEGY 3: selectOption action type ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Switch to Document Search
        FC.action_write("select#SearchCriteriaName1_DDL_SearchName", "Recorded Land Document Search"),
        FC.action_wait(4000),
        # Try a custom action type that might map to Playwright's selectOption
        {"type": "selectOption", "selector": "select#SearchFormEx1_ACSDropDownList_DocumentType", "value": "100103"},
        FC.action_wait(500),
        {"type": "selectOption", "selector": "select#SearchFormEx1_ACSDropDownList_Towns", "value": "115"},  # Newton
        FC.action_wait(500),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["html"])
    if result:
        html = result.get("html", "")
        print(f"  Got {len(html)} chars HTML")
        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_strat3.html"
        path.write_text(html[:5000])
        print(f"  Saved first 5K to {path.name}")
        return True
    else:
        print("  ❌ FireCrawl returned None (selectOption probably not supported)")
        return False


async def strategy_4_recorded_date_search():
    """
    Strategy 4: Use 'Recorded Land Recorded Date Search' criteria instead.
    This might show ALL documents by recorded date — we filter for TAKING in parser.
    Avoids needing the document type dropdown entirely.
    """
    print("\n=== STRATEGY 4: Recorded Date Search (bypass doc type dropdown) ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        # Switch to Recorded Date Search (different criteria that might not need doc type)
        FC.action_write("select#SearchCriteriaName1_DDL_SearchName", "Recorded Land Recorded Date Search"),
        FC.action_wait(4000),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["html"])
    if result:
        html = result.get("html", "")
        print(f"  Got {len(html)} chars HTML")
        # Save full HTML to see what form fields are available
        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_strat4_form.html"
        path.write_text(html)
        print(f"  Saved full HTML ({len(html)} chars) to {path.name}")

        # Check what form fields are present
        import re
        selects = re.findall(r'<select[^>]*id="([^"]*)"', html)
        inputs = re.findall(r'<input[^>]*id="([^"]*)"', html)
        print(f"  Select elements: {selects}")
        print(f"  Input elements (first 10): {inputs[:10]}")
        return True
    else:
        print("  ❌ FireCrawl returned None")
        return False


async def strategy_5_two_phase():
    """
    Strategy 5: Two separate FireCrawl calls.
    Phase 1: Load page, switch to Document Search, scrape the HTML to get form state.
    Phase 2: Load page again, try write on all fields in one go (no postback between).
    """
    print("\n=== STRATEGY 5: Two-phase approach ===")
    fc = FirecrawlClient()

    # Phase 1: Just switch to Document Search mode and get the resulting page
    print("  Phase 1: Switching to Document Search...")
    actions1 = [
        FC.action_wait(3000),
        FC.action_write("select#SearchCriteriaName1_DDL_SearchName", "Recorded Land Document Search"),
        FC.action_wait(5000),
        FC.action_screenshot(),
    ]

    result1 = await fc.scrape_with_actions(BASE_URL, actions1, formats=["html"])
    if not result1:
        print("  ❌ Phase 1 failed")
        return False

    html1 = result1.get("html", "")
    print(f"  Phase 1 got {len(html1)} chars HTML")

    # Check if doc type and town selects exist and are accessible
    import re
    has_doc_type = "SearchFormEx1_ACSDropDownList_DocumentType" in html1
    has_town = "SearchFormEx1_ACSDropDownList_Towns" in html1
    print(f"  Doc type select present: {has_doc_type}")
    print(f"  Town select present: {has_town}")

    # Phase 2: Now try writing to ALL fields at once right after the postback
    print("  Phase 2: Setting all fields and searching...")
    actions2 = [
        FC.action_wait(3000),
        # Switch to Document Search AND immediately set other fields
        FC.action_write("select#SearchCriteriaName1_DDL_SearchName", "Recorded Land Document Search"),
        FC.action_wait(5000),  # Longer wait for postback
        # Now try write with the option TEXT (not value) for the selects
        FC.action_write("select#SearchFormEx1_ACSDropDownList_DocumentType", "TAKING"),
        FC.action_wait(1000),
        FC.action_write("select#SearchFormEx1_ACSDropDownList_Towns", "NEWTON"),
        FC.action_wait(1000),
        # Click search
        FC.action_click("input#SearchFormEx1_btnSearch"),
        FC.action_wait(5000),
        FC.action_scrape(),
    ]

    result2 = await fc.scrape_with_actions(BASE_URL, actions2, formats=["html"])
    if result2:
        html2 = result2.get("html", "")
        print(f"  Phase 2 got {len(html2)} chars HTML")
        if "0 hits" in html2 or "Search criteria resulted in 0" in html2:
            print("  ❌ Still 0 hits - dropdowns not set")
        elif "GR " in html2 or "GT " in html2 or "TAKING" in html2:
            print("  ✅ Got results!")
        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_strat5.html"
        path.write_text(html2)
        print(f"  Saved to {path.name}")
        return True
    else:
        print("  ❌ Phase 2 failed")
        return False


async def strategy_6_direct_post():
    """
    Strategy 6: Try loading the page with URL hash/params that might set form state.
    Or construct the form action URL directly.
    """
    print("\n=== STRATEGY 6: Direct URL approach ===")
    fc = FirecrawlClient()

    # Try loading the page with query parameters
    test_url = (
        "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"
        "?SearchCriteria=DocumentSearch"
        "&DocType=TAKING"
        "&Town=NEWTON"
    )

    result = await fc.scrape_url(test_url, formats=["html"], wait_for=5000)
    if result:
        html = result.get("html", "")
        print(f"  Got {len(html)} chars HTML")
        if "TAKING" in html and "NEWTON" in html:
            print("  ✅ Params might have worked!")
        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_strat6.html"
        path.write_text(html[:5000])
        return True
    else:
        print("  ❌ Direct URL failed")
        return False


async def main():
    print("=" * 60)
    print("Testing Middlesex South dropdown strategies")
    print("=" * 60)

    # Run strategies that are most likely to work first
    # Strategy 4 is most promising - avoids the dropdown entirely
    await strategy_4_recorded_date_search()

    # Strategy 1 - click option directly
    await strategy_1_click_option()

    # Strategy 2 - keyboard navigation (if 1 fails)
    # await strategy_2_keyboard_nav()

    # Strategy 3 - selectOption action type
    # await strategy_3_select_action()

    print("\n" + "=" * 60)
    print("Tests complete")


if __name__ == "__main__":
    asyncio.run(main())
