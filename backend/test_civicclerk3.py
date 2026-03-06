import asyncio
from scrapers.connectors.civicclerk_client import CivicClerkClient
async def test():
    client = CivicClerkClient("BrooklineMA")
    events = await client.list_events(top=1000, min_year=2023)
    for event in events:
        pub = event.get("publishedFiles", [])
        if pub:
            for f in pub:
                print("PUBLISHED FILE:", f)
    await client.close()
asyncio.run(test())
