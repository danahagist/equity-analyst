"""Deterministic, transparent consensus from the analysts' verdicts.

This is intentionally simple and explainable (see CLAUDE.md): it summarizes the
agreement picture and a conviction-weighted blended score. It does NOT make the
final call — the PM does, reading this summary plus every analyst's writeup.
"""

from __future__ import annotations

from dataclasses import dataclass

from equity_analyst.committee.verdict import Verdict

_CONVICTION_WEIGHT = {"low": 1.0, "medium": 2.0, "high": 3.0}


def _direction(rating: int) -> str:
    if rating > 0:
        return "Buy"
    if rating < 0:
        return "Sell"
    return "Hold"


@dataclass(frozen=True, slots=True)
class ConsensusSummary:
    n: int
    counts: dict[str, int]  # {"Buy": .., "Hold": .., "Sell": ..}
    leaning: str  # majority direction, or "Split" on a tie for the top
    blended_score: float  # conviction-weighted mean rating (secondary to the picture)
    agreement_level: str  # unanimous | strong | majority | split
    dissenters: list[str]  # analysts opposing the leaning direction
    headline: str


def compute_consensus(verdicts: list[Verdict]) -> ConsensusSummary:
    if not verdicts:
        raise ValueError("cannot compute consensus over zero verdicts")

    n = len(verdicts)
    counts = {"Buy": 0, "Hold": 0, "Sell": 0}
    for v in verdicts:
        counts[_direction(v.rating)] += 1

    top = max(counts.values())
    leaders = [d for d, c in counts.items() if c == top]
    leaning = leaders[0] if len(leaders) == 1 else "Split"

    weighted = sum(v.rating * _CONVICTION_WEIGHT[v.conviction] for v in verdicts)
    weight_total = sum(_CONVICTION_WEIGHT[v.conviction] for v in verdicts)
    blended = weighted / weight_total if weight_total else 0.0

    if top == n:
        level = "unanimous"
    elif top >= -(-2 * n // 3):  # ceil(2n/3)
        level = "strong"
    elif top > n / 2:
        level = "majority"
    else:
        level = "split"

    dissenters = (
        [v.analyst for v in verdicts if _direction(v.rating) != leaning]
        if leaning != "Split"
        else []
    )

    return ConsensusSummary(
        n=n,
        counts=counts,
        leaning=leaning,
        blended_score=round(blended, 2),
        agreement_level=level,
        dissenters=dissenters,
        headline=_headline(n, counts, leaning, level, dissenters, verdicts),
    )


def _headline(
    n: int,
    counts: dict[str, int],
    leaning: str,
    level: str,
    dissenters: list[str],
    verdicts: list[Verdict],
) -> str:
    if leaning == "Split":
        parts = ", ".join(f"{c} {d}" for d, c in counts.items() if c)
        return f"No majority ({parts}) — the committee is divided."
    lead_count = counts[leaning]
    base = f"{lead_count} of {n} analysts lean {leaning} ({level} agreement)"
    if not dissenters:
        return base + "."
    notes = "; ".join(
        f"{v.analyst} dissents ({v.rating_label})"
        for v in verdicts
        if v.analyst in dissenters
    )
    return f"{base}. {notes}."
