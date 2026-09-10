"""Tests for bounded retries and resource limits around provider calls.

Generation failure must terminate safely - these tests prove there is no
unbounded retry loop, that GenerationError (deterministic content defects)
is never retried, and that an oversized provider response is rejected
before it reaches JSON parsing.
"""
from __future__ import annotations

import pytest

from src.generation.llm_utils import (
    GenerationError,
    call_provider_with_retry,
    extract_json,
)
from src.providers.base import LLMProvider, LLMProviderError, is_retryable_status
from src.security.config import SecurityConfig


class _AlwaysFailsProvider(LLMProvider):
    name = "always-fails"

    def __init__(self):
        self.call_count = 0

    def generate(self, system_prompt, user_prompt, task):
        self.call_count += 1
        raise LLMProviderError("simulated transient failure")


class _FailsTwiceThenSucceedsProvider(LLMProvider):
    name = "fails-twice"

    def __init__(self):
        self.call_count = 0

    def generate(self, system_prompt, user_prompt, task):
        self.call_count += 1
        if self.call_count < 3:
            raise LLMProviderError("simulated transient failure")
        return '{"ok": true}'


class _RaisesGenerationErrorProvider(LLMProvider):
    name = "bad-content"

    def __init__(self):
        self.call_count = 0

    def generate(self, system_prompt, user_prompt, task):
        self.call_count += 1
        raise GenerationError("deterministic content defect - retrying would not help")


class _RaisesPermanentProviderErrorProvider(LLMProvider):
    """Simulates a real provider that classified its own exception as
    non-retryable (see src/providers/groq_provider.py and
    anthropic_provider.py's status-code classification) - e.g. a 401 bad
    API key. Every attempt would fail identically; call_provider_with_retry
    must stop after the FIRST attempt, not burn the full retry budget."""

    name = "permanent-failure"

    def __init__(self):
        self.call_count = 0

    def generate(self, system_prompt, user_prompt, task):
        self.call_count += 1
        raise LLMProviderError("simulated permanent failure (e.g. bad API key)", retryable=False)


def test_retry_terminates_safely_after_max_attempts_and_reraises():
    provider = _AlwaysFailsProvider()
    config = SecurityConfig(generation_max_retries=3, generation_retry_backoff_seconds=0.0)
    with pytest.raises(LLMProviderError):
        call_provider_with_retry(provider, "sys", "user", {}, security_config=config)
    assert provider.call_count == 3  # exactly the configured max, never more


def test_retry_succeeds_within_the_attempt_budget():
    provider = _FailsTwiceThenSucceedsProvider()
    config = SecurityConfig(generation_max_retries=5, generation_retry_backoff_seconds=0.0)
    result = call_provider_with_retry(provider, "sys", "user", {}, security_config=config)
    assert result == '{"ok": true}'
    assert provider.call_count == 3


def test_generation_error_is_never_retried():
    """A GenerationError is raised by extract_json AFTER provider.generate()
    returns, so call_provider_with_retry itself never sees one from a
    correctly-implemented provider - but if a provider implementation ever
    raised one directly, it must propagate immediately without retries,
    since MockProvider-style determinism means a retry cannot succeed."""
    provider = _RaisesGenerationErrorProvider()
    config = SecurityConfig(generation_max_retries=5, generation_retry_backoff_seconds=0.0)
    with pytest.raises(GenerationError):
        call_provider_with_retry(provider, "sys", "user", {}, security_config=config)
    assert provider.call_count == 1  # not retried


def test_retry_count_of_one_means_no_retries():
    provider = _AlwaysFailsProvider()
    config = SecurityConfig(generation_max_retries=1, generation_retry_backoff_seconds=0.0)
    with pytest.raises(LLMProviderError):
        call_provider_with_retry(provider, "sys", "user", {}, security_config=config)
    assert provider.call_count == 1


def test_a_permanent_provider_error_is_not_retried_even_with_budget_remaining():
    """Regression test: a 401/403-shaped (or any explicitly non-retryable)
    provider failure must stop after the first attempt, not loop through
    the full generation_max_retries budget on a foregone conclusion - see
    src/providers/base.py's LLMProviderError.retryable."""
    provider = _RaisesPermanentProviderErrorProvider()
    config = SecurityConfig(generation_max_retries=5, generation_retry_backoff_seconds=0.0)
    with pytest.raises(LLMProviderError, match="permanent failure"):
        call_provider_with_retry(provider, "sys", "user", {}, security_config=config)
    assert provider.call_count == 1  # NOT 5 - no pointless retries


def test_is_retryable_status_rejects_known_permanent_client_errors():
    for status in (400, 401, 403, 404, 422):
        assert is_retryable_status(status) is False


def test_is_retryable_status_allows_rate_limit_and_server_errors():
    for status in (429, 500, 502, 503, 504):
        assert is_retryable_status(status) is True


def test_is_retryable_status_defaults_true_when_no_status_is_available():
    """A network error/timeout carries no HTTP status at all - the
    conservative default is retryable, never assume permanence without
    positive evidence."""
    assert is_retryable_status(None) is True


def test_oversized_provider_response_is_rejected_before_parsing():
    config = SecurityConfig(max_provider_response_chars=100)
    huge_response = '{"question": "' + ("x" * 1000) + '"}'
    with pytest.raises(GenerationError, match="exceeding"):
        extract_json(huge_response, security_config=config)


def test_response_within_bound_parses_normally():
    config = SecurityConfig(max_provider_response_chars=10_000)
    result = extract_json('{"ok": true}', security_config=config)
    assert result == {"ok": True}
