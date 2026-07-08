# Getting Started with equity-analyst

A practical guide to installing, running, and — most importantly — *reading*
the tool correctly. Ten minutes here will save you from the two classic
mistakes: over-trusting point forecasts and ignoring dissent.

## What this tool is (and isn't)

Given a ticker, five role-specialized analysts independently reach a rated
recommendation, and a portfolio manager synthesizes them into a final call:

| Seat | Looks at | Engine |
|---|---|---|
| Technical | momentum, probabilistic price forecast (1d/1w/1m/1y) | Python (statistical + ML models, backtested) |
| Fundamental | business model, financials, valuation, competition | Claude Opus over real fundamentals |
| News/Social | events, sentiment, upcoming catalysts | Claude Sonnet + live web search |
| Research | sell-side ratings, price targets, third-party research | Claude Sonnet + consensus data + web search |
| Portfolio Manager | the big picture, risk, the final call | Claude Opus over everything above |

It is **research assistance, not financial advice**, and it is honest by
design: the forecaster is benchmarked against a naive baseline and *tells you
when it has no edge*. Expect to see "no model beat naive drift" often — that is
the tool working, not failing. Anyone selling you confident short-term price
predictions is selling noise.

## Install

```bash
git clone <your-repo-url> && cd equity-analyst
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[forecast,dev]"

cp .env.example .env       # then put your ANTHROPIC_API_KEY in .env
pytest -q                  # optional: verify the install (all tests are offline)
```

Requirements: Python 3.11+, an Anthropic API key. Market data is free via
Yahoo (no key). A full run costs roughly **$0.35–0.60** in model tokens plus
web-search fees — call it under a dollar per ticker.

## First run

```bash
equity-analyst AAPL
```

What happens (progress narrates on stderr, ~2–5 minutes):

1. Pulls 5 years of prices + fundamentals + analyst consensus data.
2. Backtests five forecasting models against a random-walk baseline across
   16 rolling windows, per horizon (the slow, honest part).
3. Each analyst researches and writes its analysis independently, then its
   verdict is extracted in structured form.
4. A deterministic function computes the agreement picture; the PM reads
   everything and writes the synthesis.
5. The report prints to stdout and is saved to `outputs/AAPL-<date>.md`; the
   run and its forecasts are recorded in `data/equity_analyst.db`.

## How to read the report

**Start with the Consensus block, not the final call.** The vote split and
dissent list *are* the product:

- **Unanimous/strong agreement** → conviction. Divergence → risk that is now
  named and arguable, instead of hidden inside an average.
- The **blended score is secondary** — a +0.3 that hides a Strong Buy and a
  Strong Sell is a warning, not a mild buy.
- **Read the dissenter's section first.** A lone well-argued dissent (usually
  Fundamental on valuation) is the most information-dense part of the report.

**Holding-period guidance** (in the PM section) maps the committee onto the
horizon you actually care about:

- **1 day / 1 week** — assume noise. If the Technical section says "no skill
  vs drift" at these horizons, nobody has an edge here and the guidance will
  say so. Don't day-trade off this tool.
- **1 month** — catalyst territory: News/Social's calendar and the Technical
  forecast matter most.
- **1 year** — fundamentals and valuation dominate; the forecast interval will
  be honestly wide (often ±20–30%). The question at 1y isn't "what price" but
  "is the thesis right".

**Reading the Technical table:** each horizon shows the point estimate, an 80%
interval, which model won, and whether it beat the baseline in backtest.
`drift-only, direction not proven` means exactly that — treat the point number
as decoration around the interval.

## Best practices

- **Compare tickers on the same day**, not across days — market context shifts.
- **Re-run on a cadence** (weekly, or after earnings/major news), not
  continuously. Verdicts move with information, not with re-rolls.
- **Track the tool's record.** Every run stores forecast-vs-actual data in
  SQLite. Periodically audit whether the forecaster's intervals actually
  contain reality ~80% of the time (in a Claude Code session, the
  `forecast-skill-check` skill does this). If the tool has no skill at a
  horizon, believe it — and weight the qualitative seats accordingly.
- **Don't cherry-pick.** If you run 20 tickers and act only on the most
  bullish report, you've reinvented selection bias. Decide your universe
  first.
- **Position sizing is yours.** The committee rates direction and conviction;
  it does not know your portfolio, tax situation, or risk budget.
- **When an analyst errored** (it happens — web search flakes), the report
  says so at the top. A 3-of-4 committee is still useful; a silent gap
  wouldn't be.

## Working on the tool with Claude Code

The repo carries skills that Claude Code picks up automatically:

- `run-analysis` — run or demo the tool correctly (including offline).
- `forecast-skill-check` — audit forecast-vs-actual calibration from SQLite.
- `add-analyst` — the recipe for adding a committee seat.

`CLAUDE.md` is the working agreement — architecture decisions, honesty
guardrails, and how decisions get made. Read it before changing anything
structural.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `error: ANTHROPIC_API_KEY is not set` | Copy `.env.example` → `.env`, add your key. |
| `market data unavailable` | Yahoo hiccup or `yfinance` breakage (it's unofficial). Retry; if persistent, check for a `yfinance` update. Corporate networks/sandboxes may block Yahoo outright. |
| `LLM call failed` | Check the key is valid and has credit; the SDK already retried rate limits before this surfaced. |
| Report shows "Portfolio Manager synthesis unavailable" | The PM call failed; you got the mechanical consensus, clearly labeled low-conviction. Re-run for a full synthesis. |
| Run feels slow | ~30–60s is backtesting, the rest is LLM calls (web search seats are the long pole). `--period 2y` shortens backtests at the cost of fewer windows. |
| Forecast says "too few backtest windows" | Short price history (recent IPO, or short `--period`). The tool refuses to claim skill it can't demonstrate — pull more history if it exists. |
