import asyncio
from scrapers.connectors.civicclerk_client import CivicClerkClient
async def test():
    client = CivicClerkClient("BrooklineMA")
    events = await client.list_events(top=500, min_year=2024)
    for event in events:
        if event.get("minutesFile") and isinstance(event["minutesFile"], dict) and event["minutesFile"].get("minutesId", 0) != 0:
            print("FOUND MINUTES FILE DICT:", event["minutesFile"])
            break
        if event.get("minutesFileUrl"):
            print("FOUND MINUTES FILE URL:", event["minutesFileUrl"])
            break
        pub = event.get("publishedFiles", [])
        if pub:
            for f in pub:
                name = (f.get("name") or f.get("fileName") or "").lower()
                if "minute" in name:
                    print("FOUND PUBLISHED MINUTES:", f)
                    break
    await client.close()
asyncio.run(test())
