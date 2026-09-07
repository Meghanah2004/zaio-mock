from __future__ import annotations

import copy

from src.validation.coverage_validator import validate_coverage


def test_valid_paper_covers_blueprint_outcomes(valid_paper, fake_blueprint):
    report = validate_coverage(valid_paper, fake_blueprint)
    assert report.passed, [c for c in report.checks if not c.passed]


def test_missing_required_outcome_coverage_fails(valid_paper, fake_blueprint):
    broken_blueprint = copy.deepcopy(fake_blueprint)
    broken_blueprint["sections"][0]["outcomes"].append("KM-05-KT02")
    broken_blueprint["sections"][0]["competencies"].append("Software applications")
    broken_blueprint["sections"][0]["required_outcomes"].append("KM-05-KT02")
    report = validate_coverage(valid_paper, broken_blueprint)
    check = next(c for c in report.checks if c.name == "required_outcome_coverage:A")
    assert not check.passed
    assert "KM-05-KT02" in check.details


def test_question_declaring_unrelated_outcome_code_fails_validity(valid_paper, fake_blueprint):
    broken_paper = copy.deepcopy(valid_paper)
    broken_paper["sections"][0]["questions"][0]["outcomes"].append("KM-99-KT99")
    report = validate_coverage(broken_paper, fake_blueprint)
    check = next(c for c in report.checks if c.name == "question_outcome_validity:Q-A1")
    assert not check.passed
    assert "KM-99-KT99" in check.details


def test_competency_not_matching_declared_outcomes_fails(valid_paper, fake_blueprint):
    broken_paper = copy.deepcopy(valid_paper)
    broken_paper["sections"][0]["questions"][0]["competencies"] = ["Some unrelated competency"]
    report = validate_coverage(broken_paper, fake_blueprint)
    check = next(c for c in report.checks if c.name == "question_competency_matches_outcomes:Q-A1")
    assert not check.passed


def test_no_tautology_flagged_when_full_list_equals_required(valid_paper, fake_blueprint):
    """Regression guard for the false-positive direction: when a section's full
    outcome list and its required_outcomes are the same size (nothing was
    left out), a question legitimately covering all of them must NOT be
    flagged as a tautological copy."""
    report = validate_coverage(valid_paper, fake_blueprint)
    check = next(c for c in report.checks if c.name == "no_tautological_full_list_copy:Q-A1")
    assert check.passed


def test_tautological_full_list_copy_is_detected(valid_paper, fake_blueprint_with_slack):
    """This is the regression test for the original bug this fix addresses:
    a question that simply inherits the section's ENTIRE thematic outcome
    list (3 codes) even though only 1 is actually required must be flagged,
    even though it trivially "passes" required-outcome coverage."""
    tautological_paper = copy.deepcopy(valid_paper)
    tautological_paper["sections"][0]["questions"][0]["outcomes"] = [
        "KM-05-KT01",
        "KM-05-KT02",
        "KM-05-KT03",
    ]
    tautological_paper["sections"][0]["questions"][0]["competencies"] = [
        "Programming basics",
        "Software applications",
        "Intro to programming",
    ]
    report = validate_coverage(tautological_paper, fake_blueprint_with_slack)

    tautology_check = next(c for c in report.checks if c.name == "no_tautological_full_list_copy:Q-A1")
    assert not tautology_check.passed

    # It still (correctly) satisfies required-outcome coverage - the bug is
    # specifically that this passing is not evidence of genuine curation.
    required_check = next(c for c in report.checks if c.name == "required_outcome_coverage:A")
    assert required_check.passed


def test_genuinely_curated_subset_is_not_flagged_as_tautological(valid_paper, fake_blueprint_with_slack):
    """The fix must not punish honest, narrow curation: a question covering
    only the required subset (not the full thematic list) must pass."""
    narrow_paper = copy.deepcopy(valid_paper)
    narrow_paper["sections"][0]["questions"][0]["outcomes"] = ["KM-05-KT01"]
    narrow_paper["sections"][0]["questions"][0]["competencies"] = ["Programming basics"]
    report = validate_coverage(narrow_paper, fake_blueprint_with_slack)

    tautology_check = next(c for c in report.checks if c.name == "no_tautological_full_list_copy:Q-A1")
    assert tautology_check.passed
    required_check = next(c for c in report.checks if c.name == "required_outcome_coverage:A")
    assert required_check.passed


def test_duplicate_outcome_codes_do_not_fake_multi_outcome_coverage(valid_paper, fake_blueprint_with_slack):
    """A question that lists the same outcome code twice must not appear to
    cover two DIFFERENT required outcomes - coverage is a set union, not a
    count, so the second, genuinely-uncovered required outcome must still
    be reported as missing."""
    blueprint = copy.deepcopy(fake_blueprint_with_slack)
    blueprint["sections"][0]["required_outcomes"] = ["KM-05-KT01", "KM-05-KT02"]

    paper = copy.deepcopy(valid_paper)
    paper["sections"][0]["questions"][0]["outcomes"] = ["KM-05-KT01", "KM-05-KT01"]

    report = validate_coverage(paper, blueprint)
    check = next(c for c in report.checks if c.name == "required_outcome_coverage:A")
    assert not check.passed
    assert "KM-05-KT02" in check.details


def test_wrong_question_count_fails(valid_paper, fake_blueprint):
    broken_blueprint = copy.deepcopy(fake_blueprint)
    broken_blueprint["sections"][0]["questions_planned"] = 2
    report = validate_coverage(valid_paper, broken_blueprint)
    check = next(c for c in report.checks if c.name == "question_count:A")
    assert not check.passed


def test_empty_question_text_fails(valid_paper, fake_blueprint):
    broken = copy.deepcopy(valid_paper)
    broken["sections"][0]["questions"][0]["question"] = "   "
    report = validate_coverage(broken, fake_blueprint)
    check = next(c for c in report.checks if c.name == "no_empty_or_malformed_fields")
    assert not check.passed


def test_duplicate_question_text_detected(valid_paper, fake_blueprint):
    broken = copy.deepcopy(valid_paper)
    dup_section = copy.deepcopy(broken["sections"][0])
    dup_section["id"] = "B"
    dup_section["questions"][0]["id"] = "Q-B1"
    broken["sections"].append(dup_section)
    report = validate_coverage(broken, fake_blueprint)
    check = next(c for c in report.checks if c.name == "no_duplicate_question_text")
    assert not check.passed


def test_false_official_status_claim_detected(valid_paper, fake_blueprint):
    broken = copy.deepcopy(valid_paper)
    broken["sections"][0]["questions"][0]["question"] += " This is an official EISA question."
    report = validate_coverage(broken, fake_blueprint)
    check = next(c for c in report.checks if c.name == "no_false_official_status_claims")
    assert not check.passed


def test_missing_status_disclaimer_wording_fails(valid_paper, fake_blueprint):
    broken = copy.deepcopy(valid_paper)
    broken["status_disclaimer"] = "This is a fine assessment."
    report = validate_coverage(broken, fake_blueprint)
    check = next(c for c in report.checks if c.name == "status_disclaimer_present")
    assert not check.passed
