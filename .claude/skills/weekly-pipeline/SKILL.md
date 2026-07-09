---
name: weekly-pipeline
description: Run the full weekly equity pipeline end to end (screen → forecast → rank → committee walk-down to 5 qualifiers → digest → email), or any single phase. Use when asked to run the weekly pipeline, the full workflow, or "the whole thing".
---

# Weekly pipeline (screen → forecast → rank → walk-down → digest → email)

The funnel Dana designed: cheaply screen the whole Russell 1000, forecast all
survivors (no LLM), order a walk-down queue, run the full committee one name at
a time until **5 names qualify**, then assemble one combined decision digest.
Dana fires this himself (the committee needs Claude Code as the LLM). Each
phase is also runnable on its own; this skill chains them.

**Guardrails (non-negotiable):** research assistance, not financial advice.
Levels are decision support, never orders — no auto-execution, ever. The
ranking is **blended-score-only**: the forecast never promotes a name (the
engine has no skill vs drift at most horizons); it can only demote via the
skill-gated veto in `rank`. See CLAUDE.md.

## Parameters (ask only if the user cares; else use defaults)

- `SCREEN_TOP` = 50 — names the screen keeps and the forecaster preps.
- `NEED` = 5 — qualifying names the walk-down collects.
- `--email` — send the digest at the end (needs SMTP_* in .env).

## Phase 1 — screen

```bash
equity-analyst screen --universe russell1000 --top 50
```

Full ranking lands in `outputs/screen-<date>.csv`.

## Phase 2 — forecast the survivors (no LLM, ~1–1.5 min each)

```bash
equity-analyst prep T1 T2 ... T50        # all SCREEN_TOP names from the CSV
```

Prepping all 50 is deliberate: it feeds the veto pass and gives the risk
overlay before any committee spend.

## Phase 3 — rank (walk-down queue)

```bash
equity-analyst rank --screen-csv outputs/screen-<date>.csv --top 50
```

Orders the queue by blended score and applies the **skill-gated veto**: a name
is demoted (to the bottom, reason shown — never hidden) only when a 1m/1y
horizon whose model beat the naive baseline shows a *materially negative*
expected return (beyond the ±1% flat band). Skilled-flat forecasts annotate
("no forecast support") but never demote — at 1y the drift-beating models are
frequently flat-forecasters, and flat is not bearish. No-skill forecasts can
neither promote nor demote.

## Phase 4 — committee walk-down until 5 qualify

Take names from the top of the queue **one at a time** (batches of 2–3 are
fine to keep wall-clock sane). For each: run the committee exactly as the
**run-analysis** skill specifies (independent subagents per seat,
`submit-verdict`, `consensus`, PM synthesis, `finalize`). Then check the bar:

```bash
equity-analyst qualify T1 T2 ...          # all names committee'd so far
```

**The bar:** PM Buy or better, **medium+ conviction**, committee **not split**.
Stop when 5 qualify. Non-qualifiers stay in the digest's audit trail — they are
disclosed, not discarded. Run web seats in waves of ~6 to respect the session
limit; per-seat verdict files make a hit-the-wall run resumable.

## Phase 5 — the combined decision digest

```bash
equity-analyst digest Q1 Q2 Q3 Q4 Q5      # the 5 qualifiers
```

One document with, per name: every analyst's bottom line, the consensus and
dissents, the PM's full synthesis + risks + holding-period fit, the levels row,
and a qualification mark — plus an ETF-exposure section. Then **write the
executive summary yourself** (you have read every report): the strongest cases
and why, shared macro exposures, where the committee disagreed, what would
change the calls. Save it to a file and re-render:

```bash
equity-analyst digest Q1 ... Q5 --exec-summary-file <path>
```

The digest saves to `outputs/digest-<date>.md`. Never fabricate the executive
summary from thin air — it must be grounded in the seat writeups.

## Phase 6 — email the package (optional)

```bash
equity-analyst notify --subject "Weekly committee — <date>" \
  --body-file outputs/digest-<date>.md
```

Needs `SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_FROM/SMTP_TO` in `.env`
(Gmail: App Password). If SMTP isn't configured, `notify` exits with guidance —
report that instead of failing the run.

## Wrap-up

Lead the summary with the consensus/dissent picture and the qualification
outcomes (who made the five, who was walked past and why), then the levels
table. `equity-analyst compare` remains the cross-run index.

## Running a single phase

Each phase is independent: `screen`, `prep`, `rank`, the run-analysis skill,
`qualify`, `levels`, `etf-exposure`, `digest`, and `notify` all work
standalone. Use this skill only for the full chain.
