"""Entry/exit level tests: interval-derived plan + honesty flags."""

from __future__ import annotations

import pytest

from equity_analyst.levels import build_levels_report, plan_from_packet


def _packet(rows, last_price=100.0, ticker="TEST"):
    return {
        "ticker": ticker,
        "as_of": "2026-07-08",
        "last_price": last_price,
        "forecast_rows": rows,
    }


def _row(label, point, lower, upper, beats):
    return {
        "label": label,
        "point": point,
        "lower": lower,
        "upper": upper,
        "beats_baseline": beats,
        "target_date": "2026-08-06",
        "model": "X",
        "interval_level": 80,
        "n_windows": 16,
    }


def test_plan_uses_near_band_and_long_target() -> None:
    plan = plan_from_packet(
        _packet(
            [
                _row("1m", point=105, lower=90, upper=120, beats=True),
                _row("1y", point=140, lower=80, upper=200, beats=False),
            ]
        )
    )
    assert plan.buy_below == 90.0 and plan.fair_value == 105.0
    assert plan.trim_near == 120.0 and plan.target == 140.0
    assert plan.stop == 82.5  # lower - 0.5*(point-lower) = 90 - 7.5
    assert plan.upside_to_target_pct == pytest.approx(0.40)
    assert plan.reward_risk == pytest.approx(0.40 / 0.175, rel=1e-3)


def test_plan_flags_drift_only_and_negative_drift() -> None:
    plan = plan_from_packet(
        _packet(
            [
                _row("1m", point=100, lower=85, upper=115, beats=False),
                _row("1y", point=95, lower=60, upper=130, beats=False),
            ]
        )
    )
    assert "did not beat naive drift" in plan.notes
    assert "drift-only" in plan.notes
    assert "at or below the current price" in plan.notes


def test_plan_falls_back_when_no_1y() -> None:
    plan = plan_from_packet(_packet([_row("1w", 102, 95, 109, True)]))
    assert plan.near_label == "1w" and plan.target_label == "1w"


def test_plan_requires_forecast_rows() -> None:
    with pytest.raises(ValueError, match="no forecast rows"):
        plan_from_packet(_packet([]))


def test_levels_report_carries_disclaimer() -> None:
    plan = plan_from_packet(
        _packet([_row("1m", 105, 90, 120, True), _row("1y", 140, 80, 200, False)])
    )
    report = build_levels_report([plan], as_of="2026-07-08")
    assert "NOT financial advice" in report and "not top-tick" in report
    assert "| TEST |" in report
