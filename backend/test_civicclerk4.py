import asyncio
from scrapers.connectors.civicclerk_client import CivicClerkClient
import json

async def test():
    client = CivicClerkClient("BrooklineMA")
    events = await client.list_events(top=50, min_year=2024)
    for e in events:
        if e.get("minutesFile") and isinstance(e["minutesFile"], dict):
            if e["minutesFile"].get("minutesId") != 0:
                print("MINUTES DICT WITH ID", e["minutesFile"])
        elif e.get("minutesFile"):
            print("MINUTES FILE", e.get("minutesFile"))
        
        if e.get("publishedFiles"):
            print("PUBLISHED", e.get("publishedFiles"))
            
        print("KEYS:", list(e.keys()))
        break
    await client.close()
asyncio.run(test())
