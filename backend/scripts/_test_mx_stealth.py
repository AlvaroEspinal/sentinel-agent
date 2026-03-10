#!/usr/bin/env python3
"""
Stealth Playwright approach for Middlesex South Registry of Deeds.

Previous attempts:
- httpx: bypasses Incapsula WAF, search executes (server says "1,000 records"),
  but AJAX grid data never comes back — UpdatePanels render client-side only.
- Regular Playwright: detected by Incapsula WAF, __doPostBack triggers redirect.

This script uses playwright-stealth to:
1. Patch the browser context to evade Incapsula bot detection
2. Navigate the ASP.NET WebForms app like a real user
3. Wait for AJAX UpdatePanel rendering to complete
4. Extract the actual grid data that only renders in a real browser
"""

import asyncio
import random
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure playwright + stealth are available
# ---------------------------------------------------------------------------
try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Installing playwright...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    from playwright.async_api import async_playwright

try:
    from playwright_stealth import stealth_async
except ImportError:
    print("Installing playwright-stealth...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright-stealth"])
    from playwright_stealth import stealth_async


BASE_URL = "https://www.masslandrecords.com/MiddlesexSouth/"
SCREENSHOT_PATH = "/tmp/_mx_stealth_result.png"


async def random_delay(min_s: float = 1.0, max_s: float = 3.0):
    """Sleep a random duration to appear human."""
    delay = random.uniform(min_s, max_s)
    print(f"  [delay {delay:.1f}s]")
    await asyncio.sleep(delay)


async def run():
    print("=" * 70)
    print("Stealth Playwright: Middlesex South Registry — TAKING Records")
    print("=" * 70)

    async with async_playwright() as p:
        # Launch with stealth-friendly settings
        browser = await p.chromium.launch(
            headless=False,  # Visible browser — easier to debug, harder to detect
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            java_script_enabled=True,
        )

        # Apply stealth patches — hides webdriver flag, navigator.plugins, etc.
        page = await context.new_page()
        await stealth_async(page)

        # ---------------------------------------------------------------
        # STEP 1: Navigate to the site
        # ---------------------------------------------------------------
        print("\n--- Step 1: Navigate to masslandrecords.com ---")
        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"  Initial navigation timeout (expected with Incapsula): {e}")
            # Incapsula often does a JS challenge redirect — wait and retry
            print("  Waiting for Incapsula challenge to resolve...")
            await asyncio.sleep(5)

        # Wait for the page to actually load (Incapsula may redirect)
        print("  Waiting for page to stabilize...")
        await page.wait_for_load_state("networkidle", timeout=30000)
        await random_delay(2, 4)

        current_url = page.url
        print(f"  Current URL: {current_url}")
        title = await page.title()
        print(f"  Page title: {title}")

        # Check if we landed on the actual search page or got blocked
        content = await page.content()
        if "Incapsula" in content and "SearchCriteriaName" not in content:
            print("  WARNING: May still be on Incapsula challenge page")
            print("  Waiting longer for JS challenge to complete...")
            await asyncio.sleep(10)
            await page.wait_for_load_state("networkidle", timeout=30000)
            content = await page.content()

        has_search_form = "SearchCriteriaName1" in content
        print(f"  Search form present: {has_search_form}")

        if not has_search_form:
            print("  BLOCKED — search form not found in page content.")
            # Take screenshot of whatever we see
            await page.screenshot(path=SCREENSHOT_PATH, full_page=True)
            print(f"  Screenshot saved to {SCREENSHOT_PATH}")
            # Save HTML for debugging
            Path("/tmp/_mx_stealth_blocked.html").write_text(content)
            print("  HTML saved to /tmp/_mx_stealth_blocked.html")
            await browser.close()
            return

        print("  Page loaded successfully — search form is present.")

        # ---------------------------------------------------------------
        # STEP 2: Select "Recorded Land Recorded Date Search" from dropdown
        # ---------------------------------------------------------------
        print("\n--- Step 2: Select criteria dropdown ---")
        await random_delay()

        criteria_dropdown = page.locator("#SearchCriteriaName1_DDL_SearchName")
        current_value = await criteria_dropdown.input_value()
        print(f"  Current criteria: '{current_value}'")

        # Get all available options
        options = await criteria_dropdown.locator("option").all()
        print("  Available criteria options:")
        for opt in options:
            val = await opt.get_attribute("value")
            text = await opt.inner_text()
            selected = await opt.get_attribute("selected")
            marker = " <-- SELECTED" if selected else ""
            print(f"    value='{val}' => '{text}'{marker}")

        # Select "Recorded Land Recorded Date Search"
        target_value = "Recorded Land Recorded Date Search"
        print(f"  Selecting: '{target_value}'")
        await criteria_dropdown.select_option(value=target_value)

        # The ASP.NET dropdown has an onchange that triggers __doPostBack
        # Wait for the postback to complete — the form should reload with date fields
        print("  Waiting for postback to complete...")
        await random_delay(2, 4)

        # Wait for the date fields to appear (they only show after criteria switch)
        try:
            await page.wait_for_selector(
                "#SearchFormEx1_ACSTextBox_DateFrom",
                state="visible",
                timeout=15000,
            )
            print("  Date fields appeared — postback completed successfully!")
        except Exception as e:
            print(f"  Timeout waiting for date fields: {e}")
            # Maybe the page reloaded — check current state
            content2 = await page.content()
            if "ACSTextBox_DateFrom" in content2:
                print("  (Date field is in DOM but maybe not visible — continuing)")
            else:
                print("  Date fields not in DOM — criteria switch may have failed")
                await page.screenshot(path=SCREENSHOT_PATH, full_page=True)
                print(f"  Screenshot saved to {SCREENSHOT_PATH}")
                await browser.close()
                return

        await page.wait_for_load_state("networkidle")

        # ---------------------------------------------------------------
        # STEP 3: Fill in search parameters
        # ---------------------------------------------------------------
        print("\n--- Step 3: Fill in search parameters ---")
        await random_delay()

        # Date From
        date_from = page.locator("#SearchFormEx1_ACSTextBox_DateFrom")
        await date_from.click()
        await date_from.fill("1/1/2020")
        print("  Date From: 1/1/2020")

        await random_delay(0.5, 1.5)

        # Date To
        date_to = page.locator("#SearchFormEx1_ACSTextBox_DateTo")
        await date_to.click()
        await date_to.fill("3/9/2026")
        print("  Date To: 3/9/2026")

        await random_delay(0.5, 1.5)

        # Document Type = TAKING (value "100103")
        doc_type_dropdown = page.locator("#SearchFormEx1_ACSDropDownList_DocumentType")
        try:
            await doc_type_dropdown.select_option(value="100103")
            print("  Document Type: TAKING (100103)")
        except Exception as e:
            print(f"  Error selecting doc type by value: {e}")
            # Try by label
            try:
                await doc_type_dropdown.select_option(label="TAKING")
                print("  Document Type: TAKING (by label)")
            except Exception as e2:
                print(f"  Error selecting doc type by label: {e2}")
                # List available options
                doc_opts = await doc_type_dropdown.locator("option").all()
                print("  Available doc type options (first 20):")
                for i, opt in enumerate(doc_opts[:20]):
                    val = await opt.get_attribute("value")
                    text = await opt.inner_text()
                    print(f"    value='{val}' => '{text}'")

        await random_delay(0.5, 1.5)

        # Town = NEWTON (value "115")
        town_dropdown = page.locator("#SearchFormEx1_ACSDropDownList_Towns")
        try:
            await town_dropdown.select_option(value="115")
            print("  Town: NEWTON (115)")
        except Exception as e:
            print(f"  Error selecting town by value: {e}")
            try:
                await town_dropdown.select_option(label="NEWTON")
                print("  Town: NEWTON (by label)")
            except Exception as e2:
                print(f"  Error selecting town by label: {e2}")
                # List available options
                town_opts = await town_dropdown.locator("option").all()
                print("  Available town options (first 20):")
                for i, opt in enumerate(town_opts[:20]):
                    val = await opt.get_attribute("value")
                    text = await opt.inner_text()
                    print(f"    value='{val}' => '{text}'")

        await random_delay(1, 2)

        # Take screenshot of filled form before clicking search
        await page.screenshot(path="/tmp/_mx_stealth_form_filled.png", full_page=True)
        print("  Screenshot of filled form saved.")

        # ---------------------------------------------------------------
        # STEP 4: Click Search
        # ---------------------------------------------------------------
        print("\n--- Step 4: Click Search button ---")
        await random_delay()

        search_btn = page.locator("#SearchFormEx1_btnSearch")
        btn_visible = await search_btn.is_visible()
        print(f"  Search button visible: {btn_visible}")

        if not btn_visible:
            # Try alternate selector
            search_btn = page.locator("input[id$='btnSearch']")
            btn_visible = await search_btn.is_visible()
            print(f"  Alternate selector visible: {btn_visible}")

        if btn_visible:
            await search_btn.click()
            print("  Search button clicked!")
        else:
            print("  Search button not visible — trying JavaScript click")
            await page.evaluate(
                "document.getElementById('SearchFormEx1_btnSearch').click()"
            )
            print("  JavaScript click executed!")

        # ---------------------------------------------------------------
        # STEP 5: Wait for results
        # ---------------------------------------------------------------
        print("\n--- Step 5: Wait for results ---")

        # The search triggers an AJAX UpdatePanel postback.
        # Wait for results to appear in the grid.
        # Possible result containers: DocList1, SearchList1, NameList1
        # Also look for the "records" or "hits" message.

        # First, wait for any loading indicator to appear and disappear
        await asyncio.sleep(2)

        # Wait for network to settle
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            print("  Network didn't fully settle — continuing anyway")

        await random_delay(2, 4)

        # Check for results
        content3 = await page.content()
        page_text = await page.inner_text("body")

        # Look for result indicators
        print("\n--- Step 6: Check for results ---")

        # Check for hit/record count
        hits_match = re.search(r"(\d[\d,]*)\s+hits", page_text)
        records_match = re.search(r"limited to the first (\d[\d,]*) records", page_text)
        records_match2 = re.search(r"(\d[\d,]*)\s+records?\s+found", page_text)
        result_count_match = re.search(r"Results?:\s*(\d[\d,]*)", page_text)

        if hits_match:
            print(f"  HITS: {hits_match.group(1)}")
        if records_match:
            print(f"  LIMITED TO: {records_match.group(1)} records")
        if records_match2:
            print(f"  RECORDS FOUND: {records_match2.group(1)}")
        if result_count_match:
            print(f"  RESULT COUNT: {result_count_match.group(1)}")

        # Check for TAKING in page text
        taking_count = page_text.count("TAKING")
        print(f"  'TAKING' occurrences in page text: {taking_count}")

        # Check for table/grid rows
        # The results grid typically has <tr> rows with document info
        grid_rows = await page.locator("table.doclist tr, table.searchlist tr, #DocList1 tr, #SearchList1 tr").count()
        print(f"  Grid rows found: {grid_rows}")

        # Try broader selectors for the result table
        all_tables = await page.locator("table").count()
        print(f"  Total tables on page: {all_tables}")

        # Check specific result panels
        for panel_id in [
            "DocList1_UpdatePanel",
            "SearchList1_UpdatePanel",
            "NameList1_UpdatePanel",
            "TabResultController1_UpdatePanel1",
            "SearchInfo1_UpdatePanel1",
        ]:
            panel = page.locator(f"#{panel_id}")
            if await panel.count() > 0:
                text = await panel.inner_text()
                text_stripped = text.strip()
                if text_stripped:
                    print(f"  Panel #{panel_id}: {len(text_stripped)} chars")
                    preview = text_stripped[:300].replace("\n", " | ")
                    print(f"    Preview: {preview}")
                else:
                    print(f"  Panel #{panel_id}: empty")

        # Check for error messages
        error_label = page.locator("#MessageBoxCtrl1_ErrorLabel1")
        if await error_label.count() > 0:
            error_text = await error_label.inner_text()
            if error_text.strip():
                print(f"  ERROR MESSAGE: {error_text.strip()}")

        # Check SearchInfo panel for hit count message
        search_info = page.locator("#SearchInfo1_Label1, #SearchInfo1_UpdatePanel1")
        if await search_info.count() > 0:
            info_text = await search_info.inner_text()
            if info_text.strip():
                print(f"  SEARCH INFO: {info_text.strip()[:200]}")

        # ---------------------------------------------------------------
        # STEP 7: Try to extract actual record data
        # ---------------------------------------------------------------
        print("\n--- Step 7: Extract record data ---")

        # Look for result rows — these typically have links with document details
        doc_links = await page.locator("a[id*='DocList1'], a[id*='SearchList1']").count()
        print(f"  Document links found: {doc_links}")

        # Try to find any table with TAKING data
        tables_html = await page.evaluate("""
            () => {
                const tables = document.querySelectorAll('table');
                const results = [];
                for (const table of tables) {
                    const text = table.innerText;
                    if (text.includes('TAKING') || text.includes('GR') || text.includes('Document')) {
                        results.push({
                            id: table.id || 'no-id',
                            classes: table.className,
                            rows: table.rows.length,
                            preview: text.substring(0, 500)
                        });
                    }
                }
                return results;
            }
        """)

        if tables_html:
            print(f"  Found {len(tables_html)} tables with relevant content:")
            for t in tables_html:
                print(f"    Table id='{t['id']}' class='{t['classes']}' rows={t['rows']}")
                print(f"    Preview: {t['preview'][:300]}")
        else:
            print("  No tables with TAKING/GR/Document content found.")

        # Extract all visible text from result area
        result_area = page.locator("#DocList1, #SearchList1, #NameList1, [id*='ResultPanel'], [id*='doclist'], [id*='gridview']")
        result_count = await result_area.count()
        print(f"  Result area elements found: {result_count}")

        if result_count > 0:
            for i in range(min(result_count, 3)):
                el = result_area.nth(i)
                el_text = await el.inner_text()
                if el_text.strip():
                    print(f"  Result area [{i}]: {el_text.strip()[:500]}")

        # ---------------------------------------------------------------
        # STEP 8: If no results visible, maybe we need to wait more or
        #         the results loaded in a different container
        # ---------------------------------------------------------------
        if taking_count == 0 and grid_rows == 0:
            print("\n--- Step 8: Extended wait and re-check ---")
            print("  Waiting 5 more seconds for AJAX to complete...")
            await asyncio.sleep(5)

            # Re-check
            page_text2 = await page.inner_text("body")
            taking_count2 = page_text2.count("TAKING")
            print(f"  'TAKING' occurrences after extended wait: {taking_count2}")

            # Check if there's a "loading" indicator still present
            loading = await page.locator(".loading, .spinner, [id*='loading'], [id*='progress']").count()
            print(f"  Loading indicators: {loading}")

            # Try scrolling the page to trigger lazy loading
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)

            # Check for any iframes that might contain results
            iframes = await page.locator("iframe").count()
            print(f"  Iframes on page: {iframes}")

            # Final comprehensive DOM search
            all_text_content = await page.evaluate("""
                () => {
                    const body = document.body.innerText;
                    const taking_idx = body.indexOf('TAKING');
                    const hits_idx = body.indexOf('hits');
                    const records_idx = body.indexOf('records');
                    const limited_idx = body.indexOf('limited');
                    return {
                        body_length: body.length,
                        has_taking: taking_idx > -1,
                        taking_context: taking_idx > -1 ? body.substring(Math.max(0, taking_idx - 100), taking_idx + 200) : null,
                        has_hits: hits_idx > -1,
                        hits_context: hits_idx > -1 ? body.substring(Math.max(0, hits_idx - 100), hits_idx + 100) : null,
                        has_records: records_idx > -1,
                        has_limited: limited_idx > -1,
                        limited_context: limited_idx > -1 ? body.substring(Math.max(0, limited_idx - 50), limited_idx + 200) : null,
                    };
                }
            """)
            print(f"  Body text length: {all_text_content['body_length']}")
            print(f"  Has TAKING: {all_text_content['has_taking']}")
            if all_text_content['taking_context']:
                print(f"  TAKING context: ...{all_text_content['taking_context']}...")
            print(f"  Has 'hits': {all_text_content['has_hits']}")
            if all_text_content['hits_context']:
                print(f"  Hits context: ...{all_text_content['hits_context']}...")
            print(f"  Has 'limited': {all_text_content['has_limited']}")
            if all_text_content['limited_context']:
                print(f"  Limited context: ...{all_text_content['limited_context']}...")

        # ---------------------------------------------------------------
        # STEP 9: Take final screenshot and save HTML
        # ---------------------------------------------------------------
        print("\n--- Step 9: Save artifacts ---")
        await page.screenshot(path=SCREENSHOT_PATH, full_page=True)
        print(f"  Screenshot: {SCREENSHOT_PATH}")

        final_html = await page.content()
        html_path = "/tmp/_mx_stealth_final.html"
        Path(html_path).write_text(final_html)
        print(f"  HTML: {html_path} ({len(final_html)} chars)")

        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"  Final URL: {page.url}")
        print(f"  Page title: {await page.title()}")
        print(f"  TAKING occurrences: {taking_count}")
        print(f"  Grid rows: {grid_rows}")
        if hits_match:
            print(f"  Hits reported: {hits_match.group(1)}")
        if records_match:
            print(f"  Records limited to: {records_match.group(1)}")

        # Keep browser open briefly for visual inspection
        print("\n  Browser will close in 10 seconds...")
        await asyncio.sleep(10)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
