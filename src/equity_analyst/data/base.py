"""Data-access interface.

Every market-data source implements :class:`MarketDataSource`. The rest of the
codebase depends only on this protocol, so swapping ``yfinance`` for a keyed API
(Alpha Vantage, FMP, ...) later is a single-file change. See CLAUDE.md.

Also home to :func:`fetch_many`, the one fetch-loop used by every bulk sweep
(screen, ETF holdings/profiles/stats) — pacing, progress, failure collection,
and rate-limit backoff live here once instead of in four hand-rolled copies.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from typing import Protocol, TypeVar, runtime_checkable

import pandas as pd

# Canonical tidy price frame: one row per trading day, these columns exactly.
PRICE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class DataUnavailable(RuntimeError):
    """Raised when a source cannot be reached or returns nothing usable.

    Lives in the interface module (not the yfinance implementation) because
    every consumer catches it — it is part of the data contract.
    """


T = TypeVar("T")

_RATE_LIMITED = re.compile(r"429|rate.?limit|too many requests", re.IGNORECASE)


def fetch_many(
    items: Iterable[str],
    fetch: Callable[[str], T],
    *,
    delay: float = 0.3,
    progress: Callable[[str], None] | None = None,
    label: str = "fetch",
    progress_every: int = 10,
    retries: int = 2,
    backoff: float = 2.0,
) -> tuple[dict[str, T], list[tuple[str, str]]]:
    """Fetch each item, collecting failures instead of aborting.

    Returns ``(results, failures)`` with input order preserved in ``results``.
    A :class:`DataUnavailable` whose message looks rate-limited is retried up
    to ``retries`` times with exponential backoff (``backoff * 2**attempt``
    seconds); other failures are recorded and skipped immediately — at
    universe scale, partial coverage is the normal case and must be disclosed
    by the caller, not fatal.
    """
    keys = [str(item).upper() for item in items]
    results: dict[str, T] = {}
    failures: list[tuple[str, str]] = []
    for i, key in enumerate(keys):
        if progress and (i % progress_every == 0 or i == len(keys) - 1):
            progress(f"{label} {i + 1}/{len(keys)} ({key})")
        attempt = 0
        while True:
            try:
                results[key] = fetch(key)
                break
            except DataUnavailable as exc:
                if attempt < retries and _RATE_LIMITED.search(str(exc)):
                    time.sleep(backoff * (2**attempt))
                    attempt += 1
                    continue
                failures.append((key, str(exc)))
                break
        if delay and i < len(keys) - 1:
            time.sleep(delay)
    return results, failures


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
