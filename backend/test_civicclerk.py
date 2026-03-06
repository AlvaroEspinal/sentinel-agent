import asyncio
from scrapers.connectors.civicclerk_client import CivicClerkClient
async def test():
    client = CivicClerkClient("BrooklineMA")
    events = await client.list_events(top=20)
    meetings = client.extract_meetings_from_events(events)
    print(meetings)
    await client.close()
asyncio.run(test())
