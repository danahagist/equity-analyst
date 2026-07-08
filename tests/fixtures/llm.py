"""Offline LLM fixtures: a fake SDK client and a fake LLMClient."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from equity_analyst.llm.base import LLMResponse


# --- Fakes that mimic the Anthropic SDK response shape -----------------------


@dataclass
class _Block:
    type: str
    text: str = ""


@dataclass
class _Usage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class _Message:
    content: list
    model: str
    usage: _Usage
    stop_reason: str = "end_turn"


class FakeMessages:
    """Stands in for ``client.messages``; records the last call and replies canned."""

    def __init__(self, reply_text: str = "analysis", stop_reason: str = "end_turn") -> None:
        self.reply_text = reply_text
        self.stop_reason = stop_reason
        self.last_params: dict | None = None

    def create(self, **params):
        self.last_params = params
        return _Message(
            content=[_Block("text", self.reply_text)],
            model=params["model"],
            usage=_Usage(),
            stop_reason=self.stop_reason,
        )


class FakeSDK:
    """Stands in for ``anthropic.Anthropic()``."""

    def __init__(self, reply_text: str = "analysis", stop_reason: str = "end_turn") -> None:
        self.messages = FakeMessages(reply_text=reply_text, stop_reason=stop_reason)


# --- Fake LLMClient for exercising analysts without the SDK ------------------


@dataclass
class FakeLLMClient:
    """A scripted :class:`~equity_analyst.llm.base.LLMClient` for analyst tests.

    ``verdicts`` maps a role to the dict the analyst should receive as parsed
    structured output; ``narrative`` is the text returned for every call.
    """

    verdicts: dict[str, dict] = field(default_factory=dict)
    narrative: str = "Fake analysis."
    calls: list[dict] = field(default_factory=list)

    def analyze(self, *, role, system, prompt, schema=None) -> LLMResponse:
        self.calls.append({"role": role, "system": system, "prompt": prompt, "schema": schema})
        parsed = self.verdicts.get(role) if schema is not None else None
        text = json.dumps(parsed) if parsed is not None else self.narrative
        return LLMResponse(
            role=role,
            model="fake-model",
            text=text,
            parsed=parsed,
            usage={"input_tokens": 1, "output_tokens": 1},
        )
