"""Anthropic Claude implementation of :class:`LLMClient`.

Thin by design: it maps a role to a model/effort (see config), builds the
request (adaptive thinking, effort, optional web search, optional structured
output), calls the Messages API, and normalizes the response. The underlying
SDK client is injectable so the request-building logic is testable without a key.
"""

from __future__ import annotations

import json

from equity_analyst.llm.base import LLMError, LLMResponse
from equity_analyst.llm.config import DEFAULT_ROLE_MODELS, ModelConfig

# Web search tool with dynamic filtering (supported on Opus 4.8 / Sonnet 5).
_WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}

# Cap on pause_turn continuations before giving up on a turn.
_MAX_CONTINUATIONS = 5


class AnthropicClient:
    """:class:`~equity_analyst.llm.base.LLMClient` backed by the Anthropic SDK."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        role_models: dict[str, ModelConfig] | None = None,
        client: object | None = None,
    ) -> None:
        self._api_key = api_key
        self._role_models = dict(role_models or DEFAULT_ROLE_MODELS)
        self._client = client  # injected SDK client, or built lazily

    def _sdk(self) -> object:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - dependency always present
                raise LLMError("the 'anthropic' package is not installed") from exc
            # api_key=None lets the SDK resolve the key from the environment.
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def build_params(
        self,
        cfg: ModelConfig,
        system: str,
        prompt: str,
        schema: dict | None,
        *,
        allow_tools: bool = True,
    ) -> dict:
        """Construct the Messages API request for one role. Pure, so it's unit-tested."""
        params: dict = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": cfg.effort},
        }
        if schema is not None:
            params["output_config"]["format"] = {"type": "json_schema", "schema": schema}
        if cfg.web_search and allow_tools:
            params["tools"] = [_WEB_SEARCH_TOOL]
        return params

    def analyze(
        self,
        *,
        role: str,
        system: str,
        prompt: str,
        schema: dict | None = None,
        allow_tools: bool = True,
    ) -> LLMResponse:
        if role not in self._role_models:
            raise LLMError(f"no model configured for role {role!r}")
        cfg = self._role_models[role]
        params = self.build_params(cfg, system, prompt, schema, allow_tools=allow_tools)

        # Server-side web search can pause a long turn (stop_reason "pause_turn");
        # resume by echoing the assistant content back until the turn completes.
        # Text is accumulated across continuations so nothing is silently lost.
        text_parts: list[str] = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        message = None
        for _ in range(_MAX_CONTINUATIONS):
            try:
                message = self._sdk().messages.create(**params)
            except Exception as exc:  # noqa: BLE001 - normalize SDK/network errors
                raise LLMError(f"completion failed for role {role!r}: {exc}") from exc
            text_parts.append(_extract_text(message))
            step_usage = _extract_usage(message)
            usage = {k: usage[k] + step_usage.get(k, 0) for k in usage}
            if getattr(message, "stop_reason", None) != "pause_turn":
                break
            params = dict(params)
            params["messages"] = params["messages"] + [
                {"role": "assistant", "content": message.content}
            ]
        else:
            raise LLMError(f"turn did not complete after continuations for role {role!r}")

        if getattr(message, "stop_reason", None) == "refusal":
            raise LLMError(f"model refused the request for role {role!r}")

        text = "".join(text_parts).strip()
        parsed = None
        if schema is not None:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise LLMError(f"structured output was not valid JSON for role {role!r}") from exc

        return LLMResponse(
            role=role,
            model=getattr(message, "model", cfg.model),
            text=text,
            parsed=parsed,
            usage=usage,
        )


def _extract_text(message: object) -> str:
    """Concatenate the text blocks of an Anthropic message (unstripped — the
    caller joins segments across pause_turn continuations before stripping)."""
    parts = [
        block.text
        for block in getattr(message, "content", [])
        if getattr(block, "type", None) == "text"
    ]
    return "".join(parts)


def _extract_usage(message: object) -> dict[str, int]:
    usage = getattr(message, "usage", None)
    if usage is None:
        return {}
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
    }
