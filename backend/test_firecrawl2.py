import asyncio
import httpx
import sys
from pathlib import Path

# Add backend to path to import config
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import FIRECRAWL_API_KEY

async def test():
    if not FIRECRAWL_API_KEY:
        print("NO API KEY LOADED")
        return
        
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
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            }
        )
        print("Status:", resp.status_code)
        print("Text:", resp.text)

asyncio.run(test())
