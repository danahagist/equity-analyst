"""Data-access interface.

Every market-data source implements :class:`MarketDataSource`. The rest of the
codebase depends only on this protocol, so swapping ``yfinance`` for a keyed API
(Alpha Vantage, FMP, ...) later is a single-file change. See CLAUDE.md.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

# Canonical tidy price frame: one row per trading day, these columns exactly.
PRICE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


@runtime_checkable
class MarketDataSource(Protocol):
    """A source of price history and fundamentals for a single ticker."""

    def get_prices(self, ticker: str, *, period: str = "5y") -> pd.DataFrame:
        """Return daily OHLCV as a tidy frame with :data:`PRICE_COLUMNS`.

        ``date`` is timezone-naive ``datetime64``, ascending. Adjusted close.
        """
        ...

    def get_fundamentals(self, ticker: str) -> dict:
        """Return a flat dict of fundamental facts (market cap, margins, ...)."""
        ...

    def get_analyst_info(self, ticker: str) -> dict:
        """Return third-party analyst data (ratings, price targets) if available."""
        ...
