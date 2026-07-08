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
| Fundamental | business model, financials, valuation, competition | Claude, over real fundamentals |
| News/Social | events, sentiment, upcoming catalysts | Claude + live web search |
| Research | sell-side ratings, price targets, third-party research | Claude + consensus data + web search |
| Portfolio Manager | the big picture, risk, the final call | Claude, over everything above |

It is **research assistance, not financial advice**, and it is honest by
design: the forecaster is benchmarked against a naive baseline and *tells you
when it has no edge*. Expect to see "no model beat naive drift" often — that is
the tool working, not failing.

**No API key required.** In the default mode, Claude Code (the VS Code
extension you already use) performs the Claude seats in-chat on your Claude
subscription. Python does everything deterministic: data, forecasting,
consensus math, the report, and storage. (An optional full-auto mode with an
API key exists — see the end.)

## Install

```bash
git clone <your-repo-url> && cd equity-analyst
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[forecast,dev]"
pytest -q                  # optional: verify the install (all tests are offline)
```

Requirements: Python 3.11+, VS Code with the Claude Code extension (signed in
to your Claude account). Market data is free via Yahoo (no key).

## First run

Open the repo in VS Code, start Claude Code, and say:

> Run the committee on AAPL

That's it. The `run-analysis` skill (checked into the repo) tells Claude Code
exactly what to do:

1. `equity-analyst prep AAPL` — Python pulls 5 years of prices + fundamentals
   + analyst consensus, backtests five forecasting models against a
   random-walk baseline, records the Technical analyst's verdict, and prints a
   *briefing packet* for the remaining seats.
2. Claude Code spawns the **Fundamental, News/Social, and Research analysts as
   independent subagents** (separate context windows — so their agreement
   still means something). The search seats use live web search. Each returns
   a verdict + full writeup, saved to a session file.
3. `equity-analyst consensus AAPL` — Python computes the deterministic
   agreement summary and prints the Portfolio Manager briefing.
4. Claude Code performs the PM role — final call, key risks, holding-period
   guidance — and saves it.
5. `equity-analyst finalize AAPL` — Python validates everything, renders the
   report to `outputs/AAPL-<date>.md`, and records the run + forecasts in
   SQLite (`data/equity_analyst.db`) so the tool's track record accumulates.

Expect a few minutes end to end. Cost: your Claude subscription usage — no
separate API bill.

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
  SQLite. Periodically ask Claude Code to *"check whether the forecaster has
  skill yet"* (the `forecast-skill-check` skill) — it audits whether the 80%
  intervals actually contain reality ~80% of the time. If the tool has no
  skill at a horizon, believe it — and weight the qualitative seats
  accordingly.
- **Don't cherry-pick.** If you run 20 tickers and act only on the most
  bullish report, you've reinvented selection bias. Decide your universe
  first.
- **Position sizing is yours.** The committee rates direction and conviction;
  it does not know your portfolio, tax situation, or risk budget.
- **When a seat errored** (web search flakes happen), the report says so at
  the top. A 3-of-4 committee is still useful; a silent gap wouldn't be.
- **One honesty caveat of the in-chat mode:** seat independence relies on
  subagents having separate contexts. If Claude Code ever runs the seats
  without subagents, it will note that in the summary — treat that run's
  "agreement" a bit more skeptically.

## Talking to the tool in Claude Code

The repo ships skills, so plain requests work:

- *"Run the committee on NVDA"* → the full staged flow above.
- *"Check whether the forecaster has skill yet"* → forecast-vs-actual audit.
- *"Add a macro analyst seat"* → guided by the `add-analyst` recipe.
- *"Compare the last AAPL and MSFT reports"* → they're markdown in `outputs/`
  and rows in SQLite; Claude Code can read both.

`CLAUDE.md` is the working agreement — architecture decisions, honesty
guardrails, and how decisions get made. Read it before changing anything
structural.

## Optional: full-auto mode (API key)

If you later want unattended runs (cron a weekly universe sweep, CI, etc.),
put an `ANTHROPIC_API_KEY` from console.anthropic.com in `.env` and run:

```bash
equity-analyst analyze AAPL        # one command, ~$0.35–0.60 per ticker
```

Same prompts, same report, same storage — the tool makes the API calls itself
(Opus for judgment seats, Sonnet for search seats, per `llm/config.py`).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `market data unavailable` | Yahoo hiccup or `yfinance` breakage (it's unofficial). Retry; if persistent, check for a `yfinance` update. Corporate networks/sandboxes may block Yahoo outright. |
| `no packet for TICKER` on consensus/finalize | Run `equity-analyst prep TICKER` first (stages share state via `data/runs/`). |
| Report shows "Portfolio Manager synthesis unavailable" | The PM step never landed in the session file; you got the mechanical consensus, clearly labeled low-conviction. Re-run stage 3–5. |
| `prep` feels slow | ~30–60s is backtesting five models across 16 windows. `--period 2y` shortens it at the cost of fewer windows. |
| Forecast says "too few backtest windows" | Short price history (recent IPO, or short `--period`). The tool refuses to claim skill it can't demonstrate. |
| `analyze` says it needs an API key | That's full-auto mode only — use the keyless flow above, or add a key from console.anthropic.com. |
