import asyncio
import json
import argparse
import sys
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

# Add the backend directory to python path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

load_dotenv()

from scrapers.connectors.tax_delinquency_scraper import TaxDelinquencyScraper
from scrapers.connectors.town_config import TARGET_TOWNS
from scrapers.connectors.firecrawl_client import FirecrawlClient

from duckduckgo_search import DDGS

async def find_tax_title_pdf_url(fc: FirecrawlClient, town_name: str) -> str:
    """
    Simulates the OSINT Sub-Agent. 
    Uses Firecrawl to scrape Google for the town's Tax Title PDF.
    """
    logger.info(f"[{town_name}] 🕵️ OSINT Agent searching for Tax Title PDF...")
    
    query = f"{town_name} MA 'tax title' OR 'notice of tax taking' filetype:pdf"
    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    
    try:
        # Firecrawl will parse the google search page and extract the links
        links = await fc.extract_links(search_url)
        if not links:
            # Let's try bing as fallback
            bing_url = f"https://www.bing.com/search?q={query.replace(' ', '+')}"
            links = await fc.extract_links(bing_url)
            
        if not links:
            logger.warning(f"[{town_name}] ❌ OSINT Agent found 0 links on search.")
            return ""
            
        town_slug = town_name.lower().replace(" ", "")
        
        for link in links:
            # Ensure it's a real PDF link, not a google redirect
            if link.startswith("/url?q="):
                link = link.split("/url?q=")[1].split("&")[0]
                import urllib.parse
                link = urllib.parse.unquote(link)
                
            if link.endswith(".pdf") and (".ma.us" in link or ".gov" in link or town_slug in link):
                logger.info(f"[{town_name}] ✅ OSINT Agent found PDF: {link}")
                return link
                
        logger.warning(f"[{town_name}] ❌ OSINT Agent found links, but no direct PDFs.")
        return ""
            
    except Exception as e:
        logger.error(f"[{town_name}] OSINT Agent failed: {e}")
        return ""

async def process_town(town_id: str, town_name: str, scraper: TaxDelinquencyScraper, fc: FirecrawlClient, out_dir: Path):
    pdf_url = await find_tax_title_pdf_url(fc, town_name)
    if not pdf_url:
        logger.warning(f"[{town_name}] Skipping - no PDF found.")
        return False
        
    logger.info(f"[{town_name}] 🤖 Extraction Agent processing {pdf_url}")
    records = await scraper.extract_from_url(pdf_url)
    
    if records:
        out_file = out_dir / f"{town_id}_tax_titles.json"
        out_file.write_text(json.dumps(records, indent=2))
        logger.info(f"[{town_name}] ✨ Extracted {len(records)} records -> {out_file.name}")
        return True
    else:
        logger.error(f"[{town_name}] ❌ Extraction Agent found 0 records.")
        return False

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    scraper = TaxDelinquencyScraper()
    fc = FirecrawlClient()
    
    out_dir = Path(backend_dir) / "data" / "tax_delinquency"
    out_dir.mkdir(parents=True, exist_ok=True)

    towns = list(TARGET_TOWNS.values())[:args.limit]
    logger.info(f"🚀 Starting multi-agent pipeline for {len(towns)} towns")
    
    success_count = 0
    for town in towns:
        print(f"\n{'='*60}\n📍 Processing {town.name} ({town.id})\n{'='*60}")
        success = await process_town(town.id, town.name, scraper, fc, out_dir)
        if success:
            success_count += 1
            
        await asyncio.sleep(2)
        
    logger.info(f"🏁 Batch complete. Successfully extracted data for {success_count}/{len(towns)} towns.")
    
    await scraper.close()
    await fc.close()

if __name__ == "__main__":
    asyncio.run(main())
