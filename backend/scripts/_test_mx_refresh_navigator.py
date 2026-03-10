#!/usr/bin/env python3
"""
Middlesex South Registry: Two-step result loading.

DISCOVERY: After search POST returns "limited to 1,000 records" success,
the result UpdatePanels (DocList1, SearchList1, NameList1) are EMPTY.
The browser's JavaScript calls RefreshNavigator() -> __doPostBack('ButRefreshNavigator','')
to trigger a SECOND AJAX postback that loads actual results.

This script:
1. GET page → cookies
2. POST criteria switch → "Recorded Date Search"
3. POST search (full postback) → server stores results in session
4. POST __EVENTTARGET='ButRefreshNavigator' (AJAX partial postback) → actual results
"""

import asyncio
import re
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import httpx

BASE_URL = "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://www.masslandrecords.com",
    "Referer": BASE_URL,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
}

AJAX_HEADERS = {
    **HEADERS,
    "X-MicrosoftAjax": "Delta=true",
    "X-Requested-With": "XMLHttpRequest",
}


def extract_aspnet_fields(html: str) -> dict:
    vs = re.search(r'id="__VIEWSTATE"\s+value="([^"]*)"', html)
    ev = re.search(r'id="__EVENTVALIDATION"\s+value="([^"]*)"', html)
    vsg = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]*)"', html)
    vse = re.search(r'id="__VIEWSTATEENCRYPTED"\s+value="([^"]*)"', html)
    sm = re.search(r'id="ScriptManager1_HiddenField"\s+value="([^"]*)"', html)
    return {
        "__VIEWSTATE": vs.group(1) if vs else "",
        "__VIEWSTATEENCRYPTED": vse.group(1) if vse else "",
        "__EVENTVALIDATION": ev.group(1) if ev else "",
        "__VIEWSTATEGENERATOR": vsg.group(1) if vsg else "",
        "ScriptManager1_HiddenField": sm.group(1) if sm else "",
    }


def parse_delta_response(text: str) -> dict:
    """Parse ASP.NET AJAX delta response format."""
    panels = {}
    hidden_fields = {}
    scripts = []
    errors = []

    pos = 0
    while pos < len(text):
        pipe1 = text.find("|", pos)
        if pipe1 == -1:
            break
        try:
            length = int(text[pos:pipe1])
        except ValueError:
            break
        pipe2 = text.find("|", pipe1 + 1)
        if pipe2 == -1:
            break
        dtype = text[pipe1 + 1:pipe2]
        pipe3 = text.find("|", pipe2 + 1)
        if pipe3 == -1:
            break
        did = text[pipe2 + 1:pipe3]
        content = text[pipe3 + 1:pipe3 + 1 + length]
        pos = pipe3 + 1 + length + 1

        if dtype == "updatePanel":
            panels[did] = content
        elif dtype == "hiddenField":
            hidden_fields[did] = content
        elif dtype == "error":
            errors.append(f"{did}: {content}")
        elif dtype == "scriptBlock":
            scripts.append(content)

    return {"panels": panels, "hidden_fields": hidden_fields, "scripts": scripts, "errors": errors}


async def test_refresh_navigator():
    """
    Test A: Search + RefreshNavigator approach.
    After search POST, call RefreshNavigator() via AJAX to load results.
    """
    print("\n" + "=" * 70)
    print("Test A: Search + RefreshNavigator() to load results")
    print("=" * 70)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # Step 1: GET
        print("\n--- Step 1: GET page ---")
        r = await client.get(BASE_URL, headers={"User-Agent": HEADERS["User-Agent"], "Accept": "text/html"})
        print(f"  Status: {r.status_code}")
        if r.status_code != 200:
            print("  ❌ Failed")
            return
        f1 = extract_aspnet_fields(r.text)

        # Step 2: Switch criteria
        print("\n--- Step 2: Switch criteria ---")
        r2 = await client.post(BASE_URL, headers=HEADERS, data={
            **f1, "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName", "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
        })
        print(f"  Status: {r2.status_code}")
        sel = re.findall(r'<option\s+selected="selected"[^>]*>([^<]*)</option>', r2.text)
        print(f"  Selected: {sel}")
        if "Recorded Date Search" not in str(sel):
            print("  ❌ Criteria switch failed")
            return
        print("  ✅ Criteria switched")
        f2 = extract_aspnet_fields(r2.text)

        # Step 3: Search POST (full postback, NOT AJAX)
        print("\n--- Step 3: Full search POST (TAKING + NEWTON) ---")
        search_data = {
            **f2,
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",  # TAKING
            "SearchFormEx1$ACSDropDownList_Towns": "115",  # NEWTON
            "SearchFormEx1$ACSRadioButtonList_Search": "1",  # Compressed
            "SearchFormEx1$btnSearch": "Search",
        }
        r3 = await client.post(BASE_URL, headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}, data=search_data)
        print(f"  Status: {r3.status_code}, Size: {len(r3.text)} chars")

        if "limited to" in r3.text or "1,000" in r3.text:
            print("  ✅ Search executed! (limited to 1,000 records)")
        else:
            hits = re.search(r'(\d+)\s+hits', r3.text)
            if hits:
                print(f"  Hits: {hits.group(1)}")
            else:
                print("  ⚠️  No hits/limited message found")

        f3 = extract_aspnet_fields(r3.text)
        print(f"  __VIEWSTATE: {len(f3['__VIEWSTATE'])} chars")
        print(f"  ScriptManager1_HiddenField: '{f3['ScriptManager1_HiddenField']}'")

        # Step 4A: Try RefreshNavigator as AJAX postback
        print("\n--- Step 4A: AJAX RefreshNavigator ---")
        refresh_data = {
            **f3,
            "__EVENTTARGET": "ButRefreshNavigator",
            "__EVENTARGUMENT": "",
            "ScriptManager1": "UpdatePanelRefreshButtons|ButRefreshNavigator",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
            "SearchFormEx1$ACSRadioButtonList_Search": "1",
            "__ASYNCPOST": "true",
        }
        r4a = await client.post(BASE_URL, headers=AJAX_HEADERS, data=refresh_data)
        ct = r4a.headers.get("content-type", "")
        print(f"  Status: {r4a.status_code}, Size: {len(r4a.text)} chars, CT: {ct}")

        is_delta = r4a.text[:5].replace("|", "").strip().isdigit() if len(r4a.text) > 5 else False
        if is_delta:
            print("  ✅ Got delta response!")
            parsed = parse_delta_response(r4a.text)
            print(f"  Panels: {list(parsed['panels'].keys())}")
            for pid, pcontent in parsed['panels'].items():
                print(f"    {pid}: {len(pcontent)} chars")
                if len(pcontent) > 100:
                    print(f"      Preview: {pcontent[:300]}...")
                if "TAKING" in pcontent:
                    print(f"      ✅✅✅ TAKING found in panel {pid}!")
                if "NEWTON" in pcontent:
                    print(f"      ✅ NEWTON found in panel {pid}")
                if "GR" in pcontent or "GT" in pcontent:
                    gr = pcontent.count(">GR<") + pcontent.count(">GR ")
                    gt = pcontent.count(">GT<") + pcontent.count(">GT ")
                    if gr > 0 or gt > 0:
                        print(f"      ✅ Result rows: GR={gr}, GT={gt}")
            if parsed['errors']:
                print(f"  Errors: {parsed['errors']}")

            # Save delta response
            path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_refresh_delta.txt"
            path.write_text(r4a.text)
            print(f"  Saved to {path.name}")
        else:
            # Full HTML response
            print(f"  Got full HTML response ({len(r4a.text)} chars)")
            if "TAKING" in r4a.text:
                count = r4a.text.count("TAKING")
                print(f"  ✅ TAKING appears {count} times!")
            path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_refresh_full.html"
            path.write_text(r4a.text)
            print(f"  Saved to {path.name}")

        # Step 4B: Try different AJAX targets if 4A didn't get results
        for target_panel, trigger_btn in [
            ("DocList1$UpdatePanel|ButRefreshNavigator", "ButRefreshNavigator"),
            ("SearchList1$UpdatePanel|ButRefreshNavigator", "ButRefreshNavigator"),
            ("NameList1$UpdatePanel|ButRefreshNavigator", "ButRefreshNavigator"),
        ]:
            print(f"\n--- Step 4B: AJAX target={target_panel.split('|')[0]} ---")
            alt_data = {
                **f3,
                "__EVENTTARGET": trigger_btn,
                "__EVENTARGUMENT": "",
                "ScriptManager1": target_panel,
                "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
                "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
                "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
                "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
                "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
                "SearchFormEx1$ACSDropDownList_Towns": "115",
                "SearchFormEx1$ACSRadioButtonList_Search": "1",
                "__ASYNCPOST": "true",
            }
            r4b = await client.post(BASE_URL, headers=AJAX_HEADERS, data=alt_data)
            print(f"  Status: {r4b.status_code}, Size: {len(r4b.text)} chars")

            is_delta2 = r4b.text[:5].replace("|", "").strip().isdigit() if len(r4b.text) > 5 else False
            if is_delta2:
                parsed2 = parse_delta_response(r4b.text)
                print(f"  Panels: {list(parsed2['panels'].keys())}")
                for pid, pc in parsed2['panels'].items():
                    if len(pc) > 200:
                        print(f"    {pid}: {len(pc)} chars — {pc[:200]}...")
                        if "TAKING" in pc:
                            print(f"    ✅✅✅ GOT TAKING DATA!")
                    else:
                        print(f"    {pid}: {len(pc)} chars")
                if parsed2['errors']:
                    print(f"  Errors: {parsed2['errors']}")
            elif "TAKING" in r4b.text:
                count = r4b.text.count("TAKING")
                print(f"  ✅ TAKING in full HTML: {count} times")


async def test_search_as_ajax():
    """
    Test B: Do the SEARCH itself as an AJAX partial postback with the correct
    ScriptManager trigger ID. Then immediately call RefreshNavigator.
    """
    print("\n" + "=" * 70)
    print("Test B: AJAX search + RefreshNavigator in same session")
    print("=" * 70)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # Steps 1-2: GET + criteria switch
        print("\n--- Steps 1-2: GET + switch criteria ---")
        r = await client.get(BASE_URL, headers={"User-Agent": HEADERS["User-Agent"], "Accept": "text/html"})
        f1 = extract_aspnet_fields(r.text)
        r2 = await client.post(BASE_URL, headers=HEADERS, data={
            **f1, "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName", "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
        })
        f2 = extract_aspnet_fields(r2.text)
        sel = re.findall(r'<option\s+selected="selected"[^>]*>([^<]*)</option>', r2.text)
        print(f"  Selected: {sel}")

        # Step 3: AJAX search postback
        print("\n--- Step 3: AJAX search ---")
        search_data = {
            **f2,
            "__EVENTTARGET": "SearchFormEx1$btnSearch",
            "__EVENTARGUMENT": "",
            "ScriptManager1": "SearchFormEx1$UpdatePanel|SearchFormEx1$btnSearch",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
            "SearchFormEx1$ACSRadioButtonList_Search": "1",
            "__ASYNCPOST": "true",
        }
        r3 = await client.post(BASE_URL, headers=AJAX_HEADERS, data=search_data)
        print(f"  Status: {r3.status_code}, Size: {len(r3.text)} chars")

        is_delta3 = r3.text[:5].replace("|", "").strip().isdigit() if len(r3.text) > 5 else False
        if is_delta3:
            parsed3 = parse_delta_response(r3.text)
            print(f"  Panels: {list(parsed3['panels'].keys())}")
            if parsed3['errors']:
                print(f"  Errors: {parsed3['errors']}")
            # Extract updated hidden fields for next request
            f3_update = parsed3['hidden_fields']
            print(f"  Updated fields: {list(f3_update.keys())}")

            # Use updated fields from delta response
            f3 = {**f2}
            for k, v in f3_update.items():
                f3[k] = v
        else:
            print(f"  Full HTML response ({len(r3.text)} chars)")
            f3 = extract_aspnet_fields(r3.text)

        # Step 4: AJAX RefreshNavigator
        print("\n--- Step 4: AJAX RefreshNavigator ---")
        refresh_data = {
            **f3,
            "__EVENTTARGET": "ButRefreshNavigator",
            "__EVENTARGUMENT": "",
            "ScriptManager1": "UpdatePanelRefreshButtons|ButRefreshNavigator",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
            "SearchFormEx1$ACSRadioButtonList_Search": "1",
            "__ASYNCPOST": "true",
        }
        r4 = await client.post(BASE_URL, headers=AJAX_HEADERS, data=refresh_data)
        print(f"  Status: {r4.status_code}, Size: {len(r4.text)} chars")

        is_delta4 = r4.text[:5].replace("|", "").strip().isdigit() if len(r4.text) > 5 else False
        if is_delta4:
            parsed4 = parse_delta_response(r4.text)
            print(f"  Panels: {list(parsed4['panels'].keys())}")
            for pid, pc in parsed4['panels'].items():
                print(f"    {pid}: {len(pc)} chars")
                if "TAKING" in pc:
                    print(f"    ✅✅✅ GOT TAKING DATA IN {pid}!")
                    # Show first 500 chars
                    print(f"    Content: {pc[:500]}...")
                if ">GR<" in pc or ">GT<" in pc or ">GR " in pc:
                    print(f"    ✅ Found GR/GT result rows!")
            if parsed4['errors']:
                print(f"  Errors: {parsed4['errors']}")

            path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_refresh_after_ajax_search.txt"
            path.write_text(r4.text)
            print(f"  Saved to {path.name}")
        else:
            print(f"  Full HTML ({len(r4.text)} chars)")
            if "TAKING" in r4.text:
                print(f"  ✅ TAKING found {r4.text.count('TAKING')} times")


async def test_search_no_ajax():
    """
    Test C: Do EVERYTHING as full (non-AJAX) POSTs. No ScriptManager, no delta.
    Some ASP.NET apps degrade gracefully without JavaScript.
    """
    print("\n" + "=" * 70)
    print("Test C: Pure full-page POSTs (no AJAX at all)")
    print("=" * 70)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        plain_headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.masslandrecords.com",
            "Referer": BASE_URL,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        # Step 1: GET
        r = await client.get(BASE_URL, headers={"User-Agent": HEADERS["User-Agent"], "Accept": "text/html"})
        f1 = extract_aspnet_fields(r.text)

        # Step 2: Switch criteria
        r2 = await client.post(BASE_URL, headers=plain_headers, data={
            **f1, "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName", "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
        })
        f2 = extract_aspnet_fields(r2.text)

        # Step 3: Search with btnSearch (use the form submit button, NOT __EVENTTARGET)
        print("\n--- Step 3: Full POST search ---")
        r3 = await client.post(BASE_URL, headers=plain_headers, data={
            **f2,
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
            "SearchFormEx1$ACSRadioButtonList_Search": "1",
            "SearchFormEx1$btnSearch": "Search",
        })
        print(f"  Status: {r3.status_code}, Size: {len(r3.text)} chars")
        f3 = extract_aspnet_fields(r3.text)

        # Step 4: Full POST RefreshNavigator
        print("\n--- Step 4: Full POST RefreshNavigator ---")
        r4 = await client.post(BASE_URL, headers=plain_headers, data={
            **f3,
            "__EVENTTARGET": "ButRefreshNavigator",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
            "SearchFormEx1$ACSRadioButtonList_Search": "1",
        })
        print(f"  Status: {r4.status_code}, Size: {len(r4.text)} chars")

        # Check for results
        if "TAKING" in r4.text:
            taking_count = r4.text.count("TAKING")
            print(f"  ✅ TAKING appears {taking_count} times!")
            if taking_count > 2:
                print(f"  ✅✅✅ LIKELY GOT ACTUAL RESULTS!")

        # Check result panels
        for panel_id in ["DocList1_UpdatePanel", "SearchList1_UpdatePanel", "NameList1_UpdatePanel"]:
            match = re.search(rf'id="{panel_id}"[^>]*>(.*?)</div>\s*</div>', r4.text, re.DOTALL)
            if match:
                content = match.group(1).strip()
                if len(content) > 100:
                    print(f"  {panel_id}: {len(content)} chars")
                    if "TAKING" in content:
                        print(f"    ✅✅✅ RESULTS in {panel_id}!")
                else:
                    print(f"  {panel_id}: {len(content)} chars (likely empty)")

        # Count GR/GT rows (indicator of results)
        gr = len(re.findall(r'>GR\s*<', r4.text))
        gt = len(re.findall(r'>GT\s*<', r4.text))
        if gr > 0 or gt > 0:
            print(f"  ✅ Result rows: GR={gr}, GT={gt}")

        # Save
        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_fullpost_refresh.html"
        path.write_text(r4.text)
        print(f"  Saved to {path.name}")

        # Step 5: Try RefreshBasket too
        print("\n--- Step 5: Full POST ButRefreshBasket ---")
        f4 = extract_aspnet_fields(r4.text)
        r5 = await client.post(BASE_URL, headers=plain_headers, data={
            **f4,
            "__EVENTTARGET": "ButRefreshBasket",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
        })
        print(f"  Status: {r5.status_code}, Size: {len(r5.text)} chars")
        if "TAKING" in r5.text:
            taking_count = r5.text.count("TAKING")
            print(f"  TAKING appears {taking_count} times")


async def main():
    # Test A: Full search + RefreshNavigator (AJAX)
    await test_refresh_navigator()

    # Test B: AJAX search + AJAX refresh
    await test_search_as_ajax()

    # Test C: All full-page POSTs (no AJAX)
    await test_search_no_ajax()

    print("\n" + "=" * 70)
    print("All tests complete")


if __name__ == "__main__":
    asyncio.run(main())
