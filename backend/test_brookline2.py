import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrapers.connectors.civicclerk_client import CivicClerkClient

async def main():
    client = CivicClerkClient("brooklinema")
    
    events = await client.list_events()
    print(f"Found {len(events)} events for Brookline")
    
    found_with_files = None
    for event in events:
        if event.get("publishedFiles"):
            found_with_files = event
            break
            
    if found_with_files:
        print("Event with files:", found_with_files.get("eventName"))
        with open("brookline_event_with_files.json", "w") as f:
            json.dump(found_with_files, f, indent=2)
    else:
        print("No events found with publishedFiles")
            
    await client.close()

asyncio.run(main())
