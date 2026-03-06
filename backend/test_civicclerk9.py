import asyncio
from scrapers.connectors.civicclerk_client import CivicClerkClient
async def test():
    client = CivicClerkClient("BrooklineMA")
    events = await client.list_events(top=500, min_year=2024)
    names = set()
    for event in events:
        pub = event.get("publishedFiles", [])
        for f in pub:
            name = (f.get("name") or f.get("fileName") or "").lower()
            names.add(name)
    print("ALL PUBLISHED FILE NAMES:")
    for n in sorted(list(names)):
        print(f" - {n}")
asyncio.run(test())
