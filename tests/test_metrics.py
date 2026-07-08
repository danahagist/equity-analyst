"""Backtest metric tests (pure, no optional deps)."""

from __future__ import annotations

import numpy as np

from equity_analyst.forecast import metrics


def test_mae() -> None:
    assert metrics.mae(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0, 3.0])) == 0.0
    assert metrics.mae(np.array([1.0, 2.0]), np.array([2.0, 4.0])) == 1.5


def test_coverage() -> None:
    y = np.array([1.0, 5.0, 9.0, 11.0])
    lo = np.array([0.0, 0.0, 0.0, 0.0])
    hi = np.array([10.0, 10.0, 10.0, 10.0])
    assert metrics.coverage(y, lo, hi) == 0.75  # 11.0 is outside


def test_interval_score_rewards_tight_covered_intervals() -> None:
    y = np.array([5.0, 5.0])
    tight = metrics.interval_score(y, np.array([4.0, 4.0]), np.array([6.0, 6.0]), level=80)
    wide = metrics.interval_score(y, np.array([0.0, 0.0]), np.array([10.0, 10.0]), level=80)
    assert tight < wide  # both cover, tighter wins


def test_interval_score_penalizes_misses() -> None:
    y = np.array([100.0])
    covered = metrics.interval_score(y, np.array([90.0]), np.array([110.0]), level=80)
    missed = metrics.interval_score(y, np.array([90.0]), np.array([95.0]), level=80)
    assert missed > covered


def test_skill_ratio() -> None:
    assert metrics.skill_ratio(1.0, 2.0) == 0.5  # model beats baseline
    assert metrics.skill_ratio(2.0, 2.0) == 1.0
    assert metrics.skill_ratio(3.0, 2.0) == 1.5  # model worse
