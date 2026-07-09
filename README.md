# equity-analyst

An **investment-committee** equity research tool. Given a stock ticker, five
role-specialized analysts each independently reach a *rated recommendation*, and
a portfolio manager synthesizes them into a final call. The valuable output is
the **consensus and the disagreement**: agreement = conviction, divergence =
flagged risk.

## The committee

| Analyst | Job | Powered by |
|---|---|---|
| **Technical** | momentum, patterns, probabilistic price forecast (1d/1w/1m/1y) | Python forecasting engine |
| **Fundamental** | business model, financials, valuation, industry | real fundamentals + Claude (Opus) |
| **News/Social** | events driving price/momentum, upcoming catalysts | Claude (Sonnet) web search |
| **Research** | existing analyst ratings, price targets, 3rd-party research | analyst data + Claude web search |
| **Portfolio Manager** | synthesize, big picture, risk, final call | Claude (Opus) over the other four |

Each analyst writes a full analysis and emits a structured verdict — `rating`
(−2…+2), `conviction`, `horizon`, key evidence. A deterministic function
summarizes the agreement; the PM authors the synthesis (with justification for
any override) plus **holding-period guidance** for ~1-week, ~1-month, and
~1-year holders. See [`CLAUDE.md`](CLAUDE.md) for the full design.

## Honesty by design

- The Technical forecast is **probabilistic and benchmarked against a naive
  baseline**. Where a model can't beat naive drift at a horizon, the tool says so
  and reports drift + a wide interval — no confident point-price predictions.
- Sentiment comes from news and public pages via web search, **not** a real-time
  social firehose.
- Research assistance, **not** financial advice.

## Requirements

- Python 3.11+
- VS Code with the Claude Code extension (signed in) — **no API key needed**
- Market data via `yfinance` (free, no key)

**New here? Read [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)** — install,
first run, how to read the report correctly, and best practices.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# Core + the forecasting engine + dev tools
pip install -e ".[forecast,dev]"
```

## Usage (default: Claude Code runs the committee — no API key)

Open the repo in VS Code, start Claude Code, and say **"run the committee on
AAPL"**. The bundled `run-analysis` skill drives the staged flow:

```bash
equity-analyst prep AAPL        # Python: data + forecast + seat briefings
#   → Claude Code runs Fundamental / News/Social / Research as independent
#     subagents (search seats use live web search)
equity-analyst consensus AAPL   # Python: deterministic agreement + PM briefing
#   → Claude Code performs the Portfolio Manager synthesis
equity-analyst finalize AAPL    # Python: validate, render, persist
```

Each run writes `outputs/<TICKER>-<YYYY-MM-DD>.md` and records the run +
per-horizon forecasts in SQLite (`data/equity_analyst.db`) — the system of
record, so forecast-vs-actual skill can be audited over time. `data/` and
`outputs/` are gitignored.

### The weekly pipeline (screen → rank → walk-down → digest)

For working a whole universe instead of one ticker, the bundled
`weekly-pipeline` skill chains the funnel end to end (say **"run the weekly
pipeline"** in Claude Code):

```bash
equity-analyst screen --universe russell1000 --top 50   # cheap, LLM-free ranking
equity-analyst prep T1 ... T50                          # forecasts for all survivors
equity-analyst rank --screen-csv outputs/screen-<date>.csv --top 50
#   → walk-down queue: blended score orders it; the forecast can only demote
#     (skill-gated veto), never promote
#   → committee runs one name at a time until 5 clear the bar:
equity-analyst qualify T1 T2 ...     # PM Buy+, medium+ conviction, not split
equity-analyst etf-strategy --screen-csv outputs/screen-<date>.csv --top 50
equity-analyst digest Q1 ... Q5 --exec-summary-file <path> \
  --etf-strategy-file outputs/etf-strategy-<date>.md      # one decision document
equity-analyst notify --subject "Weekly committee" --body-file outputs/digest-<date>.md
```

Selection is by the blended screen score only — the forecast's point "upside"
never promotes a name (it has no skill vs drift at most horizons); it can only
demote via a skill-gated veto, with every demotion reasoned and visible.

### Working with accumulated runs

```bash
equity-analyst compare               # rank the latest run per ticker side by side
equity-analyst compare AAPL MSFT     # …or just these tickers
equity-analyst levels AAPL MSFT      # entry/exit bands from the calibrated intervals
equity-analyst etf-exposure AAPL     # which funds hold your candidates
equity-analyst skill-report          # audit stored forecasts vs realized prices
equity-analyst export                # dump the SQLite record to CSV (or --format xlsx)
```

The skill report is the honesty loop: it checks whether the 80% intervals
actually contained reality ~80% of the time and whether the models beat a
naive forecast out of sample. Every run stores the price history it pulled, so
realized prices backfill automatically as you keep running.

### Optional: full-auto mode (API key)

For unattended runs (cron a weekly sweep), add `ANTHROPIC_API_KEY` to `.env`
(see `.env.example`) and run everything in one command:

```bash
equity-analyst analyze AAPL          # ~$0.35–0.60/ticker via the Anthropic API
equity-analyst analyze NVDA --period 10y
```

Same prompts, same report, same storage — the tool makes the API calls itself.

## Development

```bash
pytest          # run tests (forecast/pipeline tests need the 'forecast' extra)
ruff check .    # lint
ruff format .   # format
```

## License

MIT — see [LICENSE](LICENSE).
