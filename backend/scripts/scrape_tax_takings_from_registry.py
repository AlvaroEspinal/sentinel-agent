#!/usr/bin/env python3
"""
Scrape Tax Taking records from Massachusetts Registry of Deeds.

Uses Playwright headless browser for Norfolk County ALIS (JavaScript SPA)
and httpx for Middlesex South Registry (ASP.NET WebForms).

Norfolk County ALIS (norfolkresearch.org/ALIS/)
  - JavaScript SPA: requires headless browser rendering
  - Entry Date search: W9ABR=T.T. (Tax Taking), W9TOWN=CODE
  - Results: 3 records per page with pagination via doVarButton2('search','LR13N')
  - Fields: Book-Page, Recording Date, Instrument#, Type, Town, Grantors, Grantee, References
  - Property address NOT in index (only in scanned document images)

Middlesex South (masslandrecords.com/MiddlesexSouth/)
  - ASP.NET WebForms with ViewState tokens
  - Document type: "TAKING"
  - GR/GT row pairs per record

Output: JSON files per town in data_cache/tax_delinquency/{town}_tax_takings.json
"""

import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict, field
from urllib.parse import urlencode, quote

# Setup path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir.parent / ".env", override=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tax_takings_scraper")


# ─── Data Models ───────────────────────────────────────────────────────────

@dataclass
class TaxTakingRecord:
    """A single tax taking record from the Registry of Deeds."""
    town: str
    address: str
    file_date: str
    book: str
    page: str
    grantor: str          # Property owner(s) — the party being taxed
    grantee: str          # The town/city (e.g., "BROOKLINE TOWN OF")
    doc_type: str         # "Tax Taking"
    property_description: str
    registry: str         # "norfolk" or "middlesex_south"
    source_url: str
    instrument_number: str = ""
    references: list = field(default_factory=list)


# ─── Norfolk County Registry (ALIS) ───────────────────────────────────────

NORFOLK_TOWNS = {
    "brookline": {"code": "BRKL", "name": "Brookline"},
    "needham":   {"code": "NDHM", "name": "Needham"},
    "wellesley": {"code": "WELL", "name": "Wellesley"},
    "dover":     {"code": "DOVE", "name": "Dover"},
}

NORFOLK_BASE_URL = "https://www.norfolkresearch.org/ALIS/WW400R.HTM"


def build_norfolk_search_url(town_code: str, from_date: str, to_date: str) -> str:
    """
    Build the Entry Date search URL for Norfolk ALIS.

    Parameters use MMDDYYYY format (no slashes).
    WSIQTP=LR13AP triggers search execution and results display.
    WSKYCD=E means Entry Date search mode.
    WSHTNM=WW413R00 is the first results page template.
    W9ABR=T.T. is the document type abbreviation for Tax Taking.
    """
    params = {
        "W9FDTA": from_date,      # From Date: MMDDYYYY
        "W9TDTA": to_date,        # To Date: MMDDYYYY
        "W9ABR": "T.T.",          # Doc Type: Tax Taking
        "W9TOWN": town_code,      # Town code
        "W9FC$": "",              # From Consideration (empty = no filter)
        "W9TC$": "",              # To Consideration
        "WSHTNM": "WW413R00",    # HTML template (1st results page)
        "WSIQTP": "LR13AP",      # Page type: Entry Date results
        "WSKYCD": "E",            # Search key: Entry Date
        "WSWVER": "2",            # WebServer version
    }
    return f"{NORFOLK_BASE_URL}?{urlencode(params)}"


def parse_norfolk_results_text(text: str, town_id: str) -> list[TaxTakingRecord]:
    """
    Parse tax taking records from Norfolk ALIS results page text content.

    Actual rendered format (multi-line per record):
        Bk-Pg:39537-198                 Recorded: 06-21-2021 @ 3:50:18pm  Inst #: 80579  Chg: Y  Vfy: N  Sec: N
        Pages in document: 1
        Grp: 1
        Type: TAX TAKING
        Desc: SEE RECORD
        Town: BROOKLINE
        Gtor:	AWERBUCH-FRIEDLANDER, TAMARA E (&AL) (Gtor)
        Gtor:	KANAMORI, DANIEL F (&AL) (Gtor)
        Gtee:	BROOKLINE TOWN OF (Gtee)
        Ref By: 03-14-2022 CERTIFICATE In book: 40383-508
    """
    records = []

    # Split text into record blocks using the Bk-Pg header pattern
    # Actual format: "Bk-Pg:39537-198                 Recorded: 06-21-2021 @ 3:50:18pm  Inst #: 80579"
    header_pattern = re.compile(
        r'Bk-Pg:(\d+)-(\d+)\s+'
        r'Recorded:\s*(\d{2}-\d{2}-\d{4})\s+@\s+[\d:]+[ap]m\s+'
        r'Inst\s*#:\s*(\d+)',
        re.IGNORECASE
    )

    # Find all record header positions
    headers = list(header_pattern.finditer(text))
    if not headers:
        return records

    for i, match in enumerate(headers):
        book = match.group(1)
        page = match.group(2)
        rec_date = match.group(3)  # MM-DD-YYYY
        inst_num = match.group(4)

        # Get the text block between this header and the next
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]

        # Parse Type from separate line (e.g., "Type: TAX TAKING")
        type_match = re.search(r'Type:\s*(.+?)$', block, re.MULTILINE)
        doc_type = type_match.group(1).strip() if type_match else "TAX TAKING"

        # Parse Town from separate line (e.g., "Town: BROOKLINE")
        town_match = re.search(r'Town:\s*(\S+)', block)
        town = town_match.group(1).strip() if town_match else town_id.upper()

        # Parse grantors — format: "Gtor:\tNAME (&AL) (Gtor)"
        # Remove the trailing "(Gtor)" marker and any "(&AL)" references
        gtor_pattern = re.compile(r'Gtor:\s*(.+?)(?:\s*\(Gtor\))?\s*$', re.MULTILINE)
        grantors_raw = [m.group(1).strip() for m in gtor_pattern.finditer(block)]
        grantors = []
        for g in grantors_raw:
            # Clean up: remove trailing (Gtor), (&AL) markers
            g = re.sub(r'\s*\(Gtor\)\s*$', '', g)
            g = re.sub(r'\s*\(&AL\)\s*$', '', g)
            g = g.strip()
            if g:
                grantors.append(g)

        # Parse grantee — format: "Gtee:\tBROOKLINE TOWN OF (Gtee)"
        gtee_pattern = re.compile(r'Gtee:\s*(.+?)(?:\s*\(Gtee\))?\s*$', re.MULTILINE)
        gtee_match = gtee_pattern.search(block)
        grantee = ""
        if gtee_match:
            grantee = gtee_match.group(1).strip()
            grantee = re.sub(r'\s*\(Gtee\)\s*$', '', grantee).strip()

        # Parse references — format: "Ref By: 03-14-2022 CERTIFICATE In book: 40383-508"
        ref_pattern = re.compile(
            r'Ref By:\s*(\d{2}-\d{2}-\d{4})\s+(\w+)\s+In book:\s*(\d+-\d+)',
            re.IGNORECASE
        )
        references = [
            {"date": m.group(1), "type": m.group(2).strip(), "book_page": m.group(3)}
            for m in ref_pattern.finditer(block)
        ]

        # Convert date from MM-DD-YYYY to MM/DD/YYYY for consistency
        try:
            file_date = rec_date.replace("-", "/")
        except Exception:
            file_date = rec_date

        # Combine multiple grantors with " + "
        grantor_str = " + ".join(grantors) if grantors else ""

        record = TaxTakingRecord(
            town=town_id,
            address="",  # Not available in ALIS index — only in scanned images
            file_date=file_date,
            book=book,
            page=page,
            grantor=grantor_str,
            grantee=grantee,
            doc_type="Tax Taking",
            property_description=f"Book {book}, Page {page}",
            registry="norfolk",
            source_url=NORFOLK_BASE_URL,
            instrument_number=inst_num,
            references=references,
        )
        records.append(record)

    return records


async def scrape_norfolk_town(
    page,  # playwright Page object
    town_id: str,
    town_info: dict,
    from_date: str = "01012020",
) -> list[TaxTakingRecord]:
    """
    Scrape all tax taking records for a Norfolk County town using Playwright.

    Uses the Entry Date search approach:
    1. Navigate to the search results URL (bypasses the form)
    2. Parse the rendered page text
    3. Handle pagination by calling doVarButton2('search','LR13N')
    """
    town_code = town_info["code"]
    town_name = town_info["name"]

    # Build today's date in MMDDYYYY format
    to_date = datetime.now().strftime("%m%d%Y")

    search_url = build_norfolk_search_url(town_code, from_date, to_date)
    logger.info(f"[Norfolk/{town_name}] Navigating to Entry Date search results...")

    try:
        await page.goto(search_url, wait_until="networkidle", timeout=30000)
    except Exception as e:
        logger.warning(f"[Norfolk/{town_name}] Navigation timeout (normal for ALIS): {e}")

    # Wait for JavaScript to render the results
    await page.wait_for_timeout(5000)

    # Check if page is still loading ("Your request is running") and wait longer
    for retry in range(6):  # Wait up to 30 more seconds
        try:
            body_check = await page.inner_text("body")
            if "request is running" in body_check.lower() or "do not click" in body_check.lower():
                logger.info(f"[Norfolk/{town_name}] Page still loading, waiting... (attempt {retry+1}/6)")
                await page.wait_for_timeout(5000)
            else:
                break
        except Exception:
            break

    all_records = []
    page_num = 1
    max_pages = 50  # Safety limit

    while page_num <= max_pages:
        # Get the full text content of the page
        try:
            body_text = await page.inner_text("body")
        except Exception as e:
            logger.error(f"[Norfolk/{town_name}] Failed to get page text: {e}")
            break

        # Check for "No documents found" or similar messages
        if ("no documents" in body_text.lower() or "0 documents" in body_text.lower()
                or "without finding a match" in body_text.lower()):
            logger.info(f"[Norfolk/{town_name}] No tax taking records found (confirmed by registry)")
            break

        # Parse records from this page
        page_records = parse_norfolk_results_text(body_text, town_id)

        if not page_records:
            if page_num == 1:
                # First page with no records — might be genuinely empty or parsing failed
                logger.warning(f"[Norfolk/{town_name}] No records parsed from page 1")
                # Save raw text for debugging
                debug_path = backend_dir / "data_cache" / "tax_delinquency" / f"_norfolk_{town_id}_debug.txt"
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                debug_path.write_text(body_text[:5000])
                logger.info(f"[Norfolk/{town_name}] Debug text saved to {debug_path.name}")
            break

        all_records.extend(page_records)
        logger.info(f"[Norfolk/{town_name}] Page {page_num}: {len(page_records)} records (total: {len(all_records)})")

        # Check for "Next" link — it's a JavaScript link, not a regular <a> tag
        # The link text is "Next" and calls: javascript:doVarButton2('search','LR13N')
        has_next = False
        try:
            # Look for a clickable "Next" link
            next_elem = await page.query_selector('a:has-text("Next")')
            if next_elem:
                # Verify it's actually a link (not just text)
                href = await next_elem.get_attribute("href")
                if href and "LR13N" in href:
                    has_next = True
                elif href and "doVarButton2" in (href or ""):
                    has_next = True
                else:
                    # Try clicking anyway — might be a JS link
                    onclick = await next_elem.get_attribute("onclick")
                    if onclick:
                        has_next = True
        except Exception:
            pass

        if not has_next:
            # Alternative: try calling the pagination function directly
            try:
                # Check if doVarButton2 is defined and "Next" text exists as a link
                check = await page.evaluate("""() => {
                    const links = document.querySelectorAll('a');
                    for (const link of links) {
                        if (link.textContent.trim() === 'Next') {
                            return { found: true, href: link.href || '', onclick: link.getAttribute('onclick') || '' };
                        }
                    }
                    return { found: false };
                }""")
                if check.get("found"):
                    has_next = True
            except Exception:
                pass

        if not has_next:
            logger.info(f"[Norfolk/{town_name}] No more pages (reached page {page_num})")
            break

        # Navigate to next page
        try:
            # Method 1: Click the "Next" link element
            await page.click('a:has-text("Next")')
            await page.wait_for_timeout(3000)
            page_num += 1
        except Exception as e:
            # Method 2: Call the JavaScript function directly
            try:
                await page.evaluate("doVarButton2('search','LR13N')")
                await page.wait_for_timeout(3000)
                page_num += 1
            except Exception as e2:
                logger.warning(f"[Norfolk/{town_name}] Pagination failed: {e2}")
                break

    if all_records:
        logger.info(f"[Norfolk/{town_name}] ✅ Total: {len(all_records)} tax taking records")
    else:
        logger.info(f"[Norfolk/{town_name}] ⚠️ No records found")

    return all_records


# ─── Middlesex South Registry (20/20 Perfect Vision) ──────────────────────
#
# ARCHITECTURE NOTES (discovered via interactive browser testing 2026-03):
#
# URL: /MiddlesexSouth/D/Default.aspx (NOT /LandRecords/SearchLandRecords.aspx)
# System: ASP.NET WebForms with ~50 AJAX UpdatePanels
# Key insight: Result data is rendered by JavaScript in AJAX UpdatePanels.
#   It is NOT in the initial HTML. Only a real browser (Playwright) can extract it.
#   httpx/requests/FireCrawl all fail to get result data.
#
# Search flow:
#   1. Navigate to /D/Default.aspx
#   2. Dismiss welcome popup overlay (click or wait)
#   3. Switch criteria dropdown to "Recorded Land Recorded Date Search"
#   4. Wait for ASP.NET postback (form reloads with date/type/town fields)
#   5. Click "Advanced" link to reveal Document Types and Towns listboxes
#   6. Set date range, select TAKING doc type (value "100103"), select town
#   7. Click Search
#   8. Switch to "View 100" for 100 records per page
#   9. Extract records using element ID pattern:
#      DocList1_GridView_Document_ctl{NN}_ButtonRow_{Column}_{rowIdx}
#      where NN is zero-padded starting at 02, rowIdx = NN - 2
#   10. Optionally drill into each record for detail (address, parties)
#   11. Handle pagination for >100 records
#
# Record detail drill-down postback:
#   __doPostBack('DocList1$GridView_Document$ctl{NN}$ButtonRow_File Date_{rowIdx}','')
#   Detail panel: DocDetails1_UpdatePanel1
#   Contains: Doc #, File Date, Type, Book/Page, Street, Grantor/Grantee list

MIDDLESEX_TOWNS = {
    "newton":    {"search_name": "NEWTON",    "name": "Newton"},
    "natick":    {"search_name": "NATICK",    "name": "Natick"},
    "wayland":   {"search_name": "WAYLAND",   "name": "Wayland"},
    "lexington": {"search_name": "LEXINGTON", "name": "Lexington"},
    "weston":    {"search_name": "WESTON",    "name": "Weston"},
    "concord":   {"search_name": "CONCORD",   "name": "Concord"},
    "lincoln":   {"search_name": "LINCOLN",   "name": "Lincoln"},
    "sherborn":  {"search_name": "SHERBORN",  "name": "Sherborn"},
}

MIDDLESEX_BASE_URL = "https://www.masslandrecords.com/MiddlesexSouth"
MIDDLESEX_SEARCH_URL = f"{MIDDLESEX_BASE_URL}/D/Default.aspx"


async def _mx_dismiss_popup(page) -> None:
    """Dismiss the welcome/disclaimer popup if present."""
    try:
        # The popup has a close button or "I Accept" button
        for selector in [
            'input[value="Accept"]',
            'input[value="I Accept"]',
            'button:has-text("Accept")',
            'button:has-text("Close")',
            '.popup-close',
            '#btnAccept',
            'input[type="submit"][value*="Accept"]',
        ]:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(1000)
                logger.debug("  Dismissed popup")
                return

        # Try clicking overlay to dismiss
        overlay = await page.query_selector('.modal-backdrop, .popup-overlay')
        if overlay:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
    except Exception:
        pass


async def _mx_switch_to_recorded_date_search(page) -> bool:
    """Switch the search criteria dropdown to 'Recorded Land Recorded Date Search'."""
    try:
        criteria_select = await page.query_selector(
            'select[id="SearchCriteriaName1_DDL_SearchName"]'
        )
        if not criteria_select:
            criteria_select = await page.query_selector(
                'select[name="SearchCriteriaName1$DDL_SearchName"]'
            )
        if not criteria_select:
            logger.warning("  Could not find criteria dropdown")
            return False

        # The option VALUE is "Recorded Land Recorded Date Search"
        # but the displayed LABEL is just "Recorded Date Search"
        await criteria_select.select_option(value="Recorded Land Recorded Date Search")
        # Wait for ASP.NET postback to reload the form
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.wait_for_timeout(2000)
        return True
    except Exception as e:
        logger.warning(f"  Failed to switch criteria: {e}")
        return False


async def _mx_click_advanced(page) -> bool:
    """Click the 'Advanced' link to reveal Document Types and Towns listboxes."""
    try:
        advanced = await page.query_selector('#SearchFormEx1_BtnAdvanced')
        if not advanced:
            advanced = await page.query_selector('input[value="Advanced"]')
        if not advanced:
            advanced = await page.query_selector('a:has-text("Advanced")')
        if not advanced:
            # Already in advanced mode?
            doc_type_list = await page.query_selector(
                'select[name="SearchFormEx1$ACSDropDownList_DocumentType"]'
            )
            if doc_type_list:
                return True  # Already visible
            logger.warning("  Could not find Advanced link")
            return False

        await advanced.click()
        await page.wait_for_timeout(2000)
        return True
    except Exception as e:
        logger.warning(f"  Failed to click Advanced: {e}")
        return False


async def _mx_fill_search_form(
    page, town_name: str, from_date: str, to_date: str
) -> bool:
    """Fill in the Recorded Date Search form with date range, TAKING type, and town."""
    try:
        # Set date range
        date_from = await page.query_selector(
            'input[name="SearchFormEx1$ACSTextBox_DateFrom"]'
        )
        if date_from:
            await date_from.triple_click()
            await date_from.fill(from_date)

        date_to = await page.query_selector(
            'input[name="SearchFormEx1$ACSTextBox_DateTo"]'
        )
        if date_to:
            await date_to.triple_click()
            await date_to.fill(to_date)

        # Select TAKING document type (value="100103")
        doc_type_select = await page.query_selector(
            'select[name="SearchFormEx1$ACSDropDownList_DocumentType"]'
        )
        if doc_type_select:
            try:
                await doc_type_select.select_option(value="100103")
            except Exception:
                try:
                    await doc_type_select.select_option(label="TAKING")
                except Exception:
                    logger.warning("  Could not select TAKING doc type")
                    return False
        else:
            logger.warning("  Document type dropdown not found")
            return False

        # Select town
        town_select = await page.query_selector(
            'select[name="SearchFormEx1$ACSDropDownList_Towns"]'
        )
        if town_select:
            try:
                await town_select.select_option(label=town_name)
            except Exception:
                try:
                    # Try partial match
                    options = await page.evaluate('''() => {
                        const sel = document.querySelector('select[name="SearchFormEx1$ACSDropDownList_Towns"]');
                        if (!sel) return [];
                        return Array.from(sel.options).map(o => ({value: o.value, text: o.text}));
                    }''')
                    match = None
                    for opt in options:
                        if town_name.upper() in opt["text"].upper():
                            match = opt["value"]
                            break
                    if match:
                        await town_select.select_option(value=match)
                    else:
                        logger.warning(f"  Town '{town_name}' not found in dropdown")
                        return False
                except Exception as e:
                    logger.warning(f"  Could not select town: {e}")
                    return False
        else:
            logger.warning("  Town dropdown not found")
            return False

        return True
    except Exception as e:
        logger.error(f"  Form filling failed: {e}")
        return False


async def _mx_click_search(page) -> bool:
    """Click the Search button and wait for results."""
    try:
        search_btn = await page.query_selector(
            'input[name="SearchFormEx1$btnSearch"]'
        )
        if not search_btn:
            search_btn = await page.query_selector('#SearchFormEx1_btnSearch')
        if not search_btn:
            logger.warning("  Search button not found")
            return False

        await search_btn.click()
        await page.wait_for_timeout(8000)
        return True
    except Exception as e:
        logger.error(f"  Search click failed: {e}")
        return False


async def _mx_switch_to_view_100(page) -> bool:
    """Switch to 100 records per page view."""
    try:
        view100 = await page.query_selector('#DocList1_PageView100Btn')
        if not view100:
            view100 = await page.query_selector('a:has-text("View 100")')
        if view100:
            await view100.click()
            await page.wait_for_timeout(5000)
            return True
        return False
    except Exception:
        return False


async def _mx_get_hit_count(page) -> int:
    """Extract the hit count from the results page."""
    try:
        text = await page.evaluate('''() => {
            const body = document.body.textContent || "";
            const match = body.match(/(\\d+)\\s+hits/);
            return match ? parseInt(match[1]) : -1;
        }''')
        return text
    except Exception:
        return -1


async def _mx_extract_grid_records(page) -> list[dict]:
    """
    Extract records from the results grid using the element ID pattern.

    Each record has elements with IDs like:
        DocList1_GridView_Document_ctl{NN}_ButtonRow_{Column}_{rowIdx}
    where NN is zero-padded starting at 02, rowIdx = NN - 2.
    Columns: "File Date", "Book/Page", "Type Desc.", "Town"
    """
    records = await page.evaluate('''() => {
        const results = [];
        for (let i = 2; i <= 110; i++) {
            const ctlNum = String(i).padStart(2, '0');
            const prefix = 'DocList1_GridView_Document_ctl' + ctlNum + '_ButtonRow_';
            const rowIdx = i - 2;

            const fileDateEl = document.getElementById(prefix + 'File Date_' + rowIdx);
            if (!fileDateEl) break;  // No more records

            const bookPageEl = document.getElementById(prefix + 'Book/Page_' + rowIdx);
            const typeDescEl = document.getElementById(prefix + 'Type Desc._' + rowIdx);
            const townEl = document.getElementById(prefix + 'Town_' + rowIdx);

            results.push({
                fileDate: fileDateEl ? fileDateEl.textContent.trim() : '',
                bookPage: bookPageEl ? bookPageEl.textContent.trim() : '',
                typeDesc: typeDescEl ? typeDescEl.textContent.trim() : '',
                town: townEl ? townEl.textContent.trim() : '',
                ctlNum: ctlNum,
                rowIdx: rowIdx,
            });
        }
        return results;
    }''')
    return records or []


async def _mx_extract_record_detail(page, ctl_num: str, row_idx: int) -> dict:
    """
    Drill into a single record to extract detail data (address, parties).

    Executes __doPostBack to load the detail panel, extracts key fields,
    then navigates back to the results list.
    """
    detail = {
        "doc_number": "",
        "street": "",
        "description": "",
        "consideration": "",
        "grantors": [],
        "grantees": [],
    }

    try:
        # Click the record to open detail panel
        postback_id = f"DocList1$GridView_Document$ctl{ctl_num}$ButtonRow_File Date_{row_idx}"
        await page.evaluate(f"__doPostBack('{postback_id}','')")
        await page.wait_for_timeout(3000)

        # Extract detail from DocDetails1_UpdatePanel1
        detail = await page.evaluate('''() => {
            const panel = document.getElementById('DocDetails1_UpdatePanel1');
            if (!panel) return null;

            const text = panel.textContent || "";
            const result = {
                doc_number: "",
                street: "",
                description: "",
                consideration: "",
                grantors: [],
                grantees: [],
            };

            // Extract Doc #
            const docMatch = text.match(/Doc\\s*#\\s*[:\\s]*(\\d+)/);
            if (docMatch) result.doc_number = docMatch[1];

            // Extract Street Name
            const streetMatch = text.match(/Street\\s*Name[:\\s]*([A-Z0-9][A-Z0-9\\s.,'#-]*?)(?:\\s{2,}|Description|$)/i);
            if (streetMatch) result.street = streetMatch[1].trim();

            // Extract Description
            const descMatch = text.match(/Description[:\\s]*(.+?)(?:\\s{2,}|Grantor|$)/i);
            if (descMatch) result.description = descMatch[1].trim();

            // Extract Consideration
            const considMatch = text.match(/Consideration[:\\s]*([\\d,.]+)/);
            if (considMatch) result.consideration = considMatch[1];

            // Extract Grantor/Grantee from table cells
            // They appear as rows with role labels like "Grantor" and "Grantee"
            const allCells = panel.querySelectorAll('td');
            let currentName = "";
            for (const cell of allCells) {
                const cellText = cell.textContent.trim();
                if (cellText.length > 2 && cellText.length < 100 && /^[A-Z]/.test(cellText)) {
                    if (cellText === "Grantor" && currentName) {
                        result.grantors.push(currentName);
                    } else if (cellText === "Grantee" && currentName) {
                        result.grantees.push(currentName);
                    } else if (cellText !== "Grantor" && cellText !== "Grantee") {
                        currentName = cellText;
                    }
                }
            }

            return result;
        }''')

        if detail is None:
            detail = {"doc_number": "", "street": "", "description": "",
                      "consideration": "", "grantors": [], "grantees": []}

        # Navigate back to results list
        await page.go_back()
        await page.wait_for_timeout(3000)

    except Exception as e:
        logger.debug(f"  Detail extraction failed for ctl{ctl_num}: {e}")
        try:
            await page.go_back()
            await page.wait_for_timeout(3000)
        except Exception:
            pass

    return detail


async def scrape_middlesex_town_playwright(
    page,  # playwright Page object
    town_id: str,
    town_info: dict,
    from_date: str = "01/01/2020",
    extract_details: bool = False,
) -> list[TaxTakingRecord]:
    """
    Scrape tax taking records from Middlesex South Registry using Playwright.

    The 20/20 Perfect Vision system at masslandrecords.com is an ASP.NET
    WebForms app with AJAX UpdatePanels. Only a real browser can extract
    the result data — httpx/requests/FireCrawl all fail.

    Args:
        page: Playwright Page object
        town_id: Town identifier (e.g., "newton")
        town_info: Dict with search_name and name
        from_date: Start date in MM/DD/YYYY format
        extract_details: If True, drill into each record for address/parties
                        (slower but more data — ~3-5 sec per record)
    """
    search_name = town_info["search_name"]
    display_name = town_info["name"]
    to_date = datetime.now().strftime("%m/%d/%Y")

    logger.info(f"[Middlesex/{display_name}] Starting scrape...")

    # Step 1: Navigate to search page
    try:
        await page.goto(MIDDLESEX_SEARCH_URL, wait_until="networkidle", timeout=30000)
    except Exception as e:
        logger.warning(f"[Middlesex/{display_name}] Navigation timeout (continuing): {e}")

    await page.wait_for_timeout(3000)

    # Check for WAF/bot blocking
    body_text = await page.evaluate('() => document.body.textContent.substring(0, 2000)')
    if any(w in body_text.lower() for w in ["robot", "captcha", "blocked", "incapsula"]):
        logger.warning(f"[Middlesex/{display_name}] Bot detection triggered — skipping")
        return []

    # Step 2: Dismiss popup
    await _mx_dismiss_popup(page)

    # Step 3: Switch to Recorded Date Search
    logger.info(f"[Middlesex/{display_name}] Switching to Recorded Date Search...")
    if not await _mx_switch_to_recorded_date_search(page):
        logger.error(f"[Middlesex/{display_name}] Failed to switch criteria")
        return []

    # Step 4: Click Advanced to reveal doc type and town filters
    logger.info(f"[Middlesex/{display_name}] Clicking Advanced...")
    if not await _mx_click_advanced(page):
        logger.warning(f"[Middlesex/{display_name}] Advanced click failed, trying search anyway")

    # Step 5: Fill search form
    logger.info(f"[Middlesex/{display_name}] Setting filters: TAKING, {search_name}, {from_date}-{to_date}")
    if not await _mx_fill_search_form(page, search_name, from_date, to_date):
        logger.error(f"[Middlesex/{display_name}] Form filling failed")
        return []

    # Step 6: Click Search
    logger.info(f"[Middlesex/{display_name}] Searching...")
    if not await _mx_click_search(page):
        logger.error(f"[Middlesex/{display_name}] Search failed")
        return []

    # Step 7: Check hit count
    hit_count = await _mx_get_hit_count(page)
    logger.info(f"[Middlesex/{display_name}] Hits: {hit_count}")

    if hit_count == 0:
        logger.info(f"[Middlesex/{display_name}] ⚠️ No TAKING records found")
        return []

    # Step 8: Switch to View 100 if more than 20 results
    if hit_count > 20:
        logger.info(f"[Middlesex/{display_name}] Switching to View 100...")
        await _mx_switch_to_view_100(page)

    # Step 9: Extract records from all pages
    all_grid_records = []
    page_num = 1

    while True:
        grid_records = await _mx_extract_grid_records(page)
        if not grid_records:
            break

        logger.info(f"[Middlesex/{display_name}] Page {page_num}: {len(grid_records)} records")
        all_grid_records.extend(grid_records)

        # Check if there's a next page
        if len(grid_records) < 100:
            break  # Last page

        # Try to navigate to next page
        try:
            # Page navigation links are numbered: 1, 2, 3, ...
            next_page_num = page_num + 1
            next_link = await page.query_selector(
                f'a[href*="Page${next_page_num}"]'
            )
            if not next_link:
                # Try clicking the page number directly
                next_link = await page.evaluate(f'''() => {{
                    const links = document.querySelectorAll('a');
                    for (const a of links) {{
                        if (a.textContent.trim() === '{next_page_num}' &&
                            a.id && a.id.includes('DocList1')) {{
                            return a.id;
                        }}
                    }}
                    return null;
                }}''')
                if next_link:
                    await page.click(f'#{next_link}')
                else:
                    break
            else:
                await next_link.click()

            await page.wait_for_timeout(5000)
            page_num += 1
        except Exception:
            break

    logger.info(f"[Middlesex/{display_name}] Total grid records: {len(all_grid_records)}")

    # Step 10: Convert grid records to TaxTakingRecord objects
    records = []
    seen_keys = set()

    for gr in all_grid_records:
        file_date = gr.get("fileDate", "")
        book_page = gr.get("bookPage", "")
        type_desc = gr.get("typeDesc", "")

        # Parse book/page
        book, page_val = "", ""
        if "/" in book_page:
            parts = book_page.split("/", 1)
            book = parts[0].strip()
            page_val = parts[1].strip()

        # Deduplicate by book-page-date
        dedup_key = f"{book}-{page_val}-{file_date}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        record = TaxTakingRecord(
            town=town_id,
            address="",  # Populated by detail extraction
            file_date=file_date,
            book=book,
            page=page_val,
            grantor="",  # Populated by detail extraction
            grantee="",  # Populated by detail extraction
            doc_type="Tax Taking",
            property_description="",
            registry="middlesex_south",
            source_url=MIDDLESEX_SEARCH_URL,
        )
        records.append(record)

    # Step 11: Optional detail extraction (address + parties)
    if extract_details and records:
        logger.info(f"[Middlesex/{display_name}] Extracting details for {len(records)} records...")
        # Re-extract grid to get ctl numbers (they might have changed after pagination)
        # For simplicity, only extract details from the current page view
        # TODO: For large result sets, iterate pages and extract details per page

        for i, gr in enumerate(all_grid_records[:len(records)]):
            if i > 0 and i % 10 == 0:
                logger.info(f"  Detail extraction: {i}/{len(records)}...")

            ctl_num = gr.get("ctlNum", "")
            row_idx = gr.get("rowIdx", 0)

            detail = await _mx_extract_record_detail(page, ctl_num, row_idx)

            if detail:
                records[i].address = detail.get("street", "")
                records[i].property_description = detail.get("description", "")
                grantors = detail.get("grantors", [])
                grantees = detail.get("grantees", [])
                if grantors:
                    records[i].grantor = "; ".join(grantors)
                if grantees:
                    records[i].grantee = "; ".join(grantees)

    if records:
        logger.info(f"[Middlesex/{display_name}] ✅ Total: {len(records)} tax taking records")
    else:
        debug_path = backend_dir / "data_cache" / "tax_delinquency" / f"_middlesex_{town_id}_debug.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            body = await page.evaluate('() => document.body.textContent.substring(0, 5000)')
            debug_path.write_text(body)
        except Exception:
            pass
        logger.info(f"[Middlesex/{display_name}] ⚠️ No records found (debug saved)")

    return records


# ─── Main ──────────────────────────────────────────────────────────────────

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Scrape tax taking records from MA Registry of Deeds")
    parser.add_argument("--norfolk-only", action="store_true", help="Only scrape Norfolk County")
    parser.add_argument("--middlesex-only", action="store_true", help="Only scrape Middlesex South")
    parser.add_argument("--town", type=str, help="Scrape a single town (e.g., 'brookline')")
    parser.add_argument("--from-date", type=str, default="01012020",
                       help="Start date for Norfolk in MMDDYYYY format (default: 01012020)")
    parser.add_argument("--from-date-mx", type=str, default="01/01/2020",
                       help="Start date for Middlesex in MM/DD/YYYY format (default: 01/01/2020)")
    parser.add_argument("--headless", action="store_true", default=True,
                       help="Run browser in headless mode (default: True)")
    parser.add_argument("--no-headless", action="store_true",
                       help="Run browser in visible mode for debugging")
    args = parser.parse_args()

    headless = not args.no_headless

    out_dir = backend_dir / "data_cache" / "tax_delinquency"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 70)
    logger.info("Tax Taking Scraper — Massachusetts Registry of Deeds")
    logger.info(f"  Playwright headless={'yes' if headless else 'no'}")
    logger.info("=" * 70)

    all_results = {}

    # Determine which registries to scrape
    do_norfolk = not args.middlesex_only
    do_middlesex = not args.norfolk_only

    if args.town:
        # Single town mode
        if args.town in NORFOLK_TOWNS:
            do_middlesex = False
        elif args.town in MIDDLESEX_TOWNS:
            do_norfolk = False
        else:
            logger.error(f"Unknown town: {args.town}")
            logger.info(f"Norfolk towns: {', '.join(NORFOLK_TOWNS.keys())}")
            logger.info(f"Middlesex towns: {', '.join(MIDDLESEX_TOWNS.keys())}")
            return

    # Import playwright
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        # ── Norfolk County ──
        if do_norfolk:
            logger.info("\n📍 Norfolk County Registry (ALIS)")
            logger.info("-" * 50)

            norfolk_towns = NORFOLK_TOWNS
            if args.town:
                norfolk_towns = {args.town: NORFOLK_TOWNS[args.town]}

            for town_id, town_info in norfolk_towns.items():
                records = await scrape_norfolk_town(page, town_id, town_info, args.from_date)
                all_results[town_id] = {
                    "records": records,
                    "registry": "norfolk",
                    "name": town_info["name"],
                }
                await asyncio.sleep(2)  # Rate limiting between towns

        # ── Middlesex South ──
        if do_middlesex:
            logger.info("\n📍 Middlesex South Registry (20/20 Perfect Vision)")
            logger.info("-" * 50)

            middlesex_towns = MIDDLESEX_TOWNS
            if args.town:
                middlesex_towns = {args.town: MIDDLESEX_TOWNS[args.town]}

            for town_id, town_info in middlesex_towns.items():
                records = await scrape_middlesex_town_playwright(page, town_id, town_info, args.from_date_mx)
                all_results[town_id] = {
                    "records": records,
                    "registry": "middlesex_south",
                    "name": town_info["name"],
                }
                await asyncio.sleep(3)  # Longer delay for ASP.NET

        await browser.close()

    # ── Save Results ──
    logger.info("\n📦 Saving results...")
    logger.info("-" * 50)

    total_records = 0
    for town_id, data in all_results.items():
        records = data["records"]
        registry = data["registry"]
        town_name = data["name"]

        output = {
            "town": town_id,
            "name": town_name,
            "source": "registry_of_deeds",
            "registry": registry,
            "status": "scraped" if records else "no_records_found",
            "record_count": len(records),
            "scraped_at": datetime.utcnow().isoformat() + "Z",
            "records": [asdict(r) for r in records],
        }

        out_file = out_dir / f"{town_id}_tax_takings.json"
        out_file.write_text(json.dumps(output, indent=2))
        total_records += len(records)

        status = "✅" if records else "⚠️"
        logger.info(f"  {status} {town_name}: {len(records)} records → {out_file.name}")

    logger.info(f"\n🏁 Done! Total: {total_records} records across {len(all_results)} towns")

    # ── Summary ──
    summary = {
        "run_date": datetime.utcnow().isoformat() + "Z",
        "total_towns": len(all_results),
        "total_records": total_records,
        "towns": {
            tid: {
                "count": len(data["records"]),
                "registry": data["registry"],
                "name": data["name"],
            }
            for tid, data in all_results.items()
        },
    }
    summary_file = out_dir / "_tax_takings_run_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2))
    logger.info(f"  📊 Summary saved to {summary_file.name}")


if __name__ == "__main__":
    asyncio.run(main())
