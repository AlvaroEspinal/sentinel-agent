#!/usr/bin/env python3
"""
Direct HTTP POST to Middlesex South Registry — Recorded Date Search.

BREAKTHROUGH: Python httpx bypasses Incapsula WAF directly (no FireCrawl needed!).
Previous attempt used "Document Search" which requires a document number.
This uses "Recorded Date Search" which allows date range + doc type + town filtering.

Flow:
1. GET page → extract __VIEWSTATE + cookies (bypasses Incapsula)
2. POST to switch criteria to "Recorded Land Recorded Date Search"
3. Inspect the resulting form to find correct field names
4. POST search with TAKING doc type + target town + date range
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
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.masslandrecords.com",
    "Referer": BASE_URL,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def extract_aspnet_fields(html: str) -> dict:
    """Extract __VIEWSTATE, __EVENTVALIDATION, __VIEWSTATEGENERATOR from HTML."""
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


def show_form_fields(html: str):
    """Print all form fields found in the HTML."""
    # Select elements
    selects = re.findall(r'<select[^>]*id="([^"]*)"[^>]*>', html)
    print(f"  Select elements: {selects}")

    # Input elements
    inputs = re.findall(r'<input[^>]*id="([^"]*)"[^>]*>', html)
    print(f"  Input elements: {inputs[:20]}")

    # All form field names (for POST data)
    names = re.findall(r'name="([^"]*)"', html)
    unique_names = sorted(set(names))
    print(f"  Form field names ({len(unique_names)}):")
    for name in unique_names:
        if name.startswith("__"):
            continue  # Skip ASP.NET hidden fields
        print(f"    - {name}")

    # Selected options
    selected = re.findall(r'<option\s+selected="selected"[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', html)
    print(f"  Currently selected options: {selected}")


async def test_recorded_date_search():
    """
    Main test: Use "Recorded Land Recorded Date Search" criteria.
    This should allow searching by date range + doc type + town
    without requiring a document number.
    """
    print("\n" + "=" * 60)
    print("Test: Recorded Date Search via direct httpx POST")
    print("=" * 60)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # === STEP 1: GET the page to establish session ===
        print("\n--- Step 1: GET page (bypass Incapsula WAF) ---")
        get_resp = await client.get(BASE_URL, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": HEADERS["Accept"],
        })
        print(f"  Status: {get_resp.status_code}")
        print(f"  Cookies: {list(get_resp.cookies.keys())}")

        if get_resp.status_code != 200:
            print(f"  ❌ Failed with status {get_resp.status_code}")
            if "Incapsula" in get_resp.text:
                print("  ❌ Blocked by Incapsula WAF")
            return

        html1 = get_resp.text
        fields1 = extract_aspnet_fields(html1)
        print(f"  __VIEWSTATE: {len(fields1['__VIEWSTATE'])} chars")
        print(f"  __EVENTVALIDATION: {len(fields1['__EVENTVALIDATION'])} chars")

        # Show initial criteria options
        criteria_options = re.findall(
            r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>',
            html1[:html1.find('</select>') + 20] if '</select>' in html1 else html1
        )
        print(f"  Criteria dropdown options:")
        for val, label in criteria_options[:10]:
            print(f"    value=\"{val}\" => label=\"{label}\"")

        # === STEP 2: POST to switch to Recorded Date Search ===
        print("\n--- Step 2: POST to switch criteria to 'Recorded Date Search' ---")
        switch_data = {
            **fields1,
            "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
        }

        switch_resp = await client.post(BASE_URL, data=switch_data, headers=HEADERS)
        print(f"  Status: {switch_resp.status_code}")
        print(f"  Response size: {len(switch_resp.text)} chars")

        if switch_resp.status_code != 200:
            print(f"  ❌ POST failed with status {switch_resp.status_code}")
            return

        html2 = switch_resp.text

        # Check what's selected
        crit_selected = re.findall(r'<option\s+selected="selected"[^>]*>([^<]*)</option>', html2)
        print(f"  Selected criteria after switch: {crit_selected}")

        if "Recorded Date Search" not in str(crit_selected):
            print("  ❌ Criteria did NOT switch to Recorded Date Search")
            # Save and inspect
            path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_rds_switch_fail.html"
            path.write_text(html2)
            print(f"  Saved to {path.name}")
            return

        print("  ✅ Criteria switched to Recorded Date Search!")

        # Show what form fields are available now
        print("\n  Form fields after criteria switch:")
        show_form_fields(html2)

        # Save the switched form for analysis
        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_rds_form.html"
        path.write_text(html2)
        print(f"\n  Saved switched form to {path.name}")

        # === STEP 3: POST search with TAKING + NEWTON ===
        print("\n--- Step 3: POST search with TAKING + NEWTON ---")
        fields2 = extract_aspnet_fields(html2)
        print(f"  __VIEWSTATE: {len(fields2['__VIEWSTATE'])} chars")

        search_data = {
            **fields2,
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "SearchCriteriaName1$DDL_SearchName": "Recorded Land Recorded Date Search",
            # Date range
            "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
            "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
            # TAKING doc type
            "SearchFormEx1$ACSDropDownList_DocumentType": "100103",
            # NEWTON town
            "SearchFormEx1$ACSDropDownList_Towns": "115",
            # Click search button
            "SearchFormEx1$btnSearch": "Search",
        }

        search_resp = await client.post(BASE_URL, data=search_data, headers=HEADERS)
        print(f"  Status: {search_resp.status_code}")
        print(f"  Response size: {len(search_resp.text)} chars")

        html3 = search_resp.text

        # Check for hits
        hits_match = re.search(r'(\d+)\s+hits', html3)
        if hits_match:
            h = int(hits_match.group(1))
            print(f"  Hits: {h}")
            if h > 0:
                print(f"  ✅✅✅ GOT {h} RESULTS! Direct POST with Recorded Date Search works!")
            else:
                print("  ❌ 0 hits")
        elif "0 hits" in html3:
            print("  ❌ 0 hits found in response")

        # Check for error messages
        error_match = re.search(r'id="MessageBoxCtrl1_ErrorLabel1"[^>]*>([^<]+)</span>', html3)
        if error_match:
            print(f"  ⚠️  Error message: {error_match.group(1)}")

        # Check for result rows (GR = grantor, GT = grantee)
        gr_count = len(re.findall(r'>GR\s*<', html3))
        gt_count = len(re.findall(r'>GT\s*<', html3))
        if gr_count > 0 or gt_count > 0:
            print(f"  ✅ Found result rows: GR={gr_count}, GT={gt_count}")

        # Look for TAKING in results
        if "TAKING" in html3:
            taking_count = html3.count("TAKING")
            print(f"  ✅ TAKING appears {taking_count} times in results!")

        # Save full results
        path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_rds_results.html"
        path.write_text(html3)
        print(f"  Saved results to {path.name}")

        # Show a snippet around any results
        for marker in ["hits", "TAKING", "GR", "SearchResults", "DocList"]:
            idx = html3.find(marker)
            if idx > 0:
                snippet = html3[max(0, idx-100):idx+300]
                print(f"\n  Snippet around '{marker}':")
                print(f"  ...{snippet[:400]}...")
                break


async def test_all_criteria_types():
    """
    Bonus: Try ALL criteria types to see which one has date + doc type + town fields.
    """
    print("\n" + "=" * 60)
    print("Bonus: Inspect all criteria types")
    print("=" * 60)

    criteria_values = [
        "Recorded Land Recorded Date Search",
        "Recorded Land Property Search",
        "Recorded Land Book Search",
    ]

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # GET page
        get_resp = await client.get(BASE_URL, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": HEADERS["Accept"],
        })
        if get_resp.status_code != 200:
            print("  ❌ Initial GET failed")
            return

        html = get_resp.text
        fields = extract_aspnet_fields(html)

        for criteria in criteria_values:
            print(f"\n--- Switching to: {criteria} ---")
            switch_data = {
                **fields,
                "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName",
                "__EVENTARGUMENT": "",
                "SearchCriteriaName1$DDL_SearchName": criteria,
            }

            resp = await client.post(BASE_URL, data=switch_data, headers=HEADERS)
            if resp.status_code == 200:
                html_resp = resp.text
                # Extract field names
                form_names = sorted(set(re.findall(r'name="([^"]*)"', html_resp)))
                search_fields = [n for n in form_names if "SearchForm" in n]
                print(f"  SearchForm fields: {search_fields}")

                # Check for specific field types
                has_doc_type = any("DocumentType" in n for n in search_fields)
                has_town = any("Towns" in n for n in search_fields)
                has_date_from = any("DateFrom" in n for n in search_fields)
                has_date_to = any("DateTo" in n for n in search_fields)
                has_btn_search = any("btnSearch" in n for n in search_fields)
                has_doc_num = any("DocumentNum" in n.lower() or "DocNumber" in n for n in search_fields)

                print(f"  DocType: {has_doc_type}, Town: {has_town}, DateFrom: {has_date_from}, DateTo: {has_date_to}")
                print(f"  Search button: {has_btn_search}, Doc Number field: {has_doc_num}")

                # Update fields for next iteration (use this response's viewstate)
                fields = extract_aspnet_fields(html_resp)
            else:
                print(f"  ❌ Status {resp.status_code}")


async def main():
    # Main test: Recorded Date Search
    await test_recorded_date_search()

    # Bonus: inspect all criteria types
    await test_all_criteria_types()


if __name__ == "__main__":
    asyncio.run(main())
