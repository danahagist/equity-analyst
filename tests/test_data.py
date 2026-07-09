"""Data-access layer tests (offline)."""

from __future__ import annotations

import pandas as pd

from equity_analyst.data import PRICE_COLUMNS, MarketDataSource, YahooDataSource, normalize_prices
from tests.fixtures import FakeDataSource, synthetic_prices


def test_yahoo_source_satisfies_protocol() -> None:
    # Structural check only — no network call.
    assert isinstance(YahooDataSource(), MarketDataSource)


def test_fake_source_satisfies_protocol() -> None:
    assert isinstance(FakeDataSource(), MarketDataSource)


def test_synthetic_prices_shape() -> None:
    df = synthetic_prices(days=120)
    assert list(df.columns) == PRICE_COLUMNS
    assert len(df) == 120
    assert df["date"].is_monotonic_increasing
    assert (df["high"] >= df["low"]).all()
    assert (df["close"] > 0).all()


def test_normalize_prices_maps_yfinance_columns() -> None:
    raw = pd.DataFrame(
        {
            "Open": [1.0, 2.0],
            "High": [2.0, 3.0],
            "Low": [0.5, 1.5],
            "Close": [1.5, 2.5],
            "Volume": [100, 200],
        },
        index=pd.DatetimeIndex(
            pd.to_datetime(["2024-01-02", "2024-01-03"]).tz_localize("America/New_York"),
            name="Date",
        ),
    )
    out = normalize_prices(raw)
    assert list(out.columns) == PRICE_COLUMNS
    assert out["date"].dt.tz is None  # tz stripped
    assert out["close"].tolist() == [1.5, 2.5]


def test_fetch_many_collects_failures_and_preserves_order() -> None:
    from equity_analyst.data.base import DataUnavailable, fetch_many

    def fetch(key: str) -> str:
        if key == "BAD":
            raise DataUnavailable("nothing usable")
        return f"ok-{key}"

    results, failures = fetch_many(["aaa", "BAD", "bbb"], fetch, delay=0)
    assert list(results) == ["AAA", "BBB"]  # uppercased, input order, BAD skipped
    assert results["AAA"] == "ok-AAA"
    assert failures == [("BAD", "nothing usable")]


def test_fetch_many_retries_rate_limits_but_not_other_errors() -> None:
    from equity_analyst.data.base import DataUnavailable, fetch_many

    calls: dict[str, int] = {"LIMITED": 0, "GONE": 0}

    def fetch(key: str) -> str:
        calls[key] += 1
        if key == "LIMITED" and calls[key] == 1:
            raise DataUnavailable("HTTP 429 Too Many Requests")
        if key == "GONE":
            raise DataUnavailable("no data returned")
        return "ok"

    results, failures = fetch_many(["LIMITED", "GONE"], fetch, delay=0, backoff=0)
    assert results == {"LIMITED": "ok"}
    assert calls["LIMITED"] == 2  # one retry after the 429
    assert calls["GONE"] == 1  # non-rate-limit errors fail fast
    assert failures == [("GONE", "no data returned")]


def test_data_unavailable_importable_from_both_modules() -> None:
    # The exception moved to the interface module; the yahoo re-export must
    # keep every existing `from ...yahoo import DataUnavailable` working.
    from equity_analyst.data.base import DataUnavailable as from_base
    from equity_analyst.data.yahoo import DataUnavailable as from_yahoo

    assert from_base is from_yahoo
