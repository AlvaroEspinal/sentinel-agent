import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://ecode360.com/WE0479", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        html = await page.content()
        await browser.close()
        
    soup = BeautifulSoup(html, 'html.parser')
    print("Body text snippet:")
    print(soup.body.text[:1000] if soup.body else "No body")
    
    with open("weston_raw.html", "w") as f:
        f.write(html)

if __name__ == "__main__":
    asyncio.run(main())
