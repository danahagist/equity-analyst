"""The forecasting engine behind the Technical analyst.

Pipeline (see CLAUDE.md for the rationale):
  1. Build a regular integer-indexed series from close prices (sidesteps the
     ragged trading calendar).
  2. Rolling-origin backtest of every model across all horizons.
  3. Per horizon, select the challenger that beats naive drift on point error;
     if none does, keep the baseline and say so.
  4. Refit on all data and read off point + interval at each horizon.

Statistical models only by default (Nixtla ``statsforecast``); neural models are
a separate, opt-in concern. ``statsforecast`` is imported lazily so the core
package installs without the ``forecast`` extra.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from equity_analyst.forecast import metrics
from equity_analyst.forecast.types import DEFAULT_HORIZONS, ForecastResult, HorizonForecast

BASELINE_NAME = "RWD"  # RandomWalkWithDrift — the benchmark every model must beat


@dataclass(frozen=True)
class EngineConfig:
    interval_level: int = 80
    min_train: int = 120  # minimum bars before the first backtest window
    step_size: int = 21  # spacing between rolling-origin windows
    max_windows: int = 8  # cap on backtest windows (keeps long-horizon CV bounded)


def _build_models(config: EngineConfig):
    """Instantiate the model set: baseline first, then challengers."""
    from statsforecast.models import AutoETS, RandomWalkWithDrift, Theta

    return [
        (BASELINE_NAME, RandomWalkWithDrift()),
        ("Theta", Theta()),
        ("AutoETS", AutoETS()),
    ]


class ForecastEngine:
    """Produce a :class:`ForecastResult` from a tidy price frame."""

    def __init__(
        self,
        *,
        horizons: dict[str, int] | None = None,
        config: EngineConfig | None = None,
    ) -> None:
        self.horizons = dict(horizons or DEFAULT_HORIZONS)
        self.config = config or EngineConfig()

    def forecast(self, ticker: str, prices: pd.DataFrame) -> ForecastResult:
        cfg = self.config
        series = self._prepare(prices)
        n = len(series)
        max_h = max(self.horizons.values())
        if n < cfg.min_train + 1:
            raise ValueError(
                f"need at least {cfg.min_train + 1} bars to forecast, got {n}"
            )

        from statsforecast import StatsForecast

        models = _build_models(cfg)
        model_names = [name for name, _ in models]
        sf = StatsForecast(models=[m for _, m in models], freq=1, n_jobs=1)

        # --- backtest across as many horizons as history allows ---
        feasible_h = min(max_h, n - cfg.min_train)
        n_windows = self._n_windows(n, feasible_h)
        backtest = None
        if n_windows >= 1:
            backtest = sf.cross_validation(
                df=series,
                h=feasible_h,
                n_windows=n_windows,
                step_size=cfg.step_size,
                level=[cfg.interval_level],
            )

        # --- final forecast on all data ---
        fc = sf.forecast(df=series, h=max_h, level=[cfg.interval_level])

        last_date = pd.Timestamp(prices["date"].max())
        last_price = float(series["y"].iloc[-1])

        horizons_out: list[HorizonForecast] = []
        for label, steps in sorted(self.horizons.items(), key=lambda kv: kv[1]):
            horizons_out.append(
                self._build_horizon(
                    label=label,
                    steps=steps,
                    feasible_h=feasible_h,
                    n_windows=n_windows,
                    backtest=backtest,
                    forecast=fc,
                    model_names=model_names,
                    last_date=last_date,
                    last_price=last_price,
                )
            )

        return ForecastResult(
            ticker=ticker,
            as_of_date=last_date.date().isoformat(),
            last_price=round(last_price, 4),
            interval_level=cfg.interval_level,
            horizons=horizons_out,
            models_considered=model_names,
        )

    # ------------------------------------------------------------------ helpers

    def _prepare(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Tidy close series -> Nixtla long frame with a regular integer index."""
        if "close" not in prices or "date" not in prices:
            raise ValueError("prices frame must have 'date' and 'close' columns")
        clean = prices.dropna(subset=["close"]).sort_values("date")
        if clean["close"].le(0).any():
            raise ValueError("close prices must be positive")
        return pd.DataFrame(
            {
                "unique_id": "series",
                "ds": np.arange(len(clean), dtype="int64"),
                "y": clean["close"].to_numpy(dtype="float64"),
            }
        )

    def _n_windows(self, n: int, feasible_h: int) -> int:
        cfg = self.config
        if feasible_h < 1:
            return 0
        room = n - cfg.min_train - feasible_h
        if room < 0:
            return 0
        return max(1, min(cfg.max_windows, room // cfg.step_size + 1))

    def _horizon_metrics(
        self, backtest: pd.DataFrame, steps: int, name: str, level: int
    ) -> dict[str, float] | None:
        """MAE / coverage / interval-score for one model at one horizon, or None."""
        rows = backtest[backtest["ds"] - backtest["cutoff"] == steps]
        if rows.empty:
            return None
        y = rows["y"].to_numpy()
        point = rows[name].to_numpy()
        lo = rows[f"{name}-lo-{level}"].to_numpy()
        hi = rows[f"{name}-hi-{level}"].to_numpy()
        return {
            "mae": metrics.mae(y, point),
            "coverage": metrics.coverage(y, lo, hi),
            "interval_score": metrics.interval_score(y, lo, hi, level=level),
            "n": float(len(rows)),
        }

    def _build_horizon(
        self,
        *,
        label: str,
        steps: int,
        feasible_h: int,
        n_windows: int,
        backtest: pd.DataFrame | None,
        forecast: pd.DataFrame,
        model_names: list[str],
        last_date: pd.Timestamp,
        last_price: float,
    ) -> HorizonForecast:
        level = self.config.interval_level
        selected = BASELINE_NAME
        beats = False
        note = ""
        chosen_metrics: dict[str, float] = {}
        windows_used = 0

        can_backtest = backtest is not None and steps <= feasible_h
        if can_backtest:
            per_model = {
                name: self._horizon_metrics(backtest, steps, name, level)
                for name in model_names
            }
            base = per_model.get(BASELINE_NAME)
            if base is not None:
                windows_used = int(base["n"])
                challengers = {
                    name: m["mae"]
                    for name, m in per_model.items()
                    if name != BASELINE_NAME and m is not None
                }
                if challengers:
                    best_name = min(challengers, key=challengers.get)
                    if challengers[best_name] < base["mae"]:
                        selected, beats = best_name, True
                chosen_metrics = dict(per_model[selected])
                chosen_metrics["skill_ratio"] = metrics.skill_ratio(
                    chosen_metrics["mae"], base["mae"]
                )
                if not beats:
                    note = "no model beat naive drift; reporting the baseline."
        else:
            note = "history too short to backtest this horizon; reporting naive drift."

        row = forecast[forecast["ds"] == forecast["ds"].min() + (steps - 1)].iloc[0]
        point = float(row[selected])
        lower = float(row[f"{selected}-lo-{level}"])
        upper = float(row[f"{selected}-hi-{level}"])
        chosen_metrics["expected_return"] = point / last_price - 1.0

        target_date = (last_date + pd.tseries.offsets.BDay(steps)).date().isoformat()
        return HorizonForecast(
            label=label,
            steps=steps,
            as_of_date=last_date.date().isoformat(),
            target_date=target_date,
            model=selected,
            point=round(point, 4),
            lower=round(lower, 4),
            upper=round(upper, 4),
            interval_level=level,
            beats_baseline=beats,
            baseline_model=BASELINE_NAME,
            n_backtest_windows=windows_used,
            metrics={k: round(v, 6) for k, v in chosen_metrics.items()},
            note=note,
        )
