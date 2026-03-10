#!/usr/bin/env python3
"""Quick diagnostic: What does the initial page look like?"""
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
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        print(f"Title: {await page.title()}")
        print(f"URL: {page.url}")

        info = await page.evaluate("""() => {
            const vs = document.getElementById('__VIEWSTATE');
            const btns = [];
            document.querySelectorAll('input[type=button], input[type=submit], button').forEach(b => {
                btns.push({id: b.id, value: b.value || b.textContent, type: b.type});
            });
            const forms = [];
            document.querySelectorAll('form').forEach(f => forms.push({id: f.id, action: f.action}));
            const bodyText = document.body.innerText.substring(0, 1500);

            // Check for iframe
            const iframes = [];
            document.querySelectorAll('iframe').forEach(f => {
                iframes.push({id: f.id, src: f.src, name: f.name});
            });

            // Check all hidden inputs
            const hiddens = [];
            document.querySelectorAll('input[type=hidden]').forEach(h => {
                hiddens.push({id: h.id, name: h.name, valLen: (h.value||'').length});
            });

            return {
                hasViewState: !!vs,
                viewStateLen: vs ? vs.value.length : 0,
                buttons: btns,
                forms: forms,
                iframes: iframes,
                hiddens: hiddens,
                bodyPreview: bodyText
            };
        }""")

        print(f"\nHas __VIEWSTATE: {info['hasViewState']}")
        print(f"ViewState len: {info['viewStateLen']}")
        print(f"\nButtons ({len(info['buttons'])}):")
        for b in info['buttons']:
            print(f"  {b}")
        print(f"\nForms ({len(info['forms'])}):")
        for f in info['forms']:
            print(f"  {f}")
        print(f"\nIframes ({len(info['iframes'])}):")
        for f in info['iframes']:
            print(f"  {f}")
        print(f"\nHidden inputs ({len(info['hiddens'])}):")
        for h in info['hiddens']:
            print(f"  {h}")
        print(f"\nBody text preview:\n{info['bodyPreview'][:800]}")

        # Check if there's a disclaimer that needs accepting
        accept_btn = await page.query_selector('#MessageBoxCtrl1_OK')
        if accept_btn:
            visible = await accept_btn.is_visible()
            print(f"\n*** Found #MessageBoxCtrl1_OK, visible={visible} ***")
            if visible:
                await accept_btn.click()
                print("Clicked disclaimer OK")
                await page.wait_for_load_state("networkidle", timeout=15000)
                await page.wait_for_timeout(2000)

                # Re-check
                vs2 = await page.evaluate("() => { const v = document.getElementById('__VIEWSTATE'); return v ? v.value.length : 0; }")
                print(f"After dismiss — ViewState len: {vs2}")

        # Also try looking for any accept/OK/agree buttons
        for sel in ['#btnAccept', '#btnOK', 'input[value="Accept"]', 'input[value="OK"]',
                     'input[value="I Accept"]', 'input[value="Agree"]']:
            el = await page.query_selector(sel)
            if el:
                vis = await el.is_visible()
                print(f"\nFound {sel}, visible={vis}")

        await browser.close()

asyncio.run(main())
