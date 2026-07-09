"""Committee walk-down queue: blended screen rank + skill-gated forecast veto.

The ranking philosophy (see CLAUDE.md): the committee queue is ordered by the
**blended screen score only**. The forecast engine's point "upside" never
promotes a name — at most horizons it has no skill versus naive drift, and
mixing drift extrapolation into the ranking would triple-count the same
"price rose recently / Street is anchored high" echo the Street-gap pillar
already carries.

The forecast gets exactly one vote, and only where it has earned it: a
**skill-gated veto**. A name is *demoted* (never deleted) when a 1m/1y horizon
whose model actually beat the naive baseline in backtest shows a *materially
negative* expected return (beyond the flat band). Skilled-flat forecasts only
annotate: at the 1y horizon the models that beat drift are frequently
flat-forecasters (they win on error by predicting nothing), and "validated
signal ≈ flat" is not a bearish statement — the first live run showed a
flat-catching rule demoting over half the universe. Demoted names sink below
every clean name in the walk-down queue with the reason logged — visible, not
hidden. No-skill horizons can neither promote nor demote: they are noise in
both directions.

This is a soft veto by design: a skilled point signal is still a weak signal —
strong enough not to spend committee budget on the name first, not strong
enough to declare it untouchable.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

# Horizons the veto pass looks at. 1d is excluded entirely: a skilled one-day
# signal is irrelevant to the multi-week/month holding periods the pipeline
# serves. 1w signals are annotated but cannot demote for the same reason —
# only 1m/1y skilled signals speak to the holding thesis.
VETO_HORIZONS = ("1w", "1m", "1y")
NEGATIVE_VETO_HORIZONS = ("1m", "1y")

# A skilled expected return must be below -FLAT_BAND to demote; within the band
# it is flat, and flat annotates rather than vetoes.
FLAT_BAND = 0.01


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
    A malformed packet (no usable price) disables the veto for that name rather
    than crashing the whole queue — the walk-down must survive one bad packet.
    """
    raw_price = packet.get("last_price")
    if raw_price is None or float(raw_price) <= 0:
        candidate.notes.append("packet has no usable last price — veto pass skipped")
        return candidate
    last_price = float(raw_price)
    rows = {
        r["label"]: r
        for r in packet.get("forecast_rows", [])
        if r.get("label") in VETO_HORIZONS and r.get("point") is not None
    }

    skilled = {label: r for label, r in rows.items() if r.get("beats_baseline")}
    if not skilled:
        candidate.notes.append("no skilled forecast signals — queue order is the blended rank")

    for label, row in sorted(skilled.items()):
        expected = (float(row["point"]) - last_price) / last_price
        # Two independent questions, asked in order: which side of the flat
        # band, then (for material negatives) whether this horizon may demote.
        if abs(expected) <= FLAT_BAND:
            candidate.notes.append(
                f"skilled {label} signal ≈ flat ({expected:+.1%}) — no forecast "
                "support, but flat is not bearish; no veto"
            )
        elif expected > FLAT_BAND:
            candidate.notes.append(f"skilled {label} signal: {expected:+.1%} (supportive)")
        elif label in NEGATIVE_VETO_HORIZONS:
            candidate.vetoed = True
            candidate.veto_reasons.append(
                f"skilled {label} model ({row.get('model', '?')}) shows "
                f"{expected:+.1%} expected return — the validated signal is negative"
            )
        else:
            candidate.notes.append(
                f"skilled {label} signal: {expected:+.1%} (cautionary; {label} is too "
                "short a horizon to demote)"
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

    queue.sort(key=lambda c: c.vetoed)  # stable: preserves blended-rank order within groups
    return queue


def read_screen_csv(path: Path, *, top: int) -> list[tuple[str, float | None]]:
    """Top-N (ticker, blended) pairs from a `screen` CSV, in rank order.

    Raises ValueError when the file lacks the screen's columns — a renamed
    column must fail loudly, not silently degrade every score to None (which
    would reduce the walk-down to CSV row order while looking like a success).
    """
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if "ticker" not in fields or "blended" not in fields:
            raise ValueError(
                f"{path} does not look like a `screen` CSV (needs 'ticker' and "
                f"'blended' columns; found {fields})"
            )
        rows = list(reader)
    out: list[tuple[str, float | None]] = []
    for row in rows[:top]:
        try:
            blended = float(row["blended"])
        except (TypeError, ValueError):
            blended = None  # a single blank cell degrades one row, not the file
        out.append((row["ticker"].upper(), blended))
    return out


def build_rank_report(queue: list[RankedCandidate], *, as_of: str) -> str:
    from equity_analyst.digest import BAR_DESCRIPTION

    lines = [
        f"# Committee walk-down queue ({as_of})",
        "",
        "_Ordered by the blended screen score. The forecast never promotes a name; "
        "it can only demote via a **skill-gated veto**: a "
        f"{'/'.join(NEGATIVE_VETO_HORIZONS)} horizon that beat the naive baseline "
        "in backtest showing a materially negative expected return (beyond the "
        f"±{FLAT_BAND:.0%} flat band — skilled-flat annotates, it does not veto). "
        "Demoted names sink to the bottom with the reason shown — they are not "
        "hidden. Not financial advice._",
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
        f"clear the bar ({BAR_DESCRIPTION} — check with `equity-analyst qualify`).",
    ]
    if any(c.vetoed for c in queue):
        lines += [
            "",
            "Demoted names remain reachable if the clean names run out — the veto is "
            "a budget-ordering device, not a verdict.",
        ]
    return "\n".join(lines)
