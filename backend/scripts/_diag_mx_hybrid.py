#!/usr/bin/env python3
"""
Diagnostic 4: Hybrid httpx + Playwright approach.

- httpx does the GET + criteria switch POST + search POST (bypasses WAF)
- Playwright renders the response HTML (renders AJAX/JS content)
- Then we extract grid records from the rendered page

Key question: does the httpx search response contain grid data in raw HTML?
"""

import asyncio
import re
from playwright.async_api import async_playwright
import httpx

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


async def main():
    print("=" * 60)
    print("Diagnostic 4: Hybrid httpx + Playwright")
    print("=" * 60)

    # === Phase 1: httpx does all the HTTP requests ===
    print("\n--- Phase 1: httpx HTTP chain ---")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # Step 1: GET page
        print("\n1. GET page...")
        get_resp = await client.get(BASE_URL, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": HEADERS["Accept"],
        })
        print(f"   Status: {get_resp.status_code}")
        print(f"   Size: {len(get_resp.text)} chars")

        if get_resp.status_code != 200:
            print(f"   ❌ Failed with status {get_resp.status_code}")
            return

        html1 = get_resp.text
        fields1 = extract_aspnet_fields(html1)
        print(f"   __VIEWSTATE: {len(fields1['__VIEWSTATE'])} chars")
        print(f"   __EVENTVALIDATION: {len(fields1['__EVENTVALIDATION'])} chars")

        # Step 2: POST criteria switch
        print("\n2. POST criteria switch...")
        switch_data = {
            **fields1,
            "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
        }
        switch_resp = await client.post(BASE_URL, data=switch_data, headers=HEADERS)
        print(f"   Status: {switch_resp.status_code}")
        print(f"   Size: {len(switch_resp.text)} chars")

        html2 = switch_resp.text

        # Verify criteria switched
        crit_selected = re.findall(r'<option\s+selected="selected"[^>]*>([^<]*)</option>', html2)
        print(f"   Selected criteria: {crit_selected}")

        if "Recorded Date Search" not in str(crit_selected):
            print("   ❌ Criteria did NOT switch")
            return

        print("   ✅ Criteria switched!")
        fields2 = extract_aspnet_fields(html2)
        print(f"   New __VIEWSTATE: {len(fields2['__VIEWSTATE'])} chars")

        # Step 3: POST search with TAKING + NEWTON
        print("\n3. POST search (TAKING + NEWTON)...")
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
        print(f"   Status: {search_resp.status_code}")
        print(f"   Size: {len(search_resp.text)} chars")

        html3 = search_resp.text

        # Check for hits
        hits_match = re.search(r'(\d+)\s+hits', html3)
        hits = int(hits_match.group(1)) if hits_match else -1
        print(f"   Hits: {hits}")

        # Check what's in the raw HTML
        taking_count = html3.count("TAKING")
        grid_count = len(re.findall(r'DocList1_GridView_Document_ctl', html3))
        has_update_panel = 'UpdatePanel' in html3
        has_script_manager = 'ScriptManager' in html3

        print(f"   TAKING count in raw HTML: {taking_count}")
        print(f"   Grid element count in raw HTML: {grid_count}")
        print(f"   Has UpdatePanel reference: {has_update_panel}")
        print(f"   Has ScriptManager reference: {has_script_manager}")

        if grid_count > 0:
            print(f"   ✅✅✅ Grid data IS in raw HTML! Can extract directly!")

        # Look for specific data patterns
        # Grid row pattern
        row_pattern = re.findall(r'DocList1_GridView_Document_ctl(\d+)_ButtonRow', html3)
        unique_rows = sorted(set(row_pattern))
        print(f"   Unique grid rows found: {len(unique_rows)} ({unique_rows[:5]}...)")

        # Look for date cells (File Date format like MM/DD/YYYY)
        date_pattern = re.findall(r'>(\d{1,2}/\d{1,2}/\d{4})</span>', html3)
        print(f"   Date values found: {len(date_pattern)} (first 5: {date_pattern[:5]})")

        # Look for Book/Page pattern
        book_page_pattern = re.findall(r'>(\d+)\s*/\s*(\d+)</span>', html3)
        print(f"   Book/Page values found: {len(book_page_pattern)} (first 5: {book_page_pattern[:5]})")

    if grid_count == 0 and hits > 0:
        print("\n--- Phase 2: Load response in Playwright to render AJAX ---")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            print("\n4. Loading search result HTML into Playwright...")
            await page.set_content(html3, wait_until="networkidle")
            await page.wait_for_timeout(3000)

            # Check rendered content
            info = await page.evaluate("""() => {
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
            print(f"   Grid records extracted: {len(info)}")
            for i, r in enumerate(info[:10]):
                print(f"   [{i}] {r}")
            if len(info) > 10:
                print(f"   ... ({len(info) - 10} more)")

            await browser.close()
    elif grid_count > 0:
        print("\n--- Phase 2: Extract directly from raw HTML (no Playwright needed) ---")
        # Can use regex or BeautifulSoup on raw HTML
        # Try regex extraction of grid records
        print("\n4. Extracting records from raw HTML...")

        records = []
        for i in range(200):
            ctl_num = str(i + 2).zfill(2)
            row_idx = i
            prefix = f'DocList1_GridView_Document_ctl{ctl_num}_ButtonRow_'

            # File Date
            fd_match = re.search(
                rf'id="{re.escape(prefix)}File Date_{row_idx}"[^>]*>([^<]*)</span>',
                html3
            )
            if not fd_match:
                break

            # Book/Page
            bp_match = re.search(
                rf'id="{re.escape(prefix)}Book/Page_{row_idx}"[^>]*>([^<]*)</span>',
                html3
            )
            # Type Desc
            td_match = re.search(
                rf'id="{re.escape(prefix)}Type Desc._{row_idx}"[^>]*>([^<]*)</span>',
                html3
            )
            # Town
            tw_match = re.search(
                rf'id="{re.escape(prefix)}Town_{row_idx}"[^>]*>([^<]*)</span>',
                html3
            )

            records.append({
                'fileDate': fd_match.group(1).strip() if fd_match else '',
                'bookPage': bp_match.group(1).strip() if bp_match else '',
                'typeDesc': td_match.group(1).strip() if td_match else '',
                'town': tw_match.group(1).strip() if tw_match else '',
            })

        print(f"   Records extracted: {len(records)}")
        for i, r in enumerate(records[:10]):
            print(f"   [{i}] {r}")
        if len(records) > 10:
            print(f"   ... ({len(records) - 10} more)")

    print("\n" + "=" * 60)
    print("Diagnostic 4 complete!")


if __name__ == "__main__":
    asyncio.run(main())
