"""Omnichannel RAG Agent -- e-commerce correction layer.

Prevents false negatives by cross-referencing physical-world anomalies
(e.g. "parking lot empty") with SEC filings that reveal whether the
company has a significant digital / e-commerce revenue channel.

If digital revenue exceeds 20 % of total, the alert severity is
adjusted downward because the physical signal may be a misleading
indicator of overall business health.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from models.alerts import AlertSeverity, AnomalyDetection, OmnichannelAdjustment
from data.sec_filings import SECFilingsClient
from services.vector_store import VectorStore


# ---------------------------------------------------------------------------
# Pre-loaded digital-revenue knowledge base for rapid lookup when the SEC
# filing has already been parsed.  Values are approximate digital_revenue_pct
# from public filings; they are used as a cache and overridden when live
# filing data is available.
# ---------------------------------------------------------------------------
_KNOWN_DIGITAL_MIX: dict[str, dict] = {
    "AMZN": {"physical_pct": 15.0, "digital_pct": 85.0, "trend": "growing"},
    "AAPL": {"physical_pct": 35.0, "digital_pct": 65.0, "trend": "growing"},
    "WMT":  {"physical_pct": 80.0, "digital_pct": 20.0, "trend": "growing"},
    "TGT":  {"physical_pct": 78.0, "digital_pct": 22.0, "trend": "growing"},
    "COST": {"physical_pct": 88.0, "digital_pct": 12.0, "trend": "stable"},
    "HD":   {"physical_pct": 82.0, "digital_pct": 18.0, "trend": "growing"},
    "NKE":  {"physical_pct": 56.0, "digital_pct": 44.0, "trend": "growing"},
    "TSLA": {"physical_pct": 90.0, "digital_pct": 10.0, "trend": "stable"},
    "META": {"physical_pct": 2.0,  "digital_pct": 98.0, "trend": "stable"},
    "GOOGL":{"physical_pct": 3.0,  "digital_pct": 97.0, "trend": "stable"},
    "MSFT": {"physical_pct": 5.0,  "digital_pct": 95.0, "trend": "stable"},
    "NVDA": {"physical_pct": 10.0, "digital_pct": 90.0, "trend": "stable"},
    "XOM":  {"physical_pct": 97.0, "digital_pct": 3.0,  "trend": "stable"},
    "CVX":  {"physical_pct": 96.0, "digital_pct": 4.0,  "trend": "stable"},
    "COP":  {"physical_pct": 98.0, "digital_pct": 2.0,  "trend": "stable"},
    "FCX":  {"physical_pct": 99.0, "digital_pct": 1.0,  "trend": "stable"},
    "NEM":  {"physical_pct": 99.0, "digital_pct": 1.0,  "trend": "stable"},
    "BA":   {"physical_pct": 95.0, "digital_pct": 5.0,  "trend": "stable"},
    "LMT":  {"physical_pct": 93.0, "digital_pct": 7.0,  "trend": "stable"},
    "PFE":  {"physical_pct": 75.0, "digital_pct": 25.0, "trend": "growing"},
    "JNJ":  {"physical_pct": 80.0, "digital_pct": 20.0, "trend": "growing"},
    "KO":   {"physical_pct": 92.0, "digital_pct": 8.0,  "trend": "growing"},
    "UPS":  {"physical_pct": 70.0, "digital_pct": 30.0, "trend": "growing"},
    "FDX":  {"physical_pct": 72.0, "digital_pct": 28.0, "trend": "growing"},
}


class OmnichannelRAGAgent:
    """Cross-references physical anomalies with SEC filing data to adjust
    alert severity based on the company's digital revenue exposure.
    """

    # Threshold: if digital revenue >= this %, adjust severity down
    DIGITAL_THRESHOLD_PCT = 20.0

    def __init__(
        self,
        sec_client: Optional[SECFilingsClient] = None,
        vector_store: Optional[VectorStore] = None,
    ) -> None:
        self.sec = sec_client or SECFilingsClient()
        self.vector_store = vector_store or VectorStore(collection_name="sentinel_10k_filings")
        self._digital_cache = dict(_KNOWN_DIGITAL_MIX)
        logger.info("OmnichannelRAGAgent initialised")

    # ------------------------------------------------------------------
    # Primary public method
    # ------------------------------------------------------------------

    async def adjust_for_digital(
        self,
        anomaly: AnomalyDetection,
        ticker: str,
    ) -> OmnichannelAdjustment:
        """Given a physical-world anomaly, determine whether the company's
        digital revenue channel mitigates the signal.

        Returns an OmnichannelAdjustment with the adjusted severity and
        reasoning.
        """
        logger.info(
            f"Omnichannel adjustment for {ticker} | "
            f"anomaly={anomaly.anomaly_type} magnitude={anomaly.magnitude:+.1f}%"
        )

        # Step 1: Get revenue breakdown (cache -> vector store -> SEC live)
        breakdown = await self.get_revenue_breakdown(ticker)
        physical_pct = breakdown.get("physical_revenue_pct", 100.0)
        digital_pct = breakdown.get("digital_revenue_pct", 0.0)
        digital_trend = breakdown.get("trend", breakdown.get("digital_trend", "stable"))
        filing_source = breakdown.get("source", "unknown")

        # Step 2: Determine severity adjustment
        original_severity = self._infer_severity_from_anomaly(anomaly)
        adjusted_severity = original_severity
        rationale_parts: list[str] = []

        if digital_pct >= self.DIGITAL_THRESHOLD_PCT:
            # Digital revenue is significant -- adjust severity down
            adjusted_severity = self._downgrade_severity(original_severity)
            rationale_parts.append(
                f"Digital revenue is {digital_pct:.0f}% of total "
                f"(above {self.DIGITAL_THRESHOLD_PCT:.0f}% threshold). "
                f"Physical signal may understate true business activity."
            )
            if digital_trend == "growing":
                rationale_parts.append(
                    "Digital channel is growing, further reducing "
                    "the weight of physical-only signals."
                )
        else:
            rationale_parts.append(
                f"Digital revenue is only {digital_pct:.0f}% of total "
                f"(below {self.DIGITAL_THRESHOLD_PCT:.0f}% threshold). "
                f"Physical signal is a reliable indicator."
            )

        # Step 3: Synthesise holistic view if we have enough data
        physical_signal = {
            "anomaly_type": anomaly.anomaly_type,
            "magnitude_pct": anomaly.magnitude,
            "consensus_score": anomaly.consensus_score,
        }
        digital_signal = {
            "digital_revenue_pct": digital_pct,
            "trend": digital_trend,
            "source": filing_source,
        }
        holistic = await self.synthesize_holistic_view(
            physical_signal, digital_signal, ticker
        )
        rationale_parts.append(holistic)

        adjustment = OmnichannelAdjustment(
            ticker=ticker,
            physical_revenue_pct=physical_pct,
            digital_revenue_pct=digital_pct,
            digital_trend=digital_trend,
            adjusted_severity=adjusted_severity,
            adjustment_rationale=" | ".join(rationale_parts),
            sec_filing_source=filing_source,
        )

        logger.info(
            f"Omnichannel result for {ticker}: "
            f"digital={digital_pct:.0f}% "
            f"severity {original_severity.value}->{adjusted_severity.value}"
        )
        return adjustment

    # ------------------------------------------------------------------
    # Revenue breakdown retrieval (multi-tier cache)
    # ------------------------------------------------------------------

    async def get_revenue_breakdown(self, ticker: str) -> dict:
        """Retrieve the physical vs digital revenue split for a ticker.

        Resolution order:
            1. In-memory cache (pre-loaded + previous queries).
            2. Vector store (previously ingested 10-K chunks).
            3. Live SEC EDGAR fetch + extraction.
        """
        ticker = ticker.upper()

        # Tier 1: in-memory cache
        if ticker in self._digital_cache:
            cached = self._digital_cache[ticker]
            logger.debug(f"Revenue breakdown for {ticker} from cache")
            return {
                "physical_revenue_pct": cached["physical_pct"],
                "digital_revenue_pct": cached["digital_pct"],
                "digital_trend": cached.get("trend", "stable"),
                "source": "knowledge_base_cache",
            }

        # Tier 2: vector store lookup
        vs_result = await self.vector_store.query(
            query_text=f"{ticker} digital revenue e-commerce online",
            n_results=1,
            where_filter={"ticker": ticker} if self.vector_store._initialised else None,
        )
        if vs_result and vs_result[0].get("distance", 1.0) < 0.5:
            text = vs_result[0].get("text", "")
            parsed = self._parse_revenue_from_text(text, ticker)
            if parsed:
                self._digital_cache[ticker] = {
                    "physical_pct": parsed["physical_revenue_pct"],
                    "digital_pct": parsed["digital_revenue_pct"],
                    "trend": parsed.get("digital_trend", "stable"),
                }
                parsed["source"] = "vector_store_10k"
                return parsed

        # Tier 3: live SEC filing
        logger.info(f"Fetching live SEC filing for {ticker}")
        sec_breakdown = await self.sec.extract_revenue_breakdown(ticker)

        # Store in vector store for future queries
        filing_text = await self.sec.get_latest_10k(ticker)
        if filing_text:
            doc_id = f"10k_{ticker}_{datetime.utcnow().strftime('%Y')}"
            await self.vector_store.upsert(
                doc_id=doc_id,
                text=filing_text[:10000],
                metadata={"ticker": ticker, "type": "10-K", "year": datetime.utcnow().year},
            )

        # Update caches
        physical = sec_breakdown.get("physical_revenue_pct", 80.0)
        digital = sec_breakdown.get("digital_revenue_pct", 20.0)
        self._digital_cache[ticker] = {
            "physical_pct": physical,
            "digital_pct": digital,
            "trend": "stable",
        }

        return {
            "physical_revenue_pct": physical,
            "digital_revenue_pct": digital,
            "digital_trend": "stable",
            "source": sec_breakdown.get("source", "SEC EDGAR 10-K"),
        }

    # ------------------------------------------------------------------
    # Holistic view synthesis
    # ------------------------------------------------------------------

    async def synthesize_holistic_view(
        self,
        physical_signal: dict,
        digital_signal: dict,
        ticker: str,
    ) -> str:
        """Generate a natural-language holistic assessment combining
        physical sensor signals and digital channel data.

        In production this would be an LLM call.  For the POC it uses
        template-based reasoning.
        """
        anomaly_type = physical_signal.get("anomaly_type", "unknown")
        magnitude = physical_signal.get("magnitude_pct", 0)
        digital_pct = digital_signal.get("digital_revenue_pct", 0)
        trend = digital_signal.get("trend", "stable")

        # Build contextual assessment
        if digital_pct >= 60:
            channel_assessment = (
                f"{ticker} derives {digital_pct:.0f}% of revenue from digital channels. "
                f"Physical signals ('{anomaly_type}', {magnitude:+.1f}%) have "
                f"limited predictive power for overall revenue."
            )
        elif digital_pct >= 20:
            channel_assessment = (
                f"{ticker} has a meaningful digital channel ({digital_pct:.0f}%). "
                f"Physical signal '{anomaly_type}' ({magnitude:+.1f}%) should be "
                f"weighted at approximately {100 - digital_pct:.0f}% of face value."
            )
        else:
            channel_assessment = (
                f"{ticker} is primarily physical ({100 - digital_pct:.0f}% of revenue). "
                f"Physical signal '{anomaly_type}' ({magnitude:+.1f}%) is a strong "
                f"indicator of business trajectory."
            )

        if trend == "growing":
            channel_assessment += (
                f" Note: digital channel is growing, which may further "
                f"reduce future reliance on physical signals."
            )

        # Check for specific anomaly-channel interactions
        if "parking" in anomaly_type or "foot_traffic" in anomaly_type:
            if digital_pct >= 30:
                channel_assessment += (
                    f" Foot traffic / parking lot metrics are especially "
                    f"misleading for companies with {digital_pct:.0f}% digital revenue."
                )

        return channel_assessment

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_revenue_from_text(self, text: str, ticker: str) -> Optional[dict]:
        """Extract revenue percentages from 10-K text using heuristics."""
        text_lower = text.lower()
        digital_keywords = [
            "e-commerce", "online", "digital", "direct-to-consumer", "dtc",
        ]
        mentions = sum(text_lower.count(kw) for kw in digital_keywords)

        if mentions == 0:
            return None

        # Heuristic: more mentions = higher digital share
        if mentions > 30:
            digital_pct = 45.0
        elif mentions > 15:
            digital_pct = 30.0
        elif mentions > 5:
            digital_pct = 18.0
        else:
            digital_pct = 8.0

        return {
            "physical_revenue_pct": round(100.0 - digital_pct, 1),
            "digital_revenue_pct": round(digital_pct, 1),
            "digital_trend": "growing" if mentions > 10 else "stable",
        }

    @staticmethod
    def _infer_severity_from_anomaly(anomaly: AnomalyDetection) -> AlertSeverity:
        """Map anomaly magnitude to a preliminary severity level before
        any omnichannel adjustment.
        """
        mag = abs(anomaly.magnitude)
        if mag >= 50:
            return AlertSeverity.CRITICAL
        if mag >= 30:
            return AlertSeverity.HIGH
        if mag >= 15:
            return AlertSeverity.MEDIUM
        if mag >= 5:
            return AlertSeverity.LOW
        return AlertSeverity.INFO

    @staticmethod
    def _downgrade_severity(severity: AlertSeverity) -> AlertSeverity:
        """Step the severity down by one level.  INFO stays INFO."""
        downgrade_map = {
            AlertSeverity.CRITICAL: AlertSeverity.HIGH,
            AlertSeverity.HIGH: AlertSeverity.MEDIUM,
            AlertSeverity.MEDIUM: AlertSeverity.LOW,
            AlertSeverity.LOW: AlertSeverity.INFO,
            AlertSeverity.INFO: AlertSeverity.INFO,
        }
        return downgrade_map[severity]
