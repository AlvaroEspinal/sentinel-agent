import asyncio
import re
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://aca-prod.accela.com/BROOKLINE/Cap/CapHome.aspx?module=Building", wait_until="networkidle")
        
        # Accept terms if asked
        try:
            terms = await page.query_selector("input[id$='cbxAccept']")
            if terms:
                await terms.click()
                await page.click("a[id$='btnContinue']")
                await page.wait_for_load_state("networkidle")
        except Exception:
            pass
            
        print("Dumping inputs...")
        inputs = await page.locator("input, select, textarea, button, a").all()
        for i, el in enumerate(inputs):
            tag_name = await el.evaluate("node => node.tagName")
            el_id = await el.get_attribute("id")
            name = await el.get_attribute("name")
            t_type = await el.get_attribute("type")
            title = await el.get_attribute("title")
            val = await el.get_attribute("value")
            
            # Print if it has interesting keywords like record, txt, search, btn
            combined = f"{el_id} {name} {title} {val}".lower()
            if any(k in combined for k in ['record', 'permit', 'txt', 'search', 'btn', 'button', 'alt']):
                print(f"[{tag_name}] id={el_id} name={name} type={t_type} title={title} value={val}")
                
        await browser.close()

if __name__ == "__main__": asyncio.run(main())
