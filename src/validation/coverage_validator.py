"""Blueprint coverage, structural completeness, and basic consistency checks.

Covers checklist items: ELO/outcome coverage (checked structurally from
question-level outcome declarations, never assumed from a section's full
thematic list - see _check_outcome_and_competency_coverage), missing
questions, empty/malformed fields, invalid enum values (defense-in-depth on
top of JSON Schema), duplicate content, and basic occupational-relevance /
official-status consistency checks.
"""
from __future__ import annotations

import re
from typing import Any

from src.validation.types import CheckResult, ValidationReport

_OFFICIAL_CLAIM_RE = re.compile(
    r"\bofficial\s+(EISA|QCTO|exam(ination)?|assessment instrument)\b", re.IGNORECASE
)


def _check_outcome_and_competency_coverage(paper: dict[str, Any], blueprint: dict[str, Any], report: ValidationReport) -> None:
    """Structural outcome-coverage checks.

    Deliberately does NOT trust a section's full `outcomes` list as "what
    was tested" - that list documents thematic scope only. Instead:

      1. Every question's declared `outcomes` must be a subset of its
         section's full outcome universe (no hallucinated/unrelated codes).
      2. Every question's declared `competencies` must be exactly the
         titles corresponding to its declared `outcomes` (no drift between
         the two parallel fields).
      3. A question must NOT simply restate the section's entire outcome
         list when that list is broader than what's actually required -
         this is the specific regression guard against the old
         tautological-coverage bug, where a question's outcomes were a
         blind copy of the section's full list regardless of content.
      4. The UNION of outcomes across all of a section's questions must
         cover the blueprint's `required_outcomes` for that section - this
         is the real "is the required coverage actually present" check,
         computed from question-level declarations, never assumed.
    """
    blueprint_sections = {s["id"]: s for s in blueprint["sections"]}
    for section in paper["sections"]:
        bp_section = blueprint_sections.get(section["id"])
        if bp_section is None:
            report.add(CheckResult(f"blueprint_section_exists:{section['id']}", False, "section not in blueprint"))
            continue

        full_outcomes = set(bp_section["outcomes"])
        required_outcomes = set(bp_section.get("required_outcomes", bp_section["outcomes"]))
        outcome_title_map = dict(zip(bp_section["outcomes"], bp_section["competencies"]))

        touched_outcomes: set[str] = set()
        for q in section["questions"]:
            q_outcomes = set(q.get("outcomes", []))
            q_competencies = set(q.get("competencies", []))

            hallucinated = q_outcomes - full_outcomes
            report.add(
                CheckResult(
                    f"question_outcome_validity:{q['id']}",
                    not hallucinated,
                    (
                        f"question declares outcomes outside its section's outcome universe: "
                        f"{sorted(hallucinated)}"
                    )
                    if hallucinated
                    else "ok",
                )
            )

            expected_competencies = {outcome_title_map[c] for c in q_outcomes if c in outcome_title_map}
            report.add(
                CheckResult(
                    f"question_competency_matches_outcomes:{q['id']}",
                    q_competencies == expected_competencies,
                    "ok"
                    if q_competencies == expected_competencies
                    else (
                        f"declared competencies {sorted(q_competencies)} do not exactly match the "
                        f"titles of declared outcomes {sorted(expected_competencies)}"
                    ),
                )
            )

            looks_like_full_list_copy = len(full_outcomes) > len(required_outcomes) and q_outcomes == full_outcomes
            report.add(
                CheckResult(
                    f"no_tautological_full_list_copy:{q['id']}",
                    not looks_like_full_list_copy,
                    (
                        f"question's outcomes are IDENTICAL to the section's entire thematic outcome "
                        f"list ({len(full_outcomes)} codes) even though only {len(required_outcomes)} "
                        f"are required - this is the exact tautological-coverage pattern this check "
                        f"exists to catch; the outcomes list must be genuinely curated, not copied."
                    )
                    if looks_like_full_list_copy
                    else "ok",
                )
            )

            touched_outcomes |= q_outcomes

        missing_required = required_outcomes - touched_outcomes
        report.add(
            CheckResult(
                f"required_outcome_coverage:{section['id']}",
                not missing_required,
                f"missing required outcomes (not covered by any question): {sorted(missing_required)}"
                if missing_required
                else f"all {len(required_outcomes)} required outcomes are covered by at least one question",
            )
        )


def _check_section_question_counts(paper: dict[str, Any], blueprint: dict[str, Any], report: ValidationReport) -> None:
    blueprint_sections = {s["id"]: s for s in blueprint["sections"]}
    paper_section_ids = {s["id"] for s in paper["sections"]}
    blueprint_section_ids = {s["id"] for s in blueprint["sections"]}
    missing_sections = blueprint_section_ids - paper_section_ids
    report.add(
        CheckResult(
            "no_missing_sections",
            not missing_sections,
            f"blueprint sections absent from paper: {sorted(missing_sections)}" if missing_sections else "ok",
        )
    )
    for section in paper["sections"]:
        expected_count = blueprint_sections.get(section["id"], {}).get("questions_planned")
        if expected_count is None:
            continue
        actual = len(section["questions"])
        report.add(
            CheckResult(
                f"question_count:{section['id']}",
                actual == expected_count,
                f"expected {expected_count} question(s), found {actual}",
            )
        )


def _check_empty_or_malformed_fields(paper: dict[str, Any], report: ValidationReport) -> None:
    problems: list[str] = []
    for section in paper["sections"]:
        for q in section["questions"]:
            if not q.get("question", "").strip():
                problems.append(f"{q['id']}: empty question text")
            for sq in q.get("sub_questions", []):
                if not sq.get("prompt", "").strip():
                    problems.append(f"{q['id']}.{sq.get('id')}: empty sub-question prompt")
                if not isinstance(sq.get("marks"), int) or sq["marks"] <= 0:
                    problems.append(f"{q['id']}.{sq.get('id')}: invalid marks value")
    report.add(CheckResult("no_empty_or_malformed_fields", not problems, "; ".join(problems) if problems else "ok"))


def _check_duplicate_question_text(paper: dict[str, Any], report: ValidationReport) -> None:
    seen: dict[str, str] = {}
    dupes = []
    for section in paper["sections"]:
        for q in section["questions"]:
            key = re.sub(r"\s+", " ", q["question"].strip().lower())
            if key in seen:
                dupes.append((seen[key], q["id"]))
            seen[key] = q["id"]
    report.add(
        CheckResult(
            "no_duplicate_question_text",
            not dupes,
            f"duplicate question text between: {dupes}" if dupes else "ok",
        )
    )


def _check_official_status_claims(paper: dict[str, Any], report: ValidationReport) -> None:
    disclaimer_ok = "mock" in paper.get("status_disclaimer", "").lower() or "practice" in paper.get(
        "status_disclaimer", ""
    ).lower()
    report.add(
        CheckResult(
            "status_disclaimer_present",
            disclaimer_ok,
            "status_disclaimer clearly states mock/practice status" if disclaimer_ok else "status_disclaimer missing mock/practice wording",
        )
    )

    offending: list[str] = []
    for section in paper["sections"]:
        for q in section["questions"]:
            text = " ".join(filter(None, [q.get("scenario"), q.get("question")]))
            if _OFFICIAL_CLAIM_RE.search(text):
                offending.append(q["id"])
    report.add(
        CheckResult(
            "no_false_official_status_claims",
            not offending,
            f"questions claiming official EISA/QCTO status: {offending}" if offending else "ok",
        )
    )


def _check_basic_occupational_relevance(paper: dict[str, Any], report: ValidationReport) -> None:
    missing_context = []
    for section in paper["sections"]:
        for q in section["questions"]:
            has_context = bool(q.get("scenario")) or len(q.get("question", "")) > 40
            if not has_context:
                missing_context.append(q["id"])
    report.add(
        CheckResult(
            "basic_occupational_relevance",
            not missing_context,
            f"questions with no scenario and a very short stem (heuristic check only): {missing_context}"
            if missing_context
            else "every question has scenario context or a substantive stem",
        )
    )


def validate_coverage(paper: dict[str, Any], blueprint: dict[str, Any]) -> ValidationReport:
    report = ValidationReport.empty()
    _check_outcome_and_competency_coverage(paper, blueprint, report)
    _check_section_question_counts(paper, blueprint, report)
    _check_empty_or_malformed_fields(paper, report)
    _check_duplicate_question_text(paper, report)
    _check_official_status_claims(paper, report)
    _check_basic_occupational_relevance(paper, report)
    return report
