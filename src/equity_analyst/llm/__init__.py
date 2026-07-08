"""LLM access, isolated behind :class:`LLMClient` (Anthropic Claude backend)."""

from equity_analyst.llm.anthropic_client import AnthropicClient
from equity_analyst.llm.base import LLMClient, LLMError, LLMResponse
from equity_analyst.llm.config import (
    DEFAULT_ROLE_MODELS,
    ROLE_FUNDAMENTAL,
    ROLE_NEWS_SOCIAL,
    ROLE_PORTFOLIO_MANAGER,
    ROLE_RESEARCH,
    ModelConfig,
)

__all__ = [
    "AnthropicClient",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "ModelConfig",
    "DEFAULT_ROLE_MODELS",
    "ROLE_PORTFOLIO_MANAGER",
    "ROLE_FUNDAMENTAL",
    "ROLE_NEWS_SOCIAL",
    "ROLE_RESEARCH",
]
