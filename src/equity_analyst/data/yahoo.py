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

    def get_etf_holdings(self, etf: str) -> dict[str, float]:
        """Return ``{symbol: weight_fraction}`` for an ETF's (top) holdings.

        yfinance exposes only the top holdings, not the full basket — enough to
        tell whether a stock is a *meaningful* position, which is what the
        exposure screen cares about. Raises DataUnavailable if the ticker isn't
        a fund or returns nothing.
        """
        try:
            top = self._ticker(etf).funds_data.top_holdings
        except Exception as exc:  # noqa: BLE001
            raise DataUnavailable(f"could not fetch holdings for {etf!r}: {exc}") from exc
        if top is None or top.empty:
            raise DataUnavailable(f"no holdings returned for {etf!r} (not an ETF?)")
        col = "Holding Percent" if "Holding Percent" in top.columns else top.columns[-1]
        holdings: dict[str, float] = {}
        for symbol, row in top.iterrows():
            weight = row.get(col)
            if weight is not None and weight == weight:  # NaN guard
                holdings[str(symbol).upper()] = float(weight)
        return holdings

    def get_fund_profile(self, etf: str) -> str:
        """Return the fund's own description text (what it tracks / holds).

        Tries the funds-data description first, then the general business
        summary. Raises DataUnavailable when neither exists.
        """
        description = None
        try:
            description = self._ticker(etf).funds_data.description
        except Exception:  # noqa: BLE001 - fall through to the info summary
            pass
        if not description:
            try:
                description = self._ticker(etf).info.get("longBusinessSummary")
            except Exception as exc:  # noqa: BLE001
                raise DataUnavailable(f"could not fetch profile for {etf!r}: {exc}") from exc
        if not description:
            raise DataUnavailable(f"no fund description available for {etf!r}")
        return str(description)


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
