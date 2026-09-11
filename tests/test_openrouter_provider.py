"""Tests the REAL OpenRouter provider path (src/providers/openrouter_provider.py)
can be exercised safely in CI: the ``httpx.Client`` used internally is
replaced with a fake, so no network call is ever made and no real API key
is required, but the request shape and response parsing are the same code
that runs against the live API - this is what src/cli.py's `generate`
command uses when LLM_PROVIDER=openrouter.

Mirrors tests/test_groq_provider.py's structure and coverage for the
sibling real provider.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from src.config import LLMSettings
from src.providers.base import LLMProviderError
from src.providers.openrouter_provider import OpenRouterProvider


def _settings(**overrides) -> LLMSettings:
    return LLMSettings(
        provider="openrouter",
        model=overrides.get("model", "google/gemini-3.8-flash"),
        api_key=overrides.get("api_key", "sk-or-v1-faketest0000000000000000000000000000000000000000"),
        max_tokens=overrides.get("max_tokens", 4096),
        temperature=overrides.get("temperature", 0.4),
    )


def _response(status_code: int, json_body: dict | None = None, headers: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    if json_body is not None:
        return httpx.Response(status_code, json=json_body, headers=headers or {}, request=request)
    return httpx.Response(status_code, headers=headers or {}, request=request)


def test_missing_api_key_raises_without_touching_httpx():
    with pytest.raises(LLMProviderError, match="OPENROUTER_API_KEY"):
        OpenRouterProvider(_settings(api_key=None))


def test_client_is_constructed_with_bearer_auth_header_and_base_url(monkeypatch):
    captured_kwargs: dict = {}

    def fake_client(**kwargs):
        captured_kwargs.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("httpx.Client", fake_client)

    OpenRouterProvider(_settings(api_key="sk-or-v1-realkeyshapedvalue00000000000000000000"))

    assert captured_kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert captured_kwargs["headers"]["Authorization"] == "Bearer sk-or-v1-realkeyshapedvalue00000000000000000000"
    # SecurityConfig.provider_timeout_seconds default is 60s.
    assert captured_kwargs["timeout"] == 60.0


def test_generate_sends_openai_compatible_fields_and_the_configured_model(monkeypatch):
    fake_client = MagicMock()
    fake_client.post.return_value = _response(200, {"choices": [{"message": {"content": '{"ok": true}'}}]})
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings(model="google/gemini-3.8-flash", max_tokens=222, temperature=0.7))
    result = provider.generate("system instructions", "user prompt with evidence", {"kind": "generate_section_question"})

    assert result == '{"ok": true}'
    fake_client.post.assert_called_once()
    args, kwargs = fake_client.post.call_args
    assert args[0] == "/chat/completions"
    body = kwargs["json"]
    assert body["model"] == "google/gemini-3.8-flash"
    assert body["messages"] == [
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": "user prompt with evidence"},
    ]
    assert body["max_tokens"] == 222
    assert body["temperature"] == 0.7
    # The task dict (MockProvider-only, see src/providers/base.py's module
    # docstring) must never be sent to the real API.
    assert "task" not in body


def test_generate_never_sends_groq_specific_parameters(monkeypatch):
    """Requirement: do not blindly copy Groq's reasoning_effort/
    reasoning_format/max_completion_tokens onto a different provider."""
    fake_client = MagicMock()
    fake_client.post.return_value = _response(200, {"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    provider.generate("sys", "user", {"kind": "generate_section_question"})

    _, kwargs = fake_client.post.call_args
    body = kwargs["json"]
    assert "reasoning_effort" not in body
    assert "reasoning_format" not in body
    assert "max_completion_tokens" not in body
    assert "max_tokens" in body  # the universally OpenAI-compatible field name


def test_empty_choices_raises_provider_error(monkeypatch):
    fake_client = MagicMock()
    fake_client.post.return_value = _response(200, {"choices": []})
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    with pytest.raises(LLMProviderError, match="no text content"):
        provider.generate("sys", "user", {})


def test_blank_message_content_raises_provider_error(monkeypatch):
    fake_client = MagicMock()
    fake_client.post.return_value = _response(200, {"choices": [{"message": {"content": ""}}]})
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    with pytest.raises(LLMProviderError, match="no text content"):
        provider.generate("sys", "user", {})


def test_missing_message_content_key_raises_provider_error(monkeypatch):
    fake_client = MagicMock()
    fake_client.post.return_value = _response(200, {"choices": [{"message": {}}]})
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    with pytest.raises(LLMProviderError, match="no text content"):
        provider.generate("sys", "user", {})


def test_a_401_is_classified_as_not_retryable(monkeypatch):
    fake_client = MagicMock()
    fake_client.post.return_value = _response(401, {"error": "invalid api key"})
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is False


def test_a_403_is_classified_as_not_retryable(monkeypatch):
    fake_client = MagicMock()
    fake_client.post.return_value = _response(403, {"error": "forbidden"})
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is False


def test_a_429_is_classified_as_retryable_and_captures_retry_after(monkeypatch):
    fake_client = MagicMock()
    fake_client.post.return_value = _response(429, {"error": "rate limited"}, headers={"retry-after": "4.71"})
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is True
    assert exc_info.value.retry_after == pytest.approx(4.71)


def test_a_429_without_retry_after_header_leaves_retry_after_none(monkeypatch):
    fake_client = MagicMock()
    fake_client.post.return_value = _response(429, {"error": "rate limited"})
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is True
    assert exc_info.value.retry_after is None


def test_a_5xx_is_classified_as_retryable(monkeypatch):
    fake_client = MagicMock()
    fake_client.post.return_value = _response(503, {"error": "service unavailable"})
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is True


def test_a_network_error_with_no_response_defaults_to_retryable(monkeypatch):
    fake_client = MagicMock()
    fake_client.post.side_effect = httpx.ConnectError("connection refused")
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is True
    assert exc_info.value.retry_after is None


def test_the_api_key_is_never_leaked_in_an_exception_message(monkeypatch):
    secret_key = "sk-or-v1-" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
    fake_client = MagicMock()
    fake_client.post.side_effect = RuntimeError(f"auth failed for key {secret_key}")
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings(api_key=secret_key))
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert secret_key not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_redact_secrets_recognizes_an_openrouter_shaped_key_directly():
    """Unit-level proof (no provider involved) that redact_secrets itself
    - not just this provider's error wrapping - recognizes the sk-or-v1-
    prefix, per requirement #11 ("secret redaction")."""
    from src.security.redaction import redact_secrets

    fake_key = "sk-or-v1-" + "0" * 40
    assert fake_key not in redact_secrets(f"failed with key {fake_key}")
    assert "[REDACTED]" in redact_secrets(f"failed with key {fake_key}")


def test_missing_httpx_raises_a_clear_provider_error(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "httpx", None)

    with pytest.raises(LLMProviderError, match="'httpx' package is not installed"):
        OpenRouterProvider(_settings())


def test_openrouter_receives_the_real_retrieved_evidence_through_the_generation_pipeline(monkeypatch):
    """End-to-end (still offline): builds a REAL OpenRouterProvider (fake
    httpx client, no network) and runs it through
    src/generation/question_generator.generate_paper with real retrieved
    evidence, exactly like src/cli.py's `generate` command does when
    LLM_PROVIDER=openrouter. Asserts the evidence passage and page citation
    that reached the retrieval layer are byte-for-byte present in what was
    actually sent to the (fake) OpenRouter call, and that the existing
    grounding/provenance pipeline is unaffected by which provider produced
    the text."""
    from src.generation.question_generator import generate_paper

    evidence_text = "HTML5 introduces new semantic elements such as header footer and section for structuring a page."
    evidence_by_section = {
        "B": [
            {
                "document": "Module 6-Learner Guide.pdf",
                "page": 62,
                "kt_code": "KM-06-KT06",
                "passage": evidence_text,
                "reason": "Retrieved for KM-06-KT06 (HTML5)",
                "relevance": 0.4,
            }
        ]
    }
    blueprint = {
        "paper_id": "test-paper",
        "qualification_title": "Test Qualification",
        "nqf_level": 5,
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "duration_minutes": 60,
        "total_marks": 10,
        "instructions": ["Answer all."],
        "sections": [
            {
                "id": "B",
                "title": "Front-End Web Development",
                "marks": 10,
                "outcomes": ["KM-06-KT06"],
                "competencies": ["HTML5"],
                "required_outcomes": ["KM-06-KT06"],
                "difficulty": "intermediate",
                "question_types": ["scenario_short_answer"],
                "occupational_context": "Front-end developer building a page for a client site.",
            }
        ],
    }

    fake_client = MagicMock()
    fake_client.post.return_value = _response(
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "type": "scenario_short_answer",
                                "scenario": (
                                    "A developer at Acme Retail rebuilds a page using new semantic elements "
                                    "such as header and section for structuring content."
                                ),
                                "question": "Which elements would you use and why?",
                                "expected_response_type": "short_answer",
                                "outcomes": ["KM-06-KT06"],
                            }
                        )
                    }
                }
            ]
        },
    )
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    provider = OpenRouterProvider(_settings())
    paper = generate_paper(blueprint, provider, seed=1, evidence_by_section=evidence_by_section)

    fake_client.post.assert_called_once()
    _, kwargs = fake_client.post.call_args
    sent_prompt = kwargs["json"]["messages"][1]["content"]
    assert evidence_text in sent_prompt
    assert "Module 6-Learner Guide.pdf" in sent_prompt
    assert "page 62" in sent_prompt

    question = paper["sections"][0]["questions"][0]
    assert question["grounding"][0]["passage"] == evidence_text
    assert paper["generation_meta"]["provider"] == "openrouter"
