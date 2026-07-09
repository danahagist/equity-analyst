"""Analyst interface, shared context, and the LLM-analyst base class.

Each analyst reasons **independently** from its own slice of the context — that
independence is what makes agreement across the committee meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from equity_analyst.committee.verdict import VERDICT_SCHEMA, Verdict, verdict_from_parsed
from equity_analyst.forecast.types import ForecastResult
from equity_analyst.llm.base import LLMClient


@dataclass
class AnalystContext:
    """Everything the committee may draw on for one ticker (each analyst uses a subset)."""

    ticker: str
    last_price: float | None = None
    fundamentals: dict = field(default_factory=dict)
    analyst_info: dict = field(default_factory=dict)
    forecast: ForecastResult | None = None


class Analyst(Protocol):
    name: str

    def evaluate(self, context: AnalystContext) -> Verdict:
        """Reach a rated recommendation for the ticker in ``context``."""
        ...


_EXTRACT_SYSTEM = """You extract the structured verdict that an equity analyst's \
written analysis supports. Report only what the analysis itself concludes — do not \
add claims, soften dissents, or second-guess the analyst. If the analysis states an \
explicit rating, use it; otherwise infer the closest rating the text supports."""


class LLMAnalyst:
    """Base for analysts whose verdict comes from an LLM completion.

    Evaluation is two-phase: (1) an unconstrained research/analysis completion
    (with web search where the role has it) — forcing long-form analysis through
    a JSON schema degrades reasoning quality and is fragile combined with search
    tools; (2) a cheap, tool-free extraction pass that formalizes the verdict
    the writeup supports. The full writeup rides along on the Verdict.
    """

    role: str  # maps to a model via llm config
    name: str

    def __init__(self, llm: LLMClient | None) -> None:
        # llm may be None when only build_prompt is needed (Claude-Code-native
        # sessions extract the briefings without making API calls).
        self.llm = llm

    def build_prompt(self, context: AnalystContext) -> tuple[str, str]:
        """Return ``(system, user)`` for this analyst. Subclasses implement."""
        raise NotImplementedError

    def evaluate(self, context: AnalystContext) -> Verdict:
        system, prompt = self.build_prompt(context)
        research = self.llm.analyze(role=self.role, system=system, prompt=prompt)
        if not research.text.strip():
            raise ValueError(f"{self.name}: analysis pass returned no text")

        extract_prompt = (
            f"Below is the {self.name} analyst's full written analysis of "
            f"{context.ticker}. Extract the verdict it supports.\n\n"
            f"<analysis>\n{research.text}\n</analysis>"
        )
        response = self.llm.analyze(
            role=self.role,
            system=_EXTRACT_SYSTEM,
            prompt=extract_prompt,
            schema=VERDICT_SCHEMA,
            allow_tools=False,
        )
        return verdict_from_parsed(self.name, response.parsed, writeup=research.text)


def format_fundamentals(context: AnalystContext) -> str:
    """Render the grounded fundamentals fact-sheet for a prompt."""
    lines = [f"Ticker: {context.ticker}"]
    if context.last_price is not None:
        lines.append(f"Most recent price: ${context.last_price:,.2f}")
    if context.fundamentals:
        lines.append("Fundamentals (from market data provider):")
        lines.extend(f"  - {key}: {value}" for key, value in context.fundamentals.items())
        caveats = fundamentals_caveats(context.fundamentals)
        if caveats:
            lines.append("Data caveats (auto-flagged — read the figures critically):")
            lines.extend(f"  ! {c}" for c in caveats)
    else:
        lines.append("Fundamentals: (none available)")
    return "\n".join(lines)


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fundamentals_caveats(fundamentals: dict) -> list[str]:
    """Deterministic sanity flags for provider fact-sheets.

    Yahoo's summary fields mix trailing GAAP, one-off items, and stale
    classifications without warning. These checks don't judge the stock —
    they warn the analyst which figures need critical reading.
    """
    caveats: list[str] = []
    net = _as_float(fundamentals.get("profitMargins"))
    op = _as_float(fundamentals.get("operatingMargins"))
    roe = _as_float(fundamentals.get("returnOnEquity"))
    growth = _as_float(fundamentals.get("revenueGrowth"))

    if net is not None and op is not None:
        if op < 0 < net:
            caveats.append(
                "net margin is positive while operating margin is negative — almost "
                "certainly a large one-off non-operating gain; discard trailing P/E "
                "and ROE as valuation anchors and reason from operating economics."
            )
        elif net > op + 0.05:
            caveats.append(
                "net margin exceeds operating margin — non-operating income (interest, "
                "one-offs) is flattering the bottom line; treat P/E and ROE with caution."
            )

    if roe is not None and roe > 1.0:
        caveats.append(
            "ROE above 100% signals a shrunken book-equity base (typically buybacks "
            "or accumulated losses) — ROE, price/book, and debt/equity are not "
            "meaningful signals here."
        )

    if growth is not None and growth > 3.0:
        caveats.append(
            f"revenue growth of {growth:.0%} is hypergrowth off a small or restated "
            "base — verify durability rather than extrapolating."
        )

    if "sector" in fundamentals and "longName" not in fundamentals:
        caveats.append(
            "provider did not return the company name — other classification fields "
            "(sector/industry) may be stale or wrong for this listing."
        )

    if "trailingPE" not in fundamentals and net is not None and net < 0:
        caveats.append(
            "no trailing P/E because trailing earnings are negative — expected for a "
            "GAAP-unprofitable company, not a data error."
        )

    return caveats


def format_analyst_info(context: AnalystContext) -> str:
    """Render third-party analyst/consensus data for a prompt."""
    if not context.analyst_info:
        return "Third-party analyst data: (none available)"
    info = context.analyst_info
    lines = ["Third-party analyst data (from market data provider):"]
    lines.extend(f"  - {key}: {value}" for key, value in info.items())
    missing_rating = info.get("recommendationKey") in (None, "none", "") and not info.get(
        "recommendationMean"
    )
    if missing_rating:
        lines.append(
            "Data caveat (auto-flagged): the provider returned no consensus rating "
            "fields — rely on web-sourced rating tallies and say so in the writeup."
        )
    return "\n".join(lines)
