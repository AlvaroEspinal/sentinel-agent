#!/usr/bin/env python3
"""
ASP.NET AJAX Partial Postback approach for Middlesex South Registry.

BREAKTHROUGH from previous session:
- httpx bypasses Incapsula WAF directly
- Criteria switch to "Recorded Date Search" works perfectly
- Search POST executes successfully (confirmed by "limited to 1,000 records" message)
- BUT result data is NOT in the full HTML response — it's loaded via AJAX UpdatePanels

The page uses Sys.WebForms.PageRequestManager with async postbacks.
When SearchFormEx1$btnSearch is clicked, the PageRequestManager intercepts
__doPostBack and sends an async POST with:
  - ScriptManager1 field = "UpdatePanelID|ButtonID"
  - Header: X-MicrosoftAjax: Delta=true
  - Header: X-Requested-With: XMLHttpRequest

The response comes back in ASP.NET delta format:
  length|type|id|content|length|type|id|content|...

This script tries that approach to get actual result data.
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
    """Extract ASP.NET hidden fields from HTML."""
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
    """
    Parse ASP.NET AJAX delta response format.

    Format: length|type|id|content|length|type|id|content|...
    Types: updatePanel, hiddenField, asyncPostBackControlIDs,
           postBackControlIDs, updatePanelIDs, scriptDispose,
           arrayDeclaration, onSubmit, focus, error, etc.
    """
    panels = {}
    hidden_fields = {}
    scripts = []
    errors = []

    pos = 0
    while pos < len(text):
        # Parse length
        pipe1 = text.find("|", pos)
        if pipe1 == -1:
            break
        try:
            length = int(text[pos:pipe1])
        except ValueError:
            # Not a valid delta response
            break

        # Parse type
        pipe2 = text.find("|", pipe1 + 1)
        if pipe2 == -1:
            break
        dtype = text[pipe1 + 1:pipe2]

        # Parse id
        pipe3 = text.find("|", pipe2 + 1)
        if pipe3 == -1:
            break
        did = text[pipe2 + 1:pipe3]

        # Parse content (by length)
        content = text[pipe3 + 1:pipe3 + 1 + length]

        # Move past content and trailing pipe
        pos = pipe3 + 1 + length + 1

        if dtype == "updatePanel":
            panels[did] = content
        elif dtype == "hiddenField":
            hidden_fields[did] = content
        elif dtype == "error":
            errors.append(f"{did}: {content}")
        elif dtype == "scriptBlock":
            scripts.append(content)

    return {
        "panels": panels,
        "hidden_fields": hidden_fields,
        "scripts": scripts,
        "errors": errors,
    }


async def test_ajax_postback():
    """
    Full test: GET → switch criteria (full POST) → AJAX search (async postback).
    """
    print("\n" + "=" * 60)
    print("Test: ASP.NET AJAX Partial Postback for search results")
    print("=" * 60)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # === STEP 1: GET page ===
        print("\n--- Step 1: GET page ---")
        get_resp = await client.get(BASE_URL, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        print(f"  Status: {get_resp.status_code}")
        if get_resp.status_code != 200:
            print("  ❌ Failed")
            return

        html1 = get_resp.text
        fields1 = extract_aspnet_fields(html1)
        print(f"  __VIEWSTATE: {len(fields1['__VIEWSTATE'])} chars")
        print(f"  Cookies: {list(get_resp.cookies.keys())}")

        # === STEP 2: Switch to Recorded Date Search (full POST) ===
        print("\n--- Step 2: Switch criteria to Recorded Date Search ---")
        switch_data = {
            **fields1,
            "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
        }

        switch_resp = await client.post(BASE_URL, data=switch_data, headers=HEADERS)
        print(f"  Status: {switch_resp.status_code}")

        html2 = switch_resp.text
        fields2 = extract_aspnet_fields(html2)

        crit_selected = re.findall(r'<option\s+selected="selected"[^>]*>([^<]*)</option>', html2)
        print(f"  Selected: {crit_selected}")

        if "Recorded Date Search" not in str(crit_selected):
            print("  ❌ Criteria switch failed")
            return
        print("  ✅ Criteria switched to Recorded Date Search")

        # === STEP 3A: Try AJAX async postback for search ===
        print("\n--- Step 3A: AJAX async postback search ---")

        # The ScriptManager1 field tells ASP.NET which UpdatePanel triggered the postback
        # Format: "UpdatePanelID|TriggerControlID"
        # The search button is SearchFormEx1$btnSearch inside SearchFormEx1$UpdatePanel
        ajax_search_data = {
            **fields2,
            "ScriptManager1": "SearchFormEx1$UpdatePanel|SearchFormEx1$btnSearch",
            "__EVENTTARGET": "SearchFormEx1$btnSearch",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2024",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",  # TAKING
            "SearchFormEx1$ACSDropDownList_Towns": "115",  # NEWTON
            "SearchFormEx1$ACSRadioButtonList_Search": "1",  # Compressed
            "SearchFormEx1$btnSearch": "Search",
        }

        ajax_resp = await client.post(BASE_URL, data=ajax_search_data, headers=AJAX_HEADERS)
        print(f"  Status: {ajax_resp.status_code}")
        print(f"  Response size: {len(ajax_resp.text)} chars")
        print(f"  Content-Type: {ajax_resp.headers.get('content-type', 'N/A')}")

        resp_text = ajax_resp.text

        # Check if it's a delta response (starts with a number|)
        is_delta = bool(re.match(r'^\d+\|', resp_text))
        print(f"  Is delta format: {is_delta}")

        if is_delta:
            parsed = parse_delta_response(resp_text)
            print(f"  UpdatePanels returned: {list(parsed['panels'].keys())}")
            print(f"  Hidden fields: {list(parsed['hidden_fields'].keys())}")
            if parsed['errors']:
                print(f"  Errors: {parsed['errors']}")

            # Check result panels
            for panel_id in ["DocList1_UpdatePanel", "SearchList1_UpdatePanel", "NameList1_UpdatePanel"]:
                if panel_id in parsed['panels']:
                    content = parsed['panels'][panel_id]
                    print(f"\n  Panel '{panel_id}': {len(content)} chars")
                    # Check for result content
                    if "TAKING" in content:
                        taking_count = content.count("TAKING")
                        print(f"    ✅ TAKING found {taking_count} times!")
                    if ">GR<" in content or ">GR " in content:
                        gr_count = len(re.findall(r'>GR\s*<', content))
                        print(f"    ✅ GR rows: {gr_count}")
                    if "hits" in content.lower() or "record" in content.lower():
                        # Find hit count
                        hits = re.search(r'(\d+)\s+hits', content)
                        limited = re.search(r'limited to the first (\d[\d,]*) records', content)
                        if hits:
                            print(f"    Hits: {hits.group(1)}")
                        if limited:
                            print(f"    Limited to: {limited.group(1)} records")
                    # Show snippet
                    print(f"    Preview: {content[:500]}...")

            # Also check MessageBox panel for error/info messages
            for panel_id in ["MessageBoxCtrl1_UpdatePanel1", "SearchInfo1_UpdatePanel1"]:
                if panel_id in parsed['panels']:
                    content = parsed['panels'][panel_id]
                    if content.strip():
                        print(f"\n  Panel '{panel_id}': {content[:300]}")

            # Save full delta response
            path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_ajax_delta.txt"
            path.write_text(resp_text)
            print(f"\n  Saved delta response to {path.name}")

        else:
            print("  Not a delta response. Checking as HTML...")
            # Maybe it returned full HTML instead of delta
            if "limited to" in resp_text:
                print("  Found 'limited to' message — search executed!")
            if "TAKING" in resp_text:
                taking_count = resp_text.count("TAKING")
                print(f"  TAKING appears {taking_count} times")
            if "hits" in resp_text.lower():
                hits = re.search(r'(\d+)\s+hits', resp_text)
                if hits:
                    print(f"  Hits: {hits.group(1)}")

            # Show beginning of response
            print(f"\n  Response preview (first 1000 chars):")
            print(f"  {resp_text[:1000]}")

            # Save
            path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_ajax_response.html"
            path.write_text(resp_text)
            print(f"\n  Saved response to {path.name}")

        # === STEP 3B: Try alternative — full POST but with __EVENTTARGET = btnSearch ===
        print("\n\n--- Step 3B: Full POST with __EVENTTARGET = SearchFormEx1$btnSearch ---")
        full_search_data = {
            **fields2,
            "__EVENTTARGET": "SearchFormEx1$btnSearch",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2024",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",  # TAKING
            "SearchFormEx1$ACSDropDownList_Towns": "115",  # NEWTON
            "SearchFormEx1$ACSRadioButtonList_Search": "1",  # Compressed
        }

        full_resp = await client.post(BASE_URL, data=full_search_data, headers=HEADERS)
        print(f"  Status: {full_resp.status_code}")
        print(f"  Response size: {len(full_resp.text)} chars")

        html3b = full_resp.text

        # Check for results
        if "limited to" in html3b:
            print("  Found 'limited to' message")
        if "TAKING" in html3b:
            taking_count = html3b.count("TAKING")
            print(f"  TAKING appears {taking_count} times")

        # Check DocList/SearchList/NameList UpdatePanels for content
        for panel in ["DocList1_UpdatePanel", "SearchList1_UpdatePanel", "NameList1_UpdatePanel"]:
            idx = html3b.find(f'id="{panel}"')
            if idx > 0:
                # Get content between opening and closing div
                end_tag = html3b.find("</div>", idx)
                if end_tag > idx:
                    panel_content = html3b[idx:end_tag + 6]
                    if len(panel_content) > 100:  # More than just empty div
                        print(f"  ✅ {panel} has content: {len(panel_content)} chars")
                        print(f"     Preview: {panel_content[:300]}...")
                    else:
                        print(f"  {panel}: empty ({len(panel_content)} chars)")

        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_full_post_eventtarget.html"
        path.write_text(html3b)
        print(f"\n  Saved to {path.name}")


async def test_ajax_with_link_button():
    """
    Alternative: Use the link button approach.

    The page has link buttons like:
    Navigator1$SearchCriteria1$LinnkButton_15 → "Recorded Date Search"

    These might trigger the search flow differently than the dropdown.
    After clicking, the search form appears, then we can search.
    """
    print("\n" + "=" * 60)
    print("Test: Link button approach for criteria switch")
    print("=" * 60)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # GET page
        print("\n--- Step 1: GET page ---")
        get_resp = await client.get(BASE_URL, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        if get_resp.status_code != 200:
            print("  ❌ GET failed")
            return

        html = get_resp.text
        fields = extract_aspnet_fields(html)

        # Click "Recorded Date Search" link button (LinnkButton_15)
        print("\n--- Step 2: Click Recorded Date Search link ---")
        link_data = {
            **fields,
            "__EVENTTARGET": "Navigator1$SearchCriteria1$LinnkButton_15",
            "__EVENTARGUMENT": "",
        }

        link_resp = await client.post(BASE_URL, data=link_data, headers=HEADERS)
        print(f"  Status: {link_resp.status_code}")
        print(f"  Response size: {len(link_resp.text)} chars")

        html2 = link_resp.text
        fields2 = extract_aspnet_fields(html2)

        # Check if criteria switched
        crit_selected = re.findall(r'<option\s+selected="selected"[^>]*>([^<]*)</option>', html2)
        print(f"  Selected: {crit_selected}")

        has_date_from = "ACSTextBox_DateFrom" in html2
        has_doc_type = "ACSDropDownList_DocumentType" in html2
        has_towns = "ACSDropDownList_Towns" in html2
        print(f"  Date fields: {has_date_from}, DocType: {has_doc_type}, Towns: {has_towns}")

        if not has_date_from:
            print("  ❌ Link button didn't show date search form")
            return

        # Now search with AJAX
        print("\n--- Step 3: AJAX search from link button approach ---")
        ajax_data = {
            **fields2,
            "ScriptManager1": "SearchFormEx1$UpdatePanel|SearchFormEx1$btnSearch",
            "__EVENTTARGET": "SearchFormEx1$btnSearch",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2024",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
            "SearchFormEx1$ACSRadioButtonList_Search": "1",
            "SearchFormEx1$btnSearch": "Search",
        }

        ajax_resp = await client.post(BASE_URL, data=ajax_data, headers=AJAX_HEADERS)
        print(f"  Status: {ajax_resp.status_code}")
        print(f"  Response size: {len(ajax_resp.text)} chars")

        resp_text = ajax_resp.text
        is_delta = bool(re.match(r'^\d+\|', resp_text))
        print(f"  Is delta format: {is_delta}")

        if is_delta:
            parsed = parse_delta_response(resp_text)
            print(f"  Panels: {list(parsed['panels'].keys())}")
            for pid, content in parsed['panels'].items():
                if content.strip() and len(content) > 50:
                    print(f"    {pid}: {len(content)} chars")
                    if "TAKING" in content:
                        print(f"      ✅ TAKING found!")
                    print(f"      Preview: {content[:300]}...")

            path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_linkbtn_delta.txt"
            path.write_text(resp_text)
            print(f"\n  Saved to {path.name}")
        else:
            print(f"  Response preview: {resp_text[:500]}")
            path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_linkbtn_response.html"
            path.write_text(resp_text)
            print(f"\n  Saved to {path.name}")


async def test_full_post_with_all_fields():
    """
    Try submitting ALL form fields that a browser would send,
    including radio buttons, checkboxes, and navigator settings.
    Maybe the server needs these to produce results in the full page.
    """
    print("\n" + "=" * 60)
    print("Test: Full POST with all form fields")
    print("=" * 60)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # GET page
        get_resp = await client.get(BASE_URL, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        if get_resp.status_code != 200:
            return

        html = get_resp.text
        fields = extract_aspnet_fields(html)

        # Switch criteria
        switch_data = {
            **fields,
            "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
        }
        switch_resp = await client.post(BASE_URL, data=switch_data, headers=HEADERS)
        html2 = switch_resp.text
        fields2 = extract_aspnet_fields(html2)

        # Collect ALL form field names and their values
        # Extract all checkboxes that are checked
        checked = re.findall(r'name="([^"]*)"[^>]*checked="checked"', html2)
        print(f"  Checked fields: {checked}")

        # Extract radio button values
        radios = re.findall(r'<input[^>]*type="radio"[^>]*name="([^"]*)"[^>]*value="([^"]*)"[^>]*checked', html2)
        print(f"  Selected radios: {radios}")

        # Full search with ALL fields
        print("\n--- Submitting search with comprehensive form data ---")
        search_data = {
            **fields2,
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "ScriptManager1_HiddenField": "",
            "SearchCriteriaOffice1$DDL_OfficeName": "Recorded Land",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2024",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            "SearchFormEx1$ACSDropDownList_Towns": "115",
            "SearchFormEx1$ACSRadioButtonList_Search": "1",
            "SearchFormEx1$btnSearch": "Search",
        }

        # Add checked checkboxes
        for name in checked:
            if name not in search_data:
                search_data[name] = "on"

        # Add selected radios
        for name, value in radios:
            if name not in search_data:
                search_data[name] = value

        search_resp = await client.post(BASE_URL, data=search_data, headers=HEADERS)
        print(f"  Status: {search_resp.status_code}")
        print(f"  Response size: {len(search_resp.text)} chars")

        html3 = search_resp.text

        # Look for TAKING results
        taking_count = html3.count("TAKING")
        print(f"  TAKING occurrences: {taking_count}")

        if "limited to" in html3:
            print("  Found 'limited to' message")

        # Check all result-related UpdatePanels
        for panel in ["DocList1_UpdatePanel", "SearchList1_UpdatePanel", "NameList1_UpdatePanel",
                       "SearchInfo1_UpdatePanel1", "TabController1_UpdatePanel1",
                       "TabResultController1_UpdatePanel1"]:
            start = html3.find(f'id="{panel}"')
            if start > 0:
                # Find the next </div> that closes this panel
                depth = 0
                idx = start
                panel_start = html3.find(">", start) + 1
                for i in range(panel_start, min(panel_start + 50000, len(html3))):
                    if html3[i:i+4] == "<div":
                        depth += 1
                    elif html3[i:i+6] == "</div>":
                        if depth == 0:
                            panel_content = html3[panel_start:i].strip()
                            if len(panel_content) > 10:
                                print(f"  ✅ {panel}: {len(panel_content)} chars")
                                if "TAKING" in panel_content:
                                    print(f"     TAKING found!")
                                print(f"     Preview: {panel_content[:200]}...")
                            break
                        depth -= 1

        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_full_all_fields.html"
        path.write_text(html3)
        print(f"\n  Saved to {path.name}")


async def main():
    # Test 1: AJAX async postback
    await test_ajax_postback()

    # Test 2: Link button approach
    await test_ajax_with_link_button()

    # Test 3: Full POST with all fields
    await test_full_post_with_all_fields()

    print("\n" + "=" * 60)
    print("All tests complete")


if __name__ == "__main__":
    asyncio.run(main())
