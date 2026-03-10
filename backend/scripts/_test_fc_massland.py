import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
load_dotenv(backend_dir.parent / ".env", override=True)

from scrapers.connectors.firecrawl_client import FirecrawlClient

async def main():
    print(f"Firecrawl Key: {bool(os.environ.get('FIRECRAWL_API_KEY'))}")
    fc = FirecrawlClient(api_key=os.environ.get("FIRECRAWL_API_KEY"))
    
    url = "https://www.masslandrecords.com/MiddlesexSouth/"
    actions = [
        {"type": "wait", "milliseconds": 5000},
        {"type": "executeJavascript", "script": "return document.title"}
    ]
    
    print("Trying Firecrawl scrape_with_actions on masslandrecords...")
    data = await fc.scrape_with_actions(
        url=url,
        actions=actions,
        formats=["markdown", "html"],
        only_main_content=False
    )
    
    if data:
        print("Success! Title:", data.get("markdown", "")[:200])
        html = data.get("html", "")
        if "Pardon Our Interruption" in html or "Incapsula" in html:
            print("BLOCKED BY WAF")
        else:
            print("BYPASSED WAF")
    else:
        print("Failed to scrape.")
        
    await fc.close()

if __name__ == "__main__": asyncio.run(main())
