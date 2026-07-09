"""SQLite storage round-trip tests (in-memory)."""

from __future__ import annotations

import pandas as pd

from equity_analyst.storage import (
    connect,
    load_latest_fundamentals,
    load_prices,
    save_fundamentals,
    upsert_prices,
)
from tests.fixtures import synthetic_prices


def test_prices_round_trip() -> None:
    conn = connect(":memory:")
    prices = synthetic_prices(days=50)
    written = upsert_prices(conn, "TEST", prices)
    assert written == 50

    loaded = load_prices(conn, "TEST")
    assert len(loaded) == 50
    # Close values survive the round trip (float tolerance).
    assert loaded["close"].round(6).tolist() == prices["close"].round(6).tolist()
    assert loaded["date"].tolist() == pd.to_datetime(prices["date"].dt.date).tolist()


def test_upsert_is_idempotent() -> None:
    conn = connect(":memory:")
    prices = synthetic_prices(days=30)
    upsert_prices(conn, "TEST", prices)
    upsert_prices(conn, "TEST", prices)  # same rows again
    assert len(load_prices(conn, "TEST")) == 30  # no duplicates


def test_load_prices_empty_for_unknown_ticker() -> None:
    conn = connect(":memory:")
    assert load_prices(conn, "NOPE").empty


def test_fundamentals_round_trip() -> None:
    conn = connect(":memory:")
    assert load_latest_fundamentals(conn, "TEST") is None
    save_fundamentals(
        conn, "TEST", {"marketCap": 123, "sector": "Tech"}, as_of="2026-07-08T00:00:00"
    )
    save_fundamentals(conn, "TEST", {"marketCap": 456}, as_of="2026-07-08T12:00:00")
    latest = load_latest_fundamentals(conn, "TEST")
    assert latest == {"marketCap": 456}  # most recent snapshot wins
