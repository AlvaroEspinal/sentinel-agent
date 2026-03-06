import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://ecode360.com/LE0741", wait_until="networkidle")
        html = await page.content()
        await browser.close()
        
    soup = BeautifulSoup(html, 'html.parser')
    links = soup.find_all('a', class_='titleLink')
    for l in links:
        print(l.text.strip())

if __name__ == "__main__":
    asyncio.run(main())
