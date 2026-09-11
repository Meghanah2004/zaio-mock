"""Runs every deterministic validator (plus the novelty screen) in the
fixed order the project always applies them in: schema -> marks ->
coverage -> novelty.

Extracted from ``src/cli.py`` (where it was a private, CLI-only helper) so
the API layer can run the exact same validation sequence against the exact
same functions, rather than re-implementing or duplicating this
orchestration - see docs/API.md, "Reuse over duplication."
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.validation.answer_grounding_validator import validate_answer_grounding
from src.validation.coverage_validator import validate_coverage
from src.validation.grounding_validator import validate_grounding
from src.validation.marks_validator import validate_marks
from src.validation.novelty_checker import ReferenceCorpusIndex, check_paper_novelty
from src.validation.schema_validator import validate_memo_schema, validate_paper_schema
from src.validation.types import CheckResult, ValidationReport


def run_all_validators(
    paper: dict[str, Any],
    memo: dict[str, Any],
    blueprint: dict[str, Any] | None,
    corpus_chunks_path: Path | None = None,
) -> tuple[ValidationReport, dict[str, Any] | None]:
    """Returns (deterministic ValidationReport, novelty result or None).

    ``corpus_chunks_path`` points at the cached novelty corpus written by
    the ``analyze`` step (``artifacts/reference-corpus-chunks.json``); the
    novelty check is skipped (not failed) if it doesn't exist yet, matching
    prior CLI behaviour.
    """
    report = ValidationReport.empty()

    schema_result = validate_paper_schema(paper)
    report.add(schema_result)
    memo_schema_result = validate_memo_schema(memo)
    report.add(memo_schema_result)

    if not schema_result.passed or not memo_schema_result.passed:
        # Structural failure: marks/coverage checks assume schema-valid shape,
        # so stop here rather than raising confusing KeyErrors downstream.
        return report, None

    marks_report = validate_marks(paper, memo)
    for c in marks_report.checks:
        report.add(c)

    if blueprint is not None:
        coverage_report = validate_coverage(paper, blueprint)
        for c in coverage_report.checks:
            report.add(c)

    novelty_result = None
    if corpus_chunks_path is not None and corpus_chunks_path.exists():
        chunks = json.loads(corpus_chunks_path.read_text(encoding="utf-8"))
        thresholds = (blueprint or {}).get("novelty_thresholds", {"warn": 0.35, "flag": 0.55})
        index = ReferenceCorpusIndex(chunks)
        novelty_result = check_paper_novelty(paper, index, thresholds["warn"], thresholds["flag"])
        report.add(
            CheckResult(
                "novelty_screening",
                novelty_result["overall_status"] != "regenerate",
                f"overall_status={novelty_result['overall_status']} (see validation-report.json for per-question scores)",
            )
        )

        # Independent re-check of learner-guide grounding, from scratch,
        # against the finished paper JSON + the ingested corpus - never
        # trusts that question_generator.py's generation-time grounding
        # check ran or passed (see src/validation/grounding_validator.py).
        grounding_report = validate_grounding(paper, chunks)
        for c in grounding_report.checks:
            report.add(c)

        # REWORK (real-generation audit, 2026-09-11): answer_grounding_
        # validator.py existed and was tested in isolation but was never
        # actually invoked here - the ANSWER side of grounding had no
        # independent deterministic re-check in the real pipeline, only
        # src.generation.memo_generator's generation-time self-check
        # (_answer_grounding_ok). Same gating as question-side grounding
        # immediately above (needs the same ingested corpus chunks), same
        # "never trust the generation-time check alone" principle.
        answer_grounding_report = validate_answer_grounding(memo, chunks)
        for c in answer_grounding_report.checks:
            report.add(c)

    return report, novelty_result
