"""ETF exposure tests: inversion, ranking, report (pure functions; no network)."""

from __future__ import annotations

from equity_analyst.etf_exposure import build_exposure, build_exposure_report


def test_build_exposure_ranks_by_combined_weight() -> None:
    holdings = {
        "SMH": {"NVDA": 0.18, "AVGO": 0.05, "MU": 0.06, "TSM": 0.10},
        "SPY": {"NVDA": 0.07, "AAPL": 0.06, "MSFT": 0.06},
        "GDX": {"NEM": 0.11, "AU": 0.05},
        "XLF": {"BRK-B": 0.13, "JPM": 0.10},  # no candidates
    }
    exposures = build_exposure(["NVDA", "AVGO", "MU", "NEM", "AU"], holdings)
    # XLF drops out (no matches); SMH first (0.29), then GDX (0.16), then SPY (0.07)
    assert [e.etf for e in exposures] == ["SMH", "GDX", "SPY"]
    assert exposures[0].n_matched == 3
    assert abs(exposures[0].total_weight - 0.29) < 1e-9
    assert exposures[1].matched == {"NEM": 0.11, "AU": 0.05}


def test_build_exposure_is_case_insensitive() -> None:
    exposures = build_exposure(["nvda"], {"QQQ": {"NVDA": 0.08}})
    assert exposures and exposures[0].matched == {"NVDA": 0.08}


def test_build_exposure_empty_when_no_overlap() -> None:
    assert build_exposure(["NVDA"], {"XLE": {"XOM": 0.2, "CVX": 0.15}}) == []


def test_exposure_report_shape() -> None:
    # XLE fetched fine but holds no candidate — it must still count as swept.
    holdings = {
        "SMH": {"NVDA": 0.18, "MU": 0.06},
        "GDX": {"NEM": 0.11},
        "XLE": {"XOM": 0.2},
    }
    exposures = build_exposure(["NVDA", "MU", "NEM"], holdings)
    report = build_exposure_report(
        exposures,
        tickers=["NVDA", "MU", "NEM"],
        top=10,
        failures=[("BADETF", "boom")],
        as_of="2026-07-08",
        swept=len(holdings) + 1,
    )
    assert "| 1 | SMH | 2 | 24.0% |" in report
    assert "not financial advice" in report
    assert "Swept 4 ETFs; 2 hold at least one candidate" in report
    assert "(1 fetches failed)" in report
