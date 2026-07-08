"""Per-role model assignments (see CLAUDE.md).

Match model tier to cognitive load: judgment-heavy seats (PM, Fundamental) get
Opus; search-heavy seats (News/Social, Research) get Sonnet. Config-driven so
changing a model or effort is a one-line edit, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass

# Analyst roles that drive an LLM.
ROLE_PORTFOLIO_MANAGER = "portfolio_manager"
ROLE_FUNDAMENTAL = "fundamental"
ROLE_NEWS_SOCIAL = "news_social"
ROLE_RESEARCH = "research"


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Model choice and generation settings for one role."""

    model: str
    effort: str = "high"  # low | medium | high | xhigh | max
    web_search: bool = False
    max_tokens: int = 8000


DEFAULT_ROLE_MODELS: dict[str, ModelConfig] = {
    ROLE_PORTFOLIO_MANAGER: ModelConfig("claude-opus-4-8", effort="high"),
    ROLE_FUNDAMENTAL: ModelConfig("claude-opus-4-8", effort="high"),
    ROLE_NEWS_SOCIAL: ModelConfig("claude-sonnet-5", effort="medium", web_search=True),
    ROLE_RESEARCH: ModelConfig("claude-sonnet-5", effort="medium", web_search=True),
}
