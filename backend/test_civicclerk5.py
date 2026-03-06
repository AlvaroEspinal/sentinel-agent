import asyncio
import httpx

async def test():
    async with httpx.AsyncClient() as client:
        # Get an event ID that is somewhat older, maybe has minutes
        resp = await client.get("https://BrooklineMA.api.civicclerk.com/v1/Events?$top=10&$skip=50&$orderby=eventDate desc", headers={"Accept": "application/json"})
        events = resp.json().get("value", [])
        
        for e in events:
            eid = e["id"]
            m_resp = await client.get(f"https://BrooklineMA.api.civicclerk.com/v1/Events/{eid}", headers={"Accept": "application/json"})
            m_data = m_resp.json()
            if m_data.get("minutesFile") and m_data["minutesFile"].get("minutesId") != 0:
                print(f"EVENT {eid} HAS MINUTES ID", m_data["minutesFile"])
            elif "publishedFiles" in m_data and m_data["publishedFiles"]:
                print(f"EVENT {eid} HAS PUBLISHED FILES", m_data["publishedFiles"])
asyncio.run(test())
