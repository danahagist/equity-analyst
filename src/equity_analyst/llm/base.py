"""LLM client interface and result type.

The rest of the codebase depends only on :class:`LLMClient`, so swapping the
Anthropic backend for another provider is a single-file change (mirrors the
data-access design).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class LLMError(RuntimeError):
    """Raised when a completion cannot be produced (auth, network, refusal)."""


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """The result of one analyst completion."""

    role: str
    model: str
    text: str  # the assistant's final text (analysis / narrative)
    parsed: dict | None = None  # validated JSON when a schema was requested
    usage: dict[str, int] = field(default_factory=dict)  # input/output token counts


class LLMClient(Protocol):
    """Produces an analyst completion for a given role."""

    def analyze(
        self,
        *,
        role: str,
        system: str,
        prompt: str,
        schema: dict | None = None,
        allow_tools: bool = True,
    ) -> LLMResponse:
        """Run a completion for ``role``.

        ``schema`` (a JSON Schema) forces structured output and populates
        :attr:`LLMResponse.parsed`. Web search is enabled per the role's config
        unless ``allow_tools`` is False (used for extraction passes that must
        not trigger new searches).
        """
        ...
