#!/usr/bin/env python3
"""
Diagnostic: Inspect the criteria dropdown on masslandrecords.com/MiddlesexSouth.

Goal: Find the exact option labels/values so we can fix select_option() call.
Also check if a popup is blocking interaction.
"""

import asyncio
import json
from playwright.async_api import async_playwright

URL = "https://www.masslandrecords.com/MiddlesexSouth/D/Default.aspx"


async def main():
    print("=" * 60)
    print("Diagnostic: Inspect Middlesex South dropdown options")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )

        print("\n1. Navigating to page...")
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        print(f"   Title: {await page.title()}")

        # Check for popups/modals
        print("\n2. Checking for popups/modals...")
        popup_info = await page.evaluate("""() => {
            const results = [];
            // Check for modal dialogs
            const modals = document.querySelectorAll('[class*="modal"], [class*="popup"], [class*="dialog"], [role="dialog"]');
            modals.forEach(m => {
                const style = window.getComputedStyle(m);
                results.push({
                    tag: m.tagName,
                    id: m.id,
                    className: m.className,
                    display: style.display,
                    visibility: style.visibility,
                    text: m.textContent.substring(0, 200)
                });
            });
            // Check for overlay divs
            const overlays = document.querySelectorAll('[class*="overlay"], [class*="backdrop"]');
            overlays.forEach(o => {
                const style = window.getComputedStyle(o);
                results.push({
                    tag: o.tagName,
                    id: o.id,
                    className: o.className,
                    display: style.display,
                    visibility: style.visibility,
                    text: o.textContent.substring(0, 100)
                });
            });
            // Check for any visible fixed/absolute positioned elements that might be blocking
            const allEls = document.querySelectorAll('*');
            for (const el of allEls) {
                const style = window.getComputedStyle(el);
                if ((style.position === 'fixed' || style.position === 'absolute') &&
                    style.display !== 'none' && style.visibility !== 'hidden' &&
                    parseInt(style.zIndex) > 100) {
                    results.push({
                        tag: el.tagName,
                        id: el.id,
                        className: el.className.toString().substring(0, 100),
                        zIndex: style.zIndex,
                        text: el.textContent.substring(0, 200)
                    });
                }
            }
            return results;
        }""")
        if popup_info:
            print(f"   Found {len(popup_info)} potential overlays/popups:")
            for info in popup_info:
                print(f"   - {info}")
        else:
            print("   No popups/modals found")

        # Look for specific disclaimer/welcome buttons
        print("\n3. Looking for dismiss/accept/OK buttons...")
        buttons_info = await page.evaluate("""() => {
            const results = [];
            const buttons = document.querySelectorAll('button, input[type="button"], input[type="submit"], a[class*="btn"]');
            buttons.forEach(b => {
                const text = (b.textContent || b.value || '').trim();
                if (text && text.length < 100) {
                    const style = window.getComputedStyle(b);
                    results.push({
                        tag: b.tagName,
                        id: b.id,
                        text: text,
                        display: style.display,
                        visibility: style.visibility
                    });
                }
            });
            return results;
        }""")
        print(f"   Found {len(buttons_info)} buttons:")
        for b in buttons_info:
            print(f"   - [{b['tag']}] id={b['id']} text={b['text']!r} display={b['display']}")

        # Find and inspect the criteria dropdown
        print("\n4. Inspecting criteria dropdown...")
        dropdown_info = await page.evaluate("""() => {
            // Try multiple selectors
            const selectors = [
                'select[id="SearchCriteriaName1_DDL_SearchName"]',
                'select[name="SearchCriteriaName1$DDL_SearchName"]',
                'select[id*="SearchCriteria"]',
                'select[id*="DDL_Search"]',
            ];

            for (const sel of selectors) {
                const select = document.querySelector(sel);
                if (select) {
                    const options = [];
                    for (const opt of select.options) {
                        options.push({
                            value: opt.value,
                            text: opt.text,
                            label: opt.label,
                            selected: opt.selected,
                            index: opt.index
                        });
                    }
                    const style = window.getComputedStyle(select);
                    return {
                        found: true,
                        selector: sel,
                        id: select.id,
                        name: select.name,
                        display: style.display,
                        visibility: style.visibility,
                        disabled: select.disabled,
                        optionCount: select.options.length,
                        selectedIndex: select.selectedIndex,
                        options: options
                    };
                }
            }

            // If not found, list ALL select elements
            const allSelects = document.querySelectorAll('select');
            const selectList = [];
            allSelects.forEach(s => {
                selectList.push({
                    id: s.id,
                    name: s.name,
                    optionCount: s.options.length
                });
            });
            return { found: false, allSelects: selectList };
        }""")

        if dropdown_info.get("found"):
            print(f"   ✅ Found dropdown: id={dropdown_info['id']}, name={dropdown_info['name']}")
            print(f"   Display: {dropdown_info['display']}, Disabled: {dropdown_info['disabled']}")
            print(f"   Selected index: {dropdown_info['selectedIndex']}")
            print(f"   Options ({dropdown_info['optionCount']}):")
            for opt in dropdown_info["options"]:
                marker = " <<<" if opt["selected"] else ""
                print(f"     [{opt['index']}] value={opt['value']!r} text={opt['text']!r} label={opt['label']!r}{marker}")
        else:
            print("   ❌ Criteria dropdown NOT FOUND with known selectors")
            print(f"   All select elements on page: {dropdown_info.get('allSelects', [])}")

        # Try dismissing any popup first
        print("\n5. Attempting to dismiss popups...")
        dismiss_selectors = [
            'input[value="Accept"]',
            'input[value="OK"]',
            'input[value="I Accept"]',
            'button:has-text("Accept")',
            'button:has-text("OK")',
            'button:has-text("Close")',
            'a:has-text("Accept")',
            '#btnDisclaimerAccept',
            '#btnAccept',
            '#MessageBoxCtrl1_OK',
        ]
        for sel in dismiss_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    visible = await el.is_visible()
                    print(f"   Found {sel}: visible={visible}")
                    if visible:
                        await el.click()
                        print(f"   ✅ Clicked {sel}")
                        await page.wait_for_timeout(2000)
                        break
            except Exception as e:
                pass

        # Re-check dropdown after popup dismissal
        print("\n6. Re-inspecting dropdown after popup dismissal...")
        dropdown_info2 = await page.evaluate("""() => {
            const select = document.querySelector('select[id="SearchCriteriaName1_DDL_SearchName"]') ||
                           document.querySelector('select[name="SearchCriteriaName1$DDL_SearchName"]');
            if (!select) return { found: false };

            const options = [];
            for (const opt of select.options) {
                options.push({
                    value: opt.value,
                    text: opt.text,
                    label: opt.label,
                    selected: opt.selected,
                    index: opt.index
                });
            }
            return {
                found: true,
                id: select.id,
                optionCount: select.options.length,
                options: options
            };
        }""")
        if dropdown_info2.get("found"):
            print(f"   Options ({dropdown_info2['optionCount']}):")
            for opt in dropdown_info2["options"]:
                marker = " <<<" if opt["selected"] else ""
                print(f"     [{opt['index']}] value={opt['value']!r} text={opt['text']!r}{marker}")
        else:
            print("   ❌ Still not found")

        # Try select_option with different approaches
        print("\n7. Testing select_option approaches...")
        select_el = await page.query_selector('select[id="SearchCriteriaName1_DDL_SearchName"]')
        if not select_el:
            select_el = await page.query_selector('select[name="SearchCriteriaName1$DDL_SearchName"]')

        if select_el:
            # Get the actual option texts for matching
            options_texts = await page.evaluate("""(sel) => {
                const s = document.querySelector(sel);
                if (!s) return [];
                return Array.from(s.options).map(o => ({v: o.value, t: o.text, l: o.label}));
            }""", 'select[id="SearchCriteriaName1_DDL_SearchName"]')

            # Find the right option
            target_options = [o for o in options_texts if "Recorded" in o["t"] and "Date" in o["t"]]
            print(f"   Options matching 'Recorded*Date': {target_options}")

            if target_options:
                target = target_options[0]
                print(f"   Trying select_option(value={target['v']!r})...")
                try:
                    await select_el.select_option(value=target["v"])
                    print("   ✅ select_option(value=...) succeeded!")
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"   ❌ select_option(value=...) failed: {e}")

                    print(f"   Trying select_option(label={target['t']!r})...")
                    try:
                        await select_el.select_option(label=target["t"])
                        print("   ✅ select_option(label=...) succeeded!")
                    except Exception as e2:
                        print(f"   ❌ select_option(label=...) failed: {e2}")

            # Check what happened after selection
            print("\n8. Checking page state after selection...")
            await page.wait_for_timeout(3000)

            # Check if form fields changed
            form_fields = await page.evaluate("""() => {
                const fields = [];
                const inputs = document.querySelectorAll('input[id*="SearchForm"], select[id*="SearchForm"]');
                inputs.forEach(el => {
                    fields.push({
                        tag: el.tagName,
                        id: el.id,
                        type: el.type || 'select',
                        visible: window.getComputedStyle(el).display !== 'none'
                    });
                });
                return fields;
            }""")
            print(f"   Search form fields: {len(form_fields)}")
            for f in form_fields:
                if f["visible"]:
                    print(f"   - {f['id']} ({f['type']})")
        else:
            print("   ❌ Could not find dropdown element")

        await browser.close()
        print("\n" + "=" * 60)
        print("Diagnostic complete!")


if __name__ == "__main__":
    asyncio.run(main())
