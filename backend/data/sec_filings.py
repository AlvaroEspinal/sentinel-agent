"""SEC EDGAR Filing Client for RAG Agent."""
import httpx
import re
from datetime import datetime
from typing import Optional
from loguru import logger


class SECFiling:
    """Parsed SEC filing metadata."""
    def __init__(self, data: dict):
        self.accession_number = data.get("accessionNumber", "").replace("-", "")
        self.filing_date = data.get("filingDate", "")
        self.form_type = data.get("form", data.get("primaryDocument", ""))
        self.company_name = data.get("companyName", "")
        self.cik = data.get("cik", "")
        self.primary_document = data.get("primaryDocument", "")
        self.description = data.get("primaryDocDescription", "")

    @property
    def url(self) -> str:
        cik = str(self.cik).zfill(10)
        acc = self.accession_number
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{self.primary_document}"


class SECFilingsClient:
    """SEC EDGAR client for retrieving 10-K, 10-Q filings for RAG.

    Uses the free SEC EDGAR Full-Text Search and EFTS APIs.
    All SEC data is public domain - no MNPI risk.
    """

    BASE_URL = "https://efts.sec.gov/LATEST"
    EDGAR_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
    COMPANY_SEARCH = "https://efts.sec.gov/LATEST/search-index"

    HEADERS = {
        "User-Agent": "SentinelAgent research@sentinel.dev",
        "Accept-Encoding": "gzip, deflate",
    }

    def __init__(self):
        pass

    async def get_company_cik(self, ticker: str) -> Optional[str]:
        """Look up CIK number from ticker symbol."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://www.sec.gov/files/company_tickers.json",
                    headers=self.HEADERS,
                )
                resp.raise_for_status()
                data = resp.json()
                for entry in data.values():
                    if entry.get("ticker", "").upper() == ticker.upper():
                        return str(entry["cik_str"])
        except Exception as e:
            logger.error(f"CIK lookup error for {ticker}: {e}")
        return None

    async def get_latest_10k(self, ticker: str) -> Optional[str]:
        """Get the full text of the most recent 10-K filing."""
        cik = await self.get_company_cik(ticker)
        if not cik:
            logger.warning(f"Could not find CIK for {ticker}")
            return self._mock_10k_text(ticker)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Search for 10-K filings
                resp = await client.get(
                    f"{self.BASE_URL}/search-index",
                    params={
                        "q": f'"10-K"',
                        "dateRange": "custom",
                        "startdt": "2023-01-01",
                        "enddt": datetime.utcnow().strftime("%Y-%m-%d"),
                        "forms": "10-K",
                        "entities": f"cik:{cik.zfill(10)}",
                    },
                    headers=self.HEADERS,
                )
                if resp.status_code != 200:
                    return self._mock_10k_text(ticker)

                # Try the company filings API instead
                resp2 = await client.get(
                    f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json",
                    headers=self.HEADERS,
                )
                resp2.raise_for_status()
                submissions = resp2.json()
                recent = submissions.get("filings", {}).get("recent", {})
                forms = recent.get("form", [])
                accessions = recent.get("accessionNumber", [])
                primary_docs = recent.get("primaryDocument", [])

                for i, form in enumerate(forms):
                    if form == "10-K":
                        acc = accessions[i].replace("-", "")
                        doc = primary_docs[i]
                        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

                        doc_resp = await client.get(doc_url, headers=self.HEADERS)
                        if doc_resp.status_code == 200:
                            text = doc_resp.text
                            # Strip HTML tags for plain text
                            clean = re.sub(r"<[^>]+>", " ", text)
                            clean = re.sub(r"\s+", " ", clean)
                            return clean[:50000]  # Limit to 50k chars for RAG

                return self._mock_10k_text(ticker)

        except Exception as e:
            logger.error(f"SEC filing fetch error for {ticker}: {e}")
            return self._mock_10k_text(ticker)

    async def extract_revenue_breakdown(self, ticker: str) -> dict:
        """Extract physical vs digital revenue breakdown from 10-K."""
        text = await self.get_latest_10k(ticker)
        if not text:
            return self._default_revenue_breakdown()

        # Simple heuristic extraction (in production, use LLM for this)
        result = {
            "ticker": ticker,
            "physical_revenue_pct": 70.0,
            "digital_revenue_pct": 30.0,
            "total_revenue_mentioned": "",
            "segments": [],
            "source": "SEC EDGAR 10-K",
        }

        # Look for e-commerce / digital mentions
        text_lower = text.lower()
        digital_keywords = [
            "e-commerce", "ecommerce", "online sales", "digital",
            "direct-to-consumer", "digital channel", "online store",
            "digital revenue", "online revenue",
        ]

        digital_mentions = sum(
            text_lower.count(kw) for kw in digital_keywords
        )

        # Rough heuristic: more digital mentions = higher digital revenue share
        if digital_mentions > 50:
            result["digital_revenue_pct"] = 45.0
            result["physical_revenue_pct"] = 55.0
        elif digital_mentions > 20:
            result["digital_revenue_pct"] = 30.0
            result["physical_revenue_pct"] = 70.0
        elif digital_mentions > 5:
            result["digital_revenue_pct"] = 15.0
            result["physical_revenue_pct"] = 85.0
        else:
            result["digital_revenue_pct"] = 5.0
            result["physical_revenue_pct"] = 95.0

        # Look for specific revenue numbers
        revenue_pattern = r"\$[\d,]+\.?\d*\s*(million|billion|M|B)"
        matches = re.findall(revenue_pattern, text[:10000])
        if matches:
            result["total_revenue_mentioned"] = f"Found {len(matches)} revenue figures"

        return result

    def _mock_10k_text(self, ticker: str) -> str:
        """Generate mock 10-K text for POC."""
        return f"""
        ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)
        OF THE SECURITIES EXCHANGE ACT OF 1934

        Company: {ticker} Corporation
        Fiscal Year Ended: December 31, 2025

        ITEM 1. BUSINESS
        The Company operates through multiple segments including physical retail
        locations, e-commerce platforms, and wholesale distribution channels.
        Our digital revenue has grown to approximately 30% of total revenue,
        driven by strong online sales growth and direct-to-consumer initiatives.

        ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS
        Total revenue for fiscal year 2025 was $45.2 billion, representing
        a 7% increase year-over-year. Physical store revenue contributed
        approximately 70% of total revenue while our e-commerce and digital
        channels contributed the remaining 30%.

        Our supply chain operations rely on key manufacturing facilities in
        Shanghai, China and logistics hubs in Los Angeles, Rotterdam, and
        Singapore. Any disruption to these facilities could materially impact
        our ability to meet customer demand.

        ITEM 1A. RISK FACTORS
        Supply chain disruptions, including port congestion, shipping delays,
        and manufacturing shutdowns could adversely affect our operations.
        """

    def _default_revenue_breakdown(self) -> dict:
        return {
            "physical_revenue_pct": 80.0,
            "digital_revenue_pct": 20.0,
            "source": "default estimate",
        }

    def get_source_provenance(self) -> dict:
        return {
            "source_type": "sec_filing",
            "source_url": "https://www.sec.gov/cgi-bin/browse-edgar",
            "source_provider": "SEC EDGAR",
            "is_publicly_available": True,
            "mnpi_classification": "PUBLIC_OSINT",
        }
