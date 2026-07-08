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
