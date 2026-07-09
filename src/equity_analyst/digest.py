"""The combined decision digest: everything needed to act, in one document.

The per-ticker reports in ``outputs/`` are the deep dive; ``compare`` is the
index. The digest is the middle layer Dana actually decides from: for each
shortlisted name — every analyst's bottom line, the consensus picture with
dissents, the PM's full synthesis and risks, the entry/exit levels row — plus
an ETF-exposure section and an executive summary that ties the set together.

The executive summary is authored by the committee's LLM (Claude Code in
keyless mode) and passed in via ``--exec-summary-file``; the digest never
fabricates one. Without it, a clearly-marked placeholder says what is missing.

Also home to the **qualification bar** used by the walk-down: a name counts
toward the weekly five only when the PM rates Buy or better at medium+
conviction AND the committee is not split. A plain "PM said Buy" bar does not
discriminate (committees say Buy a lot); this one bites.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from equity_analyst.committee.consensus import ConsensusSummary, compute_consensus
from equity_analyst.committee.portfolio_manager import PMSynthesis
from equity_analyst.committee.verdict import Verdict
from equity_analyst.levels import LevelPlan, plan_from_packet

_QUALIFYING_CONVICTIONS = ("medium", "high")


@dataclass(frozen=True)
class Qualification:
    ticker: str
    qualifies: bool
    reasons: list[str]  # empty when qualifying; each failed criterion otherwise


def check_bar(ticker: str, pm: PMSynthesis | None, consensus: ConsensusSummary) -> Qualification:
    """The walk-down bar: PM Buy+ at medium+ conviction, committee not split."""
    reasons: list[str] = []
    if pm is None:
        reasons.append("no PM synthesis recorded")
    else:
        if pm.rating < 1:
            reasons.append(f"PM call is {pm.rating_label}, not Buy or better")
        if pm.conviction not in _QUALIFYING_CONVICTIONS:
            reasons.append(f"PM conviction is {pm.conviction}, below medium")
    if consensus.agreement_level == "split":
        reasons.append(f"committee is split ({consensus.headline})")
    return Qualification(ticker=ticker.upper(), qualifies=not reasons, reasons=reasons)


def build_qualify_report(quals: list[Qualification], *, need: int) -> str:
    qualified = [q for q in quals if q.qualifies]
    lines = [
        "# Walk-down qualification check",
        "",
        f"Bar: PM Buy or better, medium+ conviction, committee not split. "
        f"Qualified so far: **{len(qualified)} of {need} needed**.",
        "",
    ]
    for q in quals:
        mark = "✓" if q.qualifies else "✗"
        detail = "" if q.qualifies else f" — {'; '.join(q.reasons)}"
        lines.append(f"- {mark} **{q.ticker}**{detail}")
    remaining = need - len(qualified)
    lines += [
        "",
        (
            f"Continue the walk-down: {remaining} more qualifying name(s) needed."
            if remaining > 0
            else "Bar met — stop the walk-down and build the digest."
        ),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- digest


_BOTTOM_LINE = re.compile(r"####\s*Bottom Line\s*\n(.*?)(?=\n####|\Z)", re.DOTALL)


def extract_bottom_line(writeup: str) -> str | None:
    """The '#### Bottom Line' section of a seat's writeup, if present."""
    match = _BOTTOM_LINE.search(writeup or "")
    return match.group(1).strip() if match else None


def _fmt_cap(value) -> str:
    try:
        cap = float(value)
    except (TypeError, ValueError):
        return "—"
    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if cap >= threshold:
            return f"${cap / threshold:,.1f}{suffix}"
    return f"${cap:,.0f}"


def _ticker_section(
    packet: dict,
    verdicts: list[Verdict],
    pm: PMSynthesis | None,
    consensus: ConsensusSummary,
    plan: LevelPlan | None,
) -> list[str]:
    ticker = packet["ticker"]
    fundamentals = packet.get("fundamentals") or {}
    qual = check_bar(ticker, pm, consensus)

    call = f"{pm.rating_label} ({pm.conviction} conviction, {pm.horizon})" if pm else "no PM call"
    lines = [
        f"## {ticker} — {call}",
        "",
        f"_{fundamentals.get('longName', ticker)} · {fundamentals.get('sector', '—')} · "
        f"{_fmt_cap(fundamentals.get('marketCap'))} · "
        f"${float(packet['last_price']):,.2f} (as of {packet['as_of']})_",
        "",
        f"**Committee:** {consensus.headline} "
        f"Blended {consensus.blended_score:+.2f} ({consensus.agreement_level}). "
        + (
            "**Qualifies** for the weekly five."
            if qual.qualifies
            else f"**Does not qualify** — {'; '.join(qual.reasons)}."
        ),
        "",
    ]

    if pm is not None:
        lines += ["### Portfolio Manager synthesis", "", pm.synthesis, ""]
        if pm.key_risks:
            lines += ["**Key risks:**", ""]
            lines += [f"- {risk}" for risk in pm.key_risks]
            lines.append("")
        if pm.horizon_fit:
            lines += ["**Holding-period fit:**", ""]
            lines += [f"- {line}" for line in pm.horizon_fit]
            lines.append("")

    lines += [
        "### Seat verdicts",
        "",
        "| Seat | Rating | Conviction | Horizon |",
        "|------|--------|------------|---------|",
    ]
    lines += [
        f"| {v.analyst} | {v.rating_label} ({v.rating:+d}) | {v.conviction} | {v.horizon} |"
        for v in verdicts
    ]
    lines.append("")
    for v in verdicts:
        summary = extract_bottom_line(v.writeup) or v.evidence
        lines += [f"**{v.analyst} — bottom line:** {summary}", ""]

    if plan is not None:
        rr = plan.reward_risk
        lines += [
            "### Levels (decision support, not orders)",
            "",
            f"Buy ≤ ${plan.buy_below:,.2f} · fair ${plan.fair_value:,.2f} · "
            f"trim ≈ ${plan.trim_near:,.2f} · target ${plan.target:,.2f} · "
            f"stop ${plan.stop:,.2f} · R:R {f'{rr:.1f}' if rr is not None else '—'}",
            "",
            f"_{plan.notes}_",
            "",
        ]
    return lines


EXEC_SUMMARY_PLACEHOLDER = (
    "> **Executive summary not yet written.** The summary is authored by the "
    "committee's LLM after reading this digest — write it to a file and re-run "
    "with `--exec-summary-file PATH`. It should tie the set together: the "
    "strongest cases and why, the shared macro exposures, where the committee "
    "disagreed, and what would change the calls."
)


def build_digest(
    entries: list[dict],
    *,
    as_of: str,
    exec_summary: str | None = None,
    etf_section: str | None = None,
) -> str:
    """Render the combined digest.

    Each entry: ``{"packet": .., "verdicts": [Verdict], "pm": PMSynthesis|None}``
    (consensus and levels are derived here so every section uses one source).
    """
    lines = [
        f"# Weekly committee digest — {as_of}",
        "",
        "_Research assistance, not financial advice. Ratings: −2 Strong Sell … +2 "
        "Strong Buy. Full per-ticker reports live in `outputs/`; this digest is the "
        "decision layer — every analyst's bottom line, the consensus and dissents, "
        "the PM synthesis, and the levels, in one place._",
        "",
        "## Executive summary",
        "",
        exec_summary.strip() if exec_summary else EXEC_SUMMARY_PLACEHOLDER,
        "",
        "## The shortlist at a glance",
        "",
        "| Ticker | PM call | Conviction | Committee | Blended | Qualifies |",
        "|--------|---------|------------|-----------|---------|-----------|",
    ]

    prepared = []
    for entry in entries:
        packet, verdicts, pm = entry["packet"], entry["verdicts"], entry["pm"]
        consensus = compute_consensus(verdicts)
        try:
            plan = plan_from_packet(packet)
        except ValueError:
            plan = None
        prepared.append((packet, verdicts, pm, consensus, plan))
        qual = check_bar(packet["ticker"], pm, consensus)
        lines.append(
            f"| {packet['ticker']} | {pm.rating_label if pm else '—'} "
            f"| {pm.conviction if pm else '—'} | {consensus.leaning} "
            f"| {consensus.blended_score:+.2f} | {'✓' if qual.qualifies else '✗'} |"
        )
    lines.append("")

    for packet, verdicts, pm, consensus, plan in prepared:
        lines += _ticker_section(packet, verdicts, pm, consensus, plan)

    if etf_section:
        lines += ["## Broader exposure via ETFs", "", etf_section.strip(), ""]

    lines += [
        "## Methodology",
        "",
        "- Shortlist selection: blended screen score orders the walk-down; the "
        "forecast can only demote via a skill-gated veto, never promote. Names "
        "qualify on: PM Buy or better, medium+ conviction, committee not split.",
        "- Levels derive from the forecast's calibrated 80% intervals; where a "
        "horizon didn't beat naive drift the band is a volatility range, not a "
        "directional call.",
        "- Each analyst seat reached its verdict independently; disagreement is "
        "reported, not smoothed over.",
        "",
        "_This tool provides research assistance, not financial advice._",
    ]
    return "\n".join(lines)
