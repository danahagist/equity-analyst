"""Render the committee run as a markdown report.

Leads with the agreement picture and the PM's call (not a single false-precision
number), then each analyst's rating and evidence. See CLAUDE.md.
"""

from __future__ import annotations

from equity_analyst.committee.consensus import ConsensusSummary
from equity_analyst.committee.portfolio_manager import PMSynthesis
from equity_analyst.committee.verdict import Verdict

def _signed(rating: int) -> str:
    """Signed rating, but plain '0' for Hold (avoids an odd '+0')."""
    return f"{rating:+d}" if rating else "0"


_DISCLAIMER = (
    "_Research assistance, not financial advice. Forecasts are probabilistic and "
    "benchmarked against a naive baseline; where a model cannot beat naive drift, "
    "the baseline is reported. Sentiment reflects news and public pages, not a "
    "real-time social feed._"
)


def build_report(
    *,
    ticker: str,
    as_of: str,
    verdicts: list[Verdict],
    consensus: ConsensusSummary,
    pm: PMSynthesis,
    last_price: float | None = None,
    failures: list[tuple[str, str]] | None = None,
) -> str:
    price = f" · last ${last_price:,.2f}" if last_price is not None else ""
    out: list[str] = [
        f"# {ticker} — Investment Committee ({as_of})",
        f"{price.lstrip(' ·') or as_of}",
        "",
        _DISCLAIMER,
        "",
        "## Consensus",
        "",
        f"**{consensus.headline}**",
        "",
        f"- Vote split: {consensus.counts['Buy']} Buy · "
        f"{consensus.counts['Hold']} Hold · {consensus.counts['Sell']} Sell",
        f"- Conviction-weighted blended score: **{consensus.blended_score:+.2f}** "
        f"(−2…+2; secondary to the agreement picture)",
        f"- Agreement: {consensus.agreement_level}",
    ]
    if consensus.dissenters:
        out.append(f"- Dissenting: {', '.join(consensus.dissenters)}")
    if failures:
        out.append(
            f"- ⚠️ Excluded (errored): {', '.join(name for name, _ in failures)}"
        )

    out += [
        "",
        f"## Portfolio Manager — Final Call: {pm.rating_label} "
        f"(rating {_signed(pm.rating)}, {pm.conviction} conviction, {pm.horizon})",
        "",
        pm.synthesis.strip(),
    ]
    if pm.key_risks:
        out += ["", "**Key risks**"]
        out += [f"- {risk}" for risk in pm.key_risks]

    out += ["", "## Analyst verdicts", ""]
    for v in verdicts:
        out += [
            f"### {v.analyst} — {v.rating_label} "
            f"(rating {_signed(v.rating)}, {v.conviction} conviction, horizon {v.horizon})",
            "",
            v.evidence.strip(),
            "",
        ]

    if failures:
        out += ["## Analysts that could not be reached", ""]
        out += [f"- **{name}**: {err}" for name, err in failures]
        out += [""]

    return "\n".join(out).rstrip() + "\n"
