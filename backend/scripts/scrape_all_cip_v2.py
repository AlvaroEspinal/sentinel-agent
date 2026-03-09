"""
scrape_all_cip_v2.py — Capital Improvement Plan scraper (httpx + pdfplumber, no Firecrawl).

All URLs verified working March 2026.
Uses targeted page extraction and chunked LLM calls for large PDFs.

Usage:
    python3 -m backend.scripts.scrape_all_cip_v2
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(ROOT / "backend" / ".env", override=True)
except ImportError:
    pass

import httpx
import pdfplumber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scrape_cip_v2")

CIP_DIR = ROOT / "backend" / "data_cache" / "cip"
CIP_DIR.mkdir(parents=True, exist_ok=True)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Town definitions ──────────────────────────────────────────────────────────
# page_range: (start_page, end_page) — 1-indexed, inclusive. Used when the CIP
# section is buried inside a large financial plan PDF. If None, reads up to
# max_pages from the beginning.
TOWNS: List[Dict[str, Any]] = [
    {
        "id": "newton",
        "name": "Newton",
        "page_urls": [],
        "direct_pdf_urls": [],
        # Newton blocks automated access (Akamai WAF).
    },
    {
        "id": "wellesley",
        "name": "Wellesley",
        "page_urls": [
            "https://www.wellesleyma.gov/2468/2026-Annual-Town-Meeting-Budget-Book",
        ],
        "direct_pdf_urls": [
            # FY27-FY31 Capital Plan - Schedule C
            "https://www.wellesleyma.gov/DocumentCenter/View/49968/Schedule-C",
            # Town-Wide Financial Plan
            "https://www.wellesleyma.gov/DocumentCenter/View/50095/2026-TWFP",
            # Major Capital Project Financing Schedule
            "https://www.wellesleyma.gov/DocumentCenter/View/49929/Major-Project-Financing-Schedule",
        ],
        # No page_range — full PDF is the capital schedule
    },
    {
        "id": "weston",
        "name": "Weston",
        "page_urls": [],
        "direct_pdf_urls": [
            # FY25 Capital Requests
            "https://www.westonma.gov/DocumentCenter/View/37485/4---Capital-Requests-PDF",
            # FY25 New Budget Requests
            "https://www.westonma.gov/DocumentCenter/View/37484/3---New-Requests-PDF",
            # FY25 Budget Comparison
            "https://www.westonma.gov/DocumentCenter/View/37482/1---Budget-Comparison-PDF",
        ],
    },
    {
        "id": "brookline",
        "name": "Brookline",
        "page_urls": [],
        "direct_pdf_urls": [
            # FY2027 Financial Plan — CIP section is pages 28-77
            "https://www.brooklinema.gov/DocumentCenter/View/61643/FY2027-Financial-Plan-PDF-Version",
        ],
        # CIP is in pages 28-77 (Capital Improvement Plan section + Capital Outlay Detail)
        "page_range": (28, 77),
    },
    {
        "id": "needham",
        "name": "Needham",
        "page_urls": [
            "https://www.needhamma.gov/5633/FY2026-2030-Capital-Improvement-Plan",
        ],
        "direct_pdf_urls": [
            # Complete FY2026-2030 CIP (444-page doc, pages 6-45 are exec summary + tables)
            "https://www.needhamma.gov/DocumentCenter/View/47157/Complete-FY2026---FY2030-Capital-Improvement-Plan",
        ],
        # Pages 6-45 = executive summary + CIP summary tables + capital recommendations
        "page_range": (6, 45),
    },
    {
        "id": "dover",
        "name": "Dover",
        # Dover site resets connections. No direct PDF found.
        "page_urls": [],
        "direct_pdf_urls": [],
    },
    {
        "id": "sherborn",
        "name": "Sherborn",
        "page_urls": [
            "https://sherbornma.org/390/Capital-Forecast-Guidance",
        ],
        "direct_pdf_urls": [
            # Capital forecast FY2017-2027 (comprehensive summary)
            "https://sherbornma.org/DocumentCenter/View/747/Forecast-Fiscal-Year-2017---Fiscal-Year-2027-PDF",
            # Road improvements capital requests
            "https://sherbornma.org/DocumentCenter/View/753/Road-Improvements-PDF",
            # Buildings capital requests
            "https://sherbornma.org/DocumentCenter/View/746/Buildings-PDF",
            # Non-building assets
            "https://sherbornma.org/DocumentCenter/View/748/Non-Building-Assets-PDF",
        ],
    },
    {
        "id": "natick",
        "name": "Natick",
        "page_urls": [
            "https://www.natickma.gov/379/Capital-Improvement-Program",
        ],
        "direct_pdf_urls": [
            # FY2027-2031 CIP (127-page doc; pages 8-13 are dept summary tables)
            "https://www.natickma.gov/DocumentCenter/View/21085/FY2027---FY2031-Capital-Improvement-Program-CIP",
        ],
        # Pages 8-127: summary tables (8-13) + individual project sheets (14-127)
        # Use pages 8-13 for dept summary tables first, then 14-127 in chunks for details
        "page_range": (8, 127),
    },
    {
        "id": "wayland",
        "name": "Wayland",
        # Wayland blocks all automated access. No data available.
        "page_urls": [],
        "direct_pdf_urls": [],
    },
    {
        "id": "lincoln",
        "name": "Lincoln",
        "page_urls": [
            "https://www.lincolntown.org/119/Capital-Planning-Committee",
        ],
        "direct_pdf_urls": [
            # Capital Planning Committee Jan 14, 2026 agenda
            "https://www.lincolntown.org/AgendaCenter/ViewFile/Agenda/_01142026-6572",
        ],
        "use_page_text_fallback": True,
    },
    {
        "id": "concord",
        "name": "Concord",
        "page_urls": [],
        "direct_pdf_urls": [
            # 2026 Annual Town Meeting Warrant — Article 11 is the CIP
            "https://concordma.gov/DocumentCenter/View/59793/2026-Annual-Town-Meeting-Warrant",
        ],
        "extra_pdf_urls": [
            "https://concordma.gov/documentcenter/view/58105",
        ],
    },
    {
        "id": "lexington",
        "name": "Lexington",
        "page_urls": [],
        "direct_pdf_urls": [
            # FY2027 Recommended Budget (Brown Book) — Capital section is pages 228-265
            "https://www.lexingtonma.gov/DocumentCenter/View/16495/FY2027-Budget-Brown-Book-",
        ],
        # Capital Investment section is pages 228-265
        "page_range": (228, 265),
    },
]

# ── Regex ─────────────────────────────────────────────────────────────────────
PDF_HREF_RE = re.compile(r'href=["\']([^"\']*(?:documentcenter/view/\d+|\.pdf)[^"\']*)["\']', re.IGNORECASE)
CIP_KEYWORDS_RE = re.compile(
    r"capital\s+improvement|capital\s+program|\bCIP\b|capital\s+plan|"
    r"capital\s+budget|five.year\s+plan|infrastructure\s+plan|capital\s+request",
    re.IGNORECASE,
)

CHUNK_SIZE = 12_000   # chars per LLM call
CHUNK_OVERLAP = 500   # overlap to avoid cutting mid-project


def _score_pdf_url(url: str) -> int:
    low = url.lower()
    score = 0
    for word, pts in [("capital", 3), ("cip", 4), ("improvement", 2), ("program", 1),
                      ("plan", 1), ("budget", 1), ("infrastructure", 2), ("warrant", 1),
                      ("forecast", 2), ("request", 1)]:
        if word in low:
            score += pts
    if re.search(r"202[4-9]|2030", low):
        score += 2
    return score


def _extract_pdf_links(html: str, base_url: str) -> List[str]:
    """Extract and normalize PDF links from HTML."""
    found = []
    for href in PDF_HREF_RE.findall(html):
        href = href.strip()
        clean = href.split("?")[0].split("#")[0]
        full = clean if clean.startswith("http") else urljoin(base_url, clean)
        found.append(full)
    seen: set = set()
    return [u for u in found if not (u in seen or seen.add(u))]  # type: ignore


def _extract_text_pdfplumber(
    pdf_bytes: bytes,
    page_range: Optional[Tuple[int, int]] = None,
    max_pages: int = 25,
) -> str:
    """Extract text from PDF bytes.

    Args:
        pdf_bytes: Raw PDF content.
        page_range: Optional (start, end) 1-indexed inclusive page numbers.
                    If provided, extracts only those pages.
        max_pages: Maximum pages to read (ignored if page_range is set).
    """
    texts: List[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total = len(pdf.pages)
            if page_range:
                start_idx = max(0, page_range[0] - 1)   # convert to 0-indexed
                end_idx = min(total, page_range[1])       # end is exclusive
                pages = pdf.pages[start_idx:end_idx]
                logger.info("  Extracting pages %d-%d of %d", page_range[0], min(page_range[1], total), total)
            else:
                pages = pdf.pages[:min(max_pages, total)]
            for i, page in enumerate(pages):
                txt = page.extract_text() or ""
                if txt.strip():
                    page_num = (page_range[0] + i) if page_range else (i + 1)
                    texts.append(f"--- Page {page_num} ---\n{txt}")
    except Exception as exc:
        logger.warning("pdfplumber error: %s", exc)
    return "\n".join(texts)


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks for LLM processing."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def _merge_projects(project_lists: List[List[Dict]]) -> List[Dict]:
    """Merge multiple project lists, deduplicating by project name."""
    seen_names: set = set()
    merged = []
    for projects in project_lists:
        for proj in projects:
            name = (proj.get("project_name") or "").strip().lower()
            if name and name not in seen_names:
                seen_names.add(name)
                merged.append(proj)
    return merged


def _save_result(town_id: str, result: Dict[str, Any]) -> Path:
    out_path = CIP_DIR / f"{town_id}_cip.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    return out_path


# ── LLM call ──────────────────────────────────────────────────────────────────

async def call_llm(prompt: str) -> str:
    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/sentinel-agent",
                "X-Title": "Sentinel-CIP-Scraper",
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 8192,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _build_prompt(text: str, town_name: str, chunk_num: int = 1, total_chunks: int = 1) -> str:
    chunk_note = f" (chunk {chunk_num} of {total_chunks})" if total_chunks > 1 else ""
    return f"""You are analyzing a Capital Improvement Plan (CIP) document or budget from {town_name}, Massachusetts{chunk_note}.

Extract EVERY identifiable municipal infrastructure or capital project from the text below.
Return a JSON object with a single top-level key "projects" containing an array.
Each element must have these exact fields:

{{
  "project_name": "Short descriptive name",
  "department": "Responsible department or null",
  "total_cost": 1200000,
  "fy_year": "FY2026",
  "description": "One-sentence summary",
  "category": "roads | water_sewer | schools | parks | public_safety | municipal_buildings | technology | other"
}}

Rules:
- "total_cost" is an integer dollar value (no $ or commas), or null if not stated.
- "fy_year" is the fiscal year string (e.g. "FY2026", "FY2027") or null.
- "category" MUST be one of the pipe-delimited enum values above.
- If NO identifiable capital projects exist in this text chunk, return {{"projects": []}}.
- Include EVERY named project even if cost is unknown.

Document text:
---
{text}
---

Return ONLY valid JSON, no other text."""


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        inner = parts[1]
        if inner.lower().startswith("json"):
            inner = inner[4:]
        text = inner.strip()
    return text


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def _fetch_page(url: str) -> Optional[tuple]:
    try:
        async with httpx.AsyncClient(
            timeout=30, headers=HEADERS, follow_redirects=True, verify=False
        ) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                logger.info("  HTTP %d for %s", resp.status_code, url)
                return None
            return resp.text, str(resp.url)
    except httpx.TimeoutException:
        logger.warning("  Timeout: %s", url)
        return None
    except Exception as exc:
        logger.warning("  Error %s: %s", type(exc).__name__, url)
        return None


async def _download_pdf(url: str) -> Optional[bytes]:
    url = url.strip()
    try:
        async with httpx.AsyncClient(
            timeout=60, headers=HEADERS, follow_redirects=True, verify=False
        ) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                logger.warning("  PDF HTTP %d: %s", resp.status_code, url)
                return None
            ct = resp.headers.get("content-type", "")
            if "pdf" not in ct and resp.content[:4] != b"%PDF":
                logger.info("  Not a PDF (content-type: %s): %s", ct[:40], url)
                return None
            return resp.content
    except httpx.TimeoutException:
        logger.warning("  PDF timeout: %s", url)
        return None
    except Exception as exc:
        logger.warning("  PDF error %s: %s", type(exc).__name__, url)
        return None


# ── LLM extraction with chunking ──────────────────────────────────────────────

async def _extract_projects_from_text(
    text: str,
    town_name: str,
    max_chunks: int = 8,
) -> List[Dict]:
    """Call LLM once or multiple times (chunked) and merge all projects."""
    chunks = _chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
    if len(chunks) > max_chunks:
        logger.warning("  Capping from %d to %d chunks", len(chunks), max_chunks)
        chunks = chunks[:max_chunks]

    all_project_lists: List[List[Dict]] = []
    logger.info("  Processing %d chunk(s) of text (~%d chars each)", len(chunks), CHUNK_SIZE)

    for i, chunk in enumerate(chunks, 1):
        try:
            prompt = _build_prompt(chunk, town_name, chunk_num=i, total_chunks=len(chunks))
            raw = await call_llm(prompt)
            parsed = json.loads(_strip_json(raw))
            chunk_projects = parsed.get("projects", [])
            logger.info("  Chunk %d/%d: %d projects", i, len(chunks), len(chunk_projects))
            all_project_lists.append(chunk_projects)
        except json.JSONDecodeError as exc:
            logger.error("  Chunk %d JSON parse error: %s", i, exc)
            all_project_lists.append([])
        except Exception as exc:
            logger.error("  Chunk %d LLM failed: %s", i, exc)
            all_project_lists.append([])

        # Avoid hammering the API
        if i < len(chunks):
            await asyncio.sleep(0.5)

    return _merge_projects(all_project_lists)


# ── Per-town scraper ──────────────────────────────────────────────────────────

async def scrape_town(town: Dict[str, Any]) -> Dict[str, Any]:
    town_id = town["id"]
    town_name = town["name"]
    direct_pdfs = town.get("direct_pdf_urls", [])
    extra_pdfs = town.get("extra_pdf_urls", [])
    page_urls = town.get("page_urls", [])
    use_page_text = town.get("use_page_text_fallback", False)
    page_range = town.get("page_range")  # Optional[Tuple[int, int]]

    tried_urls: List[str] = []
    found_page_url: Optional[str] = None
    page_html: str = ""
    all_pdf_urls: List[str] = list(direct_pdfs)
    extraction_text = ""
    pdf_used: Optional[str] = None

    logger.info("[%s] %d page URLs, %d direct PDFs, page_range=%s",
                town_name, len(page_urls), len(direct_pdfs), page_range)

    # ── Step 1: Fetch page URLs to discover additional PDF links ──────────────
    for url in page_urls:
        tried_urls.append(url)
        logger.info("[%s] Fetching: %s", town_name, url)
        result = await _fetch_page(url)
        if result is None:
            continue
        html, final_url = result
        page_html = html

        pdfs_on_page = _extract_pdf_links(html, final_url)
        cip_pdfs = sorted(
            [p for p in pdfs_on_page if _score_pdf_url(p) >= 2],
            key=_score_pdf_url, reverse=True
        )
        mentions_cip = bool(CIP_KEYWORDS_RE.search(html))

        if cip_pdfs or mentions_cip:
            logger.info("[%s] CIP content found (%d CIP PDFs, mentions=%s)",
                        town_name, len(cip_pdfs), mentions_cip)
            found_page_url = final_url
            combined = list(dict.fromkeys(cip_pdfs + direct_pdfs))
            all_pdf_urls = combined
            break

    all_pdf_urls = sorted(list(dict.fromkeys(all_pdf_urls)), key=_score_pdf_url, reverse=True)
    logger.info("[%s] %d PDF candidates", town_name, len(all_pdf_urls))

    # ── Step 2: Download PDFs and extract text ────────────────────────────────
    for pdf_url in all_pdf_urls[:4]:
        tried_urls.append(pdf_url)
        logger.info("[%s] Downloading: %s", town_name, pdf_url.split("/")[-1][:60])
        pdf_bytes = await _download_pdf(pdf_url)
        if pdf_bytes is None:
            continue
        logger.info("[%s] PDF: %d bytes", town_name, len(pdf_bytes))
        text = _extract_text_pdfplumber(pdf_bytes, page_range=page_range, max_pages=25)
        logger.info("[%s] Extracted %d chars", town_name, len(text))
        if len(text) >= 300:
            extraction_text = text
            pdf_used = pdf_url
            break

    # ── Step 3: Fallback to page HTML text ────────────────────────────────────
    if not extraction_text and (use_page_text or found_page_url) and page_html:
        clean = re.sub(r"<[^>]+>", " ", page_html)
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) >= 300:
            extraction_text = clean
            logger.info("[%s] Using page HTML text (%d chars)", town_name, len(extraction_text))

    # ── Step 4: Try extra PDFs ─────────────────────────────────────────────────
    if not extraction_text and extra_pdfs:
        for pdf_url in extra_pdfs[:2]:
            pdf_bytes = await _download_pdf(pdf_url)
            if pdf_bytes:
                text = _extract_text_pdfplumber(pdf_bytes, max_pages=15)
                if len(text) >= 300:
                    extraction_text = text
                    pdf_used = pdf_url
                    logger.info("[%s] Extra PDF: %d chars", town_name, len(text))
                    break

    if not extraction_text:
        logger.warning("[%s] No text available", town_name)
        result = {
            "town": town_id, "name": town_name, "status": "not_found",
            "source_url": found_page_url, "pdf_used": None,
            "scraped_at": datetime.utcnow().isoformat() + "Z",
            "tried_urls": tried_urls, "pdf_urls": all_pdf_urls,
            "project_count": 0, "projects": [],
        }
        _save_result(town_id, result)
        return result

    # ── Step 5: LLM extraction (chunked for large texts) ─────────────────────
    logger.info("[%s] LLM extraction on %d chars", town_name, len(extraction_text))
    projects: List[Dict[str, Any]] = []
    try:
        projects = await _extract_projects_from_text(extraction_text, town_name, max_chunks=8)
        logger.info("[%s] Total: %d projects after merge", town_name, len(projects))
    except Exception as exc:
        logger.error("[%s] LLM failed: %s", town_name, exc)

    status = "extracted" if projects else "pdf_found_no_data"
    result = {
        "town": town_id, "name": town_name, "status": status,
        "source_url": found_page_url or (all_pdf_urls[0] if all_pdf_urls else None),
        "pdf_used": pdf_used,
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "tried_urls": tried_urls, "pdf_urls": all_pdf_urls,
        "project_count": len(projects), "projects": projects,
    }
    _save_result(town_id, result)
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("=" * 60)
    logger.info("CIP Scraper v2 (httpx + pdfplumber) — %d towns", len(TOWNS))
    logger.info("Output: %s", CIP_DIR)
    logger.info("OpenRouter key present: %s", bool(OPENROUTER_KEY))
    logger.info("Model: %s", MODEL)
    logger.info("=" * 60)

    summary: List[Dict[str, Any]] = []
    start_total = time.perf_counter()

    for i, town in enumerate(TOWNS):
        if i > 0:
            await asyncio.sleep(1)

        town_start = time.perf_counter()
        logger.info("")
        logger.info("── [%d/%d] %s ─────────────────────────", i + 1, len(TOWNS), town["name"])

        try:
            result = await asyncio.wait_for(scrape_town(town), timeout=300.0)
        except asyncio.TimeoutError:
            logger.error("[%s] Timeout (300s)", town["name"])
            result = {
                "town": town["id"], "name": town["name"], "status": "timeout",
                "scraped_at": datetime.utcnow().isoformat() + "Z",
                "project_count": 0, "projects": [],
            }
            _save_result(town["id"], result)
        except Exception as exc:
            logger.error("[%s] Error: %s", town["name"], exc, exc_info=True)
            result = {
                "town": town["id"], "name": town["name"], "status": "error",
                "error": str(exc), "scraped_at": datetime.utcnow().isoformat() + "Z",
                "project_count": 0, "projects": [],
            }
            _save_result(town["id"], result)

        elapsed = time.perf_counter() - town_start
        summary.append({
            "town": town["name"],
            "status": result.get("status"),
            "project_count": result.get("project_count", 0),
            "pdf_used": result.get("pdf_used"),
            "elapsed_s": round(elapsed, 1),
        })

    total_elapsed = time.perf_counter() - start_total
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY — %.1fs total", total_elapsed)
    logger.info("=" * 60)
    logger.info("%-14s  %-22s  %8s  %s", "Town", "Status", "Projects", "Elapsed")
    logger.info("-" * 65)
    total_projects = 0
    for row in summary:
        total_projects += row["project_count"]
        pdf_note = " [PDF]" if row["pdf_used"] else ""
        logger.info("%-14s  %-22s  %8d  %.1fs%s",
                    row["town"], row["status"], row["project_count"],
                    row["elapsed_s"], pdf_note)
    logger.info("-" * 65)
    logger.info("Total projects extracted: %d", total_projects)

    summary_path = CIP_DIR / "_summary_v2.json"
    with open(summary_path, "w") as f:
        json.dump({
            "run_at": datetime.utcnow().isoformat() + "Z",
            "total_elapsed_s": round(total_elapsed, 1),
            "total_projects": total_projects,
            "towns": summary,
        }, f, indent=2)
    logger.info("Summary saved: %s", summary_path)


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    asyncio.run(main())
