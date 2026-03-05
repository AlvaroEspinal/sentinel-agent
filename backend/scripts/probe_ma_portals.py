#!/usr/bin/env python3
"""Probe ViewpointCloud, PermitEyes, and SimpliCITY for MA towns.

Tries common slug patterns to discover which MA municipalities
have active permit portals on these platforms.
"""
import asyncio
import httpx
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# All 351 MA municipalities - we'll try slug patterns for each
# Focus on cities/towns most likely to have online portals
MA_TOWNS = [
    # Already configured (skip these)
    # "newton", "wellesley", "weston", "brookline", "needham",
    # "dover", "sherborn", "natick", "wayland", "lincoln",
    # "concord", "lexington",

    # Large cities
    "boston", "worcester", "springfield", "cambridge", "lowell",
    "brockton", "new-bedford", "quincy", "lynn", "fall-river",
    "lawrence", "somerville", "framingham", "haverhill", "waltham",
    "malden", "medford", "taunton", "chicopee", "weymouth",
    "revere", "peabody", "methuen", "barnstable", "pittsfield",
    "attleboro", "arlington", "everett", "salem", "westfield",
    "leominster", "fitchburg", "beverly", "holyoke", "marlborough",
    "woburn", "chelsea", "braintree", "gloucester", "watertown",

    # Affluent suburbs & commuter towns
    "andover", "bedford", "belmont", "boxford", "burlington",
    "canton", "carlisle", "cohasset", "dedham", "duxbury",
    "easton", "foxborough", "franklin", "hamilton", "hanover",
    "hingham", "holbrook", "holliston", "hopkinton", "hudson",
    "kingston", "lynnfield", "mansfield", "marblehead", "marshfield",
    "medfield", "medway", "melrose", "middleborough", "milford",
    "millis", "milton", "nahant", "norfolk", "north-andover",
    "north-reading", "northborough", "norwell", "norwood",
    "pembroke", "plainville", "plymouth", "reading", "rockland",
    "scituate", "sharon", "shrewsbury", "southborough", "stoneham",
    "stoughton", "sudbury", "swampscott", "tewksbury", "wakefield",
    "wellesley", "westborough", "westford", "weston", "westwood",
    "whitman", "wilmington", "winchester", "winthrop", "wrentham",

    # Western MA
    "amherst", "northampton", "greenfield", "easthampton",
    "longmeadow", "west-springfield", "agawam", "southwick",
    "wilbraham", "ludlow", "hadley", "south-hadley",

    # Cape & Islands
    "falmouth", "sandwich", "bourne", "mashpee", "yarmouth",
    "dennis", "harwich", "chatham", "brewster", "orleans",
    "eastham", "wellfleet", "truro", "provincetown",
    "nantucket", "oak-bluffs", "tisbury", "edgartown",

    # More suburbs
    "acton", "ashland", "ayer", "billerica", "bolton",
    "boxborough", "chelmsford", "dracut", "dunstable", "grafton",
    "groton", "harvard", "lancaster", "littleton", "lunenburg",
    "maynard", "northbridge", "pepperell", "shirley", "stow",
    "townsend", "upton", "uxbridge", "westminster",
    "abington", "avon", "bridgewater", "carver", "dartmouth",
    "east-bridgewater", "freetown", "halifax", "hanson", "lakeville",
    "marion", "mattapoisett", "middleborough", "norwell",
    "rochester", "wareham", "west-bridgewater",

    # North Shore
    "amesbury", "boxford", "danvers", "essex", "georgetown",
    "groveland", "hamilton", "ipswich", "manchester",
    "merrimac", "middleton", "newbury", "newburyport",
    "rowley", "salisbury", "topsfield", "wenham", "west-newbury",

    # More MetroWest
    "ashburnham", "auburn", "barre", "berlin", "blackstone",
    "boylston", "brookfield", "charlton", "clinton", "douglas",
    "dudley", "gardner", "hardwick", "holden", "hopedale",
    "leicester", "mendon", "millbury", "millville", "new-braintree",
    "north-brookfield", "oakham", "oxford", "paxton", "princeton",
    "rutland", "southbridge", "spencer", "sterling", "sturbridge",
    "sutton", "templeton", "warren", "webster", "west-boylston",
    "west-brookfield", "winchendon",
]

ALREADY_CONFIGURED = {
    "newton", "wellesley", "weston", "brookline", "needham",
    "dover", "sherborn", "natick", "wayland", "lincoln",
    "concord", "lexington",
}

# Remove duplicates and already-configured
MA_TOWNS = list(set(t for t in MA_TOWNS if t.replace("-", "") not in ALREADY_CONFIGURED
                     and t not in ALREADY_CONFIGURED))


async def probe_viewpointcloud(town_slug: str, client: httpx.AsyncClient) -> dict | None:
    """Check if a VPC community exists and has permit data."""
    # Try {town}ma pattern
    slug = f"{town_slug.replace('-', '')}ma"
    url = f"https://api2.viewpointcloud.com/v2/{slug}/record_types"
    try:
        resp = await client.get(url, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if data:
                return {"slug": slug, "record_types": len(data), "url": url}
    except Exception:
        pass
    return None


async def probe_permiteyes(town_slug: str, client: httpx.AsyncClient) -> dict | None:
    """Check if a PermitEyes town portal exists."""
    slug = town_slug.replace("-", "")
    url = f"https://permiteyes.us/{slug}/publicview.php"
    try:
        resp = await client.get(url, timeout=10.0, follow_redirects=True)
        if resp.status_code == 200 and "DataTables" in resp.text:
            return {"slug": slug, "url": url}
    except Exception:
        pass
    return None


async def probe_simplicity(town_slug: str, client: httpx.AsyncClient) -> dict | None:
    """Check if a SimpliCITY/MapsOnline portal exists."""
    slug = f"{town_slug.replace('-', '')}ma"
    url = f"https://www.mapsonline.net/{slug}/public_permit_reports.html.php"
    try:
        resp = await client.get(url, timeout=10.0, follow_redirects=True)
        if resp.status_code == 200 and ("pf-ng" in resp.text or "permit" in resp.text.lower()):
            return {"slug": slug, "url": url}
    except Exception:
        pass
    return None


async def main():
    print(f"Probing {len(MA_TOWNS)} MA towns for permit portals...")
    print("=" * 60)

    vpc_found = []
    pe_found = []
    sc_found = []

    sem = asyncio.Semaphore(20)  # Max concurrent connections

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (permit-research)"},
        follow_redirects=True,
    ) as client:

        async def probe_town(town: str):
            async with sem:
                vpc = await probe_viewpointcloud(town, client)
                if vpc:
                    vpc_found.append((town, vpc))
                    print(f"  VPC: {town:20s} -> {vpc['slug']} ({vpc['record_types']} types)")

                pe = await probe_permiteyes(town, client)
                if pe:
                    pe_found.append((town, pe))
                    print(f"  PE:  {town:20s} -> {pe['slug']}")

                sc = await probe_simplicity(town, client)
                if sc:
                    sc_found.append((town, sc))
                    print(f"  SC:  {town:20s} -> {sc['slug']}")

        tasks = [asyncio.create_task(probe_town(t)) for t in MA_TOWNS]
        await asyncio.gather(*tasks)

    print("\n" + "=" * 60)
    print(f"ViewpointCloud: {len(vpc_found)} towns found")
    for town, info in sorted(vpc_found):
        print(f"  {town}: slug={info['slug']}, types={info['record_types']}")

    print(f"\nPermitEyes: {len(pe_found)} towns found")
    for town, info in sorted(pe_found):
        print(f"  {town}: slug={info['slug']}")

    print(f"\nSimplicity: {len(sc_found)} towns found")
    for town, info in sorted(sc_found):
        print(f"  {town}: slug={info['slug']}")

    print(f"\nTotal new towns with portals: {len(set(t for t,_ in vpc_found + pe_found + sc_found))}")


if __name__ == "__main__":
    asyncio.run(main())
