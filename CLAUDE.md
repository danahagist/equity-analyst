# CLAUDE.md — equity-analyst

Guidance for Claude Code sessions working in this repo. Read this first.

## What this is

An **investment-committee** equity research tool. Given a stock ticker, five
role-specialized analysts each independently reach a *rated recommendation* with
supporting analysis, and a portfolio manager synthesizes them into a final call.
The valuable output is the **consensus and the disagreement**: agreement across
analysts = conviction; divergence = flagged risk.

This subsumes the original "7 Wall Street analyst prompts" idea — those prompts
now live inside the relevant analysts rather than running as a flat list.

## Working agreement (how Dana likes to work)

- **Don't make architectural/strategic decisions unilaterally.** At a real fork
  (LLM provider, data source, live-data vs model-only, cost model, hard-to-migrate
  data shapes, forecasting approach), pause and present options with honest
  pros/cons; let Dana pick.
- **Terse and direct.** Explain the *why* behind recommendations. Push back when
  you disagree — that's wanted, not rude.
- **Feature branches for real changes**, never straight to `main`.
- **Intellectual honesty over impressive-looking output.** See guardrails below.

## The committee

| Analyst | Job | Powered by |
|---|---|---|
| **Technical** | momentum, patterns, probabilistic price forecast (1d/1w/1m/1y) | Python forecasting engine |
| **Fundamental** | business model, financials, valuation, industry/competitive | real fundamentals + LLM (absorbs original prompts 1–4) |
| **News/Social** | events driving price/momentum, upcoming catalysts | LLM semantic web search (absorbs prompt 6) |
| **Research** | existing analyst ratings, price targets, 3rd-party research | analyst data + LLM web search |
| **Portfolio Manager** | synthesize, big picture, risk, final call | LLM over the other four (absorbs prompts 5, 7) |

### Structured verdict (every analyst emits this)

- `rating`: integer scale −2…+2 (Strong Sell, Sell, Hold, Buy, Strong Buy)
- `conviction`: confidence in the rating (e.g. low/medium/high or 0–1)
- `horizon`: the time horizon the rating applies to
- `evidence`: the key supporting points (the analyst's written analysis)

### Consensus mechanism

1. A **deterministic, transparent** function computes an agreement summary from
   the five verdicts (e.g. "4 of 5 lean Buy; Fundamental dissents on valuation").
2. The **PM (LLM)** reads that summary *plus* each analyst's full writeup and
   authors the synthesis. It may override the mechanical blend but must justify
   any divergence.
3. Report leads with the **agreement picture**, not a single false-precision
   number. Any blended score is secondary. Disagreements are called out
   explicitly.

## Architecture decisions (settled)

- **LLM provider:** Anthropic Claude, behind a thin client module so a swap is a
  small, localized change. Key: `ANTHROPIC_API_KEY` (in `.env`, gitignored).
- **Market/financial data:** `yfinance` (free, no key), **isolated behind one
  data-access module**. It's unofficial and can break; the isolation makes moving
  to a keyed API (Alpha Vantage / FMP free tier) a one-file change later.
- **Storage:** **SQLite is the system of record** — related tables for prices,
  fundamentals, forecasts, sentiment/analyst signals, and recommendations. This
  is what lets us store forecast-vs-actual and later check whether the forecaster
  has any real skill. **CSV/Excel are an export layer on top**, not the primary store.
- **Output:** each run writes `outputs/<TICKER>-<YYYY-MM-DD>.md` (all analyst
  sections + consensus) **and** prints to stdout. `outputs/` is gitignored.

## Forecasting engine (Technical analyst)

**Framing (non-negotiable):** stock prices are near a random walk. We produce
**calibrated probabilistic forecasts benchmarked against a naive baseline**, not
confident point prices. If a model can't beat naive drift at a horizon, the tool
says so and reports drift + a wide interval.

**Architecture — M4/M5-competition-informed (accurate + mainstream):**
- Baseline to beat: random-walk-with-drift / seasonal-naive.
- Statistical: AutoARIMA, AutoETS, Theta (native prediction intervals).
- ML: LightGBM on lag/rolling features + **conformal prediction** for calibrated
  intervals.
- Neural (optional extra, off by default): N-HITS / TFT with quantile loss — used
  at a horizon only if it beats the above in backtest.
- Selection: rolling-origin backtest per horizon; pick/ensemble whatever beats the
  baseline on error *and* interval coverage.
- Horizons: 1 day, 1 week, 1 month, 1 year. Longer horizons are honestly
  presented as drift + wide interval.

**Library:** Nixtla stack — `statsforecast` + `mlforecast` + `utilsforecast`,
with `neuralforecast` behind an optional extra. Chosen over Darts for its
probabilistic-forecasting + backtesting-native design and strong baseline culture.

## Honesty guardrails

- No confident point-price predictions; always intervals + backtest context.
- Disclose when a model fails to beat the naive baseline.
- Social sentiment uses LLM web search over news + public pages, **not** a
  real-time social firehose (those are paywalled) — don't imply otherwise.
- This tool is research assistance, **not financial advice**; outputs should say so.

## Repo conventions

- Python 3.11+, `src/` layout, package `equity_analyst`, CLI entry `equity-analyst`.
- Lint/format: `ruff` (line length 100). Tests: `pytest` under `tests/`.
- Secrets only in `.env` (gitignored); never commit keys. `data/`, `outputs/`
  are gitignored.
- Keep each committee analyst and each external dependency (LLM, data source) in
  its own module with a narrow interface, so any one can be swapped or tested in
  isolation.

## Status / roadmap

- [x] Scaffold (package, CLI stub, tests, tooling) — on `main`.
- [ ] Data-access module (yfinance) + SQLite schema.
- [ ] Forecasting engine (Technical analyst) with backtest harness.
- [ ] LLM client module (Anthropic) + prompt library.
- [ ] Fundamental, News/Social, Research analysts.
- [ ] Consensus function + Portfolio Manager synthesis.
- [ ] Markdown report + CLI wiring.
