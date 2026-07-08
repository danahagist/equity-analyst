"""Result types for the forecasting engine.

Deliberately probabilistic and honest (see CLAUDE.md): every horizon carries an
interval and a flag for whether the chosen model actually beat the naive
baseline in backtest. A point number without that context is not shipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Target horizons, labelled, in trading days. 1w=5, 1m=21, 1y=252 business days.
DEFAULT_HORIZONS: dict[str, int] = {"1d": 1, "1w": 5, "1m": 21, "1y": 252}


@dataclass(frozen=True, slots=True)
class HorizonForecast:
    """Forecast for a single horizon."""

    label: str  # e.g. "1w"
    steps: int  # horizon length in trading days
    as_of_date: str  # ISO date the forecast is made from (last observed bar)
    target_date: str  # ISO date the horizon lands on
    model: str  # name of the selected model
    point: float  # central estimate (price)
    lower: float  # interval lower bound
    upper: float  # interval upper bound
    interval_level: int  # e.g. 80 (percent)
    beats_baseline: bool  # did `model` beat naive drift in backtest?
    baseline_model: str  # the baseline it was compared against
    n_backtest_windows: int  # how many out-of-sample windows the skill rests on
    metrics: dict[str, float] = field(default_factory=dict)  # mae, coverage, interval_score...
    note: str = ""  # honesty caveat when skill is weak/unmeasurable

    @property
    def expected_return(self) -> float:
        """Point-implied return vs. the last observed price is set by the engine."""
        return self.metrics.get("expected_return", float("nan"))


@dataclass(frozen=True, slots=True)
class ForecastResult:
    """Full probabilistic forecast for a ticker across all horizons."""

    ticker: str
    as_of_date: str
    last_price: float
    interval_level: int
    horizons: list[HorizonForecast]
    models_considered: list[str]
    disclaimer: str = (
        "Probabilistic forecast, not investment advice. Stock prices are near a "
        "random walk; intervals are wide by nature and long horizons are dominated "
        "by drift. Where no model beats the naive baseline, the baseline is reported."
    )

    def by_label(self, label: str) -> HorizonForecast | None:
        return next((h for h in self.horizons if h.label == label), None)
