from __future__ import annotations

import copy

from src.validation.marks_validator import validate_marks


def test_valid_paper_and_memo_pass_marks_validation(valid_paper, valid_memo):
    report = validate_marks(valid_paper, valid_memo)
    assert report.passed, [c for c in report.checks if not c.passed]


def test_duplicate_question_ids_fail(valid_paper):
    broken = copy.deepcopy(valid_paper)
    broken["sections"].append(copy.deepcopy(broken["sections"][0]))
    report = validate_marks(broken)
    dup_check = next(c for c in report.checks if c.name == "unique_question_ids")
    assert not dup_check.passed


def test_section_marks_mismatch_fails(valid_paper):
    broken = copy.deepcopy(valid_paper)
    broken["sections"][0]["marks"] = 999
    report = validate_marks(broken)
    check = next(c for c in report.checks if c.name.startswith("section_marks"))
    assert not check.passed


def test_total_marks_mismatch_fails(valid_paper):
    broken = copy.deepcopy(valid_paper)
    broken["total_marks"] = 999
    report = validate_marks(broken)
    check = next(c for c in report.checks if c.name == "total_marks")
    assert not check.passed


def test_memo_marks_not_matching_question_marks_fails(valid_paper, valid_memo):
    broken_memo = copy.deepcopy(valid_memo)
    broken_memo["sections"][0]["questions"][0]["criteria"][0]["marks"] = 999
    report = validate_marks(valid_paper, broken_memo)
    check = next(c for c in report.checks if c.name.startswith("memo_marks_match"))
    assert not check.passed


def test_memo_missing_question_fails(valid_paper, valid_memo):
    broken_memo = copy.deepcopy(valid_memo)
    broken_memo["sections"][0]["questions"] = []
    report = validate_marks(valid_paper, broken_memo)
    check = next(c for c in report.checks if c.name == "memo_question_present:Q-A1")
    assert not check.passed
