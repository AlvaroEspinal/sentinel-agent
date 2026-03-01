"""Thesis Orchestrator Agent -- the brain of the Sentinel Agent pipeline.

Parses PM natural-language theses and OMS portfolios into concrete
SensorTasking requests by mapping every ticker to its real-world
physical footprint (factories, mines, refineries, ports, HQs, DCs).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from models.portfolio import (
    AssetClass,
    GeoTarget,
    Portfolio,
    Position,
    PositionSide,
    SensorTasking,
    ThesisInput,
    TradeProposal,
)


# ---------------------------------------------------------------------------
# Ticker -> Physical Facility Knowledge Base
# Each entry: (name, lat, lon, target_type, sensors)
# ---------------------------------------------------------------------------
_FACILITY_DB: dict[str, list[tuple[str, float, float, str, list[str]]]] = {
    # ── Automotive / EV ──────────────────────────────────────────────
    "TSLA": [
        ("Tesla Shanghai Gigafactory", 31.10, 121.60, "facility", ["optical", "adsb"]),
        ("Tesla Fremont Factory", 37.50, -121.93, "facility", ["optical", "adsb"]),
        ("Tesla Austin Gigafactory", 30.22, -97.62, "facility", ["optical", "adsb"]),
        ("Tesla Berlin Gigafactory", 52.39, 13.79, "facility", ["optical", "adsb"]),
        ("Tesla Lathrop Megapack Factory", 37.81, -121.28, "facility", ["optical"]),
    ],
    "F": [
        ("Ford Rouge Complex, Dearborn", 42.30, -83.15, "facility", ["optical", "adsb"]),
        ("Ford Kentucky Truck Plant", 38.30, -85.70, "facility", ["optical"]),
        ("Ford Chicago Assembly", 41.65, -87.57, "facility", ["optical"]),
    ],
    "GM": [
        ("GM Detroit-Hamtramck (Factory ZERO)", 42.37, -83.06, "facility", ["optical"]),
        ("GM Spring Hill Assembly", 35.75, -86.93, "facility", ["optical"]),
        ("GM Wentzville Assembly", 38.82, -90.87, "facility", ["optical"]),
    ],
    "RIVN": [
        ("Rivian Normal, IL Factory", 40.50, -88.95, "facility", ["optical", "adsb"]),
        ("Rivian Stanton Springs, GA (Planned)", 33.59, -83.68, "facility", ["optical"]),
    ],
    # ── Energy / Oil & Gas ───────────────────────────────────────────
    "XOM": [
        ("ExxonMobil Baytown Refinery", 29.74, -95.01, "facility", ["optical", "ais"]),
        ("ExxonMobil Beaumont Refinery", 30.02, -94.13, "facility", ["optical", "ais"]),
        ("ExxonMobil Baton Rouge Refinery", 30.50, -91.19, "facility", ["optical"]),
        ("ExxonMobil Guyana FPSO (Liza)", 6.25, -57.90, "port", ["ais", "sar"]),
    ],
    "CVX": [
        ("Chevron El Segundo Refinery", 33.91, -118.41, "facility", ["optical"]),
        ("Chevron Richmond Refinery", 37.93, -122.37, "facility", ["optical"]),
        ("Chevron Pascagoula Refinery", 30.35, -88.53, "facility", ["optical", "ais"]),
        ("Tengizchevroil, Kazakhstan", 46.15, 53.12, "facility", ["sar"]),
    ],
    "COP": [
        ("ConocoPhillips Alaska North Slope", 70.25, -148.72, "facility", ["sar"]),
        ("ConocoPhillips Surmont Oil Sands", 55.69, -110.82, "facility", ["sar"]),
    ],
    "OXY": [
        ("Occidental Permian Basin Ops", 31.95, -102.10, "facility", ["optical", "sar"]),
        ("Occidental Ingleside Terminal", 27.82, -97.21, "port", ["ais", "optical"]),
    ],
    # ── Technology ───────────────────────────────────────────────────
    "AAPL": [
        ("Foxconn Zhengzhou (iPhone City)", 34.75, 113.65, "facility", ["optical", "adsb"]),
        ("Apple Park, Cupertino", 37.33, -122.01, "hq", ["optical", "adsb"]),
        ("Foxconn Shenzhen Campus", 22.66, 114.06, "facility", ["optical"]),
        ("TSMC Fab 18, Tainan (Apple silicon)", 23.03, 120.28, "facility", ["optical"]),
    ],
    "NVDA": [
        ("NVIDIA HQ, Santa Clara", 37.37, -121.96, "hq", ["optical", "adsb"]),
        ("TSMC Fab 18, Tainan (GPU dies)", 23.03, 120.28, "facility", ["optical"]),
        ("TSMC Arizona Fab (under construction)", 33.67, -112.01, "facility", ["optical"]),
    ],
    "MSFT": [
        ("Microsoft Redmond Campus", 47.64, -122.13, "hq", ["optical", "adsb"]),
        ("Microsoft Quincy Data Center", 47.23, -119.85, "facility", ["optical"]),
        ("Microsoft Dublin Data Center", 53.35, -6.26, "facility", ["optical"]),
    ],
    "GOOGL": [
        ("Googleplex, Mountain View", 37.42, -122.08, "hq", ["optical", "adsb"]),
        ("Google The Dalles Data Center", 45.61, -121.20, "facility", ["optical"]),
        ("Google Council Bluffs DC", 41.25, -95.86, "facility", ["optical"]),
    ],
    "META": [
        ("Meta HQ, Menlo Park", 37.48, -122.15, "hq", ["optical"]),
        ("Meta Prineville Data Center", 44.30, -120.73, "facility", ["optical"]),
        ("Meta Lulea Data Center, Sweden", 65.58, 22.15, "facility", ["sar"]),
    ],
    "AMZN": [
        ("Amazon HQ2, Arlington VA", 38.88, -77.05, "hq", ["optical", "adsb"]),
        ("Amazon SEA Fulfillment Hub", 47.55, -122.34, "facility", ["optical"]),
        ("Amazon BFI4 / BFI3 Kent, WA", 47.38, -122.23, "facility", ["optical"]),
        ("Amazon ONT8 San Bernardino", 34.09, -117.29, "facility", ["optical"]),
    ],
    "TSM": [
        ("TSMC Fab 18, Tainan", 23.03, 120.28, "facility", ["optical"]),
        ("TSMC Fab 15, Taichung", 24.27, 120.63, "facility", ["optical"]),
        ("TSMC Arizona Fab", 33.67, -112.01, "facility", ["optical"]),
    ],
    # ── Retail ───────────────────────────────────────────────────────
    "WMT": [
        ("Walmart Bentonville HQ", 36.37, -94.21, "hq", ["optical", "adsb"]),
        ("Walmart DC #6023 Brooksville FL", 28.53, -82.39, "facility", ["optical"]),
        ("Walmart DC #7024 Gas City IN", 40.48, -85.61, "facility", ["optical"]),
        ("Walmart DC #6087 Palestine TX", 31.76, -95.63, "facility", ["optical"]),
        ("Walmart DC #6058 Olney IL", 38.73, -88.08, "facility", ["optical"]),
        ("Walmart DC #6089 Chino CA", 34.02, -117.69, "facility", ["optical"]),
        ("Walmart DC #6022 Opelika AL", 32.65, -85.38, "facility", ["optical"]),
        ("Walmart DC #7048 Shelbyville TN", 35.48, -86.46, "facility", ["optical"]),
        ("Walmart DC #6096 Williamsburg VA", 37.27, -76.76, "facility", ["optical"]),
        ("Walmart DC #6054 Buckeye AZ", 33.37, -112.58, "facility", ["optical"]),
        ("Walmart DC #6097 Winter Haven FL", 28.02, -81.73, "facility", ["optical"]),
    ],
    "TGT": [
        ("Target Minneapolis HQ", 44.97, -93.28, "hq", ["optical", "adsb"]),
        ("Target DC Lacey WA", 46.83, -122.84, "facility", ["optical"]),
        ("Target DC Midway GA", 31.81, -81.42, "facility", ["optical"]),
        ("Target DC Denton TX", 33.21, -97.13, "facility", ["optical"]),
    ],
    "COST": [
        ("Costco Issaquah HQ", 47.53, -122.05, "hq", ["optical", "adsb"]),
        ("Costco DC Mira Loma CA", 33.98, -117.51, "facility", ["optical"]),
        ("Costco DC Sumner WA", 47.20, -122.24, "facility", ["optical"]),
    ],
    "HD": [
        ("Home Depot Atlanta HQ", 33.77, -84.36, "hq", ["optical", "adsb"]),
        ("Home Depot DC Dallas", 32.78, -96.80, "facility", ["optical"]),
    ],
    # ── Mining / Materials ───────────────────────────────────────────
    "FCX": [
        ("Freeport Grasberg Mine, Papua", -4.05, 137.11, "mine", ["sar", "optical"]),
        ("Freeport Morenci Mine, AZ", 33.08, -109.32, "mine", ["optical"]),
        ("Freeport Cerro Verde, Peru", -16.53, -71.60, "mine", ["sar", "optical"]),
        ("Freeport Atlantic Copper Smelter, Spain", 37.26, -6.95, "facility", ["optical"]),
    ],
    "NEM": [
        ("Newmont Boddington Mine, WA AUS", -32.75, 116.38, "mine", ["optical"]),
        ("Newmont Penasquito Mine, Mexico", 24.28, -101.85, "mine", ["sar", "optical"]),
        ("Newmont Carlin Mine, NV", 40.88, -116.07, "mine", ["optical"]),
    ],
    "BHP": [
        ("BHP Olympic Dam, SA AUS", -30.45, 136.89, "mine", ["optical", "sar"]),
        ("BHP Escondida Mine, Chile", -24.27, -69.07, "mine", ["optical", "sar"]),
        ("BHP Port Hedland, WA AUS", -20.31, 118.58, "port", ["ais", "optical"]),
    ],
    "RIO": [
        ("Rio Tinto Pilbara, WA AUS", -22.32, 118.15, "mine", ["optical", "sar"]),
        ("Rio Tinto Oyu Tolgoi, Mongolia", 43.00, 106.88, "mine", ["sar"]),
    ],
    "VALE": [
        ("Vale Carajas Mine, Brazil", -6.07, -50.17, "mine", ["sar", "optical"]),
        ("Vale Tubarao Port, Brazil", -20.28, -40.24, "port", ["ais", "optical"]),
    ],
    # ── Aerospace / Defense ──────────────────────────────────────────
    "BA": [
        ("Boeing Everett Factory", 47.92, -122.27, "facility", ["optical", "adsb"]),
        ("Boeing Renton Factory", 47.49, -122.22, "facility", ["optical", "adsb"]),
        ("Boeing North Charleston SC", 32.90, -80.04, "facility", ["optical", "adsb"]),
    ],
    "LMT": [
        ("Lockheed Martin Bethesda HQ", 38.98, -77.10, "hq", ["optical", "adsb"]),
        ("Lockheed Martin Fort Worth (F-35)", 32.77, -97.44, "facility", ["optical", "adsb"]),
        ("Lockheed Martin Marietta, GA", 33.95, -84.52, "facility", ["optical"]),
    ],
    "RTX": [
        ("RTX / Pratt & Whitney E. Hartford", 41.78, -72.65, "facility", ["optical"]),
        ("Raytheon Tucson Missile Plant", 32.16, -110.85, "facility", ["optical"]),
    ],
    # ── Logistics / Shipping ─────────────────────────────────────────
    "UPS": [
        ("UPS Worldport Louisville KY", 38.18, -85.73, "facility", ["optical", "adsb"]),
        ("UPS Atlanta HQ", 33.80, -84.44, "hq", ["optical"]),
    ],
    "FDX": [
        ("FedEx Super Hub Memphis", 35.06, -89.98, "facility", ["optical", "adsb"]),
        ("FedEx Indianapolis Hub", 39.72, -86.29, "facility", ["optical", "adsb"]),
    ],
    "MAERSK.CO": [
        ("Maersk Copenhagen HQ", 55.69, 12.60, "hq", ["optical"]),
        ("Maersk APM Terminals Rotterdam", 51.95, 4.05, "port", ["ais", "optical"]),
    ],
    # ── Pharma / Healthcare ──────────────────────────────────────────
    "PFE": [
        ("Pfizer NYC HQ", 40.75, -73.97, "hq", ["optical"]),
        ("Pfizer Kalamazoo MI Plant", 42.27, -85.56, "facility", ["optical"]),
        ("Pfizer Puurs, Belgium Plant", 51.07, 4.29, "facility", ["optical"]),
    ],
    "JNJ": [
        ("J&J New Brunswick HQ", 40.49, -74.45, "hq", ["optical"]),
        ("J&J Janssen Leiden, NL", 52.17, 4.49, "facility", ["optical"]),
    ],
    "LLY": [
        ("Eli Lilly Indianapolis HQ", 39.77, -86.16, "hq", ["optical"]),
        ("Eli Lilly RTP NC", 35.90, -78.86, "facility", ["optical"]),
    ],
    # ── Semiconductors (additional) ──────────────────────────────────
    "INTC": [
        ("Intel Hillsboro OR (D1X)", 45.53, -122.91, "facility", ["optical"]),
        ("Intel Chandler AZ (Fab 52/62)", 33.24, -111.86, "facility", ["optical"]),
        ("Intel Leixlip Ireland (Fab 34)", 53.37, -6.51, "facility", ["optical"]),
    ],
    "AMD": [
        ("AMD Santa Clara HQ", 37.38, -121.96, "hq", ["optical"]),
        ("GlobalFoundries Malta NY (AMD partner)", 42.97, -73.87, "facility", ["optical"]),
    ],
    # ── Consumer Goods ───────────────────────────────────────────────
    "NKE": [
        ("Nike WHQ Beaverton OR", 45.51, -122.83, "hq", ["optical"]),
        ("Nike Logistics Memphis", 35.16, -90.03, "facility", ["optical"]),
        ("Nike Supplier Factories Ho Chi Minh City", 10.82, 106.63, "facility", ["optical"]),
    ],
    "KO": [
        ("Coca-Cola Atlanta HQ", 33.77, -84.39, "hq", ["optical"]),
        ("Coca-Cola Auburndale FL Bottling", 28.07, -81.79, "facility", ["optical"]),
    ],
}


# ---------------------------------------------------------------------------
# Monitoring-objective keywords that hint at which sensors are needed
# ---------------------------------------------------------------------------
_OBJECTIVE_KEYWORDS: dict[str, list[str]] = {
    "production":  ["production", "output", "manufacturing", "assembly", "factory"],
    "logistics":   ["logistics", "shipping", "port", "supply chain", "freight", "export", "import"],
    "foot_traffic": ["foot traffic", "parking lot", "retail", "store activity", "customer"],
    "construction": ["construction", "build-out", "expansion", "new facility"],
    "mining":      ["mine", "extraction", "ore", "tailings"],
    "energy":      ["refinery", "pipeline", "drilling", "flaring", "rig"],
    "corporate":   ["corporate jet", "executive", "M&A", "headquarter"],
}


class ThesisOrchestrator:
    """Converts PM theses and portfolio positions into actionable SensorTasking
    objects that flow through the rest of the Sentinel pipeline.

    Lifecycle:
        1. ``process_thesis`` -- take free-form text and produce taskings.
        2. ``auto_monitor_portfolio`` -- scan every position and generate
           taskings for all known physical footprints.
    """

    def __init__(self) -> None:
        self._facility_db = _FACILITY_DB
        logger.info(
            f"ThesisOrchestrator initialised with "
            f"{len(self._facility_db)} tickers, "
            f"{sum(len(v) for v in self._facility_db.values())} facilities"
        )

    # ------------------------------------------------------------------
    # Primary public methods
    # ------------------------------------------------------------------

    async def process_thesis(
        self,
        thesis: ThesisInput,
        portfolio: Portfolio,
    ) -> list[SensorTasking]:
        """Parse a PM's natural-language thesis and produce SensorTasking list.

        Steps:
            1. Extract tickers mentioned (or use the one attached to the thesis).
            2. Identify monitoring objectives from keywords.
            3. Map tickers to GeoTargets via the built-in knowledge base.
            4. Create SensorTasking objects, choosing optimal sensors
               based on the objective.
        """
        logger.info(f"Processing thesis: {thesis.text[:120]}...")

        # Step 1 -- extract tickers
        tickers = self._extract_tickers(thesis.text, portfolio)
        if thesis.ticker and thesis.ticker.upper() not in tickers:
            tickers.append(thesis.ticker.upper())
        if not tickers:
            logger.warning("No tickers identified in thesis or portfolio")
            return []

        logger.info(f"Tickers extracted: {tickers}")

        # Step 2 -- identify monitoring objectives
        objectives = self._extract_objectives(thesis.text)
        logger.info(f"Monitoring objectives: {objectives}")

        # Step 3 -- map tickers to GeoTargets
        taskings: list[SensorTasking] = []
        priority = self._thesis_priority_score(thesis.priority)

        for ticker in tickers:
            geo_targets = self.get_geo_targets_for_ticker(ticker)
            if not geo_targets:
                logger.warning(f"No facility data for {ticker}")
                continue

            # Enrich the portfolio position with geo targets if it exists
            position = portfolio.get_position(ticker)
            if position:
                position.geo_targets = geo_targets

            # Step 4 -- create SensorTasking per target
            for gt in geo_targets:
                sensors = self._choose_sensors(gt, objectives)
                for sensor in sensors:
                    tasking = SensorTasking(
                        id=uuid.uuid4().hex[:12],
                        geo_target=gt,
                        sensor_type=sensor,
                        priority=priority,
                        requested_at=datetime.utcnow(),
                        status="pending",
                    )
                    taskings.append(tasking)

        logger.info(
            f"Thesis produced {len(taskings)} sensor taskings "
            f"across {len(tickers)} tickers"
        )
        return taskings

    async def auto_monitor_portfolio(
        self,
        portfolio: Portfolio,
    ) -> list[SensorTasking]:
        """Generate SensorTasking for every position in the portfolio by
        mapping each ticker to its known physical facilities.

        This is the 'always-on' monitoring layer that runs on a schedule
        independently of any explicit thesis.
        """
        logger.info(
            f"Auto-monitoring portfolio: {portfolio.fund_name} "
            f"({len(portfolio.positions)} positions)"
        )

        taskings: list[SensorTasking] = []
        for position in portfolio.positions:
            ticker = position.ticker.upper()
            geo_targets = self.get_geo_targets_for_ticker(ticker)
            if not geo_targets:
                continue

            position.geo_targets = geo_targets
            for gt in geo_targets:
                for sensor in gt.monitoring_sensors:
                    tasking = SensorTasking(
                        id=uuid.uuid4().hex[:12],
                        geo_target=gt,
                        sensor_type=sensor,
                        priority=self._position_priority(position),
                        requested_at=datetime.utcnow(),
                        status="pending",
                    )
                    taskings.append(tasking)

        logger.info(f"Auto-monitor generated {len(taskings)} taskings")
        return taskings

    def get_geo_targets_for_ticker(self, ticker: str) -> list[GeoTarget]:
        """Return all known physical GeoTargets for a ticker symbol."""
        ticker = ticker.upper()
        facilities = self._facility_db.get(ticker, [])
        targets: list[GeoTarget] = []
        for name, lat, lon, target_type, sensors in facilities:
            targets.append(
                GeoTarget(
                    id=uuid.uuid4().hex[:12],
                    name=name,
                    latitude=lat,
                    longitude=lon,
                    radius_km=self._radius_for_type(target_type),
                    target_type=target_type,
                    asset_ticker=ticker,
                    monitoring_sensors=sensors,
                    active=True,
                    created_at=datetime.utcnow(),
                )
            )
        return targets

    # ------------------------------------------------------------------
    # Thesis text parsing helpers
    # ------------------------------------------------------------------

    def _extract_tickers(
        self, text: str, portfolio: Portfolio
    ) -> list[str]:
        """Extract ticker symbols from free-form text.

        Uses three strategies in order:
            1. Explicit $TICKER notation.
            2. Known tickers from the facility DB that appear in the text.
            3. Tickers from the portfolio that appear in the text.
        """
        found: list[str] = []

        # Strategy 1: $TICKER
        dollar_tickers = re.findall(r"\$([A-Z]{1,6})", text.upper())
        found.extend(dollar_tickers)

        # Strategy 2: known tickers in facility DB
        text_upper = text.upper()
        for ticker in self._facility_db:
            # Require word-boundary match to avoid false positives
            if re.search(rf"\b{re.escape(ticker)}\b", text_upper):
                if ticker not in found:
                    found.append(ticker)

        # Strategy 3: portfolio tickers
        for pos in portfolio.positions:
            t = pos.ticker.upper()
            if t in text_upper and t not in found:
                found.append(t)

        # Strategy 4: company name matching (partial)
        name_map: dict[str, str] = {
            "TESLA": "TSLA", "EXXON": "XOM", "APPLE": "AAPL",
            "NVIDIA": "NVDA", "MICROSOFT": "MSFT", "GOOGLE": "GOOGL",
            "AMAZON": "AMZN", "WALMART": "WMT", "TARGET": "TGT",
            "COSTCO": "COST", "FREEPORT": "FCX", "BOEING": "BA",
            "LOCKHEED": "LMT", "RAYTHEON": "RTX", "CHEVRON": "CVX",
            "CONOCO": "COP", "OCCIDENTAL": "OXY", "FORD": "F",
            "RIVIAN": "RIVN", "INTEL": "INTC", "NIKE": "NKE",
            "COCA-COLA": "KO", "COCA COLA": "KO", "PFIZER": "PFE",
            "JOHNSON & JOHNSON": "JNJ", "J&J": "JNJ",
            "ELI LILLY": "LLY", "LILLY": "LLY",
            "HOME DEPOT": "HD", "FEDEX": "FDX", "MAERSK": "MAERSK.CO",
            "NEWMONT": "NEM", "BHP": "BHP", "RIO TINTO": "RIO",
            "VALE": "VALE", "META": "META", "FACEBOOK": "META",
        }
        for name, ticker in name_map.items():
            if name in text_upper and ticker not in found:
                found.append(ticker)

        return found

    def _extract_objectives(self, text: str) -> list[str]:
        """Identify monitoring objectives from the thesis text."""
        text_lower = text.lower()
        objectives: list[str] = []
        for objective, keywords in _OBJECTIVE_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    if objective not in objectives:
                        objectives.append(objective)
                    break
        # Default: production monitoring
        if not objectives:
            objectives.append("production")
        return objectives

    def _choose_sensors(
        self,
        geo_target: GeoTarget,
        objectives: list[str],
    ) -> list[str]:
        """Pick the optimal sensor set given a GeoTarget and the thesis
        objectives.  Always returns at least one sensor.
        """
        sensors: set[str] = set()

        # Base sensors from the GeoTarget definition
        sensors.update(geo_target.monitoring_sensors)

        # Add AIS if the thesis mentions logistics and the target is a port
        if "logistics" in objectives and geo_target.target_type in ("port", "facility"):
            sensors.add("ais")

        # Add ADSB for corporate-activity monitoring
        if "corporate" in objectives:
            sensors.add("adsb")

        # If mining objective, prefer SAR (works through dust and night)
        if "mining" in objectives:
            sensors.add("sar")

        # Ensure we always have at least optical
        if not sensors:
            sensors.add("optical")

        return sorted(sensors)

    # ------------------------------------------------------------------
    # Priority helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _thesis_priority_score(priority_str: str) -> int:
        """Map thesis priority string to an integer (1=highest)."""
        return {"critical": 1, "high": 2, "normal": 5, "low": 8}.get(
            priority_str.lower(), 5
        )

    @staticmethod
    def _position_priority(position: Position) -> int:
        """Derive a tasking priority from position characteristics."""
        # Larger positions get higher (lower number) priority
        if position.shares > 100_000:
            return 2
        if position.shares > 10_000:
            return 4
        return 6

    @staticmethod
    def _radius_for_type(target_type: str) -> float:
        """Default geofence radius in km by target type."""
        return {
            "facility": 15.0,
            "hq": 10.0,
            "mine": 30.0,
            "port": 25.0,
            "pipeline": 40.0,
            "airfield": 20.0,
        }.get(target_type, 15.0)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Trade proposal helpers
    # ------------------------------------------------------------------

    _BULLISH_KEYWORDS = [
        "growth", "ramp", "increase", "expansion", "bullish", "long",
        "buy", "upside", "production increase", "surge", "accelerat",
        "record output", "strong demand", "beat", "outperform",
    ]
    _BEARISH_KEYWORDS = [
        "decline", "shutdown", "disruption", "bearish", "short",
        "sell", "downside", "risk", "slowdown", "drop", "decrease",
        "underperform", "miss", "weak", "closure", "idle",
    ]

    @classmethod
    def _infer_side(cls, thesis_text: str) -> PositionSide:
        """Infer LONG or SHORT from thesis keywords."""
        text_lower = thesis_text.lower()
        bull = sum(1 for kw in cls._BULLISH_KEYWORDS if kw in text_lower)
        bear = sum(1 for kw in cls._BEARISH_KEYWORDS if kw in text_lower)
        return PositionSide.SHORT if bear > bull else PositionSide.LONG

    def build_trade_proposal(
        self,
        thesis: ThesisInput,
        portfolio: Portfolio,
        stock_client=None,
    ) -> Optional[TradeProposal]:
        """Build a TradeProposal from a thesis for user confirmation."""
        tickers = self._extract_tickers(thesis.text, portfolio)
        if thesis.ticker and thesis.ticker.upper() not in tickers:
            tickers.append(thesis.ticker.upper())
        if not tickers:
            return None

        ticker = tickers[0]
        side = self._infer_side(thesis.text)
        geo_targets = self.get_geo_targets_for_ticker(ticker)

        current_price = None
        name = ticker
        sector = None

        if stock_client:
            current_price = stock_client.get_current_price(ticker)
            info = stock_client.get_company_info(ticker)
            name = info.get("name", ticker)
            sector = info.get("sector")

        return TradeProposal(
            ticker=ticker,
            name=name,
            side=side,
            suggested_shares=100,
            current_price=current_price,
            sector=sector,
            thesis=thesis.text,
            geo_targets=geo_targets,
            confidence=0.75,
        )

    @property
    def supported_tickers(self) -> list[str]:
        """Return all tickers that have facility data."""
        return sorted(self._facility_db.keys())

    @property
    def total_facilities(self) -> int:
        return sum(len(v) for v in self._facility_db.values())
