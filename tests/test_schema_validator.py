from __future__ import annotations

import copy

from src.validation.schema_validator import validate_memo_schema, validate_paper_schema


def test_valid_paper_passes_schema(valid_paper):
    result = validate_paper_schema(valid_paper)
    assert result.passed, result.details


def test_valid_memo_passes_schema(valid_memo):
    result = validate_memo_schema(valid_memo)
    assert result.passed, result.details


def test_paper_missing_required_field_fails_schema(valid_paper):
    broken = copy.deepcopy(valid_paper)
    del broken["total_marks"]
    result = validate_paper_schema(broken)
    assert not result.passed


def test_paper_invalid_difficulty_enum_fails_schema(valid_paper):
    broken = copy.deepcopy(valid_paper)
    broken["sections"][0]["difficulty"] = "impossible"
    result = validate_paper_schema(broken)
    assert not result.passed


def test_memo_missing_criteria_fails_schema(valid_memo):
    broken = copy.deepcopy(valid_memo)
    del broken["sections"][0]["questions"][0]["criteria"]
    result = validate_memo_schema(broken)
    assert not result.passed
