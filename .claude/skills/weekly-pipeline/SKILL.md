---
name: weekly-pipeline
description: Run the full 4-phase weekly equity pipeline end to end (screen → prep → committee → entry/exit levels → email), or any single phase. Use when asked to run the weekly pipeline, the full workflow, or "the whole thing".
---

# Weekly pipeline (screen → prep → committee → levels → email)

The funnel Dana designed: cheaply screen the whole Russell 1000, forecast the
survivors, run the full committee only on the best, attach decision-support
entry/exit levels, and email the package. Dana fires this himself (it is not a
hands-off cron — the committee needs Claude Code as the LLM). Each phase is
also runnable on its own; this skill chains them.

**Guardrails (non-negotiable):** research assistance, not financial advice.
Levels are decision support, never orders — no auto-execution, ever. Never rank
or select on the forecast's point "upside" (the engine has no skill vs drift at
most horizons); select on the blended screen score and use the forecast only
for risk framing. See CLAUDE.md.

## Parameters (ask only if the user cares; else use defaults)

- `SCREEN_TOP` = 50 — how many the screen keeps.
- `COMMITTEE_TOP` = 10 — how many get the full committee + levels.
- `--email` — send the result package at the end (needs SMTP_* in .env).

## Phase 1 — screen

```bash
equity-analyst screen --universe russell1000 --top 50
```

Full ranking lands in `outputs/screen-<date>.csv`. Take the top
`COMMITTEE_TOP` tickers **by blended score** (not by target upside).

## Phase 2 — prep (forecasts) for the committee set

```bash
equity-analyst prep T1 T2 ... T10          # multi-ticker; ~1-1.5 min each, no API cost
```

(You may prep the full top-50 if you want the forecast as a risk overlay when
choosing the 10, but the *selection* stays blended-score-first.)

## Phase 3 — committee on the top 10

Run the committee for each ticker exactly as the **run-analysis** skill
specifies (independent subagents per seat, `submit-verdict` to record each,
deterministic `consensus`, PM synthesis, `finalize`). Batch the seats in waves
to respect concurrency/session limits. This is the usage-heavy phase — if the
user is watching usage, pause after the first few tickers and report the impact
before continuing.

## Phase 4 — entry/exit levels

```bash
equity-analyst levels T1 T2 ... T10
```

Decision-support buy/trim/target/stop from the forecast's 80% intervals. Reads
the packets from phase 2. Include this table in the final summary.

## Phase 5 — email the package (optional)

```bash
equity-analyst notify --subject "Weekly committee — <date>" \
  --body-file outputs/compare-<date>.md \
  --attach outputs/T1-<date>.md --attach outputs/T2-<date>.md ...
```

Needs `SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_FROM/SMTP_TO` in `.env`
(Gmail: App Password, not the account password). If SMTP isn't configured,
`notify` exits with guidance — report that instead of failing the run.

## Wrap-up

Finish with `equity-analyst compare` (ranked screen across all stored runs) and
lead the summary with the consensus/dissent picture and the levels table — not
just a leaderboard. Save the compare output to `outputs/compare-<date>.md` so it
can be the email body.

## Running a single phase

Each phase is independent: `screen`, `prep`, the run-analysis skill, `levels`,
and `notify` all work standalone. Use this skill only for the full chain.