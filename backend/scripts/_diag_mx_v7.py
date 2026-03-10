#!/usr/bin/env python3
"""
Diagnostic 7: Test ButRefreshNavigator postback to populate DocList grid.

Discovery from v6: httpx search POST returns "limited to first 1,000 records"
but DocList1_UpdatePanel is EMPTY. The grid data is populated by a subsequent
AJAX postback triggered by RefreshNavigator() → __doPostBack('ButRefreshNavigator','').

This script tests:
1. Regular httpx chain: GET → criteria switch → search
2. 4th POST: ButRefreshNavigator (regular form POST)
3. 4th POST: ButRefreshNavigator (ScriptManager async format)
4. Alternative: Try different ScriptManager panel targets
"""

import asyncio
import re
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


def check_grid_data(html: str, label: str) -> dict:
    """Analyze HTML for grid/result data."""
    hits_match = re.search(r'(\d+)\s+hits', html)
    hits = int(hits_match.group(1)) if hits_match else -1
    taking_count = html.count("TAKING")
    grid_count = len(re.findall(r'DocList1_GridView_Document_ctl', html))
    date_values = re.findall(r'>(\d{1,2}/\d{1,2}/\d{4})</span>', html)
    book_page_values = re.findall(r'>(\d+)\s*/\s*(\d+)</span>', html)

    # Check for "1,000 records" message
    limited_msg = "search results have been limited" in html

    # Check for specific grid elements
    has_gridview = 'GridView_Document' in html
    has_buttonrow = 'ButtonRow_' in html

    # Check if DocList1_UpdatePanel has content
    up_match = re.search(r'id="DocList1_UpdatePanel"[^>]*>(.*?)</div>', html, re.DOTALL)
    up_content_len = len(up_match.group(1).strip()) if up_match else -1

    result = {
        "hits": hits,
        "taking_count": taking_count,
        "grid_elements": grid_count,
        "date_values": len(date_values),
        "book_page_values": len(book_page_values),
        "limited_msg": limited_msg,
        "has_gridview": has_gridview,
        "has_buttonrow": has_buttonrow,
        "update_panel_content_len": up_content_len,
    }

    print(f"\n   [{label}] Analysis:")
    for k, v in result.items():
        print(f"     {k}: {v}")
    if date_values:
        print(f"     First 5 dates: {date_values[:5]}")
    if book_page_values:
        print(f"     First 5 book/page: {book_page_values[:5]}")

    return result


def extract_grid_records(html: str) -> list:
    """Extract records from GridView HTML using regex."""
    records = []
    for i in range(200):
        ctl_num = str(i + 2).zfill(2)
        row_idx = i
        prefix = f'DocList1_GridView_Document_ctl{ctl_num}_ButtonRow_'

        # File Date
        fd_match = re.search(
            rf'id="{re.escape(prefix)}File Date_{row_idx}"[^>]*>([^<]*)</span>',
            html
        )
        if not fd_match:
            break

        # Book/Page
        bp_match = re.search(
            rf'id="{re.escape(prefix)}Book/Page_{row_idx}"[^>]*>([^<]*)</span>',
            html
        )
        # Type Desc
        td_match = re.search(
            rf'id="{re.escape(prefix)}Type Desc._{row_idx}"[^>]*>([^<]*)</span>',
            html
        )
        # Town
        tw_match = re.search(
            rf'id="{re.escape(prefix)}Town_{row_idx}"[^>]*>([^<]*)</span>',
            html
        )

        records.append({
            'fileDate': fd_match.group(1).strip() if fd_match else '',
            'bookPage': bp_match.group(1).strip() if bp_match else '',
            'typeDesc': td_match.group(1).strip() if td_match else '',
            'town': tw_match.group(1).strip() if tw_match else '',
        })

    return records


def parse_scriptmanager_response(text: str) -> dict:
    """Parse ScriptManager pipe-delimited partial response."""
    parts = text.split('|')
    panels = {}
    i = 0
    while i < len(parts) - 3:
        try:
            length = int(parts[i])
            ptype = parts[i + 1]
            pid = parts[i + 2]
            content = parts[i + 3]
            if ptype in ('updatePanel', 'hiddenField', 'scriptBlock'):
                panels[f"{ptype}:{pid}"] = {
                    "length": length,
                    "type": ptype,
                    "id": pid,
                    "content_len": len(content),
                    "content_preview": content[:200] if len(content) > 200 else content,
                }
            i += 4
        except (ValueError, IndexError):
            i += 1
    return panels


async def main():
    print("=" * 70)
    print("Diagnostic 7: ButRefreshNavigator postback for DocList grid data")
    print("=" * 70)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # =============================================
        # Step 1: GET page (will get Incapsula challenge)
        # =============================================
        print("\n1. GET page...")
        get_resp = await client.get(BASE_URL, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": HEADERS["Accept"],
        })
        print(f"   Status: {get_resp.status_code}, Size: {len(get_resp.text)} chars")
        html1 = get_resp.text
        fields1 = extract_aspnet_fields(html1)
        print(f"   VS={len(fields1['__VIEWSTATE'])}, EV={len(fields1['__EVENTVALIDATION'])}")

        # =============================================
        # Step 2: POST criteria switch
        # =============================================
        print("\n2. POST criteria switch...")
        switch_data = {
            **fields1,
            "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
        }
        switch_resp = await client.post(BASE_URL, data=switch_data, headers=HEADERS)
        print(f"   Status: {switch_resp.status_code}, Size: {len(switch_resp.text)} chars")
        html2 = switch_resp.text

        crit_selected = re.findall(r'<option\s+selected="selected"[^>]*>([^<]*)</option>', html2)
        print(f"   Selected criteria: {crit_selected}")

        if "Recorded Date Search" not in str(crit_selected):
            print("   ❌ Criteria did NOT switch")
            return

        print("   ✅ Criteria switched!")
        fields2 = extract_aspnet_fields(html2)
        print(f"   VS={len(fields2['__VIEWSTATE'])}, EV={len(fields2['__EVENTVALIDATION'])}")

        # =============================================
        # Step 3: POST search (TAKING + NEWTON)
        # =============================================
        print("\n3. POST search (TAKING doc type 100103, NEWTON town 115)...")
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
        print(f"   Status: {search_resp.status_code}, Size: {len(search_resp.text)} chars")
        html3 = search_resp.text
        check_grid_data(html3, "Search response")

        fields3 = extract_aspnet_fields(html3)
        print(f"   VS={len(fields3['__VIEWSTATE'])}, EV={len(fields3['__EVENTVALIDATION'])}")

        # Save search response for reference
        with open('/tmp/_mx_v7_search.html', 'w') as f:
            f.write(html3)

        # =============================================
        # Step 4A: Regular POST with ButRefreshNavigator
        # =============================================
        print("\n" + "=" * 70)
        print("4A. Regular POST with __EVENTTARGET=ButRefreshNavigator")
        print("=" * 70)

        # Also include the search form fields to maintain state
        refresh_data = {
            **fields3,
            "__EVENTTARGET": "ButRefreshNavigator",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
        }
        refresh_resp = await client.post(BASE_URL, data=refresh_data, headers=HEADERS)
        print(f"   Status: {refresh_resp.status_code}, Size: {len(refresh_resp.text)} chars")
        html4a = refresh_resp.text
        result4a = check_grid_data(html4a, "RefreshNavigator regular")

        if result4a["grid_elements"] > 0:
            records = extract_grid_records(html4a)
            print(f"\n   ✅✅✅ GRID RECORDS FOUND: {len(records)}")
            for i, r in enumerate(records[:10]):
                print(f"   [{i}] {r}")
            if len(records) > 10:
                print(f"   ... ({len(records) - 10} more)")
            with open('/tmp/_mx_v7_refresh_regular.html', 'w') as f:
                f.write(html4a)

        fields4a = extract_aspnet_fields(html4a)

        # =============================================
        # Step 4B: ScriptManager async POST with ButRefreshNavigator
        # =============================================
        print("\n" + "=" * 70)
        print("4B. ScriptManager async POST targeting DocList1$UpdatePanel")
        print("=" * 70)

        async_data = {
            **fields3,  # Use fields from search response
            "ScriptManager1": "DocList1$UpdatePanel|ButRefreshNavigator",
            "__ASYNCPOST": "true",
            "__EVENTTARGET": "ButRefreshNavigator",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
        }
        async_headers = {
            **HEADERS,
            "X-Requested-With": "XMLHttpRequest",
            "X-MicrosoftAjax": "Delta=true",
        }
        async_resp = await client.post(BASE_URL, data=async_data, headers=async_headers)
        print(f"   Status: {async_resp.status_code}, Size: {len(async_resp.text)} chars")
        html4b = async_resp.text

        # Check if it's a ScriptManager partial response
        is_partial = html4b[:10].replace(' ', '').split('|')[0].isdigit() if '|' in html4b[:20] else False
        print(f"   Is partial response: {is_partial}")

        if is_partial:
            panels = parse_scriptmanager_response(html4b)
            print(f"   Parsed {len(panels)} response parts:")
            for name, info in panels.items():
                print(f"     {name}: len={info['content_len']}, preview={info['content_preview'][:100]}")

            # Check if any panel has grid data
            for name, info in panels.items():
                if 'GridView' in info.get('content_preview', '') or 'TAKING' in info.get('content_preview', ''):
                    print(f"   ✅ Found grid/TAKING data in {name}!")
        else:
            result4b = check_grid_data(html4b, "RefreshNavigator async")
            if result4b["grid_elements"] > 0:
                records = extract_grid_records(html4b)
                print(f"\n   ✅✅✅ GRID RECORDS FOUND: {len(records)}")
                for i, r in enumerate(records[:10]):
                    print(f"   [{i}] {r}")

        with open('/tmp/_mx_v7_refresh_async.html', 'w') as f:
            f.write(html4b)

        # =============================================
        # Step 4C: Try UpdatePanel1 as the panel target
        # =============================================
        print("\n" + "=" * 70)
        print("4C. ScriptManager async POST targeting UpdatePanel1")
        print("=" * 70)

        async_data_c = {
            **fields3,
            "ScriptManager1": "UpdatePanel1|ButRefreshNavigator",
            "__ASYNCPOST": "true",
            "__EVENTTARGET": "ButRefreshNavigator",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
        }
        async_resp_c = await client.post(BASE_URL, data=async_data_c, headers=async_headers)
        print(f"   Status: {async_resp_c.status_code}, Size: {len(async_resp_c.text)} chars")
        html4c = async_resp_c.text

        is_partial_c = html4c[:10].replace(' ', '').split('|')[0].isdigit() if '|' in html4c[:20] else False
        print(f"   Is partial response: {is_partial_c}")

        if is_partial_c:
            panels_c = parse_scriptmanager_response(html4c)
            print(f"   Parsed {len(panels_c)} response parts:")
            for name, info in panels_c.items():
                print(f"     {name}: len={info['content_len']}, preview={info['content_preview'][:100]}")
                # Full content check
                full_content = info.get('content_preview', '')
                if 'GridView' in html4c or 'ButtonRow' in html4c:
                    print(f"   ✅ Grid data present in response!")
        else:
            result4c = check_grid_data(html4c, "RefreshNavigator UpdatePanel1")
            if result4c["grid_elements"] > 0:
                records = extract_grid_records(html4c)
                print(f"\n   ✅✅✅ GRID RECORDS FOUND: {len(records)}")

        with open('/tmp/_mx_v7_refresh_panel1.html', 'w') as f:
            f.write(html4c)

        # =============================================
        # Step 4D: Try ButRefreshBasket as target (another navigator)
        # =============================================
        print("\n" + "=" * 70)
        print("4D. Regular POST with __EVENTTARGET=ButRefreshBasket")
        print("=" * 70)

        basket_data = {
            **fields3,
            "__EVENTTARGET": "ButRefreshBasket",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
        }
        basket_resp = await client.post(BASE_URL, data=basket_data, headers=HEADERS)
        print(f"   Status: {basket_resp.status_code}, Size: {len(basket_resp.text)} chars")
        html4d = basket_resp.text
        result4d = check_grid_data(html4d, "RefreshBasket")

        if result4d["grid_elements"] > 0:
            records = extract_grid_records(html4d)
            print(f"\n   ✅✅✅ GRID RECORDS FOUND: {len(records)}")
            for i, r in enumerate(records[:10]):
                print(f"   [{i}] {r}")

        # =============================================
        # Step 4E: Search POST with ScriptManager async format
        #          (search + render in one request)
        # =============================================
        print("\n" + "=" * 70)
        print("4E. ScriptManager async search POST (search + grid in one)")
        print("=" * 70)

        async_search_data = {
            **fields2,  # Use fields from criteria switch response
            "ScriptManager1": "DocList1$UpdatePanel|SearchFormEx1$btnSearch",
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
        async_search_resp = await client.post(BASE_URL, data=async_search_data, headers=async_headers)
        print(f"   Status: {async_search_resp.status_code}, Size: {len(async_search_resp.text)} chars")
        html4e = async_search_resp.text

        is_partial_e = html4e[:10].replace(' ', '').split('|')[0].isdigit() if '|' in html4e[:20] else False
        print(f"   Is partial response: {is_partial_e}")

        taking_in_resp = html4e.count("TAKING")
        grid_in_resp = len(re.findall(r'DocList1_GridView_Document_ctl', html4e))
        print(f"   TAKING count: {taking_in_resp}")
        print(f"   Grid elements: {grid_in_resp}")

        if is_partial_e:
            panels_e = parse_scriptmanager_response(html4e)
            print(f"   Parsed {len(panels_e)} response parts:")
            for name, info in panels_e.items():
                if info['content_len'] > 500:
                    print(f"     {name}: len={info['content_len']} (LARGE)")
                else:
                    print(f"     {name}: len={info['content_len']}, preview={info['content_preview'][:80]}")

        if grid_in_resp > 0:
            records = extract_grid_records(html4e)
            print(f"\n   ✅✅✅ GRID RECORDS FOUND: {len(records)}")
            for i, r in enumerate(records[:10]):
                print(f"   [{i}] {r}")

        with open('/tmp/_mx_v7_async_search.html', 'w') as f:
            f.write(html4e)

        # =============================================
        # Summary
        # =============================================
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        approaches = [
            ("4A: Regular ButRefreshNavigator", result4a),
        ]
        if 'result4b' in dir():
            approaches.append(("4B: Async ButRefreshNavigator (DocList1)", result4b if 'result4b' in dir() else {}))
        print("\nApproach results:")
        for name, res in approaches:
            grid = res.get('grid_elements', 0)
            status = "✅ HAS GRID DATA" if grid > 0 else "❌ No grid data"
            print(f"  {name}: {status} (grid={grid}, taking={res.get('taking_count', 0)})")


if __name__ == "__main__":
    asyncio.run(main())
