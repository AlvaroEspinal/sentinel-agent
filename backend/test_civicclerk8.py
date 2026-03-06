import asyncio
from scrapers.connectors.civicclerk_client import CivicClerkClient
async def test():
    client = CivicClerkClient("BrooklineMA")
    events = await client.list_events(top=500, min_year=2023)
    for event in events:
        pub = event.get("publishedFiles", [])
        for f in pub:
            name = (f.get("name") or f.get("fileName") or "").lower()
            if "minute" in name:
                print("MINUTES PUBLISHED RECORD:", f)
                break
asyncio.run(test())
