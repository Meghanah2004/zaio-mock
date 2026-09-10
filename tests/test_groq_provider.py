"""Tests the REAL Groq provider path (src/providers/groq_provider.py) can
be exercised safely in CI: the ``groq`` SDK client is replaced with a fake,
so no network call is ever made and no real API key is required, but the
request shape and response parsing are the same code that runs against the
live API - this is what src/cli.py's `generate` command uses when
LLM_PROVIDER=groq.

Mirrors tests/test_anthropic_provider.py and tests/test_gemini_provider.py's
structure and coverage for the other two real providers.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import groq
import pytest

from src.config import LLMSettings
from src.providers.base import LLMProviderError
from src.providers.groq_provider import GroqProvider


def _settings(**overrides) -> LLMSettings:
    return LLMSettings(
        provider="groq",
        model=overrides.get("model", "openai/gpt-oss-120b"),
        api_key=overrides.get("api_key", "gsk_fake0000000000000000000000000000test"),
        max_tokens=overrides.get("max_tokens", 4096),
        temperature=overrides.get("temperature", 0.4),
    )


def test_missing_api_key_raises_without_touching_the_sdk():
    with pytest.raises(LLMProviderError, match="GROQ_API_KEY"):
        GroqProvider(_settings(api_key=None))


def test_client_is_constructed_with_the_api_key_and_a_second_based_timeout(monkeypatch):
    fake_client = MagicMock()
    captured_kwargs: dict = {}

    def fake_groq_client(**kwargs):
        captured_kwargs.update(kwargs)
        return fake_client

    monkeypatch.setattr("groq.Groq", fake_groq_client)

    GroqProvider(_settings(api_key="fake-key-123"))

    assert captured_kwargs["api_key"] == "fake-key-123"
    # SecurityConfig.provider_timeout_seconds default is 60s; Groq's client
    # `timeout` is documented (by the installed SDK's own signature) as
    # seconds - unlike Gemini's millisecond HttpOptions.timeout - so this
    # must NOT be multiplied the way GeminiProvider's is.
    assert captured_kwargs["timeout"] == 60.0
    # Regression test for a real production incident (backend log
    # 2026-09-10 12:14:55, request_id 7748bf00-...): the SDK's own default
    # internal retry (max_retries=2) compounded with
    # src.generation.llm_utils.call_provider_with_retry's own bounded retry
    # loop, turning one confirmed-non-retryable 429 (daily token quota) into
    # several minutes of doomed nested retrying. Retry policy must live in
    # exactly one place.
    assert captured_kwargs["max_retries"] == 0


def test_generate_sends_system_and_user_messages_and_the_configured_model(monkeypatch):
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]
    fake_client.chat.completions.create.return_value = fake_response
    monkeypatch.setattr("groq.Groq", lambda **kwargs: fake_client)

    provider = GroqProvider(_settings(model="openai/gpt-oss-120b", max_tokens=222, temperature=0.7))
    result = provider.generate(
        "system instructions", "user prompt with evidence", {"kind": "generate_section_question"}
    )

    assert result == '{"ok": true}'
    fake_client.chat.completions.create.assert_called_once()
    _, kwargs = fake_client.chat.completions.create.call_args
    assert kwargs["model"] == "openai/gpt-oss-120b"
    assert kwargs["messages"] == [
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": "user prompt with evidence"},
    ]
    assert kwargs["max_completion_tokens"] == 222
    assert kwargs["temperature"] == 0.7
    # The task dict (which MockProvider reads for deterministic fixture
    # selection) must never be sent to the real API - only the two prompt
    # strings the generation layer built from prompts/*.txt + retrieved
    # evidence.
    assert "task" not in kwargs


def test_empty_choices_raises_provider_error(monkeypatch):
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.choices = []
    fake_client.chat.completions.create.return_value = fake_response
    monkeypatch.setattr("groq.Groq", lambda **kwargs: fake_client)

    provider = GroqProvider(_settings())
    with pytest.raises(LLMProviderError, match="no text content"):
        provider.generate("sys", "user", {})


def test_blank_message_content_raises_provider_error(monkeypatch):
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content=""))]
    fake_client.chat.completions.create.return_value = fake_response
    monkeypatch.setattr("groq.Groq", lambda **kwargs: fake_client)

    provider = GroqProvider(_settings())
    with pytest.raises(LLMProviderError, match="no text content"):
        provider.generate("sys", "user", {})


def test_sdk_exception_is_wrapped_and_the_api_key_is_never_leaked(monkeypatch):
    fake_client = MagicMock()
    secret_key = "gsk_" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
    fake_client.chat.completions.create.side_effect = RuntimeError(f"auth failed for key {secret_key}")
    monkeypatch.setattr("groq.Groq", lambda **kwargs: fake_client)

    provider = GroqProvider(_settings(api_key=secret_key))
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert secret_key not in str(exc_info.value)


def test_a_401_sdk_error_is_classified_as_not_retryable(monkeypatch):
    """Regression test for src/providers/base.py's is_retryable_status
    hardening: a bad/revoked API key (401) fails identically on every
    retry, so call_provider_with_retry should not waste the retry budget
    on it - see tests/test_security_retry_and_resource_limits.py for the
    call_provider_with_retry-level behavior this classification feeds."""
    import httpx

    fake_client = MagicMock()
    response = httpx.Response(status_code=401, request=httpx.Request("POST", "https://api.groq.com/x"))
    fake_client.chat.completions.create.side_effect = groq.AuthenticationError("bad key", response=response, body=None)
    monkeypatch.setattr("groq.Groq", lambda **kwargs: fake_client)

    provider = GroqProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is False


def test_a_429_sdk_error_is_still_classified_as_retryable(monkeypatch):
    """A rate limit CAN clear within the bounded retry window (unlike a bad
    credential) - must remain retryable, not lumped in with permanent 4xx
    failures."""
    import httpx

    fake_client = MagicMock()
    response = httpx.Response(status_code=429, request=httpx.Request("POST", "https://api.groq.com/x"))
    fake_client.chat.completions.create.side_effect = groq.RateLimitError("rate limited", response=response, body=None)
    monkeypatch.setattr("groq.Groq", lambda **kwargs: fake_client)

    provider = GroqProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is True


def test_missing_sdk_raises_a_clear_provider_error(monkeypatch):
    # Setting a module to None in sys.modules is the standard way to force
    # `import groq` to raise ImportError, simulating an environment where
    # the groq package was never installed - without needing to actually
    # uninstall it for this test.
    monkeypatch.setitem(sys.modules, "groq", None)

    with pytest.raises(LLMProviderError, match="'groq' package is not installed"):
        GroqProvider(_settings())


def test_groq_receives_the_real_retrieved_evidence_through_the_generation_pipeline(monkeypatch):
    """End-to-end (still offline): builds a REAL GroqProvider (fake SDK
    client, no network) and runs it through
    src/generation/question_generator.generate_paper with real retrieved
    evidence, exactly like src/cli.py's `generate` command does when
    LLM_PROVIDER=groq. Asserts the evidence passage and page citation that
    reached the retrieval layer are byte-for-byte present in what was
    actually sent to the (fake) Groq SDK call, and that the existing
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
    fake_response = MagicMock()
    fake_response.choices = [
        MagicMock(
            message=MagicMock(
                content=(
                    '{"type": "scenario_short_answer", '
                    '"scenario": "A developer at Acme Retail rebuilds a page using new semantic elements such as '
                    'header and section for structuring content.", '
                    '"question": "Which elements would you use and why?", '
                    '"expected_response_type": "short_answer", '
                    '"outcomes": ["KM-06-KT06"]}'
                )
            )
        )
    ]
    fake_client.chat.completions.create.return_value = fake_response
    monkeypatch.setattr("groq.Groq", lambda **kwargs: fake_client)

    provider = GroqProvider(_settings())
    paper = generate_paper(blueprint, provider, seed=1, evidence_by_section=evidence_by_section)

    fake_client.chat.completions.create.assert_called_once()
    _, kwargs = fake_client.chat.completions.create.call_args
    sent_prompt = kwargs["messages"][1]["content"]
    assert evidence_text in sent_prompt
    assert "Module 6-Learner Guide.pdf" in sent_prompt
    assert "page 62" in sent_prompt

    question = paper["sections"][0]["questions"][0]
    assert question["grounding"][0]["passage"] == evidence_text
    assert paper["generation_meta"]["provider"] == "groq"


def test_groq_memo_with_bad_criteria_sum_is_rejected_then_corrected_end_to_end(monkeypatch):
    """Reproduces the real production failure ("Q-E1 sub-question 1: memo
    criteria sum to 5, expected 4") through a real GroqProvider (mocked
    SDK, no network): the first Groq response gets a sub-question's
    criteria sum wrong, the second (after the retry note) gets it right -
    see src/generation/memo_generator.py."""
    from src.generation.memo_generator import generate_memo

    question = {
        "id": "Q-E1",
        "section_id": "E",
        "marks": 10,
        "question": "Answer the following questions about SDLC and security.",
        "sub_questions": [
            {"id": "1", "prompt": "Identify the SDLC phase.", "marks": 4},
            {"id": "2", "prompt": "Fix the vulnerability.", "marks": 6},
        ],
    }
    paper = {
        "paper_id": "test-paper",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 10,
        "sections": [{"id": "E", "questions": [question]}],
    }

    def _memo_json(sub1_marks: list[int]) -> str:
        import json as _json

        return _json.dumps(
            {
                "question_id": "Q-E1",
                "total_marks": 10,
                "model_answer": "See per-part model answers below.",
                "criteria": [{"description": "see sub_questions", "marks": 10}],
                "accepted_alternatives": [],
                "sub_questions": [
                    {
                        "id": "1",
                        "total_marks": 4,
                        "model_answer": "Testing.",
                        "criteria": [{"description": f"c{i}", "marks": m} for i, m in enumerate(sub1_marks)],
                        "accepted_alternatives": [],
                    },
                    {
                        "id": "2",
                        "total_marks": 6,
                        "model_answer": "Use parameterised queries.",
                        "criteria": [{"description": "c0", "marks": 6}],
                        "accepted_alternatives": [],
                    },
                ],
            }
        )

    fake_client = MagicMock()
    bad_response = MagicMock()
    bad_response.choices = [MagicMock(message=MagicMock(content=_memo_json([2, 3])))]  # sums to 5, not 4
    good_response = MagicMock()
    good_response.choices = [MagicMock(message=MagicMock(content=_memo_json([2, 2])))]  # sums to 4
    fake_client.chat.completions.create.side_effect = [bad_response, good_response]
    monkeypatch.setattr("groq.Groq", lambda **kwargs: fake_client)

    provider = GroqProvider(_settings())
    memo = generate_memo(paper, provider, seed=1)

    assert fake_client.chat.completions.create.call_count == 2
    memo_sub1 = memo["sections"][0]["questions"][0]["sub_questions"][0]
    assert sum(c["marks"] for c in memo_sub1["criteria"]) == 4


def test_groq_section_marks_mismatch_is_rejected_then_corrected_end_to_end(monkeypatch):
    """Reproduces the real production failure ("Q-D1: generated marks (25)
    do not equal section 'D' target marks (20)") through a real
    GroqProvider (mocked SDK, no network): the first Groq response's
    sub-question marks sum to 25 instead of the section's 20; the second
    (after the retry note) sums to exactly 20 - see
    src/generation/question_generator.py."""
    from src.generation.question_generator import generate_paper

    blueprint = {
        "paper_id": "test-paper",
        "qualification_title": "Test Qualification",
        "nqf_level": 5,
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "duration_minutes": 60,
        "total_marks": 20,
        "instructions": ["Answer all."],
        "sections": [
            {
                "id": "D",
                "title": "Data, Databases and Querying",
                "marks": 20,
                "outcomes": ["KM-08-KT01"],
                "competencies": ["Understanding core database concepts"],
                "required_outcomes": ["KM-08-KT01"],
                "difficulty": "intermediate",
                "question_types": ["code_writing"],
                "occupational_context": "Developer designing a relational database for an application.",
            }
        ],
    }
    evidence_by_section = {
        "D": [
            {
                "document": "Module 8-Learner Guide.pdf",
                "page": 10,
                "kt_code": "KM-08-KT01",
                "passage": "A primary key uniquely identifies each record in a relational database table without duplication.",
                "reason": "Retrieved for KM-08-KT01 (Understanding core database concepts)",
                "relevance": 0.4,
            }
        ]
    }

    def _question_json(sub_marks: list[int]) -> str:
        import json as _json

        return _json.dumps(
            {
                "type": "code_writing",
                "scenario": (
                    "A developer at Acme Retail needs a small relational database to track products "
                    "and suppliers, using primary keys to identify each product record without duplication."
                ),
                "question": "Complete the following database tasks.",
                "sub_questions": [
                    {"id": str(i), "prompt": f"Sub-task {i}: write the relevant SQL.", "marks": m, "expected_response_type": "sql_code"}
                    for i, m in enumerate(sub_marks, start=1)
                ],
                "outcomes": ["KM-08-KT01"],
            }
        )

    fake_client = MagicMock()
    bad_response = MagicMock()
    bad_response.choices = [MagicMock(message=MagicMock(content=_question_json([10, 15])))]  # sums to 25, not 20
    good_response = MagicMock()
    good_response.choices = [MagicMock(message=MagicMock(content=_question_json([10, 10])))]  # sums to 20
    fake_client.chat.completions.create.side_effect = [bad_response, good_response]
    monkeypatch.setattr("groq.Groq", lambda **kwargs: fake_client)

    provider = GroqProvider(_settings())
    paper = generate_paper(blueprint, provider, seed=1, evidence_by_section=evidence_by_section)

    assert fake_client.chat.completions.create.call_count == 2
    question = paper["sections"][0]["questions"][0]
    assert question["marks"] == 20
    assert sum(sq["marks"] for sq in question["sub_questions"]) == 20
