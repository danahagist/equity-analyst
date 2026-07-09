"""Tests for compare, skill-report, and export (all offline, seeded SQLite)."""

from __future__ import annotations

import pandas as pd
import pytest

from equity_analyst.comparison import build_comparison, load_latest_runs
from equity_analyst.skill_report import build_skill_report, resolve_forecasts
from equity_analyst.storage import connect, save_forecast_rows, save_run, upsert_prices
from equity_analyst.storage.export import export_tables


def _seed_run(conn, ticker, as_of, pm_rating, conviction="medium", leaning="Buy", blended=0.5):
    save_run(
        conn,
        ticker=ticker,
        as_of=as_of,
        created_at=f"{as_of}T00:00:00Z",
        pm_rating=pm_rating,
        pm_conviction=conviction,
        consensus_leaning=leaning,
        blended_score=blended,
        report_md="# report",
    )


# --- compare -------------------------------------------------------------


def test_compare_ranks_and_flags_staleness() -> None:
    conn = connect(":memory:")
    _seed_run(conn, "AAA", "2026-07-01", 2, "medium", "Buy", 1.2)
    _seed_run(conn, "BBB", "2026-07-08", 1, "high", "Buy", 0.8)
    _seed_run(conn, "CCC", "2026-07-08", -1, "low", "Sell", -0.6)
    # older AAA run must be superseded by its latest
    _seed_run(conn, "AAA", "2026-06-01", 0, "low", "Hold", 0.0)

    rows = load_latest_runs(conn)
    assert [r["ticker"] for r in rows] == ["AAA", "BBB", "CCC"]  # rating-ranked
    assert rows[0]["as_of"] == "2026-07-01"  # latest AAA run won

    md = build_comparison(rows, requested=["AAA", "BBB", "CCC", "ZZZ"])
    assert "| 1 | AAA | Strong Buy" in md
    assert "different dates" in md  # staleness warning
    assert "No stored runs for: ZZZ" in md


def test_compare_empty_db_is_actionable() -> None:
    conn = connect(":memory:")
    assert "run the committee" in build_comparison(load_latest_runs(conn))


# --- skill report ----------------------------------------------------------


def _seed_skill_data(conn) -> None:
    # Price path: close = 100 at as_of, 110 at/after target.
    upsert_prices(
        conn,
        "TEST",
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02", "2026-02-02", "2026-02-04"]),
                "open": [100.0, 110.0, 111.0],
                "high": [100.0, 110.0, 111.0],
                "low": [100.0, 110.0, 111.0],
                "close": [100.0, 110.0, 111.0],
                "volume": [1e6] * 3,
            }
        ),
    )
    save_forecast_rows(
        conn,
        "TEST",
        "2026-01-02",
        [
            # covered, point closer than naive → skillful
            {
                "label": "1m",
                "target_date": "2026-02-02",
                "model": "LGB",
                "point": 108.0,
                "lower": 95.0,
                "upper": 115.0,
                "interval_level": 80,
                "beats_baseline": True,
                "n_windows": 16,
            },
            # missed interval, point worse than naive (realized 110 vs naive 100)
            {
                "label": "1w",
                "target_date": "2026-02-03",
                "model": "RWD",
                "point": 80.0,
                "lower": 75.0,
                "upper": 85.0,
                "interval_level": 80,
                "beats_baseline": False,
                "n_windows": 16,
            },
            # not matured yet — excluded by `today`
            {
                "label": "1y",
                "target_date": "2027-01-02",
                "model": "RWD",
                "point": 120.0,
                "lower": 90.0,
                "upper": 150.0,
                "interval_level": 80,
                "beats_baseline": False,
                "n_windows": 16,
            },
        ],
    )


def test_skill_report_math_and_maturity() -> None:
    conn = connect(":memory:")
    _seed_skill_data(conn)
    resolved, unresolvable = resolve_forecasts(conn, today="2026-07-08")
    assert len(resolved) == 2 and unresolvable == 0  # 1y not matured

    one_m = next(r for r in resolved if r.label == "1m")
    assert one_m.base_price == 100.0 and one_m.realized == 110.0

    md = build_skill_report(resolved, unresolvable=0, today="2026-07-08")
    # 1m: covered (110 in [95,115]), MAE model 2 vs naive 10 → ratio 0.200
    assert "| 1m | 1 ⚠️ small sample | 100% (80%) | 2.00 | 10.00 | 0.200 |" in md
    # 1w: missed ([75,85] misses 111 — first bar on/after 2026-02-03 is 2026-02-04)
    assert "| 1w | 1 ⚠️ small sample | 0% (80%) | 31.00 | 11.00 |" in md
    assert "on trial" in md  # beats_baseline subset table present


def test_skill_report_unresolvable_and_empty() -> None:
    conn = connect(":memory:")
    save_forecast_rows(
        conn,
        "NOPRICES",
        "2026-01-02",
        [
            {
                "label": "1d",
                "target_date": "2026-01-05",
                "model": "RWD",
                "point": 1.0,
                "lower": 0.5,
                "upper": 1.5,
                "interval_level": 80,
                "beats_baseline": False,
                "n_windows": 4,
            },
        ],
    )
    resolved, unresolvable = resolve_forecasts(conn, today="2026-07-08")
    assert resolved == [] and unresolvable == 1
    md = build_skill_report(resolved, unresolvable=unresolvable, today="2026-07-08")
    assert "No matured forecasts" in md and "backfill" in md


def test_skill_report_ticker_filter() -> None:
    conn = connect(":memory:")
    _seed_skill_data(conn)
    resolved, _ = resolve_forecasts(conn, today="2026-07-08", ticker="other")
    assert resolved == []


# --- export -----------------------------------------------------------------


def test_export_csv_round_trip(tmp_path) -> None:
    conn = connect(":memory:")
    _seed_run(conn, "AAA", "2026-07-01", 2)
    _seed_skill_data(conn)

    paths = export_tables(conn, tmp_path, fmt="csv")
    names = {p.name for p in paths}
    assert names == {"runs.csv", "forecasts.csv", "prices.csv", "fundamentals.csv", "screens.csv"}

    runs = pd.read_csv(tmp_path / "runs.csv")
    assert list(runs["ticker"]) == ["AAA"]
    assert "report_md" not in runs.columns  # reports live in outputs/, not exports
    assert len(pd.read_csv(tmp_path / "forecasts.csv")) == 3


def test_export_xlsx_needs_openpyxl_or_works(tmp_path) -> None:
    conn = connect(":memory:")
    _seed_run(conn, "AAA", "2026-07-01", 2)
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="openpyxl"):
            export_tables(conn, tmp_path, fmt="xlsx")
    else:
        paths = export_tables(conn, tmp_path, fmt="xlsx")
        assert paths[0].name == "equity_analyst.xlsx" and paths[0].exists()


def test_export_rejects_unknown_format(tmp_path) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        export_tables(connect(":memory:"), tmp_path, fmt="json")
