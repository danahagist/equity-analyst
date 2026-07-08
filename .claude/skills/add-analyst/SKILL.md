---
name: add-analyst
description: Add a new analyst seat to the investment committee (e.g. a macro, insider-activity, or options-flow analyst). Use when asked to add, create, or extend committee analysts or roles.
---

# Add a committee analyst

Every seat follows the same contract; the committee's value comes from
independent verdicts, so keep the new seat's inputs disjoint from the others
where possible.

## Steps

1. **Pick the engine type:**
   - *Deterministic* (pure Python over data, like Technical): implement
     `evaluate(context) -> Verdict` directly. No LLM plumbing.
   - *LLM-driven*: subclass `LLMAnalyst` (`committee/base.py`) and implement
     `build_prompt(context) -> (system, user)`. Evaluation is two-phase
     automatically (free-form research → tool-free verdict extraction); do NOT
     ask for JSON in your prompt.
2. **LLM seats: register a role** in `llm/config.py` — add a `ROLE_*` constant
   and a `ModelConfig` entry in `DEFAULT_ROLE_MODELS`. Match model tier to
   cognitive load (Opus for judgment, Sonnet for search/aggregation);
   `web_search=True` only if the seat genuinely needs live information.
3. **Ground the prompt.** Only claim data actually present in
   `AnalystContext`; if the seat needs new data, extend the
   `MarketDataSource` protocol + Yahoo impl + `FakeDataSource` together, and
   instruct the analyst to reason qualitatively when a field is missing.
4. **Wire into the pipeline** — add to the `analysts` list in `pipeline.py`.
   Order doesn't matter; failures are isolated per-seat.
5. **Consensus/PM pick it up automatically** (they operate on the verdict
   list), but tell the PM what the new seat covers: update the roster
   sentence in `committee/portfolio_manager.py`'s `_SYSTEM`.
6. **Tests** (offline, via `FakeLLMClient` / hand-built contexts):
   - routing: correct role, two-phase calls, prompt grounded on context
   - verdict validation and, for deterministic seats, the rating logic itself
   - a pipeline test asserting the new seat appears in `result.verdicts`
7. **Docs**: add the seat to the committee tables in CLAUDE.md and README.

## Invariants (don't break)

- Verdict scale stays −2…+2 with low/medium/high conviction.
- Independence: an analyst never reads another analyst's verdict (only the PM
  synthesizes).
- Honesty guardrails from CLAUDE.md apply to prompts verbatim — no invented
  figures, disclose data gaps, research-not-advice framing.
