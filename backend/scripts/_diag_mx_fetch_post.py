#!/usr/bin/env python3
"""
Diagnostic 3: Use in-page fetch() to do the criteria switch POST.

The idea: Playwright navigates to the page (bypasses Incapsula WAF).
Then we use page.evaluate(fetch()) to submit the form POST ourselves,
and write the response HTML into the page. This avoids the WAF blocking
the form submission.
"""

import asyncio
from playwright.async_api import async_playwright

URL = "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"


async def main():
    print("=" * 60)
    print("Diagnostic 3: In-page fetch POST for criteria switch")
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
        print(f"   Title: {await page.title()}")

        # Step 2: Extract hidden fields and do criteria switch via fetch()
        print("\n2. Criteria switch via in-page fetch()...")
        result = await page.evaluate("""async () => {
            // Extract ASP.NET hidden fields
            const viewstate = document.getElementById('__VIEWSTATE')?.value || '';
            const eventval = document.getElementById('__EVENTVALIDATION')?.value || '';
            const vsg = document.getElementById('__VIEWSTATEGENERATOR')?.value || '';
            const vse = document.getElementById('__VIEWSTATEENCRYPTED')?.value || '';

            if (!viewstate) return { error: 'No __VIEWSTATE found' };

            // Build form data for criteria switch
            const formData = new URLSearchParams();
            formData.set('__VIEWSTATE', viewstate);
            formData.set('__VIEWSTATEENCRYPTED', vse);
            formData.set('__EVENTVALIDATION', eventval);
            formData.set('__VIEWSTATEGENERATOR', vsg);
            formData.set('__EVENTTARGET', 'SearchCriteriaName1$DDL_SearchName');
            formData.set('__EVENTARGUMENT', '');
            formData.set('SearchCriteriaName1$DDL_SearchName', 'Recorded Land Recorded Date Search');

            try {
                const resp = await fetch(window.location.href, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: formData.toString(),
                });

                if (!resp.ok) return { error: 'fetch failed: ' + resp.status };

                const html = await resp.text();
                return {
                    status: resp.status,
                    htmlLen: html.length,
                    hasDateFrom: html.includes('ACSTextBox_DateFrom'),
                    hasDocType: html.includes('ACSDropDownList_DocumentType'),
                    hasTowns: html.includes('ACSDropDownList_Towns'),
                    hasSearch: html.includes('btnSearch'),
                    hasAdvanced: html.includes('BtnAdvanced'),
                    html: html  // We'll write this to the page
                };
            } catch (e) {
                return { error: e.toString() };
            }
        }""")

        if result.get("error"):
            print(f"   ❌ {result['error']}")
            await browser.close()
            return

        html = result.pop("html", "")
        print(f"   Status: {result.get('status')}")
        print(f"   HTML length: {result.get('htmlLen')}")
        print(f"   Has DateFrom: {result.get('hasDateFrom')}")
        print(f"   Has DocType: {result.get('hasDocType')}")
        print(f"   Has Towns: {result.get('hasTowns')}")
        print(f"   Has Search btn: {result.get('hasSearch')}")
        print(f"   Has Advanced btn: {result.get('hasAdvanced')}")

        if not html:
            print("   ❌ No HTML returned")
            await browser.close()
            return

        # Step 3: Write the response HTML into the page
        print("\n3. Writing response HTML into the page...")
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # Check what we have now
        print("\n4. Checking page state after set_content...")
        fields = await page.evaluate("""() => {
            const fields = [];
            document.querySelectorAll('input, select').forEach(el => {
                if (el.id && el.id.includes('SearchForm')) {
                    fields.push({id: el.id, tag: el.tagName, type: el.type || 'select'});
                }
            });
            return fields;
        }""")
        print(f"   SearchForm fields: {len(fields)}")
        for f in fields:
            print(f"     - {f['id']} ({f['tag']}/{f['type']})")

        # Check if Advanced mode shows doc type + towns
        has_dt = any("DocumentType" in f["id"] for f in fields)
        has_towns = any("Towns" in f["id"] for f in fields)
        print(f"\n   DocType visible: {has_dt}")
        print(f"   Towns visible: {has_towns}")

        if not has_dt:
            print("\n5. Clicking Advanced via JavaScript...")
            # Check if Advanced button exists
            adv = await page.evaluate("""() => {
                const btn = document.getElementById('SearchFormEx1_BtnAdvanced');
                if (btn) {
                    btn.click();
                    return 'clicked';
                }
                return 'not found';
            }""")
            print(f"   Advanced: {adv}")
            await page.wait_for_timeout(1000)

            # Re-check
            fields2 = await page.evaluate("""() => {
                const fields = [];
                document.querySelectorAll('input, select').forEach(el => {
                    if (el.id && el.id.includes('SearchForm')) {
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none') {
                            fields.push({id: el.id, tag: el.tagName, type: el.type || 'select'});
                        }
                    }
                });
                return fields;
            }""")
            print(f"   Visible fields after Advanced: {len(fields2)}")
            for f in fields2:
                print(f"     - {f['id']} ({f['tag']}/{f['type']})")

        # Step 6: Now try the search POST
        print("\n6. Doing search POST via in-page fetch()...")
        search_result = await page.evaluate("""async () => {
            const viewstate = document.getElementById('__VIEWSTATE')?.value || '';
            const eventval = document.getElementById('__EVENTVALIDATION')?.value || '';
            const vsg = document.getElementById('__VIEWSTATEGENERATOR')?.value || '';
            const vse = document.getElementById('__VIEWSTATEENCRYPTED')?.value || '';

            if (!viewstate) return { error: 'No __VIEWSTATE for search' };

            const formData = new URLSearchParams();
            formData.set('__VIEWSTATE', viewstate);
            formData.set('__VIEWSTATEENCRYPTED', vse);
            formData.set('__EVENTVALIDATION', eventval);
            formData.set('__VIEWSTATEGENERATOR', vsg);
            formData.set('__EVENTTARGET', '');
            formData.set('__EVENTARGUMENT', '');
            formData.set('SearchCriteriaName1$DDL_SearchName', 'Recorded Land Recorded Date Search');
            formData.set('SearchFormEx1$ACSTextBox_DateFrom', '1/1/2020');
            formData.set('SearchFormEx1$ACSTextBox_DateTo', '3/9/2026');
            formData.set('SearchFormEx1$ACSDropDownList_DocumentType', '100103');
            formData.set('SearchFormEx1$ACSDropDownList_Towns', '115');  // NEWTON
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

                // Check for TAKING in results
                const takingCount = (html.match(/TAKING/g) || []).length;

                // Check for grid records
                const gridCount = (html.match(/DocList1_GridView_Document_ctl/g) || []).length;

                return {
                    status: resp.status,
                    htmlLen: html.length,
                    hits: hits,
                    takingCount: takingCount,
                    gridCount: gridCount,
                    html: html
                };
            } catch (e) {
                return { error: e.toString() };
            }
        }""")

        if search_result.get("error"):
            print(f"   ❌ {search_result['error']}")
        else:
            search_html = search_result.pop("html", "")
            print(f"   Status: {search_result.get('status')}")
            print(f"   HTML length: {search_result.get('htmlLen')}")
            print(f"   Hits: {search_result.get('hits')}")
            print(f"   TAKING count: {search_result.get('takingCount')}")
            print(f"   Grid element count: {search_result.get('gridCount')}")

            if search_result.get("hits", 0) > 0:
                print(f"   ✅✅✅ GOT {search_result['hits']} RESULTS!")

                # Write search results into the page
                print("\n7. Loading search results into page...")
                await page.set_content(search_html, wait_until="networkidle")
                await page.wait_for_timeout(2000)

                # Try extracting grid records
                records = await page.evaluate("""() => {
                    const results = [];
                    for (let i = 2; i <= 110; i++) {
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
                print(f"\n8. Grid records extracted: {len(records)}")
                for i, r in enumerate(records[:5]):
                    print(f"   [{i}] {r}")
                if len(records) > 5:
                    print(f"   ... ({len(records) - 5} more)")

        await browser.close()
        print("\n" + "=" * 60)
        print("Diagnostic 3 complete!")


if __name__ == "__main__":
    asyncio.run(main())
