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
from scrapers.connectors.town_config import TARGET_TOWNS

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

async def main():
    print("Initializing Zoning Bylaw Scraper...")
    scraper = ZoningBylawScraper()
    
    # Create output directory
    out_dir = Path(__file__).parent.parent / "data" / "zoning"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Filter towns with ecode360 URLs
    target_towns = [t for t in TARGET_TOWNS.values() if t.zoning_bylaw_url and "ecode360.com" in t.zoning_bylaw_url.lower()]
    
    # Put Lexington first since we know its URL is a direct chapter link
    lex_town = next((t for t in target_towns if t.id == "lexington"), None)
    if lex_town:
        target_towns.remove(lex_town)
        target_towns.insert(0, lex_town)
        
    print(f"Found {len(target_towns)} towns with eCode360 zoning URLs.")
    
    for t in target_towns:
        print(f"\n--- Processing {t.name} ({t.id}) ---")
        url = t.zoning_bylaw_url
        print(f"URL: {url}")
        
        try:
            result = await scraper.extract_table_of_uses(t.name, url)
            
            if result:
                out_path = out_dir / f"{t.id}_zoning.json"
                with open(out_path, "w") as f:
                    json.dump(result, f, indent=2)
                print(f"✅ Successfully wrote {t.id}_zoning.json")
            else:
                print(f"❌ Failed to extract zoning for {t.name}")
        except Exception as e:
            print(f"❌ Error processing {t.name}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
