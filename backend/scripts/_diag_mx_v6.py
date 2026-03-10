#!/usr/bin/env python3
"""
Diagnostic 6: Two approaches
A) Re-examine httpx search response more carefully (ScriptManager partial update format?)
B) Try Playwright __doPostBack with longer waits / WAF challenge completion
"""

import asyncio
import re
import httpx
from playwright.async_api import async_playwright

BASE_URL = "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.masslandrecords.com",
    "Referer": BASE_URL,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def extract_aspnet_fields(html: str) -> dict:
    vs = re.search(r'id="__VIEWSTATE"\s+value="([^"]*)"', html)
    ev = re.search(r'id="__EVENTVALIDATION"\s+value="([^"]*)"', html)
    vsg = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]*)"', html)
    vse = re.search(r'id="__VIEWSTATEENCRYPTED"\s+value="([^"]*)"', html)
    return {
        "__VIEWSTATE": vs.group(1) if vs else "",
        "__VIEWSTATEENCRYPTED": vse.group(1) if vse else "",
        "__EVENTVALIDATION": ev.group(1) if ev else "",
        "__VIEWSTATEGENERATOR": vsg.group(1) if vsg else "",
    }


async def approach_a():
    """Re-examine httpx search response to understand format."""
    print("=" * 60)
    print("APPROACH A: Deep examination of httpx search response")
    print("=" * 60)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # Step 1: GET
        get_resp = await client.get(BASE_URL, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": HEADERS["Accept"],
        })
        html1 = get_resp.text
        fields1 = extract_aspnet_fields(html1)
        print(f"1. GET: {get_resp.status_code}, {len(html1)} chars, VS={len(fields1['__VIEWSTATE'])}")

        # Step 2: Criteria switch
        switch_data = {
            **fields1,
            "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
        }
        switch_resp = await client.post(BASE_URL, data=switch_data, headers=HEADERS)
        html2 = switch_resp.text
        fields2 = extract_aspnet_fields(html2)
        print(f"2. Criteria switch: {switch_resp.status_code}, {len(html2)} chars, VS={len(fields2['__VIEWSTATE'])}")

        # Step 3: Search
        search_data = {
            **fields2,
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
            "SearchFormEx1$btnSearch": "Search",
        }
        search_resp = await client.post(BASE_URL, data=search_data, headers=HEADERS)
        html3 = search_resp.text
        print(f"3. Search: {search_resp.status_code}, {len(html3)} chars")

        # Deep analysis of search response
        print(f"\n--- Response analysis ---")
        print(f"First 300 chars: {repr(html3[:300])}")
        print(f"Last 300 chars: {repr(html3[-300:])}")

        # Check if it's a ScriptManager partial update
        is_partial = html3.startswith("|") or "|updatePanel|" in html3 or "pageRedirect" in html3
        print(f"\nIs partial update: {is_partial}")

        # Check for pipe-delimited format (ScriptManager async postback)
        pipe_count = html3.count("|")
        print(f"Pipe count: {pipe_count}")

        # Find TAKING context
        for m in re.finditer(r'TAKING', html3, re.IGNORECASE):
            start = max(0, m.start() - 100)
            end = min(len(html3), m.end() + 100)
            print(f"\n'TAKING' found at pos {m.start()}: ...{repr(html3[start:end])}...")

        # Check for different grid patterns
        print(f"\n--- Grid pattern search ---")
        patterns = [
            ("GridView", r"GridView"),
            ("DocList", r"DocList"),
            ("DataGrid", r"DataGrid"),
            ("ResultList", r"ResultList"),
            ("gvResults", r"gvResults"),
            ("<table", r"<table"),
            ("<tr>", r"<tr>"),
            ("hits", r"\d+\s+hits"),
            ("record", r"\d+\s+record"),
            ("result", r"\d+\s+result"),
            ("found", r"\d+\s+found"),
            ("matches", r"\d+\s+match"),
        ]
        for name, pat in patterns:
            matches = re.findall(pat, html3, re.IGNORECASE)
            if matches:
                print(f"  {name}: {len(matches)} occurrences")
                if len(matches) <= 3:
                    for m in re.finditer(pat, html3, re.IGNORECASE):
                        ctx_start = max(0, m.start() - 50)
                        ctx_end = min(len(html3), m.end() + 50)
                        print(f"    ...{repr(html3[ctx_start:ctx_end])}...")

        # Check if there's a redirect or meta refresh
        meta_refresh = re.search(r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*>', html3, re.IGNORECASE)
        if meta_refresh:
            print(f"\nMeta refresh: {meta_refresh.group()}")

        # Check for ScriptManager update panels
        update_panels = re.findall(r'<div[^>]*UpdatePanel[^>]*>', html3, re.IGNORECASE)
        print(f"\nUpdatePanel divs: {len(update_panels)}")

        # Look for async postback trigger
        async_trigger = re.findall(r'Sys\.WebForms\.PageRequestManager|ScriptManager', html3)
        print(f"ScriptManager/PageRequestManager refs: {len(async_trigger)}")

        # Save for manual inspection
        with open("/tmp/_mx_search_response_v6.html", "w") as f:
            f.write(html3)
        print(f"\nSaved search response to /tmp/_mx_search_response_v6.html")

        # ALSO try the ScriptManager async postback format
        print(f"\n--- Trying ScriptManager async postback ---")
        async_search_data = {
            **fields2,
            "ScriptManager1": "UpdatePanel1|SearchFormEx1$btnSearch",
            "__ASYNCPOST": "true",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
            "SearchFormEx1$btnSearch": "Search",
        }
        async_headers = {
            **HEADERS,
            "X-Requested-With": "XMLHttpRequest",
            "X-MicrosoftAjax": "Delta=true",
        }
        async_resp = await client.post(BASE_URL, data=async_search_data, headers=async_headers)
        async_html = async_resp.text
        print(f"Async POST: {async_resp.status_code}, {len(async_html)} chars")
        print(f"First 300 chars: {repr(async_html[:300])}")

        # Check for grid data in async response
        async_taking = async_html.count("TAKING")
        async_grid = len(re.findall(r'DocList1_GridView_Document_ctl', async_html))
        async_hits = re.search(r'(\d+)\s+hits', async_html)
        print(f"TAKING count: {async_taking}")
        print(f"Grid count: {async_grid}")
        print(f"Hits: {async_hits.group(1) if async_hits else 'none'}")

        if async_grid > 0 or async_taking > 3:
            print(">>> ASYNC POST HAS DATA! <<<")
            with open("/tmp/_mx_async_response_v6.html", "w") as f:
                f.write(async_html)
            print("Saved async response to /tmp/_mx_async_response_v6.html")

        return html3, async_html


async def approach_b():
    """Try Playwright __doPostBack with WAF challenge wait."""
    print("\n" + "=" * 60)
    print("APPROACH B: Playwright __doPostBack with long WAF wait")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        # Track navigations
        nav_log = []
        page.on("framenavigated", lambda frame: nav_log.append(f"NAV: {frame.url[:100]}"))

        print("\n1. Navigate to page...")
        await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        print(f"   Title: {await page.title()}")

        # Check initial state
        dropdown_value = await page.evaluate("""() => {
            const sel = document.getElementById('SearchCriteriaName1_DDL_SearchName');
            return sel ? { value: sel.value, text: sel.options[sel.selectedIndex]?.text } : null;
        }""")
        print(f"   Current dropdown: {dropdown_value}")

        # Try __doPostBack
        print("\n2. Triggering __doPostBack for criteria switch...")
        nav_log.clear()

        # First set the value, then trigger postback
        await page.evaluate("""() => {
            const sel = document.getElementById('SearchCriteriaName1_DDL_SearchName');
            if (sel) {
                sel.value = 'Recorded Land Recorded Date Search';
            }
        }""")

        # Now call __doPostBack
        try:
            # Use Promise.race to handle the navigation
            await page.evaluate("""() => {
                if (typeof __doPostBack === 'function') {
                    __doPostBack('SearchCriteriaName1$DDL_SearchName', '');
                } else {
                    throw new Error('__doPostBack not found');
                }
            }""")
        except Exception as e:
            print(f"   __doPostBack eval error (expected if navigation): {e}")

        # Wait for navigation chain to complete
        print("   Waiting for WAF challenge resolution (up to 30s)...")
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception as e:
            print(f"   networkidle wait error: {e}")

        await page.wait_for_timeout(5000)
        print(f"   Navigations: {nav_log}")
        print(f"   Current URL: {page.url}")

        # Check result
        result = await page.evaluate("""() => {
            const sel = document.getElementById('SearchCriteriaName1_DDL_SearchName');
            const hasDateFrom = !!document.getElementById('SearchFormEx1_ACSTextBox_DateFrom');
            const hasDocType = !!document.getElementById('SearchFormEx1_ACSDropDownList_DocumentType');
            const hasTowns = !!document.getElementById('SearchFormEx1_ACSDropDownList_Towns');
            const vs = document.getElementById('__VIEWSTATE');
            return {
                dropdownValue: sel ? sel.value : 'missing',
                hasDateFrom,
                hasDocType,
                hasTowns,
                vsLen: vs ? vs.value.length : -1,
                bodyText: document.body.innerText.substring(0, 200),
            };
        }""")
        print(f"   Dropdown: {result.get('dropdownValue')}")
        print(f"   Has DateFrom: {result.get('hasDateFrom')}")
        print(f"   Has DocType: {result.get('hasDocType')}")
        print(f"   Has Towns: {result.get('hasTowns')}")
        print(f"   VS len: {result.get('vsLen')}")
        print(f"   Body: {result.get('bodyText')[:200]}")

        if result.get("hasDateFrom"):
            print("   ✅ Criteria switch worked via __doPostBack!")

            # Try filling form and searching
            print("\n3. Filling search form...")
            await page.evaluate("""() => {
                const df = document.getElementById('SearchFormEx1_ACSTextBox_DateFrom');
                if (df) df.value = '1/1/2020';
                const dt = document.getElementById('SearchFormEx1_ACSTextBox_DateTo');
                if (dt) dt.value = '3/9/2026';
                const docType = document.getElementById('SearchFormEx1_ACSDropDownList_DocumentType');
                if (docType) docType.value = '100103';
                const towns = document.getElementById('SearchFormEx1_ACSDropDownList_Towns');
                if (towns) towns.value = '115';
            }""")

            # Click search button
            print("4. Clicking Search button...")
            nav_log.clear()
            try:
                search_btn = await page.query_selector("#SearchFormEx1_btnSearch")
                if search_btn:
                    await search_btn.click()
                    print("   Clicked, waiting...")
                else:
                    print("   Search button not found, trying __doPostBack...")
                    await page.evaluate("""() => {
                        __doPostBack('SearchFormEx1$btnSearch', '');
                    }""")
            except Exception as e:
                print(f"   Click error: {e}")

            # Wait for result
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as e:
                print(f"   networkidle wait: {e}")

            await page.wait_for_timeout(5000)
            print(f"   Navigations: {nav_log}")

            # Check for results
            search_result = await page.evaluate("""() => {
                const hitsEl = document.body.innerText.match(/(\d+)\s+hits/);
                const gridEls = document.querySelectorAll('[id*="DocList1_GridView_Document_ctl"]');
                return {
                    hits: hitsEl ? parseInt(hitsEl[1]) : -1,
                    gridCount: gridEls.length,
                    bodyText: document.body.innerText.substring(0, 500),
                };
            }""")
            print(f"   Hits: {search_result.get('hits')}")
            print(f"   Grid elements: {search_result.get('gridCount')}")
            print(f"   Body: {search_result.get('bodyText')[:300]}")

            if search_result.get("gridCount", 0) > 0:
                print("   ✅✅✅ GRID DATA FOUND!")
        else:
            print("   ❌ Criteria switch did NOT work")

            # Try approach C: use cookies from Playwright + httpx
            print("\n--- Approach C: Extract Playwright cookies for httpx ---")
            cookies = await context.cookies()
            print(f"   Cookies: {len(cookies)}")
            for c in cookies:
                print(f"     {c['name']}: {c['value'][:50]}...")

            # Create httpx client with these cookies
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=30,
                cookies=cookie_dict
            ) as client:
                # Try GET with Playwright's cookies
                get_resp = await client.get(BASE_URL, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                })
                print(f"\n   httpx GET with PW cookies: {get_resp.status_code}, {len(get_resp.text)} chars")

                if len(get_resp.text) > 1000:
                    fields = extract_aspnet_fields(get_resp.text)
                    print(f"   VS len: {len(fields['__VIEWSTATE'])}")
                    print(f"   EV len: {len(fields['__EVENTVALIDATION'])}")

                    if len(fields["__VIEWSTATE"]) > 0:
                        print("   ✅ Got real viewstate with Playwright cookies!")

                        # Criteria switch
                        switch_data = {
                            **fields,
                            "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName",
                            "__EVENTARGUMENT": "",
                            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
                        }
                        switch_resp = await client.post(BASE_URL, data=switch_data, headers=HEADERS)
                        html2 = switch_resp.text
                        fields2 = extract_aspnet_fields(html2)
                        print(f"   Criteria switch: {switch_resp.status_code}, {len(html2)} chars")

                        # Search
                        search_data = {
                            **fields2,
                            "__EVENTTARGET": "",
                            "__EVENTARGUMENT": "",
                            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
                            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
                            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
                            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
                            "SearchFormEx1$ACSDropDownList_Towns": "115",
                            "SearchFormEx1$btnSearch": "Search",
                        }
                        search_resp = await client.post(BASE_URL, data=search_data, headers=HEADERS)
                        html3 = search_resp.text
                        hits_match = re.search(r'(\d+)\s+hits', html3)
                        grid_count = len(re.findall(r'DocList1_GridView_Document_ctl', html3))
                        print(f"   Search: {search_resp.status_code}, {len(html3)} chars")
                        print(f"   Hits: {hits_match.group(1) if hits_match else -1}")
                        print(f"   Grid count: {grid_count}")

                        if grid_count > 0:
                            print("   ✅✅✅ GOT GRID DATA WITH PW COOKIES + HTTPX!")
                            with open("/tmp/_mx_search_pw_cookies.html", "w") as f:
                                f.write(html3)

        await browser.close()


async def main():
    html3, async_html = await approach_a()
    await approach_b()
    print("\n" + "=" * 60)
    print("Diagnostic 6 complete!")


if __name__ == "__main__":
    asyncio.run(main())
