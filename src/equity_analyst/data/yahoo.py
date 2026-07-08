"""Yahoo Finance data source (via ``yfinance``).

Free and keyless, but unofficial and prone to breakage/rate-limits — which is
exactly why it lives behind :class:`~equity_analyst.data.base.MarketDataSource`.
Network egress to Yahoo may be blocked in some environments; callers should treat
:class:`DataUnavailable` as a normal, recoverable condition.
"""

from __future__ import annotations

import pandas as pd

from equity_analyst.data.base import PRICE_COLUMNS


class DataUnavailable(RuntimeError):
    """Raised when the source cannot be reached or returns nothing usable."""


class YahooDataSource:
    """:class:`~equity_analyst.data.base.MarketDataSource` backed by ``yfinance``."""

    def _ticker(self, ticker: str):
        import yfinance as yf  # imported lazily so the package loads without network deps

        return yf.Ticker(ticker)

    def get_prices(self, ticker: str, *, period: str = "5y") -> pd.DataFrame:
        try:
            raw = self._ticker(ticker).history(period=period, auto_adjust=True)
        except Exception as exc:  # noqa: BLE001 - normalize any yfinance/network error
            raise DataUnavailable(f"could not fetch prices for {ticker!r}: {exc}") from exc
        if raw is None or raw.empty:
            raise DataUnavailable(f"no price data returned for {ticker!r}")
        return normalize_prices(raw)

    def get_fundamentals(self, ticker: str) -> dict:
        try:
            info = self._ticker(ticker).info
        except Exception as exc:  # noqa: BLE001
            raise DataUnavailable(f"could not fetch fundamentals for {ticker!r}: {exc}") from exc
        return {key: info.get(key) for key in _FUNDAMENTAL_KEYS if info.get(key) is not None}

    def get_analyst_info(self, ticker: str) -> dict:
        try:
            info = self._ticker(ticker).info
        except Exception as exc:  # noqa: BLE001
            raise DataUnavailable(f"could not fetch analyst info for {ticker!r}: {exc}") from exc
        return {key: info.get(key) for key in _ANALYST_KEYS if info.get(key) is not None}


def normalize_prices(raw: pd.DataFrame) -> pd.DataFrame:
    """Coerce a ``yfinance`` history frame into the canonical tidy price frame."""
    df = raw.reset_index().rename(
        columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df[PRICE_COLUMNS].sort_values("date").reset_index(drop=True)
    return df


_FUNDAMENTAL_KEYS = (
    "longName",
    "sector",
    "industry",
    "marketCap",
    "trailingPE",
    "forwardPE",
    "priceToBook",
    "profitMargins",
    "grossMargins",
    "operatingMargins",
    "returnOnEquity",
    "totalRevenue",
    "revenueGrowth",
    "earningsGrowth",
    "totalDebt",
    "totalCash",
    "freeCashflow",
    "debtToEquity",
    "currentPrice",
)

_ANALYST_KEYS = (
    "recommendationKey",
    "recommendationMean",
    "numberOfAnalystOpinions",
    "targetMeanPrice",
    "targetHighPrice",
    "targetLowPrice",
    "targetMedianPrice",
)
