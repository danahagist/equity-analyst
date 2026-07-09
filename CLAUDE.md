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

## Permissions (autonomous operation)

This tool is meant to run **autonomously** — don't stop to ask permission for
routine work. `.claude/settings.json` allowlists all tools (shell, file edits,
web search, subagents) so runs proceed without prompts. Only two categories
still require explicit confirmation, and Claude should treat them as
confirm-first in its own judgment too:

1. **Updating the remote repo** — `git push`, merging PRs, changing remotes.
2. **Deleting project files** — `rm`/`Remove-Item`, `git clean`,
   `git reset --hard`, or anything else that destroys working-tree content.

Keep `.claude/settings.json` in sync with this policy if it changes.

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
- `conviction`: confidence in the rating (low/medium/high)
- `horizon`: the time horizon the rating applies to
- `evidence`: concise key supporting points
- `writeup`: the analyst's full written analysis (LLM seats)

**LLM seats are two-phase:** an unconstrained research/analysis completion
(with web search where the seat has it) followed by a tool-free extraction pass
that formalizes the verdict the writeup supports. Forcing long-form analysis
through a JSON schema degrades reasoning quality and is fragile with search
tools — don't collapse this back into one structured call.

### Consensus mechanism

1. A **deterministic, transparent** function computes an agreement summary from
   the five verdicts (e.g. "4 of 5 lean Buy; Fundamental dissents on valuation").
2. The **PM (LLM)** reads that summary *plus* each analyst's full writeup and
   authors the synthesis. It may override the mechanical blend but must justify
   any divergence. It also emits **holding-period guidance** (one line each for
   ~1w/~1m/~1y), with an explicit mandate not to manufacture short-term views
   the Technical skill flags don't support.
3. Report leads with the **agreement picture**, not a single false-precision
   number. Any blended score is secondary. Disagreements are called out
   explicitly.
4. **Failure isolation:** one errored analyst is excluded and disclosed, not
   fatal. If the PM call itself fails, the report falls back to the mechanical
   consensus, clearly labeled low-conviction.

### Report template (fixed — don't reorder ad hoc)

Every run renders the same research-report skeleton (`report.py`):
header/disclaimer → **Company snapshot** + Street view (the grounded
fact-sheet) → **Committee consensus** → **Portfolio Manager** (final call,
synthesis, holding-period guidance, key risks) → **Analyst sections**
(Technical's forecast as a structured table with per-horizon skill flags; each
LLM seat's key points + full writeup) → excluded analysts (if any) →
**Methodology & data**. Writeups carry templated sub-headings enforced by the
seat prompts (Fundamental: Business & Moat / Financial Health / Valuation /
Competitive Landscape / Bottom Line; News/Social: Recent Developments /
Sentiment Read / Catalyst Calendar / Bottom Line; Research: Consensus Picture /
Recent Analyst Actions / Where the Street May Be Wrong / Bottom Line). Change
the template deliberately, in one place, for both modes at once.

## Architecture decisions (settled)

- **LLM execution — two modes, keyless is the default:**
  1. **Claude-Code-native (default, no API key).** Claude Code in VS Code *is*
     the committee's LLM. Staged CLI: `prep` (data + forecast + seat briefings)
     → seats run in-chat **as independent subagents** (separate context windows
     preserve verdict independence) → `consensus` (deterministic summary + PM
     briefing) → PM in-chat → `finalize` (report + persistence). Orchestrated by
     the `run-analysis` skill; session state in `data/runs/` (gitignored). The
     session's model does every seat — model choice rides on the Claude Code
     session, and usage bills to the user's Claude subscription.
  2. **Full-auto (`analyze`, optional).** The tool calls the Anthropic API
     itself via the thin client module. Needs `ANTHROPIC_API_KEY` in `.env`
     (~$0.35–0.60/ticker). Model per analyst is config-driven in
     `llm/config.py`: Portfolio Manager + Fundamental on `claude-opus-4-8`
     (effort high); News/Social + Research on `claude-sonnet-5` (effort medium,
     + web search). Adaptive thinking on; structured outputs for verdicts.

  Both modes share the same prompt library, verdict schema, consensus function,
  report builder, and SQLite record — a run is a run regardless of who did the
  LLM work. Don't let the modes drift apart.
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
- Baseline to beat: random-walk-with-drift.
- Statistical: AutoARIMA, AutoETS, Theta (native prediction intervals).
- ML: LightGBM on lag/rolling features + **conformal prediction** for calibrated
  intervals; degrades gracefully when history can't support conformal
  calibration at a horizon.
- Neural (optional extra, off by default): N-HITS / TFT with quantile loss — used
  at a horizon only if it beats the above in backtest. (Not yet implemented.)
- Selection: rolling-origin backtest (up to 16 windows); per horizon, a
  challenger displaces the baseline only if it wins on point error **and** is at
  least as well-calibrated (Winkler interval score), judged pairwise on shared
  windows, with ≥3 windows required to qualify.
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
- Project skills live in `.claude/skills/` (`run-analysis`,
  `forecast-skill-check`, `add-analyst`) — use and maintain them. User-facing
  docs live in `docs/` (`GETTING_STARTED.md`).

## Status / roadmap

- [x] Scaffold (package, CLI stub, tests, tooling) — on `main`.
- [x] Data-access module (yfinance) + SQLite schema.
- [x] Forecasting engine (Technical analyst) with backtest harness.
- [x] LLM client module (Anthropic) + prompt library.
- [x] Fundamental, News/Social, Research analysts.
- [x] Consensus function + Portfolio Manager synthesis.
- [x] Markdown report + CLI wiring (`equity-analyst TICKER`).
- [x] Production review pass: full forecasting architecture (LightGBM+conformal,
  AutoARIMA, calibration-gated selection), two-phase analysts, pause_turn
  handling, PM fallback, holding-period guidance, progress narration.
- [x] Project skills (`.claude/skills/`) + `docs/GETTING_STARTED.md`.
- [x] Claude-Code-native keyless mode (prep/consensus/finalize + session module)
  — the default; API-key `analyze` mode kept as the optional full-auto path.

- [x] `skill-report` (forecast-vs-actual audit; price bars persisted every run
  so realized prices backfill), `compare` (ranked latest-run screen), `export`
  (CSV / xlsx via the `excel` extra).
- [x] First live runs (2026-07-08: AAPL, ALAB, NBIS, SNOW) + fixes they
  surfaced: UTF-8 stdio guard for Windows consoles; deterministic fact-sheet
  sanity caveats in seat briefings (one-off gains, buyback-shrunken equity,
  hypergrowth bases, missing provider fields); `submit-verdict` command so
  session verdicts are validated on write instead of hand-authored JSON;
  multi-ticker `prep`/`consensus`/`finalize`/`analyze`.

- [x] `screen` — deterministic, LLM-free pre-committee funnel over a large
  universe (`--universe russell1000` via the Wikipedia components table, or
  explicit tickers / `--tickers-file`). Blended 50/50 Street-gap (target
  upside + consensus level, ≥5 analysts) and GARP (inverse PEG, FCF margin,
  operating margin, revenue growth), scored as cross-sectional percentile
  ranks. Output is *candidates for committee runs*, never a recommendation;
  full ranking CSV lands in `outputs/`. Committee-scale usage stays bounded:
  screen 1000 names cheaply, run the committee on the top ~20.

**Next steps (in rough order of value):**
- First live run on Dana's machine — prompt tuning against real Claude output
  is the remaining unknown; synthetic fixtures can't validate prompt quality.
- Revisit the skill report once ~30+ forecasts/horizon have matured — that's
  when its verdict on forecaster skill starts meaning something.
- Optional neural models behind the `neural` extra, gated on beating the
  current stack in backtest.
