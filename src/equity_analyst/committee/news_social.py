"""News/Social analyst (LLM, Sonnet + web search).

Absorbs the original prompt 6: catalysts and events driving price/momentum.
Sentiment is drawn from news and public pages via web search — not a real-time
social firehose (those are paywalled), and the analyst says so.
"""

from __future__ import annotations

from equity_analyst.committee.base import AnalystContext, LLMAnalyst
from equity_analyst.llm.config import ROLE_NEWS_SOCIAL

_SYSTEM = """You are a senior analyst monitoring news flow, market sentiment, and \
upcoming catalysts for equities. Use web search to find recent, dated information:
- Events driving the stock's recent price and momentum (earnings, guidance, \
management changes, legal/regulatory news, macro developments).
- Public sentiment from news coverage and public discussion pages. Be explicit that \
this reflects news and public pages, NOT a real-time social-media firehose.
- Upcoming catalysts: next earnings date, product launches, industry events, macro \
events on the calendar.

Cite what you found (source and rough date) in your evidence. Distinguish confirmed \
facts from speculation. Then commit to a rated verdict on the −2…+2 scale (−2 Strong \
Sell … +2 Strong Buy) reflecting how the news/catalyst picture bears on the stock, \
with your conviction, the horizon it applies to, and the supporting evidence. This is \
research analysis, not financial advice."""


class NewsSocialAnalyst(LLMAnalyst):
    role = ROLE_NEWS_SOCIAL
    name = "News/Social"

    def build_prompt(self, context: AnalystContext) -> tuple[str, str]:
        price = (
            f" Its most recent price is ${context.last_price:,.2f}."
            if context.last_price is not None
            else ""
        )
        user = (
            f"Research the current news, sentiment, and upcoming catalysts for "
            f"{context.ticker}.{price} Search the web for recent developments, then "
            f"conclude with your explicit verdict: rating on the −2…+2 scale, "
            f"conviction (low/medium/high), and the horizon it applies to."
        )
        return _SYSTEM, user
