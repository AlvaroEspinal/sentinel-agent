#!/usr/bin/env python3
"""
Diagnostic 5: In-page fetch POST using Playwright's browser session.

Key insight: Playwright page has all form elements but empty __VIEWSTATE.
But maybe empty viewstate works! The httpx chain showed that POSTing with
empty viewstate still gets a response. Let's try it from the browser.

Also: check if viewstate is populated via ScriptManager or other mechanism.
"""

import asyncio
from playwright.async_api import async_playwright

URL = "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"

async def main():
    print("=" * 60)
    print("Diagnostic 5: In-page fetch with browser cookies")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )

        print("\n1. Navigate to page...")
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        print(f"   Title: {await page.title()}")

        # Check viewstate and other hidden fields
        print("\n2. Checking hidden fields...")
        hidden_info = await page.evaluate("""() => {
            const fields = {};
            ['__VIEWSTATE', '__EVENTVALIDATION', '__VIEWSTATEENCRYPTED',
             '__VIEWSTATEGENERATOR', 'ScriptManager1_HiddenField'].forEach(id => {
                const el = document.getElementById(id);
                fields[id] = el ? el.value.length : -1;
            });
            // Also check if there's a viewstate in any hidden input
            const allHiddens = [];
            document.querySelectorAll('input[type=hidden]').forEach(h => {
                if (h.value.length > 50) {
                    allHiddens.push({name: h.name, id: h.id, valLen: h.value.length});
                }
            });
            return {fields, allHiddens};
        }""")
        print(f"   Hidden field sizes: {hidden_info['fields']}")
        print(f"   Large hidden inputs: {hidden_info['allHiddens']}")

        # Step 2: Try criteria switch POST via in-page fetch with EMPTY viewstate
        print("\n3. Criteria switch via in-page fetch (empty viewstate)...")
        result = await page.evaluate("""async () => {
            // Build form data - use whatever values exist (might be empty)
            const formData = new URLSearchParams();
            const vs = document.getElementById('__VIEWSTATE');
            formData.set('__VIEWSTATE', vs ? vs.value : '');

            const ev = document.getElementById('__EVENTVALIDATION');
            if (ev) formData.set('__EVENTVALIDATION', ev.value);

            const vsg = document.getElementById('__VIEWSTATEGENERATOR');
            if (vsg) formData.set('__VIEWSTATEGENERATOR', vsg.value);

            const vse = document.getElementById('__VIEWSTATEENCRYPTED');
            if (vse) formData.set('__VIEWSTATEENCRYPTED', vse.value);

            formData.set('__EVENTTARGET', 'SearchCriteriaName1$DDL_SearchName');
            formData.set('__EVENTARGUMENT', '');
            formData.set('SearchCriteriaName1$DDL_SearchName', 'Recorded Land Recorded Date Search');

            try {
                const resp = await fetch(window.location.href, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: formData.toString(),
                });

                const html = await resp.text();

                // Check if criteria switched
                const hasDateFrom = html.includes('ACSTextBox_DateFrom');
                const hasDocType = html.includes('ACSDropDownList_DocumentType');
                const hasTowns = html.includes('ACSDropDownList_Towns');
                const hasBtnSearch = html.includes('btnSearch');
                const selectedMatch = html.match(/selected="selected"[^>]*>([^<]*)</g);

                // Extract viewstate from response
                const vsMatch = html.match(/id="__VIEWSTATE"\\s+value="([^"]*)"/);
                const evMatch = html.match(/id="__EVENTVALIDATION"\\s+value="([^"]*)"/);

                return {
                    status: resp.status,
                    htmlLen: html.length,
                    hasDateFrom,
                    hasDocType,
                    hasTowns,
                    hasBtnSearch,
                    selectedCriteria: selectedMatch ? selectedMatch.slice(0, 5) : [],
                    responseVSLen: vsMatch ? vsMatch[1].length : -1,
                    responseEVLen: evMatch ? evMatch[1].length : -1,
                    html: html
                };
            } catch (e) {
                return { error: e.toString() };
            }
        }""")

        if result.get("error"):
            print(f"   ❌ {result['error']}")
            await browser.close()
            return

        html2 = result.pop("html", "")
        print(f"   Status: {result.get('status')}")
        print(f"   HTML len: {result.get('htmlLen')}")
        print(f"   Has DateFrom: {result.get('hasDateFrom')}")
        print(f"   Has DocType: {result.get('hasDocType')}")
        print(f"   Has Towns: {result.get('hasTowns')}")
        print(f"   Has btnSearch: {result.get('hasBtnSearch')}")
        print(f"   Selected criteria: {result.get('selectedCriteria')}")
        print(f"   Response __VIEWSTATE len: {result.get('responseVSLen')}")
        print(f"   Response __EVENTVALIDATION len: {result.get('responseEVLen')}")

        if not result.get('hasDateFrom'):
            print("   ❌ Criteria switch didn't work, aborting")
            await browser.close()
            return

        print("   ✅ Criteria switch worked via in-page fetch!")

        # Step 3: Load criteria switch response into page
        print("\n4. Loading criteria switch HTML into page...")
        await page.set_content(html2, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # Step 4: Search POST via in-page fetch
        print("\n5. Search POST via in-page fetch...")
        search_result = await page.evaluate("""async () => {
            const formData = new URLSearchParams();
            const vs = document.getElementById('__VIEWSTATE');
            formData.set('__VIEWSTATE', vs ? vs.value : '');

            const ev = document.getElementById('__EVENTVALIDATION');
            if (ev) formData.set('__EVENTVALIDATION', ev.value);

            const vsg = document.getElementById('__VIEWSTATEGENERATOR');
            if (vsg) formData.set('__VIEWSTATEGENERATOR', vsg.value);

            const vse = document.getElementById('__VIEWSTATEENCRYPTED');
            if (vse) formData.set('__VIEWSTATEENCRYPTED', vse.value);

            formData.set('__EVENTTARGET', '');
            formData.set('__EVENTARGUMENT', '');
            formData.set('SearchCriteriaName1$DDL_SearchName', 'Recorded Land Recorded Date Search');
            formData.set('SearchFormEx1$ACSTextBox_DateFrom', '1/1/2020');
            formData.set('SearchFormEx1$ACSTextBox_DateTo', '3/9/2026');
            formData.set('SearchFormEx1$ACSDropDownList_DocumentType', '100103');
            formData.set('SearchFormEx1$ACSDropDownList_Towns', '115');
            formData.set('SearchFormEx1$btnSearch', 'Search');

            try {
                const resp = await fetch('https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: formData.toString(),
                });

                const html = await resp.text();

                // Check for hits
                const hitsMatch = html.match(/(\\d+)\\s+hits/);
                const hits = hitsMatch ? parseInt(hitsMatch[1]) : -1;
                const takingCount = (html.match(/TAKING/gi) || []).length;
                const gridCount = (html.match(/DocList1_GridView_Document_ctl/g) || []).length;

                // Check for partial update (UpdatePanel/ScriptManager)
                const hasPartialUpdate = html.includes('|updatePanel|') || html.includes('pageRedirect');
                const firstChars = html.substring(0, 200);
                const lastChars = html.substring(html.length - 200);

                return {
                    status: resp.status,
                    htmlLen: html.length,
                    hits,
                    takingCount,
                    gridCount,
                    hasPartialUpdate,
                    firstChars,
                    lastChars,
                    html: html
                };
            } catch (e) {
                return { error: e.toString() };
            }
        }""")

        if search_result.get("error"):
            print(f"   ❌ {search_result['error']}")
            await browser.close()
            return

        search_html = search_result.pop("html", "")
        print(f"   Status: {search_result.get('status')}")
        print(f"   HTML len: {search_result.get('htmlLen')}")
        print(f"   Hits: {search_result.get('hits')}")
        print(f"   TAKING count: {search_result.get('takingCount')}")
        print(f"   Grid count: {search_result.get('gridCount')}")
        print(f"   Has partial update: {search_result.get('hasPartialUpdate')}")
        print(f"   First 200 chars: {search_result.get('firstChars')}")
        print(f"   Last 200 chars: {search_result.get('lastChars')}")

        if search_result.get('hits', 0) > 0 and search_result.get('gridCount', 0) > 0:
            print(f"   ✅✅✅ GOT HITS AND GRID DATA!")

            # Load into page and extract
            print("\n6. Loading search results into page...")
            await page.set_content(search_html, wait_until="networkidle")
            await page.wait_for_timeout(2000)

            records = await page.evaluate("""() => {
                const results = [];
                for (let i = 2; i <= 200; i++) {
                    const ctlNum = String(i).padStart(2, '0');
                    const prefix = 'DocList1_GridView_Document_ctl' + ctlNum + '_ButtonRow_';
                    const rowIdx = i - 2;

                    const fileDateEl = document.getElementById(prefix + 'File Date_' + rowIdx);
                    if (!fileDateEl) break;

                    const bookPageEl = document.getElementById(prefix + 'Book/Page_' + rowIdx);
                    const typeDescEl = document.getElementById(prefix + 'Type Desc._' + rowIdx);
                    const townEl = document.getElementById(prefix + 'Town_' + rowIdx);

                    results.push({
                        fileDate: fileDateEl ? fileDateEl.textContent.trim() : '',
                        bookPage: bookPageEl ? bookPageEl.textContent.trim() : '',
                        typeDesc: typeDescEl ? typeDescEl.textContent.trim() : '',
                        town: townEl ? townEl.textContent.trim() : '',
                    });
                }
                return results;
            }""")
            print(f"\n7. Grid records extracted: {len(records)}")
            for i, r in enumerate(records[:15]):
                print(f"   [{i}] {r}")
            if len(records) > 15:
                print(f"   ... ({len(records) - 15} more)")
        elif search_result.get('hits', 0) > 0:
            print(f"   ⚠️ Got hits but no grid data — need pagination or different approach")
            # Save for analysis
            with open('/tmp/_mx_search_result.html', 'w') as f:
                f.write(search_html)
            print("   Saved to /tmp/_mx_search_result.html")
        else:
            print(f"   ⚠️ No hits found, checking if response is valid...")
            # Save for analysis
            with open('/tmp/_mx_search_result.html', 'w') as f:
                f.write(search_html)
            print("   Saved to /tmp/_mx_search_result.html")

        await browser.close()
        print("\n" + "=" * 60)
        print("Diagnostic 5 complete!")


if __name__ == "__main__":
    asyncio.run(main())
