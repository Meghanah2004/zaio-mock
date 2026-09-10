"""Regression tests for a real production failure: a real Gemini call
returned "Provider output contained malformed JSON: Invalid control
character at: line 31 column 148 (char 1641)".

Root cause: Gemini wrote a multi-line code sample into a JSON string value
(a sub-question "prompt") using a literal newline BYTE instead of the
two-character JSON escape "\\n". RFC 8259 requires every control character
(U+0000-U+001F) inside a JSON string literal to be escaped; Python's
``json`` module correctly rejects the raw byte. This is a real, observed
LLM output defect, not a hypothetical edge case.

The fix in src/generation/llm_utils.py (_escape_raw_control_chars_in_json_
strings, _parse_json_object) is a targeted, single-pass normalization that
ONLY rewrites a raw control character found INSIDE a string literal into
its JSON escape sequence - never touching structural JSON whitespace
outside strings, and never accepting a document broken for any other
reason (a genuinely truncated/malformed document must still raise).
"""
from __future__ import annotations

import json

import pytest

from src.generation.llm_utils import (
    GenerationError,
    _escape_raw_control_chars_in_json_strings,
    extract_json,
)


def test_extract_json_handles_a_raw_newline_inside_a_string_value():
    """Reproduces the exact real failure shape: a multi-line code sample
    pasted into a string value with a literal newline byte instead of the
    JSON escape "\\n"."""
    raw = (
        '{"type": "code_writing", "question": "Refactor this.", '
        '"sub_questions": [{"id": "1", "prompt": "Fix this snippet:\n'
        'function add(a, b) {\n'
        '  return a + b;\n'
        '}", "marks": 10, "expected_response_type": "javascript_code"}], '
        '"expected_response_type": "javascript_code", "outcomes": ["KM-06-KT08"]}'
    )
    # Sanity: this is genuinely invalid per strict JSON, matching the real
    # production error - confirms the test fixture reproduces the actual bug.
    with pytest.raises(json.JSONDecodeError, match="Invalid control character"):
        json.loads(raw)

    parsed = extract_json(raw)

    prompt_text = parsed["sub_questions"][0]["prompt"]
    assert "function add(a, b) {" in prompt_text
    assert "return a + b;" in prompt_text
    # Lossless round-trip: the recovered content has real newlines - the
    # exact same characters Gemini intended - not escaped literal "\n" text
    # and not stripped/altered.
    assert prompt_text.count("\n") == 3


def test_extract_json_handles_tab_and_other_control_characters_inside_strings():
    raw = '{"type": "short_answer", "question": "Column1\tColumn2\x01End", "expected_response_type": "short_answer", "outcomes": ["KM-05-KT01"]}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)

    parsed = extract_json(raw)
    assert parsed["question"] == "Column1\tColumn2\x01End"


def test_extract_json_with_markdown_fences_and_a_raw_control_character():
    """Requirement: markdown-fenced JSON must also be handled - the fence
    stripping and control-character normalization must compose correctly."""
    raw = (
        "```json\n"
        '{"type": "code_writing", "question": "Trace this:\nprint(1)\nprint(2)", '
        '"expected_response_type": "trace_table", "outcomes": ["KM-05-KT01"]}\n'
        "```"
    )
    parsed = extract_json(raw)
    assert parsed["question"] == "Trace this:\nprint(1)\nprint(2)"


def test_extract_json_still_rejects_genuinely_malformed_json():
    """The fix must NOT paper over a document broken for any other reason
    (requirement: do not simply catch the exception and accept malformed
    output) - a missing colon is not a control-character defect and must
    still raise, even though the braces are balanced."""
    raw = '{"type": "short_answer" "question": "missing the colon above"}'
    with pytest.raises(GenerationError, match="malformed JSON"):
        extract_json(raw)


def test_extract_json_with_no_closing_brace_at_all_is_rejected_not_invented():
    raw = '{"type": "short_answer", "question": "Unterminated'
    with pytest.raises(GenerationError, match="did not contain a JSON object"):
        extract_json(raw)


def test_extract_json_still_rejects_a_trailing_comma():
    raw = '{"type": "short_answer", "question": "Q?",}'
    with pytest.raises(GenerationError, match="malformed JSON"):
        extract_json(raw)


def test_malformed_json_error_includes_a_diagnostic_snippet_of_the_failing_text():
    """Regression test for a real production incident: a real Groq response
    failed to parse with only "Provider output contained malformed JSON:
    Expecting ',' delimiter: line 69 column 10 (char 4496)" ever recorded -
    server logs (see api/errors.handle_generation_error, which logs
    str(GenerationError) but never sends it to the client) had no way to
    show what the model had actually produced, so diagnosing it required
    paying for a fresh real API call to try to reproduce it. The error must
    now carry a bounded snippet of the actual text around the failure
    position, not just the parser's position-only message."""
    # A missing comma between two fields, deep enough into the document
    # that a snippet must be taken from AROUND the failure, not just from
    # the start of the string, to be useful - the same shape as the real
    # incident (a field boundary defect found far into a long response).
    padding = '"padding' + str(list(range(200))) + '": "x", '
    raw = '{' + padding + '"a": "value1" "b": "value2"}'
    with pytest.raises(GenerationError) as exc_info:
        extract_json(raw)
    message = str(exc_info.value)
    assert "malformed JSON" in message
    assert "Context around the failure" in message
    # The snippet must actually contain real text from around the defect
    # (the two adjacent string values missing their separating comma),
    # not just the parser's position-only message repeated.
    assert '"a": "value1" "b": "value2"' in message


def test_extract_json_raises_when_no_json_object_present_at_all():
    with pytest.raises(GenerationError, match="did not contain a JSON object"):
        extract_json("Sure, here is your answer in plain prose, no JSON at all.")


def test_escape_raw_control_chars_leaves_structural_whitespace_outside_strings_untouched():
    """Control characters OUTSIDE any string literal (e.g. real newlines
    between object members in pretty-printed JSON) are already legal JSON
    there - the sanitizer must not rewrite them, only what is illegal."""
    pretty = '{\n  "a": "line1\nline2",\n  "b": 1\n}'
    sanitized = _escape_raw_control_chars_in_json_strings(pretty)

    # The structural newlines/indentation between "a" and "b" are unchanged...
    assert '"a": "line1\\nline2",\n  "b": 1' in sanitized
    # ...while the ONE newline that was illegally raw inside the "a" string
    # value has been converted to its escape sequence.
    assert "line1\\nline2" in sanitized
    assert json.loads(sanitized) == {"a": "line1\nline2", "b": 1}


def test_escape_raw_control_chars_does_not_double_escape_an_already_valid_escape():
    already_valid = '{"a": "line1\\nline2"}'
    # Already strictly valid JSON - json.loads succeeds on the first try,
    # so the sanitizer is never even invoked for this input.
    assert extract_json(already_valid) == {"a": "line1\nline2"}


def test_escape_raw_control_chars_does_not_break_escaped_quotes_or_backslashes():
    raw = '{"a": "she said \\"hi\\" then a backslash \\\\ then a raw\nnewline"}'
    parsed = extract_json(raw)
    assert parsed["a"] == 'she said "hi" then a backslash \\ then a raw\nnewline'
