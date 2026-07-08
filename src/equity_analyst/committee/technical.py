"""Technical analyst: turns the probabilistic forecast into a rated verdict.

Deterministic and transparent — no LLM. The rating follows the medium-horizon
expected return; conviction is honest about backtest skill (drift-only forecasts
are low conviction by construction).
"""

from __future__ import annotations

from equity_analyst.committee.base import AnalystContext
from equity_analyst.committee.verdict import Verdict
from equity_analyst.forecast.types import ForecastResult, HorizonForecast

# Expected-return thresholds (fraction) mapping to the −2…+2 scale.
_STRONG = 0.05
_MILD = 0.02


def rating_from_forecast(forecast: ForecastResult) -> tuple[int, str, str, str]:
    """Return ``(rating, conviction, horizon_label, evidence)`` from a forecast."""
    primary = _primary_horizon(forecast)
    exp_ret = primary.metrics.get("expected_return", 0.0)
    rating = _bucket(exp_ret)

    beats = sum(1 for h in forecast.horizons if h.beats_baseline)
    if primary.beats_baseline:
        conviction = "high" if beats >= 3 else "medium"
    else:
        # Forecast is naive drift at the primary horizon — direction only, no skill.
        conviction = "low"

    return rating, conviction, primary.label, _evidence(forecast, primary, conviction)


def _primary_horizon(forecast: ForecastResult) -> HorizonForecast:
    """Prefer the 1-month horizon; fall back to the longest available shorter one."""
    for label in ("1m", "1w", "1d", "1y"):
        h = forecast.by_label(label)
        if h is not None:
            return h
    raise ValueError("forecast has no horizons")


def _bucket(exp_ret: float) -> int:
    if exp_ret >= _STRONG:
        return 2
    if exp_ret >= _MILD:
        return 1
    if exp_ret <= -_STRONG:
        return -2
    if exp_ret <= -_MILD:
        return -1
    return 0


def _evidence(forecast: ForecastResult, primary: HorizonForecast, conviction: str) -> str:
    lines = [
        f"Probabilistic price forecast for {forecast.ticker} from "
        f"${forecast.last_price:,.2f} (as of {forecast.as_of_date}), "
        f"{forecast.interval_level}% intervals:"
    ]
    for h in forecast.horizons:
        er = h.metrics.get("expected_return", 0.0) * 100
        skill = "beats naive drift" if h.beats_baseline else "no skill vs drift"
        lines.append(
            f"  {h.label}: ${h.point:,.2f} [{h.lower:,.2f}, {h.upper:,.2f}] "
            f"({er:+.1f}%, {h.model}, {skill}, {h.n_backtest_windows} windows)"
        )
    lines.append(
        f"Primary signal: {primary.label} expected return "
        f"{primary.metrics.get('expected_return', 0.0) * 100:+.1f}%; conviction {conviction} "
        f"({'model beats baseline' if primary.beats_baseline else 'drift-only, direction not proven'})."
    )
    return "\n".join(lines)


class TechnicalAnalyst:
    """:class:`~equity_analyst.committee.base.Analyst` driven by the forecast engine."""

    name = "Technical"

    def evaluate(self, context: AnalystContext) -> Verdict:
        if context.forecast is None:
            raise ValueError("TechnicalAnalyst requires context.forecast")
        rating, conviction, horizon, evidence = rating_from_forecast(context.forecast)
        return Verdict(
            analyst=self.name,
            rating=rating,
            conviction=conviction,
            horizon=horizon,
            evidence=evidence,
        )
