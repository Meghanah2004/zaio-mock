"""Tests the REAL provider path (src/providers/anthropic_provider.py) can be
exercised safely in CI: the ``anthropic`` SDK client is replaced with a
fake, so no network call is ever made and no real API key is required, but
the request shape and response parsing are the same code that runs against
the live API - this is what src/cli.py's `generate` command uses when
LLM_PROVIDER=anthropic (see docs/DESIGN.md, "Real generation").
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from anthropic.types import TextBlock

from src.config import LLMSettings
from src.providers.anthropic_provider import AnthropicProvider
from src.providers.base import LLMProviderError


def _settings(**overrides) -> LLMSettings:
    return LLMSettings(
        provider="anthropic",
        model=overrides.get("model", "claude-sonnet-5"),
        api_key=overrides.get("api_key", "sk-ant-fake-test-key-not-real"),
        max_tokens=overrides.get("max_tokens", 4096),
        temperature=overrides.get("temperature", 0.4),
    )


def test_missing_api_key_raises_without_touching_the_sdk():
    with pytest.raises(LLMProviderError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider(_settings(api_key=None))


def test_client_is_constructed_with_internal_sdk_retries_disabled(monkeypatch):
    """Regression test for a real production incident (see
    tests/test_groq_provider.py's identical test for the full story): the
    SDK's own default internal retry (max_retries=2) would otherwise
    compound with src.generation.llm_utils.call_provider_with_retry's own
    bounded retry loop, turning one confirmed-non-retryable failure into
    several minutes of doomed nested retrying. Retry policy must live in
    exactly one place."""
    fake_client = MagicMock()
    captured_kwargs: dict = {}

    def fake_anthropic_client(**kwargs):
        captured_kwargs.update(kwargs)
        return fake_client

    monkeypatch.setattr("anthropic.Anthropic", fake_anthropic_client)

    AnthropicProvider(_settings(api_key="fake-key-123"))

    assert captured_kwargs["api_key"] == "fake-key-123"
    assert captured_kwargs["max_retries"] == 0


def test_generate_sends_system_and_user_prompt_and_the_configured_model(monkeypatch):
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.content = [TextBlock(type="text", text='{"ok": true}')]
    fake_client.messages.create.return_value = fake_response

    monkeypatch.setattr("anthropic.Anthropic", lambda **kwargs: fake_client)

    provider = AnthropicProvider(_settings(model="claude-sonnet-5", max_tokens=111))
    result = provider.generate("system instructions", "user prompt with evidence", {"kind": "generate_section_question"})

    assert result == '{"ok": true}'
    fake_client.messages.create.assert_called_once()
    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["max_tokens"] == 111
    assert kwargs["system"] == "system instructions"
    assert kwargs["messages"] == [{"role": "user", "content": "user prompt with evidence"}]
    # The task dict (which MockProvider reads for deterministic fixture
    # selection) must never be sent to the real API - only the two prompt
    # strings the generation layer built from prompts/*.txt.
    assert "task" not in kwargs


def test_joins_multiple_text_blocks_in_order(monkeypatch):
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.content = [
        TextBlock(type="text", text="first part "),
        TextBlock(type="text", text="second part"),
    ]
    fake_client.messages.create.return_value = fake_response
    monkeypatch.setattr("anthropic.Anthropic", lambda **kwargs: fake_client)

    provider = AnthropicProvider(_settings())
    result = provider.generate("sys", "user", {})
    assert result == "first part \nsecond part"


def test_empty_response_raises_provider_error(monkeypatch):
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.content = []
    fake_client.messages.create.return_value = fake_response
    monkeypatch.setattr("anthropic.Anthropic", lambda **kwargs: fake_client)

    provider = AnthropicProvider(_settings())
    with pytest.raises(LLMProviderError, match="no text content"):
        provider.generate("sys", "user", {})


def test_sdk_exception_is_wrapped_and_the_api_key_is_never_leaked(monkeypatch):
    fake_client = MagicMock()
    secret_key = "sk-ant-super-secret-real-looking-key-0123456789"
    fake_client.messages.create.side_effect = RuntimeError(f"auth failed for key {secret_key}")
    monkeypatch.setattr("anthropic.Anthropic", lambda **kwargs: fake_client)

    provider = AnthropicProvider(_settings(api_key=secret_key))
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert secret_key not in str(exc_info.value)


def test_a_401_sdk_error_is_classified_as_not_retryable(monkeypatch):
    """Regression test for src/providers/base.py's is_retryable_status
    hardening: a bad/revoked API key (401) fails identically on every
    retry, so call_provider_with_retry should not waste the retry budget
    on it."""
    import anthropic
    import httpx

    fake_client = MagicMock()
    response = httpx.Response(status_code=401, request=httpx.Request("POST", "https://api.anthropic.com/x"))
    fake_client.messages.create.side_effect = anthropic.AuthenticationError("bad key", response=response, body=None)
    monkeypatch.setattr("anthropic.Anthropic", lambda **kwargs: fake_client)

    provider = AnthropicProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is False


def test_a_429_sdk_error_is_still_classified_as_retryable(monkeypatch):
    import anthropic
    import httpx

    fake_client = MagicMock()
    response = httpx.Response(status_code=429, request=httpx.Request("POST", "https://api.anthropic.com/x"))
    fake_client.messages.create.side_effect = anthropic.RateLimitError("rate limited", response=response, body=None)
    monkeypatch.setattr("anthropic.Anthropic", lambda **kwargs: fake_client)

    provider = AnthropicProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is True
