"""LLM client tests (offline; a fake SDK client is injected)."""

from __future__ import annotations

import pytest

from equity_analyst.llm import (
    ROLE_FUNDAMENTAL,
    ROLE_NEWS_SOCIAL,
    ROLE_PORTFOLIO_MANAGER,
    AnthropicClient,
    LLMError,
)
from tests.fixtures.llm import FakeSDK


def test_routes_model_and_effort_per_role() -> None:
    sdk = FakeSDK()
    client = AnthropicClient(client=sdk)
    client.analyze(role=ROLE_PORTFOLIO_MANAGER, system="s", prompt="p")
    assert sdk.messages.last_params["model"] == "claude-opus-4-8"
    assert sdk.messages.last_params["output_config"]["effort"] == "high"
    assert sdk.messages.last_params["thinking"] == {"type": "adaptive"}


def test_search_seat_enables_web_search_and_sonnet() -> None:
    sdk = FakeSDK()
    client = AnthropicClient(client=sdk)
    client.analyze(role=ROLE_NEWS_SOCIAL, system="s", prompt="p")
    params = sdk.messages.last_params
    assert params["model"] == "claude-sonnet-5"
    assert params["tools"] == [{"type": "web_search_20260209", "name": "web_search"}]


def test_allow_tools_false_disables_web_search() -> None:
    # Extraction passes must not trigger new searches, even on search seats.
    sdk = FakeSDK()
    client = AnthropicClient(client=sdk)
    client.analyze(role=ROLE_NEWS_SOCIAL, system="s", prompt="p", allow_tools=False)
    assert "tools" not in sdk.messages.last_params


def test_pause_turn_resumes_and_accumulates_text() -> None:
    # Server-side web search can pause a turn; the client must resume and keep
    # the text from every segment.
    sdk = FakeSDK(script=[("first part. ", "pause_turn"), ("second part.", "end_turn")])
    client = AnthropicClient(client=sdk)
    resp = client.analyze(role=ROLE_NEWS_SOCIAL, system="s", prompt="p")
    assert resp.text == "first part. second part."
    # The continuation request echoed the assistant content back.
    assert len(sdk.messages.all_params) == 2
    assert [m["role"] for m in sdk.messages.all_params[1]["messages"]] == ["user", "assistant"]
    assert resp.usage == {"input_tokens": 20, "output_tokens": 40}  # summed across segments


def test_judgment_seat_has_no_web_search() -> None:
    sdk = FakeSDK()
    client = AnthropicClient(client=sdk)
    client.analyze(role=ROLE_FUNDAMENTAL, system="s", prompt="p")
    assert "tools" not in sdk.messages.last_params


def test_schema_requests_structured_output_and_parses() -> None:
    sdk = FakeSDK(reply_text='{"rating": 1, "conviction": "high"}')
    client = AnthropicClient(client=sdk)
    schema = {"type": "object", "properties": {"rating": {"type": "integer"}}}
    resp = client.analyze(role=ROLE_FUNDAMENTAL, system="s", prompt="p", schema=schema)
    fmt = sdk.messages.last_params["output_config"]["format"]
    assert fmt == {"type": "json_schema", "schema": schema}
    assert resp.parsed == {"rating": 1, "conviction": "high"}


def test_no_schema_leaves_parsed_none_and_returns_text() -> None:
    sdk = FakeSDK(reply_text="free-form analysis")
    client = AnthropicClient(client=sdk)
    resp = client.analyze(role=ROLE_FUNDAMENTAL, system="s", prompt="p")
    assert resp.parsed is None
    assert resp.text == "free-form analysis"
    assert resp.usage == {"input_tokens": 10, "output_tokens": 20}


def test_refusal_raises() -> None:
    sdk = FakeSDK(stop_reason="refusal")
    client = AnthropicClient(client=sdk)
    with pytest.raises(LLMError, match="refused"):
        client.analyze(role=ROLE_FUNDAMENTAL, system="s", prompt="p")


def test_unknown_role_raises() -> None:
    client = AnthropicClient(client=FakeSDK())
    with pytest.raises(LLMError, match="no model configured"):
        client.analyze(role="nope", system="s", prompt="p")


def test_bad_json_under_schema_raises() -> None:
    sdk = FakeSDK(reply_text="not json")
    client = AnthropicClient(client=sdk)
    with pytest.raises(LLMError, match="not valid JSON"):
        client.analyze(role=ROLE_FUNDAMENTAL, system="s", prompt="p", schema={"type": "object"})
