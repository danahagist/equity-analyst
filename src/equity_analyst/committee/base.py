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


class LLMAnalyst:
    """Base for analysts whose verdict comes from an LLM completion."""

    role: str  # maps to a model via llm config
    name: str

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def build_prompt(self, context: AnalystContext) -> tuple[str, str]:
        """Return ``(system, user)`` for this analyst. Subclasses implement."""
        raise NotImplementedError

    def evaluate(self, context: AnalystContext) -> Verdict:
        system, prompt = self.build_prompt(context)
        response = self.llm.analyze(
            role=self.role, system=system, prompt=prompt, schema=VERDICT_SCHEMA
        )
        return verdict_from_parsed(self.name, response.parsed)


def format_fundamentals(context: AnalystContext) -> str:
    """Render the grounded fundamentals fact-sheet for a prompt."""
    lines = [f"Ticker: {context.ticker}"]
    if context.last_price is not None:
        lines.append(f"Most recent price: ${context.last_price:,.2f}")
    if context.fundamentals:
        lines.append("Fundamentals (from market data provider):")
        lines.extend(f"  - {key}: {value}" for key, value in context.fundamentals.items())
    else:
        lines.append("Fundamentals: (none available)")
    return "\n".join(lines)


def format_analyst_info(context: AnalystContext) -> str:
    """Render third-party analyst/consensus data for a prompt."""
    if not context.analyst_info:
        return "Third-party analyst data: (none available)"
    lines = ["Third-party analyst data (from market data provider):"]
    lines.extend(f"  - {key}: {value}" for key, value in context.analyst_info.items())
    return "\n".join(lines)
