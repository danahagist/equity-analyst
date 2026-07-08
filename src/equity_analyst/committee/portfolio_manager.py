"""Portfolio Manager: synthesizes the committee into a final call (LLM, Opus).

Absorbs the original prompts 5 (risk mapping) and 7 (final summary). Reads the
deterministic consensus summary plus every analyst's full verdict, then authors
the synthesis — it may override the mechanical blend but must justify divergence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from equity_analyst.committee.consensus import ConsensusSummary
from equity_analyst.committee.verdict import RATING_LABELS, Verdict
from equity_analyst.llm.base import LLMClient
from equity_analyst.llm.config import ROLE_PORTFOLIO_MANAGER

PM_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "rating": {"type": "integer", "enum": [-2, -1, 0, 1, 2]},
        "conviction": {"type": "string", "enum": ["low", "medium", "high"]},
        "horizon": {"type": "string"},
        "synthesis": {"type": "string"},
        "key_risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["rating", "conviction", "horizon", "synthesis", "key_risks"],
    "additionalProperties": False,
}

_SYSTEM = """You are the portfolio manager chairing an investment committee. Five \
role-specialized analysts (Technical, Fundamental, News/Social, Research) have each \
independently rated a stock on a −2…+2 scale (−2 Strong Sell … +2 Strong Buy). You \
are given a mechanical agreement summary and each analyst's full writeup.

Your job is the big picture and the final call:
- Weigh where the committee agrees (that is conviction) against where it diverges \
(that is risk). Take dissents seriously — a lone well-argued dissent can outweigh a \
shallow majority.
- Map the primary risks to this position: macro, industry disruption, \
management/execution, and financial.
- Reach a final rated verdict. You MAY override the mechanical blend, but if you do, \
justify the divergence explicitly.

Keep the synthesis tight and decision-useful — lead with the call and why. This is \
research analysis, not financial advice."""


@dataclass(frozen=True, slots=True)
class PMSynthesis:
    rating: int
    conviction: str
    horizon: str
    synthesis: str
    key_risks: list[str] = field(default_factory=list)

    @property
    def rating_label(self) -> str:
        return RATING_LABELS[self.rating]


class PortfolioManager:
    role = ROLE_PORTFOLIO_MANAGER
    name = "Portfolio Manager"

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def synthesize(
        self, ticker: str, verdicts: list[Verdict], consensus: ConsensusSummary
    ) -> PMSynthesis:
        prompt = build_pm_prompt(ticker, verdicts, consensus)
        response = self.llm.analyze(
            role=self.role, system=_SYSTEM, prompt=prompt, schema=PM_SCHEMA
        )
        parsed = response.parsed or {}
        return PMSynthesis(
            rating=int(parsed["rating"]),
            conviction=str(parsed["conviction"]),
            horizon=str(parsed["horizon"]),
            synthesis=str(parsed["synthesis"]),
            key_risks=[str(r) for r in parsed.get("key_risks", [])],
        )


def build_pm_prompt(
    ticker: str, verdicts: list[Verdict], consensus: ConsensusSummary
) -> str:
    lines = [
        f"Ticker under review: {ticker}",
        "",
        "MECHANICAL AGREEMENT SUMMARY (deterministic, for context only):",
        f"  {consensus.headline}",
        f"  Vote split: {consensus.counts}",
        f"  Conviction-weighted blended score: {consensus.blended_score:+.2f} "
        f"(−2…+2 scale)",
        "",
        "ANALYST VERDICTS (each reached independently):",
    ]
    for v in verdicts:
        lines.append(
            f"\n[{v.analyst}] {v.rating_label} (rating {v.rating:+d}, "
            f"conviction {v.conviction}, horizon {v.horizon})"
        )
        lines.append(f"Evidence:\n{v.evidence}")
    lines.append(
        "\nSynthesize the committee into your final call and key risks for "
        f"{ticker}, following your mandate."
    )
    return "\n".join(lines)
