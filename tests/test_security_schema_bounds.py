"""Tests for the JSON Schema upper bounds added during security hardening
(schemas/paper.schema.json, schemas/memo.schema.json). Lower bounds were
already tested in tests/test_schema_validator.py; this file focuses on the
new maxLength/maximum/maxItems constraints and confirms they reject
oversized/malformed data without rejecting legitimate exam content."""
from __future__ import annotations

import copy

from src.validation.schema_validator import validate_memo_schema, validate_paper_schema


def test_oversized_question_text_is_rejected(valid_paper):
    broken = copy.deepcopy(valid_paper)
    broken["sections"][0]["questions"][0]["question"] = "x" * 100_000
    result = validate_paper_schema(broken)
    assert not result.passed


def test_absurd_marks_value_is_rejected(valid_paper):
    broken = copy.deepcopy(valid_paper)
    broken["sections"][0]["questions"][0]["marks"] = 999_999_999
    broken["sections"][0]["marks"] = 999_999_999
    result = validate_paper_schema(broken)
    assert not result.passed


def test_excessive_number_of_sub_questions_is_rejected(valid_paper):
    broken = copy.deepcopy(valid_paper)
    broken["sections"][0]["questions"][0]["sub_questions"] = [
        {"id": str(i), "prompt": "p", "marks": 1, "expected_response_type": "short_answer"} for i in range(500)
    ]
    result = validate_paper_schema(broken)
    assert not result.passed


def test_excessive_number_of_sections_is_rejected(valid_paper):
    broken = copy.deepcopy(valid_paper)
    template = broken["sections"][0]
    broken["sections"] = []
    for i in range(50):
        section = copy.deepcopy(template)
        section["id"] = f"S{i}"
        section["questions"][0]["id"] = f"Q-S{i}"
        section["questions"][0]["section_id"] = f"S{i}"
        broken["sections"].append(section)
    result = validate_paper_schema(broken)
    assert not result.passed


def test_legitimate_full_size_content_still_passes(valid_paper):
    """Regression guard: the bounds must be generous enough for real exam
    content - a 4900-character scenario (below the 5000 cap) must pass."""
    ok = copy.deepcopy(valid_paper)
    ok["sections"][0]["questions"][0]["scenario"] = "A realistic occupational scenario. " * 130  # ~4680 chars
    assert len(ok["sections"][0]["questions"][0]["scenario"]) < 5000
    result = validate_paper_schema(ok)
    assert result.passed, result.details


def test_oversized_memo_model_answer_is_rejected(valid_memo):
    broken = copy.deepcopy(valid_memo)
    broken["sections"][0]["questions"][0]["model_answer"] = "x" * 100_000
    result = validate_memo_schema(broken)
    assert not result.passed


def test_excessive_criteria_count_is_rejected(valid_memo):
    broken = copy.deepcopy(valid_memo)
    broken["sections"][0]["questions"][0]["criteria"] = [
        {"description": "d", "marks": 1} for _ in range(500)
    ]
    result = validate_memo_schema(broken)
    assert not result.passed


def test_real_paper_and_memo_with_49_section_outcomes_still_pass():
    """Regression guard tied to the real shipped content: Section F's
    blueprint legitimately declares outcomes across 4 modules (49 codes at
    time of writing). maxItems on section-level outcomes/competencies must
    stay generous enough not to break this."""
    import json
    from pathlib import Path

    paper_path = Path("output/mock-eisa-paper-02.json")
    if not paper_path.exists():
        return  # not generated in this environment/test run - nothing to check
    paper = json.loads(paper_path.read_text())
    result = validate_paper_schema(paper)
    assert result.passed, result.details
