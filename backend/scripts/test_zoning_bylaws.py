import asyncio
import os
import sys
import json
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from scrapers.connectors.zoning_bylaw_scraper import ZoningBylawScraper

async def main():
    print("Initializing Zoning Bylaw Scraper...")
    scraper = ZoningBylawScraper()
    
    # Lexington MA Zoning eCode360 URL - e.g. Chapter 135 Zoning
    # We use a URL to the specific Use Regulations article if possible,
    # or the general zoning code landing page.
    town = "Lexington"
    # This URL targets the "Zoning" chapter directly which contains PDF attachments:
    url = "https://ecode360.com/10529421" 
    
    print(f"Extracting Table of Uses for {town} from {url}...")
    result = await scraper.extract_table_of_uses(town, url)
    
    if result:
        print("\n--- EXTRACTION SUCCESS ---")
        print(json.dumps(result, indent=2))
    else:
        print("\n--- EXTRACTION FAILED ---")

if __name__ == "__main__":
    asyncio.run(main())
