#!/usr/bin/env python3
"""Quick diagnostic: Check if page content loads after waiting."""
import asyncio
from playwright.async_api import async_playwright

URL = "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )

        # Track requests
        requests_log = []
        page.on("request", lambda req: requests_log.append(f"{req.method} {req.url[:100]}"))

        print("1. Navigating...")
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        print(f"   Title: {await page.title()}")
        print(f"   Requests so far: {len(requests_log)}")

        # Check raw HTML size
        html = await page.content()
        print(f"   HTML size: {len(html)} chars")

        # Check for __VIEWSTATE in raw HTML (maybe it's in a script block)
        import re
        vs_matches = re.findall(r'__VIEWSTATE.*?value="([^"]{0,20})"', html)
        print(f"   __VIEWSTATE in HTML: {vs_matches}")

        # Check if there's encrypted viewstate or other ASP.NET fields
        vs_encrypted = '__VIEWSTATEENCRYPTED' in html
        ev = '__EVENTVALIDATION' in html
        print(f"   Has __VIEWSTATEENCRYPTED: {vs_encrypted}")
        print(f"   Has __EVENTVALIDATION: {ev}")

        # Wait a bit more and check again
        print("\n2. Waiting 5s for dynamic content...")
        await page.wait_for_timeout(5000)

        info2 = await page.evaluate("""() => {
            const vs = document.getElementById('__VIEWSTATE');
            const ev = document.getElementById('__EVENTVALIDATION');
            const selects = [];
            document.querySelectorAll('select').forEach(s => {
                selects.push({id: s.id, optCount: s.options.length});
            });
            const inputs = [];
            document.querySelectorAll('input').forEach(i => {
                if (i.type !== 'hidden') {
                    inputs.push({id: i.id, type: i.type});
                }
            });
            return {
                vsLen: vs ? vs.value.length : -1,
                evLen: ev ? ev.value.length : -1,
                selects: selects,
                inputs: inputs,
                bodyTextLen: document.body.innerText.length,
                bodyText: document.body.innerText.substring(0, 500),
            };
        }""")
        print(f"   ViewState len: {info2['vsLen']}")
        print(f"   EventValidation len: {info2['evLen']}")
        print(f"   Selects: {info2['selects']}")
        print(f"   Non-hidden inputs: {info2['inputs'][:10]}")
        print(f"   Body text length: {info2['bodyTextLen']}")
        print(f"   Body text: {info2['bodyText'][:300]}")

        # Wait even more
        print("\n3. Waiting 10 more seconds...")
        await page.wait_for_timeout(10000)

        info3 = await page.evaluate("""() => {
            const vs = document.getElementById('__VIEWSTATE');
            return {
                vsLen: vs ? vs.value.length : -1,
                selectCount: document.querySelectorAll('select').length,
                inputCount: document.querySelectorAll('input').length,
                bodyLen: document.body.innerText.length,
            };
        }""")
        print(f"   ViewState len: {info3['vsLen']}")
        print(f"   Selects: {info3['selectCount']}, Inputs: {info3['inputCount']}")
        print(f"   Body text len: {info3['bodyLen']}")

        # Check the first 2000 chars of HTML for clues
        print(f"\n4. HTML first 2000 chars:")
        print(html[:2000])

        # Check network requests
        print(f"\n5. Total requests: {len(requests_log)}")
        for r in requests_log[:20]:
            print(f"   {r}")

        await browser.close()

asyncio.run(main())
