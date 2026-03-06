import os
import json
import logging
import asyncio
import re
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class ZoningBylawScraper:
    def __init__(self):
        try:
            from anthropic import AsyncAnthropic
            self.client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        except ImportError:
            logger.error("anthropic package not installed.")
            self.client = None

    async def extract_table_of_uses(self, town_name: str, ecode_url: str) -> Optional[Dict[str, Any]]:
        if not self.client:
            logger.error("Anthropic client not initialized.")
            return None

        logger.info(f"Extracting zoning bylaws for {town_name} from {ecode_url}...")
        
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("playwright not installed.")
            return None
            
        extracted_text = ""
        attachment_urls = []

        if ecode_url.lower().endswith(".pdf") or "/attachment/" in ecode_url.lower():
            logger.info(f"Target URL is a PDF or attachment. Skipping Playwright.")
            attachment_urls.append(ecode_url)
        else:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=False,
                    channel="chrome"
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={'width': 1280, 'height': 800}
                )
                page = await context.new_page()
                
                try:
                    await page.goto(ecode_url, wait_until="domcontentloaded", timeout=45000)
                    # wait a little bit for dynamic JS to render the TOC or pass Cloudflare
                    await page.wait_for_timeout(5000)
                    html = await page.content()
                    
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # 1. Grab any inline HTML tables
                    tables = soup.find_all('table')
                    if tables:
                        logger.info(f"Found {len(tables)} inline tables.")
                        for t in tables:
                            extracted_text += t.get_text(separator=" | ", strip=True) + "\n\n"
                            
                    # 2. Look for attachment links
                    attachments = soup.find_all('a', href=True)
                    for a in attachments:
                        href = a['href']
                        text = a.get_text(strip=True).lower()
                        
                        if ('use' in text or 'dimension' in text or 'table' in text or 'standard' in text or href.endswith('.pdf')):
                            if '/attachment/' in href or href.endswith('.pdf') or 'attachmentslink' in a.get('class', []) or 'nonxml' in a.get('class', []):
                                full_url = urljoin("https://ecode360.com", href)
                                if full_url not in attachment_urls:
                                    attachment_urls.append(full_url)
                    
                    # 3. If no tables and no attachments, try clicking the "Zoning" chapter
                    if not tables and not attachment_urls:
                        logger.info("No tables/attachments found on main page. Looking for Zoning chapter link...")
                        # In eCode360, chapter links can just be <a> tags with 'titleLink' or similar
                        zoning_links = soup.find_all('a')
                        for zl in zoning_links:
                            z_text = zl.get_text(strip=True).lower()
                            if 'zoning' in z_text and 'amendment' not in z_text and 'map' not in z_text:
                                z_href = zl.get('href', '')
                                match = re.search(r'\d{6,}', z_href)
                                if match:
                                    guid = match.group(0)
                                    full_url = f"https://ecode360.com/{guid}"
                                    logger.info(f"Navigating to Zoning chapter: {full_url}")
                                    try:
                                        await page.goto(full_url, wait_until="domcontentloaded", timeout=45000)
                                        await page.wait_for_timeout(3000)
                                        html2 = await page.content()
                                        soup2 = BeautifulSoup(html2, 'html.parser')
                                        tables2 = soup2.find_all('table')
                                        for t in tables2:
                                            extracted_text += t.get_text(separator=" | ", strip=True) + "\n\n"
                                        
                                        atts2 = soup2.find_all('a', href=True)
                                        for a2 in atts2:
                                            href2 = a2['href']
                                            text2 = a2.get_text(strip=True).lower()
                                            if ('use' in text2 or 'dimension' in text2 or 'table' in text2 or 'standard' in text2 or href2.endswith('.pdf')):
                                                if '/attachment/' in href2 or href2.endswith('.pdf') or 'attachmentslink' in a2.get('class', []) or 'nonxml' in a2.get('class', []):
                                                    f_url = urljoin("https://ecode360.com", href2)
                                                    if f_url not in attachment_urls:
                                                        attachment_urls.append(f_url)
                                    except Exception as e:
                                        logger.error(f"Failed to fetch {full_url}: {e}")
                                    break
                except Exception as e:
                    logger.error(f"Failed to fetch {ecode_url}: {e}")
                    
                await browser.close()

        # 4. Download and parse any PDF attachments
        if attachment_urls:
            import httpx
            import pdfplumber
            import io
            
            logger.info(f"Found {len(attachment_urls)} attachment URLs to process.")
            async with httpx.AsyncClient() as client:
                for att_url in attachment_urls[:3]:
                    logger.info(f"Downloading PDF: {att_url}")
                    try:
                        resp = await client.get(att_url, timeout=30.0)
                        if resp.status_code == 200:
                            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                                for page in pdf.pages:
                                    extracted_text += page.extract_text() + "\n\n"
                                    table = page.extract_table()
                                    if table:
                                        for row in table:
                                            clean_row = [str(c) if c else "" for c in row]
                                            extracted_text += " | ".join(clean_row) + "\n"
                        else:
                            logger.warning(f"Failed to download {att_url}, status {resp.status_code}")
                    except Exception as e:
                        logger.error(f"Error processing PDF {att_url}: {e}")

        if not extracted_text.strip():
            logger.error("Could not find any tables or PDF text to extract.")
            return None
            
        logger.info(f"Successfully collected {len(extracted_text)} characters of text. Sending to LLM...")

        prompt = f"""You are an expert real estate attorney and municipal data engineer.
I am providing you with extracted text (from HTML tables and PDFs) of the Zoning Bylaws for {town_name}, Massachusetts.

Your exact objective is to locate the "Table of Use Regulations" (which defines what is allowed to be built in which district) and "Dimensional Requirements" (if present) and extract them into a clean, structured JSON format.

Please output valid JSON ONLY with the following schema:
{{
  "town": "{town_name}",
  "districts": [
    {{
      "code": "e.g. RO, RS, CB",
      "name": "e.g. One-Family Dwelling, Central Business",
      "allowed_uses": ["List of permitted uses (by right)"],
      "special_permit_uses": ["List of uses requiring a special permit"],
      "dimensional_requirements": {{
        "min_lot_size_sqft": "e.g. 15000 (numeric if possible, else string)",
        "min_frontage_ft": "e.g. 100",
        "max_height_ft": "e.g. 35"
      }}
    }}
  ]
}}

If the document does not contain dimensional data, omit the "dimensional_requirements" object. Do your best to map the text accurately. If there are massive amounts of uses, group them logically or list the most common ones.

Extracted text:
---
{extracted_text[:100000]}
---

Return ONLY valid JSON, no other text or explanation. DO NOT wrap the output in markdown code blocks like ```json .
"""
        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8192,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}]
            )
            
            result_text = response.content[0].text.strip()

            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            try:
                parsed = json.loads(result_text)
                return parsed
            except json.JSONDecodeError as exc:
                logger.error(f"Failed to parse LLM JSON output: {exc}")
                with open('/tmp/failed_zoning_json.txt', 'w') as f:
                    f.write(result_text)
                logger.info("Raw LLM output dumped to /tmp/failed_zoning_json.txt")
                return None

        except Exception as e:
            logger.error(f"Error extracting structured zoning via LLM: {e}")
            return None
