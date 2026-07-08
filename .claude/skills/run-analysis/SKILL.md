---
name: run-analysis
description: Run the equity-analyst investment committee for a ticker — environment checks, command variants, offline/sandbox fallback, and where outputs land. Use when asked to run, launch, or demo the tool, or to analyze a stock end to end.
---

# Run a committee analysis

## Preconditions (check in order)

1. **Virtualenv + install**: `pip install -e ".[forecast,dev]"` (the `forecast`
   extra is required for a real run — statsforecast, mlforecast, lightgbm).
2. **API key**: `ANTHROPIC_API_KEY` must be set in `.env` (copy `.env.example`).
   Without it the CLI exits with code 2 before any work happens.
3. **Network**: market data comes from Yahoo Finance via `yfinance`. In
   sandboxed/remote sessions, Yahoo is often blocked by egress policy
   (`fc.yahoo.com` 403). Do NOT route around a policy denial — fall back to the
   offline demo below and tell the user a live run needs their machine.

## Commands

```bash
equity-analyst AAPL                  # full run → outputs/AAPL-<date>.md + stdout
equity-analyst NVDA --period 10y     # longer history = better backtest windows
equity-analyst TSLA --no-save        # stdout only
equity-analyst MSFT --no-db          # skip SQLite persistence
equity-analyst AAPL --quiet          # suppress stderr progress narration
```

A run takes a few minutes: ~30–60s of forecast backtesting plus four LLM calls
(two of them with web search). Progress narrates to stderr; the report goes to
stdout and `outputs/`.

## Offline demo (no key, no network)

Drive the full pipeline with fixtures — real forecast engine, fake data + LLM:

```bash
python - <<'PY'
from equity_analyst.forecast.engine import EngineConfig, ForecastEngine
from equity_analyst.pipeline import run_committee
from tests.fixtures import FakeDataSource
from tests.fixtures.llm import FakeLLMClient
from equity_analyst.llm.config import (ROLE_FUNDAMENTAL, ROLE_NEWS_SOCIAL,
                                       ROLE_RESEARCH, ROLE_PORTFOLIO_MANAGER)

llm = FakeLLMClient(verdicts={
    ROLE_FUNDAMENTAL: {"rating": 1, "conviction": "high", "horizon": "1y", "evidence": "demo"},
    ROLE_NEWS_SOCIAL: {"rating": 0, "conviction": "low", "horizon": "1m", "evidence": "demo"},
    ROLE_RESEARCH: {"rating": 1, "conviction": "medium", "horizon": "1y", "evidence": "demo"},
    ROLE_PORTFOLIO_MANAGER: {"rating": 1, "conviction": "medium", "horizon": "6-12mo",
                             "synthesis": "demo", "key_risks": [], "horizon_fit": []},
})
res = run_committee("DEMO", data_source=FakeDataSource(days=600),
                    engine=ForecastEngine(config=EngineConfig(max_windows=4, use_ml=False)),
                    llm=llm)
print(res.report_md)
PY
```

## Verifying a change works

`pytest -q` (50+ offline tests) then the offline demo above; for changes to
prompts or LLM plumbing, a live single-ticker run on the user's machine is the
real test — synthetic data can't validate prompt quality.
