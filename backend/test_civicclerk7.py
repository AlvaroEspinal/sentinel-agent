import asyncio
from scrapers.connectors.civicclerk_client import CivicClerkClient
async def test():
    client = CivicClerkClient("BrooklineMA")
    events = await client.list_events(top=500, min_year=2024)
    for event in events:
        if event.get("minutesFileUrl"):
            print("minutesFileUrl found: ", event["minutesFileUrl"])
            break
asyncio.run(test())
