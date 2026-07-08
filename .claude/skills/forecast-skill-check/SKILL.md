---
name: forecast-skill-check
description: Evaluate whether the forecasting engine has real predictive skill by comparing stored forecasts against realized prices in SQLite. Use when asked if the forecaster works, to audit calibration/coverage, or after enough runs have accumulated to judge forecast-vs-actual.
---

# Forecast-vs-actual skill check

The whole honesty premise of this tool (see CLAUDE.md) is that forecast claims
get audited. Every run stores its per-horizon forecast in the `forecast` table
of `data/equity_analyst.db`; each row has a `target_date`. Once target dates
have passed, realized prices tell us whether the engine has skill.

## What to measure

1. **Interval coverage** — the fraction of realized prices falling inside the
   stored `[lower, upper]` bands should match `interval_level` (80% → ~0.80).
   Coverage well below nominal = overconfident intervals (the serious failure).
   Well above = intervals too wide to be useful (the mild failure).
2. **Point accuracy vs drift** — MAE of `point` vs realized, compared against a
   naive forecast (last price at `as_of` carried forward). If stored forecasts
   don't beat that, say so plainly — that IS the expected outcome for efficient
   markets and the tool is designed to admit it.
3. **Split by `beats_baseline`** — rows where a model claimed skill in backtest
   are the ones on trial. If "skilled" forecasts don't outperform out-of-sample,
   the backtest gate is leaking.

## How

```sql
-- forecasts whose target date has passed
SELECT ticker, as_of, label, target_date, model, point, lower, upper,
       interval_level, beats_baseline
FROM forecast
WHERE target_date <= date('now')
ORDER BY ticker, as_of, label;
```

Realized prices: prefer the `price_bar` table (`SELECT close FROM price_bar
WHERE ticker=? AND date>=? ORDER BY date LIMIT 1` — first bar on/after the
target date, since targets can land on non-trading days). If bars are missing,
fetch via the data source on the user's machine.

Report per horizon label (1d/1w/1m/1y): n, coverage, MAE(model) vs MAE(naive),
and the beats_baseline split. Small n caveat: under ~30 resolved forecasts per
horizon, say the sample is too small to conclude anything.

## Caveats

- Runs on consecutive days share overlapping outcome windows — the samples are
  not independent; don't quote significance tests without accounting for it.
- Never delete or rewrite history in `forecast` to "fix" results.
