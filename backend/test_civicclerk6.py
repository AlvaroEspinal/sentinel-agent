import asyncio
from scrapers.connectors.civicclerk_client import CivicClerkClient
async def test():
    client = CivicClerkClient("BrooklineMA")
    events = await client.list_events(top=500, min_year=2024)
    for event in events:
        m = event.get("minutesFile")
        if m and isinstance(m, dict) and m.get("minutesId") != 0:
            print("MINUTES DICT:", m)
            break
asyncio.run(test())
