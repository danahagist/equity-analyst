"""Committee walk-down queue: blended screen rank + skill-gated forecast veto.

The ranking philosophy (see CLAUDE.md): the committee queue is ordered by the
**blended screen score only**. The forecast engine's point "upside" never
promotes a name — at most horizons it has no skill versus naive drift, and
mixing drift extrapolation into the ranking would triple-count the same
"price rose recently / Street is anchored high" echo the Street-gap pillar
already carries.

The forecast gets exactly one vote, and only where it has earned it: a
**skill-gated veto**. A name is *demoted* (never deleted) when a horizon whose
model actually beat the naive baseline in backtest shows a negative expected
return, or when the calibrated risk/reward is poor at a skill-flagged target
horizon. Demoted names sink below every clean name in the walk-down queue with
the reason logged — visible, not hidden. No-skill horizons can neither promote
nor demote: they are noise in both directions.

This is a soft veto by design: a skilled point signal is still a weak signal —
strong enough not to spend committee budget on the name first, not strong
enough to declare it untouchable.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from equity_analyst.levels import plan_from_packet

# Horizons the veto pass looks at. 1d is excluded entirely: a skilled one-day
# signal is irrelevant to the multi-week/month holding periods the pipeline
# serves. 1w signals are annotated but cannot demote for the same reason —
# only 1m/1y skilled signals speak to the holding thesis.
VETO_HORIZONS = ("1w", "1m", "1y")
NEGATIVE_VETO_HORIZONS = ("1m", "1y")

# Reward:risk below this at a *skill-flagged* target horizon demotes.
MIN_REWARD_RISK = 1.0


@dataclass
class RankedCandidate:
    ticker: str
    blended: float | None  # screen score; None when not screened this cycle
    vetoed: bool = False
    veto_reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # non-demoting annotations
    has_packet: bool = True


def apply_veto(candidate: RankedCandidate, packet: dict) -> RankedCandidate:
    """Apply the skill-gated forecast veto to one candidate, in place.

    Demotes only on evidence the backtest validated; annotates everything else.
    """
    last_price = float(packet["last_price"])
    rows = {r["label"]: r for r in packet.get("forecast_rows", []) if r["label"] in VETO_HORIZONS}

    skilled = {label: r for label, r in rows.items() if r.get("beats_baseline")}
    if not skilled:
        candidate.notes.append("no skilled forecast signals — queue order is the blended rank")

    for label, row in sorted(skilled.items()):
        expected = (float(row["point"]) - last_price) / last_price
        if expected <= 0 and label in NEGATIVE_VETO_HORIZONS:
            candidate.vetoed = True
            candidate.veto_reasons.append(
                f"skilled {label} model ({row.get('model', '?')}) shows "
                f"{expected:+.1%} expected return — the one validated signal is not positive"
            )
        else:
            tone = "supportive" if expected > 0 else "cautionary; 1w cannot demote"
            candidate.notes.append(f"skilled {label} signal: {expected:+.1%} ({tone})")

    # Risk/reward veto, gated on the 1y target horizon having beaten the
    # baseline — an R:R computed from a drift-only point is not evidence, and
    # an R:R against a near-term fallback target is not the holding thesis.
    try:
        plan = plan_from_packet(packet)
    except ValueError:
        plan = None
    if plan is not None and plan.target_label == "1y" and plan.target_beats_drift:
        rr = plan.reward_risk
        if rr is not None and rr < MIN_REWARD_RISK and not candidate.vetoed:
            candidate.vetoed = True
            candidate.veto_reasons.append(
                f"reward:risk {rr:.1f} < {MIN_REWARD_RISK:.1f} at the skill-flagged "
                f"{plan.target_label} target horizon"
            )

    return candidate


def build_queue(
    candidates: list[tuple[str, float | None]],
    packets: dict[str, dict],
) -> list[RankedCandidate]:
    """Order the walk-down queue: clean names by blended rank, vetoed names last.

    ``candidates`` is (ticker, blended) in screen-rank order; ``packets`` maps
    ticker -> prep packet (a missing packet is flagged, not silently dropped).
    """
    queue: list[RankedCandidate] = []
    for ticker, blended in candidates:
        cand = RankedCandidate(ticker=ticker.upper(), blended=blended)
        packet = packets.get(cand.ticker)
        if packet is None:
            cand.has_packet = False
            cand.notes.append("no prep packet — run `equity-analyst prep` before the committee")
        else:
            apply_veto(cand, packet)
        queue.append(cand)

    order = {c.ticker: i for i, c in enumerate(queue)}
    queue.sort(key=lambda c: (c.vetoed, order[c.ticker]))
    return queue


def read_screen_csv(path: Path, *, top: int) -> list[tuple[str, float | None]]:
    """Top-N (ticker, blended) pairs from a `screen` CSV, in rank order."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    out: list[tuple[str, float | None]] = []
    for row in rows[:top]:
        try:
            blended = float(row["blended"])
        except (KeyError, TypeError, ValueError):
            blended = None
        out.append((row["ticker"].upper(), blended))
    return out


def build_rank_report(queue: list[RankedCandidate], *, as_of: str) -> str:
    lines = [
        f"# Committee walk-down queue ({as_of})",
        "",
        "_Ordered by the blended screen score. The forecast never promotes a name; "
        "it can only demote via a **skill-gated veto** (a horizon that beat the naive "
        "baseline in backtest showing a negative expected return, or poor reward:risk "
        "at a skill-flagged target). Demoted names sink to the bottom with the reason "
        "shown — they are not hidden. Not financial advice._",
        "",
        "| # | Ticker | Blended | Veto | Notes |",
        "|---|--------|---------|------|-------|",
    ]
    for i, c in enumerate(queue, start=1):
        blended = f"{c.blended:.3f}" if c.blended is not None else "—"
        status = "DEMOTED" if c.vetoed else ("no packet" if not c.has_packet else "—")
        detail = "; ".join(c.veto_reasons or c.notes) or "—"
        lines.append(f"| {i} | {c.ticker} | {blended} | {status} | {detail} |")
    lines += [
        "",
        "Walk-down: run the committee one name at a time in this order until 5 names "
        "clear the bar (PM Buy or better, medium+ conviction, no split committee — "
        "check with `equity-analyst qualify`).",
    ]
    if any(c.vetoed for c in queue):
        lines += [
            "",
            "Demoted names remain reachable if the clean names run out — the veto is "
            "a budget-ordering device, not a verdict.",
        ]
    return "\n".join(lines)
