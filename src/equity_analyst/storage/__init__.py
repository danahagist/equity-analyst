"""SQLite persistence: the system of record."""

from equity_analyst.storage.db import connect, init_schema
from equity_analyst.storage.repository import (
    load_latest_fundamentals,
    load_prices,
    save_fundamentals,
    upsert_prices,
)

__all__ = [
    "connect",
    "init_schema",
    "upsert_prices",
    "load_prices",
    "save_fundamentals",
    "load_latest_fundamentals",
]
