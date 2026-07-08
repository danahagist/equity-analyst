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
- An Anthropic API key (`ANTHROPIC_API_KEY`) for the LLM analysts
- Market data via `yfinance` (free, no key)

**New here? Read [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)** — install,
first run, how to read the report correctly, and best practices.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# Core + the forecasting engine + dev tools
pip install -e ".[forecast,dev]"

cp .env.example .env                 # then add your ANTHROPIC_API_KEY
```

## Usage

```bash
equity-analyst AAPL                  # full committee run → outputs/AAPL-<date>.md + stdout
equity-analyst NVDA --period 10y     # more price history for the forecast
equity-analyst TSLA --no-save        # stdout only, don't write the report file
equity-analyst MSFT --no-db          # don't persist the run to SQLite
```

Each run writes `outputs/<TICKER>-<YYYY-MM-DD>.md` and prints to stdout. SQLite
(`data/equity_analyst.db`) is the system of record — it keeps every run's
recommendation plus the per-horizon forecast, so forecast-vs-actual skill can be
checked over time. `data/` and `outputs/` are gitignored.

## Development

```bash
pytest          # run tests (forecast/pipeline tests need the 'forecast' extra)
ruff check .    # lint
ruff format .   # format
```

## License

MIT — see [LICENSE](LICENSE).
