import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from playwright.async_api import async_playwright, Page, BrowserContext

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = REPO_ROOT / "backend" / "data_cache" / "permits"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ACCELA_BASE = "https://aca-prod.accela.com/BROOKLINE"
MODULES = [
    "Building", "Conservation", "Fire", "BoardOfHealth", 
    "Planning", "Historic", "PublicWorks", "Licenses", 
    "ClerkOffice", "Zoning"
]

# Common Brookline/Accela prefixes
PREFIXES = [
    "BP", "PP", "EP", "GP", "SHT", "WIR", "TR", "TS", # Building
    "FP", "CIA", # Fire
    "BO", "BH", # Health
    "PB", "ZBA", # Planning/Zoning
    "PW", "SW", "EX", # Public Works
]

async def parse_page_records(page: Page) -> List[Dict[str, Any]]:
    """Parse the records currently displayed on the page."""
    html = await page.content()
    permits = []
    
    row_pattern = re.compile(r'<tr[^>]*ACA_TabRow_(?:Even|Odd)[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
    for row_m in row_pattern.finditer(html):
        row_html = row_m.group(1)
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
        texts = [" ".join(re.sub(r"<[^>]+>", "", c).split()).strip() for c in cells]
        
        if len(texts) < 8:
            continue
            
        rec_num_span = re.search(r'<span[^>]*lblPermitNumber[^>]*>([^<]+)</span>', row_html, re.IGNORECASE)
        record_number = rec_num_span.group(1).strip() if rec_num_span else texts[3]
        
        if not record_number:
            continue
            
        addr_span = re.search(r'<span[^>]*lblAddress[^>]*>([^<]+)</span>', row_html, re.IGNORECASE)
        address = addr_span.group(1).strip() if addr_span else texts[7]
        
        type_span = re.search(r'<span[^>]*lblType[^>]*>([^<]+)</span>', row_html, re.IGNORECASE)
        record_type = type_span.group(1).strip() if type_span else texts[1]
        
        date_span = re.search(r'<span[^>]*lblUpdatedTime[^>]*>([^<]+)</span>', row_html, re.IGNORECASE)
        date_created = date_span.group(1).strip() if date_span else texts[6]
        
        cap_m = re.search(r'CapDetail\.aspx\?[^"\'<\s]+', row_html, re.IGNORECASE)
        cap_url = cap_m.group(0) if cap_m else ""
        
        permits.append({
            "source": "accela_brookline",
            "record_number": record_number,
            "record_type": record_type,
            "status": texts[4] if len(texts) > 4 else "",
            "expiration_date": texts[5] if len(texts) > 5 else "",
            "date_created": date_created,
            "address": address,
            "town": "Brookline",
            "state": "MA",
            "cap_detail_url": f"{ACCELA_BASE}/{cap_url}" if cap_url else "",
        })
    return permits

async def extract_all_pages(page: Page) -> List[Dict[str, Any]]:
    """Extract records from all available pagination links on the current search results."""
    all_permits = []
    seen = set()
    
    page_num = 1
    while True:
        # Wait for table to be visible
        try:
            await page.wait_for_selector(".ACA_TabRow_Odd, .ACA_TabRow_Even", timeout=4000)
        except Exception:
            print("        [-] No table found or timed out waiting for table.")
            return all_permits # No results or timeout
            
        current_page_permits = await parse_page_records(page)
        new_count = 0
        for p in current_page_permits:
            if p["record_number"] not in seen:
                seen.add(p["record_number"])
                all_permits.append(p)
                new_count += 1
                
        print(f"        [Page {page_num}] Parsed {len(current_page_permits)} rows, {new_count} new.")
        if new_count == 0:
            break
            
        next_link = None
        pagination_links = await page.query_selector_all(".aca_pagination_td a")
        for link in pagination_links:
            text = await link.inner_text()
            if "Next" in text:
                next_link = link
                break
                
        if next_link:
            try:
                await next_link.click(timeout=5000, force=True)
                await page.wait_for_load_state("domcontentloaded", timeout=4000)
            except Exception as e:
                print(f"        [!] Error clicking Next: {e}")
                break
            await asyncio.sleep(2) # Extra buffer for ViewState rendering
            page_num += 1
        else:
            print("        [-] No 'Next >' link found, ending pagination.")
            break
            
    return all_permits

async def search_prefix(page: Page, module: str, prefix: str) -> List[Dict[str, Any]]:
    """Execute a search for a specific prefix on a specific module."""
    print(f"    Searching {module} for '{prefix}'...")
    url = f"{ACCELA_BASE}/Cap/CapHome.aspx?module={module}"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(1)
    
    # Wait for the search form
    try:
        await page.wait_for_selector("input[id$='txtGSPermitNumber']", timeout=10000)
    except Exception:
        print(f"      [!] Search form not found for {module}")
        return []

    # Clear and fill the record number
    await page.fill("input[id$='txtGSPermitNumber']", prefix)
    
    # Click search (the button ID usually ends with btnNewSearch)
    search_btn = await page.query_selector("a[id$='btnNewSearch']")
    if search_btn:
        await search_btn.click()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(2) # Wait for postback
    else:
        print(f"      [!] Search button not found for {module}")
        return []
        
    return await extract_all_pages(page)

async def recursive_search(page: Page, module: str, prefix: str, collected: List[Dict[str, Any]]) -> None:
    """Recursively search prefixes to avoid the 100-record cap."""
    results = await search_prefix(page, module, prefix)
    
    if len(results) >= 100:
        print(f"      [!] {prefix} hit the 100 limit ({len(results)} found). Splitting...")
        # Since permit numbers usually have digits after the year, append 0-9
        for i in range(10):
            new_prefix = f"{prefix}0{i}" if not prefix.endswith("-") else f"{prefix}0{i}"[-2:] # Adjust based on format
            # Typical format BP-2024-000227. If prefix is "BP-2024", we want "BP-2024-0", "BP-2024-1" etc.
            if not prefix.endswith("-") and len(prefix.split("-")) == 2:
                new_prefix = f"{prefix}-{i}"
            else:
                new_prefix = f"{prefix}{i}"
            await recursive_search(page, module, new_prefix, collected)
    else:
        print(f"      Found {len(results)} records for {prefix}.")
        collected.extend(results)

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", required=True, type=str, help="Year to scrape (e.g. 2024)")
    args = parser.parse_args()
    
    year = args.year
    output_file = OUTPUT_DIR / f"brookline_permits_{year}.json"
    
    print(f"Starting Brookline Accela Playwright Scraper for Year {year}")
    
    all_permits = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # Accept terms if present (Accela sometimes has a welcome disclaimer)
        await page.goto(ACCELA_BASE, wait_until="domcontentloaded")
        try:
            terms = await page.query_selector("input[id$='cbxAccept']")
            if terms:
                await terms.click()
                await page.click("a[id$='btnContinue']")
                await page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass

        for module in MODULES:
            print(f"\n--- Module: {module} ---")
            for pfx in PREFIXES:
                search_term = f"{pfx}-{year}"
                module_permits = []
                await recursive_search(page, module, search_term, module_permits)
                
                # Add module descriptor to results
                for permit in module_permits:
                    permit["module"] = module
                
                print(f"  Total for {search_term} in {module}: {len(module_permits)}")
                all_permits.extend(module_permits)
                
        await browser.close()
        
    print(f"\nScraping complete. Total unique records found: {len(all_permits)}")
    
    # Deduplicate universally
    unique_permits = {p["record_number"]: p for p in all_permits}.values()
    print(f"Total after universal deduplication: {len(unique_permits)}")
    
    results = {
        "town": "brookline",
        "portal_type": "accela",
        "scrape_date": time.strftime("%Y-%m-%d"),
        "year": year,
        "total_permits": len(unique_permits),
        "permits": list(unique_permits)
    }
    
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"Saved to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
