import asyncio
import os
import httpx

async def test():
    api_key = os.getenv("FIRECRAWL_API_KEY", "")
    url = "https://www.newtonma.gov/government/planning/conservation-commission"
    payload = {
        "url": url,
        "limit": 20,
        "scrapeOptions": {
            "formats": ["markdown", "links"],
            "onlyMainContent": True
        }
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.firecrawl.dev/v1/crawl",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )
        print("Status:", resp.status_code)
        print("Text:", resp.text)

asyncio.run(test())
