#!/usr/bin/env python3
"""
Strategy: Direct HTTP POST to Middlesex South Registry.

FireCrawl can't interact with <select> elements on this site.
Instead:
1. Use FireCrawl to load the page (bypasses Incapsula WAF, gets cookies)
2. Extract __VIEWSTATE, __EVENTVALIDATION, and cookies
3. Use Python httpx to POST the form directly with all required fields

The ASP.NET WebForms page needs:
  - __VIEWSTATE (huge encoded string)
  - __VIEWSTATEENCRYPTED (empty)
  - __EVENTVALIDATION (encoded string)
  - Form fields with proper name attributes
"""

import asyncio
import re
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir.parent / ".env", override=True)

from scrapers.connectors.firecrawl_client import FirecrawlClient

FC = FirecrawlClient
BASE_URL = "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"


async def test_extract_viewstate():
    """
    Step 1: Load the page with FireCrawl to get __VIEWSTATE and other hidden fields.
    """
    print("\n=== STEP 1: Extract __VIEWSTATE from page ===")
    fc = FirecrawlClient()

    actions = [
        FC.action_wait(3000),
        FC.action_scrape(),
    ]

    result = await fc.scrape_with_actions(BASE_URL, actions, formats=["rawHtml"])
    if not result:
        print("  ❌ FireCrawl returned None")
        return None

    html = result.get("rawHtml", "") or result.get("html", "")
    print(f"  Got {len(html)} chars")

    # Extract hidden fields
    viewstate = re.search(r'id="__VIEWSTATE"\s+value="([^"]*)"', html)
    viewstate_enc = re.search(r'id="__VIEWSTATEENCRYPTED"\s+value="([^"]*)"', html)
    eventval = re.search(r'id="__EVENTVALIDATION"\s+value="([^"]*)"', html)
    viewstate_gen = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]*)"', html)

    print(f"  __VIEWSTATE: {'found' if viewstate else 'NOT FOUND'} ({len(viewstate.group(1)) if viewstate else 0} chars)")
    print(f"  __VIEWSTATEENCRYPTED: {'found' if viewstate_enc else 'NOT FOUND'}")
    print(f"  __EVENTVALIDATION: {'found' if eventval else 'NOT FOUND'} ({len(eventval.group(1)) if eventval else 0} chars)")
    print(f"  __VIEWSTATEGENERATOR: {'found' if viewstate_gen else 'NOT FOUND'}")

    # Extract all form input names
    inputs = re.findall(r'name="([^"]*)"', html)
    unique_names = sorted(set(inputs))
    print(f"\n  Form field names ({len(unique_names)}):")
    for name in unique_names:
        print(f"    - {name}")

    # Save for analysis
    path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_viewstate.html"
    path.write_text(html)
    print(f"\n  Saved to {path.name}")

    return {
        "__VIEWSTATE": viewstate.group(1) if viewstate else "",
        "__VIEWSTATEENCRYPTED": viewstate_enc.group(1) if viewstate_enc else "",
        "__EVENTVALIDATION": eventval.group(1) if eventval else "",
        "__VIEWSTATEGENERATOR": viewstate_gen.group(1) if viewstate_gen else "",
    }


async def test_direct_post(form_data: dict):
    """
    Step 2: Try posting directly with httpx.
    First attempt: simple POST with viewstate to switch criteria.
    """
    import httpx

    print("\n=== STEP 2: Direct POST to switch criteria ===")

    # Build form data for criteria switch (ASP.NET __doPostBack pattern)
    post_data = {
        "__VIEWSTATE": form_data["__VIEWSTATE"],
        "__VIEWSTATEENCRYPTED": form_data["__VIEWSTATEENCRYPTED"],
        "__EVENTVALIDATION": form_data["__EVENTVALIDATION"],
        "__VIEWSTATEGENERATOR": form_data["__VIEWSTATEGENERATOR"],
        "__EVENTTARGET": "SearchCriteriaName1$DDL_SearchName",
        "__EVENTARGUMENT": "",
        "SearchCriteriaName1$DDL_SearchName": "Recorded Land Document Search",
        # Keep default values for other fields
        "SearchFormEx1$ACSTextBox_DateFrom": "1/1/1900",
        "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
        "SearchFormEx1$ACSDropDownList_DocumentType": "",
        "SearchFormEx1$ACSDropDownList_Towns": "",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.masslandrecords.com",
        "Referer": BASE_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            # First, GET the page to get cookies (Incapsula needs this)
            print("  Getting cookies from initial page load...")
            get_resp = await client.get(BASE_URL, headers={
                "User-Agent": headers["User-Agent"],
                "Accept": headers["Accept"],
            })
            print(f"  GET status: {get_resp.status_code}")
            print(f"  Cookies: {list(get_resp.cookies.keys())}")

            if get_resp.status_code != 200:
                # Incapsula might block us
                if "Incapsula" in get_resp.text or "_Incapsula" in get_resp.text:
                    print("  ❌ Blocked by Incapsula WAF (as expected)")
                    return False
                print(f"  ❌ Unexpected status: {get_resp.status_code}")
                print(f"  Body preview: {get_resp.text[:500]}")
                return False

            # Extract fresh __VIEWSTATE from the GET response
            html = get_resp.text
            vs = re.search(r'id="__VIEWSTATE"\s+value="([^"]*)"', html)
            ev = re.search(r'id="__EVENTVALIDATION"\s+value="([^"]*)"', html)
            vsg = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]*)"', html)

            if vs:
                post_data["__VIEWSTATE"] = vs.group(1)
                print(f"  Fresh __VIEWSTATE: {len(vs.group(1))} chars")
            if ev:
                post_data["__EVENTVALIDATION"] = ev.group(1)
            if vsg:
                post_data["__VIEWSTATEGENERATOR"] = vsg.group(1)

            # Now POST to switch criteria
            print("  Posting criteria switch...")
            post_resp = await client.post(
                BASE_URL,
                data=post_data,
                headers=headers,
            )
            print(f"  POST status: {post_resp.status_code}")
            print(f"  Response size: {len(post_resp.text)} chars")

            if post_resp.status_code == 200:
                html2 = post_resp.text

                # Check if criteria switched
                crit_selected = re.findall(r'<option\s+selected="selected"[^>]*>([^<]*)</option>', html2)
                print(f"  Selected after POST: {crit_selected}")

                # Check for Document Search specific fields
                if "Document Search" in str(crit_selected):
                    print("  ✅ Criteria switched to Document Search!")

                    # Now we need to POST again with doc type and town
                    vs2 = re.search(r'id="__VIEWSTATE"\s+value="([^"]*)"', html2)
                    ev2 = re.search(r'id="__EVENTVALIDATION"\s+value="([^"]*)"', html2)
                    vsg2 = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]*)"', html2)

                    search_data = {
                        "__VIEWSTATE": vs2.group(1) if vs2 else "",
                        "__VIEWSTATEENCRYPTED": "",
                        "__EVENTVALIDATION": ev2.group(1) if ev2 else "",
                        "__VIEWSTATEGENERATOR": vsg2.group(1) if vsg2 else "",
                        "__EVENTTARGET": "",
                        "__EVENTARGUMENT": "",
                        "SearchCriteriaName1$DDL_SearchName": "Recorded Land Document Search",
                        "SearchFormEx1$ACSDropDownList_DocumentType": "100103",  # TAKING
                        "SearchFormEx1$ACSDropDownList_Towns": "115",  # NEWTON
                        "SearchFormEx1$ACSTextBox_DateFrom": "1/1/2020",
                        "SearchFormEx1$ACSTextBox_DateTo": "3/9/2026",
                        "SearchFormEx1$btnSearch": "Search",
                    }

                    print("  Posting search with TAKING + NEWTON...")
                    search_resp = await client.post(
                        BASE_URL,
                        data=search_data,
                        headers=headers,
                    )
                    print(f"  Search POST status: {search_resp.status_code}")
                    print(f"  Search response size: {len(search_resp.text)} chars")

                    html3 = search_resp.text
                    hits = re.search(r'(\d+)\s+hits', html3)
                    if hits:
                        h = int(hits.group(1))
                        print(f"  Hits: {h}")
                        if h > 0:
                            print(f"  ✅✅✅ GOT {h} RESULTS! Direct POST works!")
                    elif "0 hits" in html3:
                        print("  ❌ 0 hits")

                    path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_direct_post_results.html"
                    path.write_text(html3)
                    print(f"  Saved results to {path.name}")
                else:
                    print("  ❌ Criteria did not switch")

                path = backend_dir / "data_cache" / "tax_delinquency" / "_mx_direct_post_switch.html"
                path.write_text(html2)
                print(f"  Saved switch response to {path.name}")
                return True
            else:
                print(f"  ❌ POST failed with status {post_resp.status_code}")
                return False

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("=" * 60)
    print("Testing direct HTTP POST approach")
    print("=" * 60)

    # Step 1: Get viewstate from FireCrawl
    form_data = await test_extract_viewstate()
    if not form_data:
        print("\nFailed to get viewstate. Trying direct GET instead...")
        # Fallback: try direct GET (might be blocked by WAF)
        form_data = {"__VIEWSTATE": "", "__VIEWSTATEENCRYPTED": "",
                     "__EVENTVALIDATION": "", "__VIEWSTATEGENERATOR": ""}

    # Step 2: Direct POST
    await test_direct_post(form_data)

    print("\n" + "=" * 60)
    print("Tests complete")


if __name__ == "__main__":
    asyncio.run(main())
