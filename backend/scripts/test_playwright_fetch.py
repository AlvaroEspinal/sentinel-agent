import asyncio
from playwright.async_api import async_playwright
import sys
from bs4 import BeautifulSoup

async def main():
    url = sys.argv[1]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        print(f"Loading {url}...")
        await page.goto(url, wait_until="networkidle")
        html = await page.content()
        await browser.close()
        
    soup = BeautifulSoup(html, 'html.parser')
    
    tables = soup.find_all('table')
    print(f"Found {len(tables)} tables")
    
    attachments = soup.find_all('a', class_='attachmentslink')
    print(f"Found {len(attachments)} attachment links:")
    for a in attachments:
        print(f" - {a.text}: {a.get('href', '')}")
        
    other_links = soup.select('a[href*="attachment"]')
    print(f"Found {len(other_links)} links with 'attachment' in href:")
    for a in other_links:
        print(f" - {a.text}: {a.get('href', '')}")

if __name__ == "__main__":
    asyncio.run(main())
