#!/usr/bin/env python3
"""
Diagnostic 2: Trace what happens after criteria dropdown selection.

The select_option() call succeeds, but the ASP.NET postback doesn't seem
to load the new form fields. Need to figure out if:
1. The postback fires at all
2. What form fields are available after the postback
3. Whether we need to wait differently
"""

import asyncio
from playwright.async_api import async_playwright

URL = "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"


async def main():
    print("=" * 60)
    print("Diagnostic 2: Trace criteria switch postback")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )

        # Track navigation events
        navigations = []
        page.on("framenavigated", lambda frame: navigations.append(f"navigated: {frame.url[:80]}"))

        print("\n1. Navigating to page...")
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        print(f"   Title: {await page.title()}")
        print(f"   URL: {page.url}")

        # Show initial form state
        print("\n2. Initial form state...")
        initial_fields = await page.evaluate("""() => {
            const fields = [];
            document.querySelectorAll('input, select').forEach(el => {
                if (el.id && el.id.includes('SearchForm')) {
                    fields.push({id: el.id, tag: el.tagName, type: el.type || 'select'});
                }
            });
            return fields;
        }""")
        print(f"   SearchForm fields: {len(initial_fields)}")
        for f in initial_fields:
            print(f"     - {f['id']} ({f['tag']}/{f['type']})")

        # 3. Select the criteria - use page.select_option on the locator
        print("\n3. Selecting 'Recorded Land Recorded Date Search'...")
        print("   Method A: page.select_option() ...")

        # Use page-level select_option with proper locator
        try:
            await page.select_option(
                'select#SearchCriteriaName1_DDL_SearchName',
                value='Recorded Land Recorded Date Search'
            )
            print("   ✅ page.select_option() succeeded")
        except Exception as e:
            print(f"   ❌ page.select_option() failed: {e}")

        print(f"   Navigations so far: {navigations}")

        # Wait for postback navigation
        print("\n4. Waiting for postback...")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
            print("   ✅ networkidle reached")
        except Exception as e:
            print(f"   ⚠️ networkidle timeout: {e}")

        await page.wait_for_timeout(3000)
        print(f"   URL after wait: {page.url}")
        print(f"   Navigations: {navigations}")

        # Check form state after postback
        print("\n5. Form state after criteria switch...")
        post_fields = await page.evaluate("""() => {
            const fields = [];
            document.querySelectorAll('input, select').forEach(el => {
                if (el.id && (el.id.includes('SearchForm') || el.id.includes('SearchCriteria'))) {
                    const style = window.getComputedStyle(el);
                    fields.push({
                        id: el.id,
                        tag: el.tagName,
                        type: el.type || 'select',
                        display: style.display,
                        value: el.value ? el.value.substring(0, 50) : ''
                    });
                }
            });
            return fields;
        }""")
        print(f"   Fields found: {len(post_fields)}")
        for f in post_fields:
            print(f"     - {f['id']} ({f['tag']}/{f['type']}) display={f['display']} val={f['value']!r}")

        # Check selected criteria
        print("\n6. Selected criteria option...")
        selected = await page.evaluate("""() => {
            const sel = document.querySelector('select#SearchCriteriaName1_DDL_SearchName');
            if (!sel) return 'NOT FOUND';
            return sel.options[sel.selectedIndex].text + ' (value=' + sel.value + ')';
        }""")
        print(f"   Selected: {selected}")

        # Check if the postback actually happened (form might need __doPostBack)
        print("\n7. Checking if __doPostBack exists...")
        has_dopostback = await page.evaluate("""() => {
            return typeof __doPostBack === 'function';
        }""")
        print(f"   __doPostBack exists: {has_dopostback}")

        # Try triggering postback manually via JavaScript
        if len(post_fields) <= 2:  # If postback didn't work
            print("\n8. Manually triggering __doPostBack...")
            try:
                await page.evaluate("""() => {
                    __doPostBack('SearchCriteriaName1$DDL_SearchName', '');
                }""")
                print("   ✅ __doPostBack called")

                # Wait for navigation
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    print("   ✅ networkidle after __doPostBack")
                except:
                    print("   ⚠️ networkidle timeout after __doPostBack")

                await page.wait_for_timeout(3000)

                # Re-check form fields
                post_fields2 = await page.evaluate("""() => {
                    const fields = [];
                    document.querySelectorAll('input, select').forEach(el => {
                        if (el.id && el.id.includes('SearchForm')) {
                            const style = window.getComputedStyle(el);
                            fields.push({
                                id: el.id,
                                tag: el.tagName,
                                type: el.type || 'select',
                                display: style.display,
                            });
                        }
                    });
                    return fields;
                }""")
                print(f"   Fields after manual __doPostBack: {len(post_fields2)}")
                for f in post_fields2:
                    print(f"     - {f['id']} ({f['tag']}/{f['type']}) display={f['display']}")

                # Check for Advanced button
                adv_btn = await page.evaluate("""() => {
                    const btn = document.getElementById('SearchFormEx1_BtnAdvanced');
                    if (!btn) return null;
                    return {id: btn.id, value: btn.value, display: window.getComputedStyle(btn).display};
                }""")
                print(f"   Advanced button: {adv_btn}")

                # Check for Search button
                search_btn = await page.evaluate("""() => {
                    const btn = document.getElementById('SearchFormEx1_btnSearch');
                    if (!btn) return null;
                    return {id: btn.id, value: btn.value, display: window.getComputedStyle(btn).display};
                }""")
                print(f"   Search button: {search_btn}")

            except Exception as e:
                print(f"   ❌ __doPostBack failed: {e}")

        # Alternative approach: Try dispatchEvent after select
        print("\n9. Alternative: Fresh page + select + dispatch change event...")
        page2 = await browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )
        await page2.goto(URL, wait_until="networkidle", timeout=30000)

        # Set value AND dispatch change event
        await page2.evaluate("""() => {
            const sel = document.querySelector('#SearchCriteriaName1_DDL_SearchName');
            sel.value = 'Recorded Land Recorded Date Search';
            sel.dispatchEvent(new Event('change', { bubbles: true }));
        }""")
        print("   Set value + dispatched change event")

        try:
            await page2.wait_for_load_state("networkidle", timeout=15000)
        except:
            pass
        await page2.wait_for_timeout(4000)

        fields_alt = await page2.evaluate("""() => {
            const fields = [];
            document.querySelectorAll('input, select').forEach(el => {
                if (el.id && el.id.includes('SearchForm')) {
                    fields.push({id: el.id, tag: el.tagName, type: el.type || 'select'});
                }
            });
            return fields;
        }""")
        print(f"   Fields after dispatchEvent: {len(fields_alt)}")
        for f in fields_alt:
            print(f"     - {f['id']} ({f['tag']}/{f['type']})")

        selected_alt = await page2.evaluate("""() => {
            const sel = document.querySelector('#SearchCriteriaName1_DDL_SearchName');
            if (!sel) return 'NOT FOUND';
            return sel.options[sel.selectedIndex].text + ' (value=' + sel.value + ')';
        }""")
        print(f"   Selected criteria: {selected_alt}")

        await page2.close()
        await browser.close()

        print("\n" + "=" * 60)
        print("Diagnostic 2 complete!")


if __name__ == "__main__":
    asyncio.run(main())
