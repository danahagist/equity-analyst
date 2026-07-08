"""Research analyst (LLM, Sonnet + web search).

Aggregates existing sell-side ratings, price targets, and third-party research —
grounded in the consensus data from the market-data provider and enriched with
recent analyst actions found via web search.
"""

from __future__ import annotations

from equity_analyst.committee.base import AnalystContext, LLMAnalyst, format_analyst_info
from equity_analyst.llm.config import ROLE_RESEARCH

_SYSTEM = """You are an equity analyst who aggregates third-party research: sell-side \
analyst ratings, price targets, and independent research. Given the consensus data \
provided, and using web search for recent analyst actions (upgrades/downgrades, \
target changes, notable research notes with their dates), assess:
- Where the analyst consensus sits and how dispersed it is (agreement vs division).
- How current price compares to the mean/median price target (implied upside/downside).
- Recent rating momentum and any contrarian or standout third-party views.

Cite sources and dates in your evidence, and note when data is stale or thin. Weigh \
the third-party picture — do not simply echo the consensus if the evidence warrants \
skepticism. Then commit to a rated verdict on the −2…+2 scale (−2 Strong Sell … +2 \
Strong Buy) with your conviction, the horizon it applies to, and the supporting \
evidence. This is research analysis, not financial advice."""


class ResearchAnalyst(LLMAnalyst):
    role = ROLE_RESEARCH
    name = "Research"

    def build_prompt(self, context: AnalystContext) -> tuple[str, str]:
        price = (
            f"Most recent price: ${context.last_price:,.2f}\n"
            if context.last_price is not None
            else ""
        )
        user = (
            f"Assess the third-party research and analyst consensus for "
            f"{context.ticker}. Search the web for recent analyst actions, then deliver "
            f"your structured verdict.\n\n{price}{format_analyst_info(context)}"
        )
        return _SYSTEM, user
