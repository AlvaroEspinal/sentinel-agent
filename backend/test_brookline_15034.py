import httpx
import json
import asyncio

async def run():
    resp = await httpx.AsyncClient().get('https://brooklinema.api.civicclerk.com/v1/Events/15034')
    with open('brookline_15034.json', 'w') as f:
        json.dump(resp.json(), f, indent=2)

asyncio.run(run())
