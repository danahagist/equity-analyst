"""Forecasting engine tests. Skipped unless the ``forecast`` extra is installed."""

from __future__ import annotations

import pytest

pytest.importorskip("statsforecast", reason="install the 'forecast' extra")

from equity_analyst.forecast.engine import BASELINE_NAME, ForecastEngine  # noqa: E402
from equity_analyst.forecast.types import ForecastResult  # noqa: E402
from tests.fixtures import synthetic_prices  # noqa: E402


@pytest.fixture(scope="module")
def result() -> ForecastResult:
    prices = synthetic_prices(days=900, seed=42)
    return ForecastEngine().forecast("TEST", prices)


def test_returns_all_horizons(result: ForecastResult) -> None:
    assert [h.label for h in result.horizons] == ["1d", "1w", "1m", "1y"]
    assert result.ticker == "TEST"
    # Statistical models always run; LGB joins when history supports conformal.
    assert {BASELINE_NAME, "Theta", "AutoETS", "AutoARIMA"} <= set(result.models_considered)
    assert "LGB" in result.models_considered  # 900 bars is plenty


def test_intervals_are_ordered_and_contain_point(result: ForecastResult) -> None:
    for h in result.horizons:
        assert h.lower <= h.point <= h.upper


def test_intervals_widen_with_horizon(result: ForecastResult) -> None:
    # Different models may win different horizons, so adjacent widths aren't
    # strictly monotone — but 1y must be far wider than 1d (honest uncertainty).
    widths = {h.label: h.upper - h.lower for h in result.horizons}
    assert widths["1y"] > widths["1m"] > widths["1d"]


def test_honesty_flags_are_consistent(result: ForecastResult) -> None:
    for h in result.horizons:
        if not h.beats_baseline:
            assert h.model == BASELINE_NAME
            assert h.note  # a caveat is always attached when we fall back
        else:
            assert h.model != BASELINE_NAME
        assert h.n_backtest_windows >= 1  # 900 bars backtests every horizon


def test_expected_return_matches_point(result: ForecastResult) -> None:
    for h in result.horizons:
        expected = h.point / result.last_price - 1.0
        assert h.metrics["expected_return"] == pytest.approx(expected, abs=1e-4)


def test_short_history_flags_long_horizon() -> None:
    # ~150 bars: enough for short horizons, too short to backtest 1y (252d).
    prices = synthetic_prices(days=150, seed=1)
    res = ForecastEngine().forecast("SHORT", prices)
    year = res.by_label("1y")
    assert year is not None
    assert year.model == BASELINE_NAME
    assert year.n_backtest_windows == 0
    assert "too short" in year.note


def test_raises_on_insufficient_data() -> None:
    prices = synthetic_prices(days=50, seed=1)
    with pytest.raises(ValueError, match="at least"):
        ForecastEngine().forecast("TINY", prices)
