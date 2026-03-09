"""
Scraper for Brookline, MA building permits via Accela Citizen Access.

Portal: https://aca-prod.accela.com/BROOKLINE
Portal type: Accela (ASP.NET WebForms + Angular, JS-driven)

Key findings from investigation:
- Date range and permit-number filters are IGNORED by the server-side form handler.
  Every search returns the same "most recent 100+" records.
- The portal caps display at 10 pages × 10 records = 100 records max.
- Pagination requires in-browser JS execution (ASP.NET __doPostBack with 
  session-scoped ViewState — cannot be replicated via plain HTTP POSTs).
- Solution: Use Firecrawl browser actions to scrape all 10 pages of results.
  The module tabs (Building, Conservation, Fire, BoardOfHealth, Planning,
  Historic, PublicWorks, Licenses, ClerkOffice, Zoning) each have their own
  100-record view.

Strategy:
1. For each module tab, load the page and click Search (no filters).
2. Paginate through all 10 pages using Firecrawl browser click actions.
3. Parse permit records from each page's HTML.
4. Deduplicate by record_number across all modules.
5. Save to backend/data_cache/permits/brookline_permits.json.

Note: This gives the most-recent ~1,000 records per module (10 modules × 100 each).
For historical data, the Accela portal would require authenticated API access.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

OUTPUT_PATH = REPO_ROOT / "backend" / "data_cache" / "permits" / "brookline_permits.json"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

ACCELA_BASE = "https://aca-prod.accela.com/BROOKLINE"

# All module tabs available in Brookline's Accela portal
MODULES = [
    ("Building",     "Building"),
    ("Conservation", "Conservation"),
    ("Fire",         "Fire"),
    ("BoardOfHealth","BoardOfHealth"),
    ("Planning",     "Planning"),
    ("Historic",     "Historic"),
    ("PublicWorks",  "PublicWorks"),
    ("Licenses",     "Licenses"),
    ("ClerkOffice",  "ClerkOffice"),
    ("Zoning",       "Zoning"),
]

# Firecrawl API config
FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v1"

# Total pages displayed = 10, 10 records/page = 100 per module
PAGES_PER_MODULE = 10


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def _parse_permit_rows(html: str, module: str) -> List[Dict[str, Any]]:
    """Parse all permit records from an Accela result page HTML."""
    permits: List[Dict[str, Any]] = []

    row_pattern = re.compile(
        r'<tr[^>]*ACA_TabRow_(?:Even|Odd)[^>]*>(.*?)</tr>',
        re.DOTALL | re.IGNORECASE,
    )

    for row_m in row_pattern.finditer(html):
        row_html = row_m.group(1)
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
        texts = [
            " ".join(re.sub(r"<[^>]+>", "", c).split()).strip()
            for c in cells
        ]

        if len(texts) < 8:
            continue

        # Extract record number from specific span
        rec_num_span = re.search(
            r'<span[^>]*lblPermitNumber[^>]*>([^<]+)</span>', row_html, re.IGNORECASE
        )
        record_number = rec_num_span.group(1).strip() if rec_num_span else texts[3]

        if not record_number:
            continue

        # Extract address from lblAddress or lblPermitAddress
        addr_span = re.search(
            r'<span[^>]*lblAddress[^>]*>([^<]+)</span>', row_html, re.IGNORECASE
        )
        address = addr_span.group(1).strip() if addr_span else texts[7]

        # Record type from lblType span
        type_span = re.search(
            r'<span[^>]*lblType[^>]*>([^<]+)</span>', row_html, re.IGNORECASE
        )
        record_type = type_span.group(1).strip() if type_span else texts[1]

        # Date from lblUpdatedTime span
        date_span = re.search(
            r'<span[^>]*lblUpdatedTime[^>]*>([^<]+)</span>', row_html, re.IGNORECASE
        )
        date_created = date_span.group(1).strip() if date_span else texts[6]

        # CapDetail URL for record
        cap_m = re.search(
            r'CapDetail\.aspx\?[^"\'<\s]+', row_html, re.IGNORECASE
        )
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
            "module": module,
            "cap_detail_url": f"{ACCELA_BASE}/{cap_url}" if cap_url else "",
        })

    return permits


def _get_page_count(html: str) -> int:
    m = re.search(r'PageCount="(\d+)"', html)
    return int(m.group(1)) if m else 1


def _get_showing(html: str) -> str:
    m = re.search(r'Showing\s+[\d,]+-[\d,]+\s+of\s+\S+', html)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# Firecrawl browser-action scraper
# ---------------------------------------------------------------------------

async def _scrape_module_page(
    client: Any,
    api_key: str,
    module: str,
    tab: str,
    page_num: int,
) -> Optional[str]:
    """
    Use Firecrawl to load an Accela module page and navigate to the given page number.

    page_num: 1-indexed. Page 1 = just click Search.
              Page N (2..10) = click Search, then click the Nth page link.
    
    The pager structure on page 1:
      TD[0]="< Prev" (span, disabled)
      TD[1]="1" (span, selected)
      TD[2..10]="2..10" (anchor links)
      TD[11]="..."
      TD[12]="Next >"
    
    So clicking the (N-1)th anchor in .aca_pagination_td gets us to page N.
    After going to page 2, the pager shows page 2 selected and links 3..10.
    To reach page N from page 2, we click the (N-2)th anchor.
    
    Simpler: build a sequence of actions:
    - For page 2: search, click 1st pagination anchor
    - For page 3: search, click 1st pagination anchor (page 2), 
                  then click 1st pagination anchor again (page 3 from page 2)
    - This doesn't work linearly. Instead, we click nth anchor:
      From page 1: anchors are [2,3,4,5,6,7,8,9,10,Next]
                   To get to page N: click anchor index (N-2)
    """
    page_url = f"{ACCELA_BASE}/Cap/CapHome.aspx?module={module}&TabName={tab}"

    actions: List[Dict[str, Any]] = [
        {"type": "wait", "milliseconds": 2000},
        {"type": "click", "selector": "#ctl00_PlaceHolderMain_btnNewSearch"},
        {"type": "wait", "milliseconds": 3000},
    ]

    # From page 1, TD structure (0-indexed): Prev, 1(sel), 2, 3, 4, ..., 10, ..., Next
    # Anchor links in .aca_pagination_td: index 0 = page 2, index 1 = page 3, ...
    # To reach page N directly from page 1:
    #   - click .aca_pagination_td:nth-child(N+1) a  (N+1 because 1-indexed CSS, TD[0]=Prev, TD[1]=1sel, TD[N]=page N link)
    #   This maps: page 2 → td:nth-child(3) a (TD[2])
    #              page 3 → td:nth-child(4) a (TD[3])
    #              page N → td:nth-child(N+1) a

    if page_num >= 2:
        # Click the page N link directly from page 1 results
        # CSS :nth-child is 1-indexed, so page N is at position N+1
        nth = page_num + 1
        actions.append({
            "type": "click",
            "selector": f".aca_pagination_td:nth-child({nth}) a",
        })
        actions.append({"type": "wait", "milliseconds": 2000})

    payload = {
        "url": page_url,
        "formats": ["html"],
        "actions": actions,
        "onlyMainContent": False,
    }

    try:
        resp = await client.post(
            f"{FIRECRAWL_BASE_URL}/scrape",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=180.0,
        )
        if resp.status_code != 200:
            print(f"    Firecrawl error: HTTP {resp.status_code}")
            return None
        d = resp.json()
        if not d.get("success"):
            print(f"    Firecrawl error: {d.get('error', 'unknown')}")
            return None
        return d["data"].get("html", "")
    except Exception as exc:
        print(f"    Firecrawl exception: {exc}")
        return None


async def scrape_module(
    api_key: str,
    module: str,
    tab: str,
    max_pages: int = PAGES_PER_MODULE,
) -> List[Dict[str, Any]]:
    """Scrape all pages of a single Accela module tab."""
    all_permits: List[Dict[str, Any]] = []
    seen_rec_nums: set = set()

    import httpx
    async with httpx.AsyncClient(timeout=180) as client:
        for page_num in range(1, max_pages + 1):
            print(f"      Page {page_num}/{max_pages}...", end=" ", flush=True)

            html = await _scrape_module_page(
                client=client,
                api_key=api_key,
                module=module,
                tab=tab,
                page_num=page_num,
            )

            if not html:
                print("FAILED")
                break

            showing = _get_showing(html)
            rows = _parse_permit_rows(html, module)

            new_count = 0
            for p in rows:
                uid = p["record_number"]
                if uid not in seen_rec_nums:
                    seen_rec_nums.add(uid)
                    all_permits.append(p)
                    new_count += 1

            print(f"{len(rows)} rows, {new_count} new ({showing})")

            # If no new records, we've probably looped or hit end
            if len(rows) == 0:
                print(f"      No rows on page {page_num}, stopping module.")
                break

            # Small delay between Firecrawl calls
            await asyncio.sleep(1.0)

    return all_permits


async def scrape_all_modules(
    api_key: str,
    modules: Optional[List[tuple]] = None,
    max_pages: int = PAGES_PER_MODULE,
) -> List[Dict[str, Any]]:
    """Scrape all Brookline Accela module tabs."""
    if modules is None:
        modules = MODULES

    all_permits: List[Dict[str, Any]] = []
    global_seen: set = set()

    for module, tab in modules:
        print(f"\n  Module: {module}")
        permits = await scrape_module(
            api_key=api_key,
            module=module,
            tab=tab,
            max_pages=max_pages,
        )

        for p in permits:
            uid = p["record_number"]
            if uid not in global_seen:
                global_seen.add(uid)
                all_permits.append(p)

        print(f"  Module {module}: {len(permits)} permits scraped ({len(all_permits)} total unique)")

    return all_permits


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape Brookline permits via Accela + Firecrawl browser actions"
    )
    parser.add_argument(
        "--modules",
        nargs="*",
        default=None,
        help="Module names to scrape (default: all). E.g.: --modules Building Fire",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=10,
        help="Max pages per module (default: 10, max: 10)",
    )
    args = parser.parse_args()

    # Load API key
    from dotenv import load_dotenv
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(str(env_path))

    api_key = os.getenv("FIRECRAWL_API_KEY", "")
    if not api_key:
        print("ERROR: FIRECRAWL_API_KEY not set in environment or .env")
        sys.exit(1)

    # Filter modules if specified
    modules_to_scrape = MODULES
    if args.modules:
        modules_to_scrape = [
            (m, t) for m, t in MODULES if m in args.modules
        ]
        if not modules_to_scrape:
            print(f"ERROR: No matching modules found for: {args.modules}")
            sys.exit(1)

    max_pages = min(args.pages, 10)

    print(f"Brookline Accela Permit Scraper")
    print(f"Modules: {[m for m, _ in modules_to_scrape]}")
    print(f"Pages per module: {max_pages}")
    print(f"Output: {OUTPUT_PATH}")
    print(f"Portal: {ACCELA_BASE}")
    print()

    t0 = time.time()
    permits = asyncio.run(
        scrape_all_modules(
            api_key=api_key,
            modules=modules_to_scrape,
            max_pages=max_pages,
        )
    )
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"Total permits scraped: {len(permits)}")
    print(f"Elapsed: {elapsed:.1f}s")

    if permits:
        print("\nSample records (first 5):")
        for p in permits[:5]:
            print(f"  {p['record_number']:25s} | {p['module']:15s} | {p['date_created']:12s} | {p['address'][:50]}")

    # Save output
    output = {
        "town": "brookline",
        "portal_type": "accela",
        "portal_url": ACCELA_BASE,
        "scrape_date": time.strftime("%Y-%m-%d"),
        "total_permits": len(permits),
        "modules_scraped": [m for m, _ in modules_to_scrape],
        "note": (
            "Accela portal caps display at 100 records per module (10 pages x 10/page). "
            "Results are the most recent activity. Date/permit-number filters are not "
            "enforced server-side in this portal instance."
        ),
        "permits": permits,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
