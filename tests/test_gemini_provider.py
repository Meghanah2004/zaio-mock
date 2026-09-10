"""Tests the REAL Gemini provider path (src/providers/gemini_provider.py)
can be exercised safely in CI: the ``google-genai`` SDK client is replaced
with a fake, so no network call is ever made and no real API key is
required, but the request shape and response parsing are the same code
that runs against the live API - this is what src/cli.py's `generate`
command uses when LLM_PROVIDER=gemini (see docs/DESIGN_NOTE.md).

Mirrors tests/test_anthropic_provider.py's structure and coverage for the
other real provider.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from src.config import LLMSettings
from src.providers.base import LLMProviderError
from src.providers.gemini_provider import GeminiProvider


def _settings(**overrides) -> LLMSettings:
    return LLMSettings(
        provider="gemini",
        model=overrides.get("model", "gemini-3.6-flash"),
        api_key=overrides.get("api_key", "fake-test-gemini-key-not-real"),
        max_tokens=overrides.get("max_tokens", 4096),
        temperature=overrides.get("temperature", 0.4),
    )


def test_missing_api_key_raises_without_touching_the_sdk():
    with pytest.raises(LLMProviderError, match="GEMINI_API_KEY"):
        GeminiProvider(_settings(api_key=None))


def test_client_is_constructed_with_the_api_key_and_a_millisecond_timeout(monkeypatch):
    fake_client = MagicMock()
    captured_kwargs: dict = {}

    def fake_genai_client(**kwargs):
        captured_kwargs.update(kwargs)
        return fake_client

    monkeypatch.setattr("google.genai.Client", fake_genai_client)

    GeminiProvider(_settings(api_key="fake-key-123"))

    assert captured_kwargs["api_key"] == "fake-key-123"
    # SecurityConfig.provider_timeout_seconds default is 60s; the SDK's
    # HttpOptions.timeout field is documented (by the installed SDK itself)
    # as milliseconds, so this must be converted, not passed through raw.
    assert captured_kwargs["http_options"].timeout == 60_000


def test_generate_sends_system_instruction_user_prompt_and_configured_model(monkeypatch):
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.text = '{"ok": true}'
    fake_client.models.generate_content.return_value = fake_response
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: fake_client)

    provider = GeminiProvider(_settings(model="gemini-3.6-flash", max_tokens=222, temperature=0.7))
    result = provider.generate(
        "system instructions", "user prompt with evidence", {"kind": "generate_section_question"}
    )

    assert result == '{"ok": true}'
    fake_client.models.generate_content.assert_called_once()
    _, kwargs = fake_client.models.generate_content.call_args
    assert kwargs["model"] == "gemini-3.6-flash"
    assert kwargs["contents"] == "user prompt with evidence"
    config = kwargs["config"]
    assert config.system_instruction == "system instructions"
    assert config.max_output_tokens == 222
    assert config.temperature == 0.7
    # The task dict (which MockProvider reads for deterministic fixture
    # selection) must never be sent to the real API - only the two prompt
    # strings the generation layer built from prompts/*.txt + retrieved
    # evidence.
    assert "task" not in kwargs


def test_empty_response_raises_provider_error(monkeypatch):
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.text = None
    fake_client.models.generate_content.return_value = fake_response
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: fake_client)

    provider = GeminiProvider(_settings())
    with pytest.raises(LLMProviderError, match="no text content"):
        provider.generate("sys", "user", {})


def test_blank_string_response_also_raises_provider_error(monkeypatch):
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.text = ""
    fake_client.models.generate_content.return_value = fake_response
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: fake_client)

    provider = GeminiProvider(_settings())
    with pytest.raises(LLMProviderError, match="no text content"):
        provider.generate("sys", "user", {})


def test_sdk_exception_is_wrapped_and_the_api_key_is_never_leaked(monkeypatch):
    fake_client = MagicMock()
    # Realistic shape of a real Google/Gemini API key (AIza + 35 chars,
    # 39 total) - see src/security/redaction.py's dedicated pattern for it.
    secret_key = "AIzaSyFAKE0123456789abcdefghijklmnopqrst"[:39]
    fake_client.models.generate_content.side_effect = RuntimeError(f"auth failed for key {secret_key}")
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: fake_client)

    provider = GeminiProvider(_settings(api_key=secret_key))
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert secret_key not in str(exc_info.value)


def test_a_401_sdk_error_is_classified_as_not_retryable(monkeypatch):
    """Regression test for src/providers/base.py's is_retryable_status
    hardening: a bad/revoked API key (401) fails identically on every
    retry, so call_provider_with_retry should not waste the retry budget
    on it. Gemini's SDK exposes the HTTP status as `.code`, not
    `.status_code` (verified directly - see src/providers/gemini_provider.py)."""
    from google.genai import errors

    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = errors.ClientError(401, {"error": {"message": "bad key"}})
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: fake_client)

    provider = GeminiProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is False


def test_a_429_sdk_error_is_still_classified_as_retryable(monkeypatch):
    from google.genai import errors

    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = errors.ClientError(429, {"error": {"message": "rate limited"}})
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: fake_client)

    provider = GeminiProvider(_settings())
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("sys", "user", {})
    assert exc_info.value.retryable is True


def test_gemini_receives_the_real_retrieved_evidence_through_the_generation_pipeline(monkeypatch):
    """End-to-end (still offline): builds a REAL GeminiProvider (fake SDK
    client, no network) and runs it through
    src/generation/question_generator.generate_paper with real retrieved
    evidence, exactly like src/cli.py's `generate` command does when
    LLM_PROVIDER=gemini. Asserts the evidence passage and page citation
    that reached the retrieval layer are byte-for-byte present in what was
    actually sent to the (fake) Gemini SDK call - proving Gemini gets the
    RAG evidence, not just a topic name, without needing a real API call."""
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
    fake_response.text = (
        '{"type": "scenario_short_answer", '
        '"scenario": "A developer at Acme Retail rebuilds a page using new semantic elements such as '
        'header and section for structuring content.", '
        '"question": "Which elements would you use and why?", '
        '"expected_response_type": "short_answer", '
        '"outcomes": ["KM-06-KT06"]}'
    )
    fake_client.models.generate_content.return_value = fake_response
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: fake_client)

    provider = GeminiProvider(_settings())
    paper = generate_paper(blueprint, provider, seed=1, evidence_by_section=evidence_by_section)

    fake_client.models.generate_content.assert_called_once()
    _, kwargs = fake_client.models.generate_content.call_args
    sent_prompt = kwargs["contents"]
    assert evidence_text in sent_prompt
    assert "Module 6-Learner Guide.pdf" in sent_prompt
    assert "page 62" in sent_prompt

    question = paper["sections"][0]["questions"][0]
    assert question["grounding"][0]["passage"] == evidence_text
    assert paper["generation_meta"]["provider"] == "gemini"


def test_real_gemini_response_with_a_raw_control_character_is_handled_end_to_end(monkeypatch):
    """Reproduces the EXACT real production failure with a mocked Gemini
    SDK response (no real API call): "Provider output contained malformed
    JSON: Invalid control character at: line 31 column 148 (char 1641)".
    Gemini had written a multi-line JavaScript snippet into a sub-question
    "prompt" string using a literal newline byte instead of "\\n" - see
    src/generation/llm_utils.py's _escape_raw_control_chars_in_json_strings
    for the fix. This must succeed end-to-end through generate_paper, with
    the code sample's content preserved exactly (real newlines, not
    escaped text, not stripped)."""
    from src.generation.question_generator import generate_paper

    evidence_by_section = {
        "B": [
            {
                "document": "Module 6-Learner Guide.pdf",
                "page": 88,
                "kt_code": "KM-06-KT08",
                "passage": "JavaScript is a lightweight, interpreted programming language used to build interactive web pages.",
                "reason": "Retrieved for KM-06-KT08 (JavaScript)",
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
                "outcomes": ["KM-06-KT08"],
                "competencies": ["JavaScript"],
                "required_outcomes": ["KM-06-KT08"],
                "difficulty": "intermediate",
                "question_types": ["code_analysis"],
                "occupational_context": "Front-end developer reviewing a teammate's code for a client site.",
            }
        ],
    }

    fake_client = MagicMock()
    fake_response = MagicMock()
    # Deliberately contains REAL newline bytes inside the "prompt" string
    # value (between the function body lines) - not the JSON escape "\n" -
    # the exact defect shape from the real failure. Built with an f-string
    # so the literal \n characters below are actual newline bytes in the
    # text sent to json.loads, not the two-character escape sequence.
    fake_response.text = (
        '{"type": "code_analysis", '
        '"scenario": "A developer at Acme Retail reviews a teammate\'s JavaScript function that uses interactive elements.", '
        '"question": "Review the function below.", '
        '"sub_questions": [{"id": "1", "prompt": "Trace through this function:\n'
        "function add(a, b) {\n"
        "  return a + b;\n"
        '}", "marks": 10, "expected_response_type": "trace_table_or_output_list"}], '
        '"outcomes": ["KM-06-KT08"]}'
    )
    fake_client.models.generate_content.return_value = fake_response
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: fake_client)

    provider = GeminiProvider(_settings())
    paper = generate_paper(blueprint, provider, seed=1, evidence_by_section=evidence_by_section)

    prompt_text = paper["sections"][0]["questions"][0]["sub_questions"][0]["prompt"]
    assert "function add(a, b) {" in prompt_text
    assert "return a + b;" in prompt_text
    assert prompt_text.count("\n") == 3


def test_afc_is_explicitly_disabled_since_no_tools_are_ever_used(monkeypatch):
    """Regression test for a real production log line: 'Direct use of
    automatic function calling (AFC) in Models.generate_content is not
    recommended...'. Root cause (confirmed by reading the installed SDK's
    google.genai._extra_utils.should_disable_afc): AFC defaults to enabled
    unless GenerateContentConfig.automatic_function_calling.disable is
    explicitly set - this pipeline never supplies `tools`, so AFC serves no
    purpose here and should be turned off rather than left to warn."""
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.text = '{"ok": true}'
    fake_client.models.generate_content.return_value = fake_response
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: fake_client)

    provider = GeminiProvider(_settings())
    provider.generate("sys", "user", {})

    _, kwargs = fake_client.models.generate_content.call_args
    assert kwargs["config"].automatic_function_calling.disable is True


def test_real_gemini_response_missing_a_required_field_is_handled_end_to_end(monkeypatch):
    """Reproduces the EXACT real production failure with a mocked Gemini
    SDK response (no real API call): a Section-C-shaped design_task
    question whose sub_questions each declare their own
    expected_response_type, but with no top-level 'expected_response_type'
    field - the literal shape a real Gemini call returned, which used to
    raise "provider output missing fields: {'expected_response_type'}".
    """
    from src.generation.question_generator import generate_paper

    evidence_by_section = {
        "B": [
            {
                "document": "Module 6-Learner Guide.pdf",
                "page": 62,
                "kt_code": "KM-06-KT06",
                "passage": "HTML5 introduces new semantic elements such as header footer and section for structuring a page.",
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
                "question_types": ["design_task"],
                "occupational_context": "Front-end developer building a page for a client site.",
            }
        ],
    }

    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.text = (
        '{"type": "design_task", '
        '"scenario": "A developer at Acme Retail models a page using semantic elements such as header and section.", '
        '"question": "Model the following aspects using UML.", '
        '"sub_questions": ['
        '{"id": "1", "prompt": "Describe a class diagram.", "marks": 6, "expected_response_type": "structured_uml_description"}, '
        '{"id": "2", "prompt": "Describe the sequence of messages.", "marks": 4, "expected_response_type": "structured_uml_description"}'
        '], '
        '"outcomes": ["KM-06-KT06"]}'
        # Deliberately no top-level "expected_response_type" - reproduces
        # the exact real Gemini response shape for Section C.
    )
    fake_client.models.generate_content.return_value = fake_response
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: fake_client)

    provider = GeminiProvider(_settings())
    paper = generate_paper(blueprint, provider, seed=1, evidence_by_section=evidence_by_section)

    question = paper["sections"][0]["questions"][0]
    assert question["expected_response_type"] == "structured_uml_description"


def test_missing_sdk_raises_a_clear_provider_error(monkeypatch):
    # Setting a module to None in sys.modules is the standard way to force
    # `import google` (and therefore `from google import genai`) to raise
    # ImportError, simulating an environment where google-genai was never
    # installed - without needing to actually uninstall it for this test.
    monkeypatch.setitem(sys.modules, "google", None)
    monkeypatch.setitem(sys.modules, "google.genai", None)

    with pytest.raises(LLMProviderError, match="google-genai"):
        GeminiProvider(_settings())
