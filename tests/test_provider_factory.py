"""Tests for src/providers/factory.py's provider selection.

No test here makes a real network call: the "real credentials configured"
branches are exercised only up to construction (which itself never
connects - AnthropicProvider, GeminiProvider, and GroqProvider only build
an SDK client object) or are monkeypatched to a fake SDK client, matching
tests/test_anthropic_provider.py, tests/test_gemini_provider.py, and
tests/test_groq_provider.py.
"""
from __future__ import annotations

import pytest

from src.config import LLMSettings
from src.providers.base import LLMProviderError
from src.providers.factory import build_provider
from src.providers.mock_provider import MockProvider
from src.security.config import SecurityConfig


def test_mock_provider_selected_by_default():
    provider = build_provider(LLMSettings(provider="mock"))
    assert isinstance(provider, MockProvider)


def test_anthropic_without_api_key_falls_back_to_mock_with_a_warning(capsys):
    provider = build_provider(LLMSettings(provider="anthropic", api_key=None))
    assert isinstance(provider, MockProvider)
    captured = capsys.readouterr()
    assert "ANTHROPIC_API_KEY is not set" in captured.err


def test_gemini_without_api_key_falls_back_to_mock_with_a_warning(capsys):
    provider = build_provider(LLMSettings(provider="gemini", api_key=None))
    assert isinstance(provider, MockProvider)
    captured = capsys.readouterr()
    assert "GEMINI_API_KEY is not set" in captured.err


def test_groq_without_api_key_falls_back_to_mock_with_a_warning(capsys):
    provider = build_provider(LLMSettings(provider="groq", api_key=None))
    assert isinstance(provider, MockProvider)
    captured = capsys.readouterr()
    assert "GROQ_API_KEY is not set" in captured.err


def test_anthropic_with_api_key_builds_the_real_provider_class(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr("anthropic.Anthropic", lambda **kwargs: MagicMock())
    from src.providers.anthropic_provider import AnthropicProvider

    provider = build_provider(LLMSettings(provider="anthropic", api_key="sk-ant-fake-not-real"))
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"


def test_gemini_with_api_key_builds_the_real_provider_class(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr("google.genai.Client", lambda **kwargs: MagicMock())
    from src.providers.gemini_provider import GeminiProvider

    provider = build_provider(LLMSettings(provider="gemini", api_key="AIzaSyFAKE0123456789abcdefghijklmnopqrst"[:39]))
    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini"


def test_groq_with_api_key_builds_the_real_provider_class(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr("groq.Groq", lambda **kwargs: MagicMock())
    from src.providers.groq_provider import GroqProvider

    provider = build_provider(LLMSettings(provider="groq", api_key="gsk_fake0000000000000000000000000000test"))
    assert isinstance(provider, GroqProvider)
    assert provider.name == "groq"


def test_unknown_provider_raises_value_error_naming_all_supported_providers():
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER") as exc_info:
        build_provider(LLMSettings(provider="does-not-exist"))
    message = str(exc_info.value)
    assert "mock" in message
    assert "anthropic" in message
    assert "gemini" in message
    assert "groq" in message


# ---------------------------------------------------------------------------
# require_real_provider (REQUIRE_REAL_PROVIDER=true - production hardening):
# turns the "silent-but-logged fallback to MockProvider" behavior above into
# a hard, immediate failure - see src/providers/factory.py's REWORK
# docstring for the real risk this addresses (an unattended production
# deployment serving fake fixture content with only a stderr warning nobody
# is watching). Default is false, so every test above (which never passes
# this flag) is a regression guard that the DEFAULT behavior is unchanged.
# ---------------------------------------------------------------------------
def test_require_real_provider_rejects_mock_provider_outright():
    strict = SecurityConfig(require_real_provider=True)
    with pytest.raises(LLMProviderError, match="LLM_PROVIDER is 'mock'"):
        build_provider(LLMSettings(provider="mock"), strict)


def test_require_real_provider_rejects_a_missing_groq_key_instead_of_falling_back(capsys):
    strict = SecurityConfig(require_real_provider=True)
    with pytest.raises(LLMProviderError, match="GROQ_API_KEY is not set"):
        build_provider(LLMSettings(provider="groq", api_key=None), strict)
    # Must fail BEFORE printing the fallback warning - no stderr noise
    # implying a (never-taken) fallback happened.
    captured = capsys.readouterr()
    assert "Falling back" not in captured.err


def test_require_real_provider_rejects_a_missing_anthropic_key():
    strict = SecurityConfig(require_real_provider=True)
    with pytest.raises(LLMProviderError, match="ANTHROPIC_API_KEY is not set"):
        build_provider(LLMSettings(provider="anthropic", api_key=None), strict)


def test_require_real_provider_rejects_a_missing_gemini_key():
    strict = SecurityConfig(require_real_provider=True)
    with pytest.raises(LLMProviderError, match="GEMINI_API_KEY is not set"):
        build_provider(LLMSettings(provider="gemini", api_key=None), strict)


def test_require_real_provider_still_builds_the_real_provider_when_properly_configured(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr("groq.Groq", lambda **kwargs: MagicMock())
    from src.providers.groq_provider import GroqProvider

    strict = SecurityConfig(require_real_provider=True)
    provider = build_provider(LLMSettings(provider="groq", api_key="gsk_fake0000000000000000000000000000test"), strict)
    assert isinstance(provider, GroqProvider)


def test_require_real_provider_defaults_to_false_and_does_not_change_default_behavior():
    """SecurityConfig() with no override, and build_provider's own default
    (no security_config argument at all) must behave identically - both
    exercise the same, unchanged, fallback-with-a-warning default path."""
    assert SecurityConfig().require_real_provider is False
    provider = build_provider(LLMSettings(provider="mock"))
    assert isinstance(provider, MockProvider)
