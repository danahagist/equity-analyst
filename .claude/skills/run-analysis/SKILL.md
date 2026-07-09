---
name: run-analysis
description: Run the equity-analyst investment committee for one or more tickers. Default mode needs NO API key — Claude Code itself performs the LLM analyst seats via the staged prep/consensus/finalize CLI. Use when asked to run, analyze, screen, or demo the tool on stocks.
---

# Run a committee analysis (Claude-Code-native, no API key)

You (Claude Code) are the committee's LLM seats. Python does everything
deterministic: data, forecasting, the Technical verdict, consensus math,
report rendering, and storage. Follow the stages exactly — the value of the
committee is **independent** verdicts, so respect the independence rules.

## Preconditions

- Installed: `pip install -e ".[forecast,dev]"` in the project venv.
- Network to Yahoo Finance (yfinance). In sandboxed sessions Yahoo is often
  blocked (403) — do NOT route around a policy denial; tell the user a live
  run needs their machine.
- No API key needed for this flow.

## Stage 1 — prep

```bash
equity-analyst prep TICKER          # ~1-2 min; add --period 10y for more history
equity-analyst prep T1 T2 T3        # multi-ticker screen: preps run back to back
```

Prints a packet: the Technical analyst's verdict (already recorded) plus a
SYSTEM/TASK briefing for each LLM seat, the verdict JSON format, and the
verdicts file path (`data/runs/<TICKER>-<date>-verdicts.json`).

## Stage 2 — run the three seats as INDEPENDENT subagents

Spawn one subagent per seat (Fundamental, News/Social, Research) — in
parallel, in a single message. Subagents have separate context windows, which
preserves the independence that makes consensus meaningful. For each:

- Pass that seat's SYSTEM and TASK text from the packet **verbatim** as the
  core of the subagent's prompt, plus: "Return ONLY a JSON object:
  {"rating": <int -2..2>, "conviction": "low|medium|high", "horizon": "<str>",
  "evidence": "<3-6 key points>", "writeup": "<your full written analysis>"}".
- News/Social and Research subagents MUST use web search and cite what they
  found (source + date) in the writeup. Fundamental needs no web access —
  it reasons from the fact-sheet in its TASK.
- Do NOT include the packet's other briefings, the Technical verdict, or any
  other seat's output in a subagent's prompt.

If subagents are unavailable, run the seats one at a time yourself with this
discipline: complete each seat's analysis fully before reading the next
briefing, never reference another seat's conclusions inside a writeup, and
note in the final summary that seats shared one context window.

Record each seat's JSON verdict with `submit-verdict` (validates the schema
immediately instead of letting mistakes surface at finalize). Write each
verdict to a temp file, then:

```bash
equity-analyst submit-verdict TICKER --analyst Fundamental --file verdict.json
equity-analyst submit-verdict TICKER --analyst "News/Social" --file ...
equity-analyst submit-verdict TICKER --analyst Research --file ...
```

Do NOT hand-author the combined verdicts file — that path is error-prone with
long escaped writeups. If a seat fails (e.g. web search unavailable), omit
it — finalize will disclose the gap honestly. Never fabricate a verdict.

For multi-ticker screens: prep all tickers first, then spawn ALL seats for
ALL tickers in one parallel batch (independence rules apply per seat, not per
ticker), then consensus/PM/finalize per ticker.

## Stage 3 — consensus + PM

```bash
equity-analyst consensus TICKER
```

Prints the deterministic agreement summary and the Portfolio Manager
briefing. Now perform the PM role yourself in the main conversation (this
seat is *supposed* to see everything). Follow the briefing's mandate —
especially: do not manufacture short-term views the Technical skill flags
don't support, and justify any override of the mechanical blend. Record the
synthesis (exact schema shown in the briefing) via:

```bash
equity-analyst submit-verdict TICKER --analyst PM --file pm.json
```

## Stage 4 — finalize

```bash
equity-analyst finalize TICKER
```

Validates the session, renders the report to `outputs/<TICKER>-<date>.md`,
persists the run + forecasts to SQLite (skill tracking depends on this — don't
use --no-db casually), and prints the report. Show the user the report and
call out the consensus picture and any dissent first, not just the final call.

## Integrity rules (non-negotiable)

- Never edit the Technical verdict, the consensus numbers, or another seat's
  verdict to make the story cleaner. Disagreement is the product.
- Ground every claim; no invented figures. Missing data → reason
  qualitatively and say so.
- The report's disclaimers stay. This is research assistance, not advice.

## Full-auto alternative (API key)

With `ANTHROPIC_API_KEY` in `.env`, `equity-analyst analyze TICKER` does the
whole committee in one command via the Anthropic API (per-seat models from
`llm/config.py`). Same prompts, same report, same storage.

## Offline demo (no network at all)

`pytest -q tests/test_session.py` exercises the full staged flow with fixture
data, or build a demo packet in Python via `prep_packet(FakeDataSource(), ...)`
— see those tests for the pattern.
