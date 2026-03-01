"""Stock Market Data Client for backtesting and real-time prices."""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger


class StockDataClient:
    """Yahoo Finance client for stock price data and financial analysis."""

    def __init__(self):
        self._cache: dict[str, pd.DataFrame] = {}
        self._info_cache: dict[str, dict] = {}

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get the latest price for a ticker."""
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            return float(info.get("lastPrice", info.get("previousClose", 0)))
        except Exception as e:
            logger.error(f"Price fetch error for {ticker}: {e}")
            return None

    def get_historical_prices(
        self, ticker: str, period_years: int = 10
    ) -> Optional[pd.DataFrame]:
        """Get historical daily price data."""
        cache_key = f"{ticker}_{period_years}y"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            t = yf.Ticker(ticker)
            df = t.history(period=f"{period_years}y")
            if df.empty:
                return None
            self._cache[cache_key] = df
            return df
        except Exception as e:
            logger.error(f"Historical data error for {ticker}: {e}")
            return None

    def get_company_info(self, ticker: str) -> dict:
        """Get company fundamental info."""
        if ticker in self._info_cache:
            return self._info_cache[ticker]

        try:
            t = yf.Ticker(ticker)
            info = t.info
            result = {
                "ticker": ticker,
                "name": info.get("longName", ticker),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                "market_cap": info.get("marketCap", 0),
                "revenue": info.get("totalRevenue", 0),
                "employees": info.get("fullTimeEmployees", 0),
                "country": info.get("country", ""),
                "website": info.get("website", ""),
                "description": info.get("longBusinessSummary", "")[:500],
            }
            self._info_cache[ticker] = result
            return result
        except Exception as e:
            logger.error(f"Company info error for {ticker}: {e}")
            return {"ticker": ticker, "name": ticker}

    def calculate_event_correlation(
        self,
        ticker: str,
        event_dates: list[datetime],
        window_days: int = 14,
        direction: str = "negative",  # "negative" for drops, "positive" for rallies
    ) -> dict:
        """Calculate how a stock historically reacted to events on specific dates.

        This is the core of the Quant Regression Agent's backtest.
        Returns R-squared, average impact, and prediction.
        """
        df = self.get_historical_prices(ticker, period_years=10)
        if df is None or len(event_dates) < 3:
            return {
                "r_squared": 0.0,
                "avg_impact_pct": 0.0,
                "sample_size": 0,
                "is_material": False,
                "prediction_window_days": window_days,
            }

        impacts = []
        for event_date in event_dates:
            try:
                # Find the closest trading day
                idx = df.index.get_indexer([event_date], method="nearest")[0]
                if idx < 0 or idx + window_days >= len(df):
                    continue

                pre_price = df.iloc[idx]["Close"]
                post_price = df.iloc[idx + window_days]["Close"]
                impact_pct = ((post_price - pre_price) / pre_price) * 100
                impacts.append(impact_pct)
            except (IndexError, KeyError):
                continue

        if len(impacts) < 2:
            return {
                "r_squared": 0.0,
                "avg_impact_pct": 0.0,
                "sample_size": len(impacts),
                "is_material": False,
                "prediction_window_days": window_days,
            }

        avg_impact = np.mean(impacts)
        std_impact = np.std(impacts)

        # Calculate consistency (pseudo R-squared based on signal-to-noise)
        if std_impact > 0:
            consistency = min(1.0, abs(avg_impact) / std_impact)
        else:
            consistency = 1.0 if avg_impact != 0 else 0.0

        # Direction check: are impacts consistently in the expected direction?
        if direction == "negative":
            directional_pct = sum(1 for x in impacts if x < 0) / len(impacts)
        else:
            directional_pct = sum(1 for x in impacts if x > 0) / len(impacts)

        r_squared = consistency * directional_pct

        return {
            "r_squared": round(r_squared, 4),
            "avg_impact_pct": round(avg_impact, 2),
            "std_impact_pct": round(std_impact, 2),
            "directional_consistency": round(directional_pct, 2),
            "sample_size": len(impacts),
            "impacts": [round(x, 2) for x in impacts],
            "is_material": r_squared >= 0.3,  # 30% threshold
            "prediction_window_days": window_days,
        }

    def get_sector_peers(self, ticker: str, limit: int = 5) -> list[str]:
        """Get peer tickers in the same sector."""
        info = self.get_company_info(ticker)
        sector = info.get("sector", "")
        if not sector:
            return []

        # Common sector ETFs and large caps as proxies
        sector_map = {
            "Technology": ["AAPL", "MSFT", "GOOGL", "NVDA", "META"],
            "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
            "Consumer Cyclical": ["AMZN", "TSLA", "HD", "NKE", "MCD"],
            "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK"],
            "Financial Services": ["JPM", "BAC", "GS", "MS", "WFC"],
            "Industrials": ["CAT", "HON", "UPS", "BA", "GE"],
            "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST"],
            "Basic Materials": ["LIN", "APD", "FCX", "NEM", "DOW"],
            "Real Estate": ["AMT", "PLD", "CCI", "SPG", "EQIX"],
            "Utilities": ["NEE", "DUK", "SO", "AEP", "D"],
            "Communication Services": ["GOOGL", "META", "DIS", "NFLX", "CMCSA"],
        }
        peers = sector_map.get(sector, [])
        return [p for p in peers if p != ticker.upper()][:limit]

    def get_source_provenance(self) -> dict:
        return {
            "source_type": "api",
            "source_url": "https://finance.yahoo.com",
            "source_provider": "Yahoo Finance",
            "is_publicly_available": True,
            "mnpi_classification": "PUBLIC_OSINT",
        }
