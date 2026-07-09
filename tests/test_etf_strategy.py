"""ETF strategy tests: greedy coverage, overlap awareness, stats math, honesty."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_analyst.etf_strategy import (
    basket_correlations,
    build_basket,
    build_strategy_report,
    compute_stats,
    fetch_stats,
)


def test_greedy_basket_is_overlap_aware() -> None:
    # FUND_A holds the two highest-scored names; FUND_B duplicates one of them
    # plus a new one; FUND_C only duplicates. Greedy must pick A, then B for its
    # MARGINAL name, and never C (no new coverage).
    candidates = [("AAA", 0.9), ("BBB", 0.8), ("CCC", 0.7)]
    holdings = {
        "FUND_A": {"AAA": 0.10, "BBB": 0.05},
        "FUND_B": {"AAA": 0.20, "CCC": 0.04},
        "FUND_C": {"AAA": 0.05, "BBB": 0.03},  # same names as A, less weight
    }
    picks, uncovered = build_basket(candidates, holdings, max_etfs=5)
    assert [p.etf for p in picks] == ["FUND_A", "FUND_B"]
    assert picks[1].marginal == {"CCC": 0.04}  # AAA excluded: already covered
    assert picks[1].overlap == {"AAA": 0.20}  # ...but disclosed as overlap
    assert uncovered == []


def test_basket_stops_early_and_reports_uncovered() -> None:
    candidates = [("AAA", 0.9), ("ZZZ", 0.5)]
    holdings = {"FUND_A": {"AAA": 0.10}}
    picks, uncovered = build_basket(candidates, holdings, max_etfs=5)
    assert len(picks) == 1
    assert uncovered == ["ZZZ"]


def test_basket_prefers_higher_blended_mass() -> None:
    # FUND_B covers one 0.9-name; FUND_A covers two names worth 0.5+0.5=1.0.
    candidates = [("HI", 0.9), ("LO1", 0.5), ("LO2", 0.5)]
    holdings = {"FUND_A": {"LO1": 0.02, "LO2": 0.02}, "FUND_B": {"HI": 0.30}}
    picks, _ = build_basket(candidates, holdings, max_etfs=1)
    assert picks[0].etf == "FUND_A"


def _price_frame(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"date": dates, "close": closes})


def test_compute_stats_math() -> None:
    # Deterministic geometric growth: +0.1% every day for 2 years.
    closes = list(100 * (1.001 ** np.arange(504)))
    stats = compute_stats(_price_frame(closes), spy_returns=None)
    assert stats["years"] == pytest.approx(2.0, abs=0.1)
    assert stats["cagr"] == pytest.approx(1.001**252 - 1, rel=1e-6)
    assert stats["ann_vol"] == pytest.approx(0.0, abs=1e-9)  # constant returns
    assert stats["max_drawdown"] == pytest.approx(0.0, abs=1e-9)  # monotonic rise
    # iloc[-252] is 251 growth steps before the last close
    assert stats["total_return_1y"] == pytest.approx(1.001**251 - 1, rel=1e-6)


def test_compute_stats_rejects_short_history() -> None:
    stats = compute_stats(_price_frame([100.0] * 30), spy_returns=None)
    assert "too short" in stats["error"]


def test_beta_of_self_is_one() -> None:
    rng = np.random.default_rng(7)
    closes = list(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 400)))
    frame = _price_frame(closes)
    self_returns = frame.set_index("date")["close"].pct_change().dropna()
    stats = compute_stats(frame, spy_returns=self_returns)
    assert stats["beta_vs_spy"] == pytest.approx(1.0, abs=1e-9)


class _FakeSource:
    """MarketDataSource stub serving canned price frames."""

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames

    def get_prices(self, ticker: str, *, period: str = "5y") -> pd.DataFrame:
        from equity_analyst.data.yahoo import DataUnavailable

        if ticker not in self.frames:
            raise DataUnavailable(f"no data for {ticker}")
        return self.frames[ticker]

    def get_fundamentals(self, ticker: str) -> dict:  # pragma: no cover - protocol
        return {}

    def get_analyst_info(self, ticker: str) -> dict:  # pragma: no cover - protocol
        return {}


def test_fetch_stats_survives_missing_fund_and_spy() -> None:
    rng = np.random.default_rng(3)
    good = _price_frame(list(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 300))))
    source = _FakeSource({"GOOD": good})  # no SPY, no BAD
    stats = fetch_stats(["GOOD", "BAD"], data_source=source, delay=0)
    assert stats[0].error is None and stats[0].beta_vs_spy is None
    assert stats[1].error is not None


def test_strategy_report_carries_the_honesty_block() -> None:
    candidates = [("AAA", 0.9), ("ZZZ", 0.5)]
    picks, uncovered = build_basket(candidates, {"FUND_A": {"AAA": 0.10}}, max_etfs=5)
    rng = np.random.default_rng(5)
    frame = _price_frame(list(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 300))))
    stats = fetch_stats(["FUND_A"], data_source=_FakeSource({"FUND_A": frame}), delay=0)
    report = build_strategy_report(
        picks,
        stats,
        candidates=candidates,
        uncovered=uncovered,
        correlations=basket_correlations(stats),
        swept=1,
        as_of="2026-07-08",
        descriptions={"FUND_A": "Tracks widget makers. They sell widgets for money."},
    )
    assert "### What each fund is" in report
    assert "**FUND_A** — Tracks widget makers." in report
    assert "TOP holdings" in report and "understated" in report
    assert "whole fund" in report
    assert "dilutes the stock-level signal" in report
    assert "not a Sharpe ratio" in report
    assert "## Not covered (1 of 2)" in report and "ZZZ" in report
    assert "not financial advice" in report
