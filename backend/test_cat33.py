import httpx
import json
import asyncio

async def run():
    url = "https://brooklinema.api.civicclerk.com/v1/Events?$orderby=eventDate+desc&$top=200&$filter=eventCategoryId+eq+33+and+year(eventDate)+ge+2024"
    resp = await httpx.AsyncClient().get(url)
    with open('brookline_cat33.json', 'w') as f:
        json.dump(resp.json(), f, indent=2)

asyncio.run(run())
