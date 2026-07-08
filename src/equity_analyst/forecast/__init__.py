"""Probabilistic price forecasting (Technical analyst).

The heavy ``statsforecast`` dependency is imported lazily inside the engine, so
importing this package does not require the optional ``forecast`` extra.
"""

from equity_analyst.forecast.types import (
    DEFAULT_HORIZONS,
    ForecastResult,
    HorizonForecast,
)

__all__ = ["DEFAULT_HORIZONS", "ForecastResult", "HorizonForecast"]
