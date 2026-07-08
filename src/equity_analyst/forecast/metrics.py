"""Backtest scoring functions. Pure NumPy, no state — easy to unit-test.

Point accuracy uses MAE; interval quality uses empirical coverage and the
Winkler interval score (rewards sharp intervals, penalizes misses in proportion
to how far outside they fall). Model skill is expressed relative to the naive
baseline, because absolute error on prices is meaningless out of context.
"""

from __future__ import annotations

import numpy as np


def mae(y: np.ndarray, yhat: np.ndarray) -> float:
    """Mean absolute error."""
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(yhat))))


def coverage(y: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    """Fraction of actuals falling within [lower, upper]. Should track the level."""
    y, lower, upper = np.asarray(y), np.asarray(lower), np.asarray(upper)
    return float(np.mean((y >= lower) & (y <= upper)))


def interval_score(
    y: np.ndarray, lower: np.ndarray, upper: np.ndarray, *, level: int
) -> float:
    """Winkler/interval score for a central prediction interval. Lower is better.

    ``level`` is the nominal coverage percent (e.g. 80), so alpha = 1 - level/100.
    """
    y, lower, upper = np.asarray(y), np.asarray(lower), np.asarray(upper)
    alpha = 1.0 - level / 100.0
    width = upper - lower
    below = (lower - y) * (y < lower)
    above = (y - upper) * (y > upper)
    return float(np.mean(width + (2.0 / alpha) * (below + above)))


def skill_ratio(model_error: float, baseline_error: float) -> float:
    """model/baseline error ratio. < 1 means the model beats the baseline."""
    if baseline_error == 0:
        return float("inf") if model_error > 0 else 1.0
    return model_error / baseline_error
