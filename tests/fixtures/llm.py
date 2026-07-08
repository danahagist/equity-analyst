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
    """Stands in for ``client.messages``; records calls and replies from a script.

    ``script`` is a list of ``(text, stop_reason)`` replies consumed in order;
    the last entry repeats once exhausted (so single-reply setups stay simple).
    """

    def __init__(self, script: list[tuple[str, str]]) -> None:
        self.script = list(script)
        self.last_params: dict | None = None
        self.all_params: list[dict] = []

    def create(self, **params):
        self.last_params = params
        self.all_params.append(params)
        text, stop_reason = self.script[0]
        if len(self.script) > 1:
            self.script.pop(0)
        return _Message(
            content=[_Block("text", text)],
            model=params["model"],
            usage=_Usage(),
            stop_reason=stop_reason,
        )


class FakeSDK:
    """Stands in for ``anthropic.Anthropic()``."""

    def __init__(
        self,
        reply_text: str = "analysis",
        stop_reason: str = "end_turn",
        script: list[tuple[str, str]] | None = None,
    ) -> None:
        self.messages = FakeMessages(script or [(reply_text, stop_reason)])


# --- Fake LLMClient for exercising analysts without the SDK ------------------


@dataclass
class FakeLLMClient:
    """A scripted :class:`~equity_analyst.llm.base.LLMClient` for analyst tests.

    ``verdicts`` maps a role to the dict returned as parsed structured output on
    schema calls; ``narrative`` is the free-form text returned on non-schema
    (research) calls — matching the two-phase analyst pattern.
    """

    verdicts: dict[str, dict] = field(default_factory=dict)
    narrative: str = "Fake analysis."
    calls: list[dict] = field(default_factory=list)

    def analyze(self, *, role, system, prompt, schema=None, allow_tools=True) -> LLMResponse:
        self.calls.append(
            {
                "role": role,
                "system": system,
                "prompt": prompt,
                "schema": schema,
                "allow_tools": allow_tools,
            }
        )
        parsed = self.verdicts.get(role) if schema is not None else None
        text = json.dumps(parsed) if parsed is not None else self.narrative
        return LLMResponse(
            role=role,
            model="fake-model",
            text=text,
            parsed=parsed,
            usage={"input_tokens": 1, "output_tokens": 1},
        )
