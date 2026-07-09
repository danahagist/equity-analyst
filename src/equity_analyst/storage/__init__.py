"""SQLite persistence: the system of record."""

from equity_analyst.storage.db import connect, init_schema
from equity_analyst.storage.repository import (
    load_latest_fundamentals,
    load_prices,
    load_screen_results,
    save_forecast_rows,
    save_fundamentals,
    save_run,
    save_screen_results,
    upsert_prices,
)

__all__ = [
    "connect",
    "init_schema",
    "upsert_prices",
    "load_prices",
    "save_fundamentals",
    "load_latest_fundamentals",
    "save_run",
    "save_forecast_rows",
    "save_screen_results",
    "load_screen_results",
]
