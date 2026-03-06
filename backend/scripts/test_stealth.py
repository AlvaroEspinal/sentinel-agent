import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def main():
    print("Testing Playwright stealth bypass...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800},
            extra_http_headers={"Referer": "https://www.google.com/"}
        )
        page = await context.new_page()
        
        from playwright_stealth import Stealth
        await Stealth().apply_stealth_async(page)
        
        url = "https://ecode360.com/NE0839"
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="domcontentloaded")
        
        # Wait a few seconds to let any Cloudflare JS run
        print("Waiting 5 seconds for anti-bot checks...")
        await page.wait_for_timeout(5000)
        
        html = await page.content()
        await browser.close()
        
    soup = BeautifulSoup(html, 'html.parser')
    
    body_text = soup.body.text if soup.body else ""
    if "Cloudflare" in body_text or "security service" in body_text:
        print("❌ Still blocked by Cloudflare:")
        print(body_text[:500])
    else:
        print("✅ Bypassed Cloudflare!")
        
        # Log all links containing 'zoning' text
        zlinks = soup.find_all(lambda tag: tag.name == 'a' and 'zoning' in tag.get_text(strip=True).lower())
        print(f"Found {len(zlinks)} links containing 'zoning':")
        for l in zlinks:
            print(f" - text: '{l.text.strip()}'")
            print(f"   href: {l.get('href', 'no href')}")
            print(f"   class: {l.get('class', 'no class')}")
            print(f"   id: {l.get('id', 'no id')}")
        
        with open("/tmp/zoning_bypassed_lexington.html", "w") as f:
            f.write(html)
        print("Wrote full HTML to /tmp/zoning_bypassed_lexington.html")

if __name__ == "__main__":
    asyncio.run(main())
