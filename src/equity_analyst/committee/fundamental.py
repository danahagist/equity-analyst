"""Fundamental analyst (LLM, Opus).

Absorbs the original prompts 1–4: business model, financial statements,
valuation, and industry/competitive analysis — grounded in the real fact-sheet.
"""

from __future__ import annotations

from equity_analyst.committee.base import AnalystContext, LLMAnalyst, format_fundamentals
from equity_analyst.llm.config import ROLE_FUNDAMENTAL

_SYSTEM = """You are a senior Wall Street equity research analyst specializing in \
fundamental analysis. Assess a company across four dimensions:
1. Business & industry: business model, revenue streams, competitive advantages \
(moat), growth drivers, and long-term industry outlook.
2. Financial health: revenue trends, profit margins, debt levels, cash flow, and \
profitability metrics — call out strengths, weaknesses, and red flags.
3. Valuation: is the stock undervalued, fairly valued, or overvalued? Reason from \
earnings growth, industry comparables, and valuation ratios.
4. Competitive landscape: key competitors, market trends, and threats to long-term \
performance.

Ground every claim in the data provided. Do NOT invent figures; if a needed data \
point is missing, reason qualitatively and say so. Then commit to a rated verdict on \
the −2…+2 scale (−2 Strong Sell, −1 Sell, 0 Hold, +1 Buy, +2 Strong Buy) with your \
conviction, the horizon your rating applies to, and the evidence behind it. This is \
research analysis, not financial advice."""


class FundamentalAnalyst(LLMAnalyst):
    role = ROLE_FUNDAMENTAL
    name = "Fundamental"

    def build_prompt(self, context: AnalystContext) -> tuple[str, str]:
        user = (
            f"Perform a fundamental analysis of {context.ticker}. Conclude with your "
            f"explicit verdict: rating on the −2…+2 scale, conviction (low/medium/high), "
            f"and the horizon it applies to.\n\n{format_fundamentals(context)}"
        )
        return _SYSTEM, user
