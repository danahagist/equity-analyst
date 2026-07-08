"""Deterministic synthetic market data for tests (no network).

A geometric-random-walk price series with a fixed seed, so tests are reproducible
and the forecasting engine has realistic-looking input to backtest against.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from equity_analyst.data.base import PRICE_COLUMNS


def synthetic_prices(
    *, days: int = 400, start: str = "2023-01-02", seed: int = 7, start_price: float = 100.0
) -> pd.DataFrame:
    """Return a canonical tidy price frame of ``days`` business days of OHLCV."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=days)
    returns = rng.normal(loc=0.0004, scale=0.015, size=days)
    close = start_price * np.exp(np.cumsum(returns))
    intraday = np.abs(rng.normal(scale=0.008, size=days))
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": close * (1 - rng.normal(scale=0.004, size=days)),
            "high": close * (1 + intraday),
            "low": close * (1 - intraday),
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, size=days).astype(float),
        }
    )
    return frame[PRICE_COLUMNS]


class FakeDataSource:
    """A :class:`~equity_analyst.data.base.MarketDataSource` serving fixtures offline."""

    def __init__(self, *, days: int = 400) -> None:
        self._days = days

    def get_prices(self, ticker: str, *, period: str = "5y") -> pd.DataFrame:
        return synthetic_prices(days=self._days, seed=abs(hash(ticker)) % 1000)

    def get_fundamentals(self, ticker: str) -> dict:
        return {"longName": f"{ticker} Inc.", "sector": "Technology", "marketCap": 1_000_000_000}

    def get_analyst_info(self, ticker: str) -> dict:
        return {"recommendationKey": "buy", "numberOfAnalystOpinions": 20, "targetMeanPrice": 150.0}
