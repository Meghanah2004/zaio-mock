"""Deterministic mark-arithmetic and paper/memo-consistency checks.

Covers checklist items: unique question/section IDs, total paper marks,
section mark totals, question/sub-question mark totals, memo coverage, and
memo marks matching exam marks.
"""
from __future__ import annotations

from typing import Any

from src.validation.types import CheckResult, ValidationReport


def _check_unique_ids(paper: dict[str, Any], report: ValidationReport) -> None:
    section_ids = [s["id"] for s in paper["sections"]]
    dupes = {x for x in section_ids if section_ids.count(x) > 1}
    report.add(CheckResult("unique_section_ids", not dupes, f"duplicates: {dupes}" if dupes else "ok"))

    question_ids = [q["id"] for s in paper["sections"] for q in s["questions"]]
    dupes_q = {x for x in question_ids if question_ids.count(x) > 1}
    report.add(CheckResult("unique_question_ids", not dupes_q, f"duplicates: {dupes_q}" if dupes_q else "ok"))


def _check_total_marks(paper: dict[str, Any], report: ValidationReport) -> None:
    section_sum = sum(s["marks"] for s in paper["sections"])
    ok = section_sum == paper["total_marks"]
    report.add(
        CheckResult(
            "total_marks",
            ok,
            f"declared total_marks={paper['total_marks']}, sum of section marks={section_sum}",
        )
    )


def _check_section_marks(paper: dict[str, Any], report: ValidationReport) -> None:
    for section in paper["sections"]:
        q_sum = sum(q["marks"] for q in section["questions"])
        ok = q_sum == section["marks"]
        report.add(
            CheckResult(
                f"section_marks:{section['id']}",
                ok,
                f"section marks={section['marks']}, sum of question marks={q_sum}",
            )
        )


def _check_question_subquestion_marks(paper: dict[str, Any], report: ValidationReport) -> None:
    for section in paper["sections"]:
        for q in section["questions"]:
            subs = q.get("sub_questions")
            if not subs:
                continue
            sub_sum = sum(sq["marks"] for sq in subs)
            ok = sub_sum == q["marks"]
            report.add(
                CheckResult(
                    f"question_subquestion_marks:{q['id']}",
                    ok,
                    f"question marks={q['marks']}, sum of sub_question marks={sub_sum}",
                )
            )


def _check_memo_coverage_and_marks(paper: dict[str, Any], memo: dict[str, Any], report: ValidationReport) -> None:
    memo_sections = {s["id"]: s for s in memo["sections"]}
    all_question_ids = {q["id"] for s in paper["sections"] for q in s["questions"]}
    memo_question_ids: set[str] = set()

    for section in paper["sections"]:
        memo_section = memo_sections.get(section["id"])
        if memo_section is None:
            report.add(CheckResult(f"memo_section_present:{section['id']}", False, "no matching memo section"))
            continue
        report.add(CheckResult(f"memo_section_present:{section['id']}", True, "ok"))

        memo_questions = {mq["question_id"]: mq for mq in memo_section["questions"]}
        for q in section["questions"]:
            memo_question_ids.add(q["id"])
            mq = memo_questions.get(q["id"])
            if mq is None:
                report.add(CheckResult(f"memo_question_present:{q['id']}", False, "no matching memo question"))
                continue
            report.add(CheckResult(f"memo_question_present:{q['id']}", True, "ok"))

            if q.get("sub_questions"):
                memo_subs = {msq["id"]: msq for msq in mq.get("sub_questions", [])}
                expected = {sq["id"] for sq in q["sub_questions"]}
                missing = expected - memo_subs.keys()
                report.add(
                    CheckResult(
                        f"memo_subquestion_coverage:{q['id']}",
                        not missing,
                        f"missing memo sub-questions: {missing}" if missing else "ok",
                    )
                )
                for sq in q["sub_questions"]:
                    msq = memo_subs.get(sq["id"])
                    if msq is None:
                        continue
                    criteria_sum = sum(c["marks"] for c in msq["criteria"])
                    ok = criteria_sum == sq["marks"]
                    report.add(
                        CheckResult(
                            f"memo_marks_match:{q['id']}.{sq['id']}",
                            ok,
                            f"question sub-mark={sq['marks']}, memo criteria sum={criteria_sum}",
                        )
                    )
            else:
                criteria_sum = sum(c["marks"] for c in mq["criteria"])
                ok = criteria_sum == q["marks"] and mq["total_marks"] == q["marks"]
                report.add(
                    CheckResult(
                        f"memo_marks_match:{q['id']}",
                        ok,
                        f"question marks={q['marks']}, memo criteria sum={criteria_sum}, "
                        f"memo total_marks={mq['total_marks']}",
                    )
                )

    orphan_memo_questions = memo_question_ids and (
        {mq["question_id"] for s in memo["sections"] for mq in s["questions"]} - all_question_ids
    )
    if orphan_memo_questions:
        report.add(
            CheckResult("memo_no_orphan_questions", False, f"memo has questions not in paper: {orphan_memo_questions}")
        )
    else:
        report.add(CheckResult("memo_no_orphan_questions", True, "ok"))

    total_ok = memo["total_marks"] == paper["total_marks"]
    report.add(
        CheckResult(
            "memo_total_marks_match_paper",
            total_ok,
            f"paper total_marks={paper['total_marks']}, memo total_marks={memo['total_marks']}",
        )
    )


def validate_marks(paper: dict[str, Any], memo: dict[str, Any] | None = None) -> ValidationReport:
    report = ValidationReport.empty()
    _check_unique_ids(paper, report)
    _check_total_marks(paper, report)
    _check_section_marks(paper, report)
    _check_question_subquestion_marks(paper, report)
    if memo is not None:
        _check_memo_coverage_and_marks(paper, memo, report)
    return report
