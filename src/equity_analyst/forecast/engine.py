"""The forecasting engine behind the Technical analyst.

Pipeline (see CLAUDE.md for the rationale):
  1. Build a regular integer-indexed series from close prices (sidesteps the
     ragged trading calendar).
  2. Rolling-origin backtest of every model across all horizons — statistical
     models (statsforecast) plus LightGBM with conformal intervals (mlforecast).
  3. Per horizon, select the challenger that beats naive drift on point error
     AND is at least as well-calibrated (interval score); if none qualifies,
     keep the baseline and say so.
  4. Refit on all data and read off point + interval at each horizon.

The ML layer degrades gracefully: if conformal calibration needs more history
than is available, the run proceeds with statistical models only. Heavy
dependencies are imported lazily so the core package installs without the
``forecast`` extra.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from equity_analyst.forecast import metrics
from equity_analyst.forecast.types import DEFAULT_HORIZONS, ForecastResult, HorizonForecast

BASELINE_NAME = "RWD"  # RandomWalkWithDrift — the benchmark every model must beat
ML_NAME = "LGB"  # LightGBM on lag/rolling features + conformal intervals


@dataclass(frozen=True)
class EngineConfig:
    interval_level: int = 80
    min_train: int = 120  # minimum bars before the first backtest window
    step_size: int = 10  # spacing between rolling-origin windows
    max_windows: int = 16  # cap on backtest windows (keeps long-horizon CV bounded)
    min_qualify_windows: int = 3  # paired samples a challenger needs to displace the baseline
    use_ml: bool = True  # LightGBM challenger (skipped gracefully on short history)
    ml_conformal_windows: int = 2  # conformal calibration windows inside each fit


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
            raise ValueError(f"need at least {cfg.min_train + 1} bars to forecast, got {n}")

        feasible_h = min(max_h, n - cfg.min_train)
        n_windows = self._n_windows(n, feasible_h)

        backtest, forecast, model_names = self._run_models(
            series, n=n, max_h=max_h, feasible_h=feasible_h, n_windows=n_windows
        )

        last_date = pd.Timestamp(prices["date"].max())
        last_price = float(series["y"].iloc[-1])

        horizons_out = [
            self._build_horizon(
                label=label,
                steps=steps,
                feasible_h=feasible_h,
                backtest=backtest,
                forecast=forecast,
                model_names=model_names,
                last_date=last_date,
                last_price=last_price,
            )
            for label, steps in sorted(self.horizons.items(), key=lambda kv: kv[1])
        ]

        return ForecastResult(
            ticker=ticker,
            as_of_date=last_date.date().isoformat(),
            last_price=round(last_price, 4),
            interval_level=cfg.interval_level,
            horizons=horizons_out,
            models_considered=model_names,
        )

    # ---------------------------------------------------------------- modeling

    def _run_models(
        self, series: pd.DataFrame, *, n: int, max_h: int, feasible_h: int, n_windows: int
    ) -> tuple[pd.DataFrame | None, pd.DataFrame, list[str]]:
        """Backtest + final forecast for statistical models, ML merged in if viable."""
        cfg = self.config

        from statsforecast import StatsForecast
        from statsforecast.models import AutoARIMA, AutoETS, RandomWalkWithDrift, Theta

        sf = StatsForecast(
            models=[
                RandomWalkWithDrift(),
                Theta(),
                AutoETS(),
                AutoARIMA(season_length=1),
            ],
            freq=1,
            n_jobs=1,
        )
        model_names = [BASELINE_NAME, "Theta", "AutoETS", "AutoARIMA"]

        backtest = None
        if n_windows >= 1:
            backtest = sf.cross_validation(
                df=series,
                h=feasible_h,
                n_windows=n_windows,
                step_size=cfg.step_size,
                level=[cfg.interval_level],
            )
        forecast = sf.forecast(df=series, h=max_h, level=[cfg.interval_level])

        if cfg.use_ml:
            ml = self._run_ml(series, max_h=max_h, feasible_h=feasible_h, n_windows=n_windows)
            if ml is not None:
                ml_backtest, ml_forecast = ml
                if backtest is not None and ml_backtest is not None:
                    backtest = backtest.merge(
                        ml_backtest.drop(columns=["y"]),
                        on=["unique_id", "ds", "cutoff"],
                        how="left",
                    )
                forecast = forecast.merge(ml_forecast, on=["unique_id", "ds"], how="left")
                model_names.append(ML_NAME)

        return backtest, forecast, model_names

    def _ml_n_windows(self, n: int, feasible_h: int, n_windows: int) -> int:
        """How many CV windows LightGBM can support given conformal data needs.

        Conformal calibration reserves ``ml_conformal_windows * h`` observations
        inside every training window, plus ``min_train`` bars to fit on. The ML
        challenger backtests on the most recent windows it can afford (often
        fewer than the statistical models get); selection compares each
        challenger against the baseline pairwise on shared windows, so the
        comparison stays apples-to-apples.
        """
        cfg = self.config
        train_floor = cfg.ml_conformal_windows * feasible_h + cfg.min_train
        room = n - feasible_h - train_floor
        if room < 0:
            return 0
        return min(n_windows, room // cfg.step_size + 1)

    def _run_ml(
        self, series: pd.DataFrame, *, max_h: int, feasible_h: int, n_windows: int
    ) -> tuple[pd.DataFrame | None, pd.DataFrame] | None:
        """LightGBM CV + final forecast with conformal intervals; None if infeasible."""
        cfg = self.config
        ml_windows = self._ml_n_windows(len(series), feasible_h, n_windows)
        # Without backtest windows the challenger could never qualify — skip
        # rather than paying for an unusable fit.
        if n_windows >= 1 and ml_windows < 1:
            return None
        try:
            import lightgbm as lgb
            from mlforecast import MLForecast
            from mlforecast.lag_transforms import RollingMean
            from mlforecast.utils import PredictionIntervals

            def make() -> MLForecast:
                return MLForecast(
                    models={ML_NAME: lgb.LGBMRegressor(n_estimators=200, verbosity=-1)},
                    freq=1,
                    lags=[1, 2, 3, 5, 10, 21],
                    lag_transforms={5: [RollingMean(5)], 21: [RollingMean(21)]},
                )

            ml_backtest = None
            if ml_windows >= 1:
                ml_backtest = make().cross_validation(
                    df=series,
                    h=feasible_h,
                    n_windows=ml_windows,
                    step_size=cfg.step_size,
                    level=[cfg.interval_level],
                    prediction_intervals=PredictionIntervals(
                        n_windows=cfg.ml_conformal_windows, h=feasible_h
                    ),
                )

            mlf = make()
            mlf.fit(
                series,
                prediction_intervals=PredictionIntervals(
                    n_windows=cfg.ml_conformal_windows, h=max_h
                ),
            )
            ml_forecast = mlf.predict(max_h, level=[cfg.interval_level])
            return ml_backtest, ml_forecast
        except Exception:  # noqa: BLE001 - ML is a challenger, never a blocker
            return None

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

    def _metrics_on(self, rows: pd.DataFrame, name: str, level: int) -> dict[str, float]:
        """MAE / coverage / interval-score for one model over the given CV rows."""
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
            rows = backtest[backtest["ds"] - backtest["cutoff"] == steps]
            base_rows = rows.dropna(subset=[BASELINE_NAME])
            if not base_rows.empty:
                windows_used = len(base_rows)
                # Selection gate (see CLAUDE.md): a challenger must beat the
                # baseline on point error AND be at least as well-calibrated,
                # judged pairwise on the windows both models covered.
                qualified: dict[str, dict[str, float]] = {}
                had_candidates = False
                for name in model_names:
                    if name == BASELINE_NAME or name not in rows.columns:
                        continue
                    paired = rows.dropna(subset=[name, BASELINE_NAME])
                    if len(paired) < self.config.min_qualify_windows:
                        continue
                    had_candidates = True
                    m_c = self._metrics_on(paired, name, level)
                    m_b = self._metrics_on(paired, BASELINE_NAME, level)
                    if m_c["mae"] < m_b["mae"] and m_c["interval_score"] <= m_b["interval_score"]:
                        m_c["skill_ratio"] = metrics.skill_ratio(m_c["mae"], m_b["mae"])
                        qualified[name] = m_c
                if qualified:
                    selected = min(qualified, key=lambda k: qualified[k]["skill_ratio"])
                    beats = True
                    chosen_metrics = dict(qualified[selected])
                    windows_used = int(chosen_metrics["n"])
                else:
                    chosen_metrics = self._metrics_on(base_rows, BASELINE_NAME, level)
                    chosen_metrics["skill_ratio"] = 1.0
                    note = (
                        "no model beat naive drift on both error and calibration; "
                        "reporting the baseline."
                        if had_candidates
                        else "too few backtest windows to qualify a challenger; "
                        "reporting the baseline."
                    )
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
