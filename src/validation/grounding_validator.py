"""Independent, deterministic re-check of a paper's learner-guide grounding.

This is the "validation must be independent" half of the grounding
contract: src/generation/question_generator.py already enforces grounding
AT GENERATION TIME (rejecting/regenerating an ungrounded question before it
ever reaches the paper), but this module re-derives the same judgement from
scratch, purely from the finished paper JSON plus the ingested corpus -
exactly like marks_validator/coverage_validator re-check things
question_generator.py already enforced once. It never trusts a
generation-time "this passed" flag; it recomputes.

Three checks per question, all deterministic (no LLM):
  1. grounding_present - every question must carry a non-empty ``grounding``
     provenance list (document/page/passage/reason per citation).
  2. grounding_pages_exist - every cited (document, page) pair must actually
     exist in the ingested corpus (src/analysis/reference_analyzer.
     extract_corpus_chunks output) - this is the concrete "do not fabricate
     page numbers" check.
  3. grounding_overlap_in_range - the question's own text must share
     enough vocabulary with its cited evidence to plausibly be DERIVED from
     it (not pure invention), but not so much that it reads as a
     near-verbatim copy of a single passage (not a transformation).
"""
from __future__ import annotations

from typing import Any

from src.retrieval.text_similarity import cosine_similarity
from src.security.config import SecurityConfig
from src.validation.types import CheckResult, ValidationReport


def _question_text(q: dict[str, Any]) -> str:
    parts = [q.get("scenario") or "", q.get("question", "")]
    parts.extend(sq.get("prompt", "") for sq in q.get("sub_questions", []))
    return " ".join(parts)


def validate_grounding(
    paper: dict[str, Any],
    corpus_chunks: list[dict[str, Any]],
    security_config: SecurityConfig | None = None,
) -> ValidationReport:
    """Independently re-check grounding for every question in ``paper``.

    ``paper["generation_meta"]["grounded"]`` (set by
    src/generation/question_generator.generate_paper whenever it was called
    with real retrieved evidence - i.e. REAL GENERATION MODE, see that
    module's docstring) decides whether a missing ``grounding`` list is a
    hard failure or merely informational:
      - grounded paper: every question MUST carry non-empty grounding - the
        whole point of this rework - so a missing one is a real defect.
      - non-grounded paper (TEST MODE, or the API layer, which - per Phase 1
        scope - does not perform retrieval; see docs/DESIGN.md and
        api/service.py): a missing grounding list is expected, not a defect,
        and is recorded as a passing/informational check rather than failing
        validation for a code path that never claimed to be grounded.
    """
    security_config = security_config or SecurityConfig()
    report = ValidationReport.empty()
    valid_pages = {(c["source"], c["page"]) for c in corpus_chunks if "page" in c}
    grounded_mode = bool(paper.get("generation_meta", {}).get("grounded"))

    for section in paper["sections"]:
        for q in section["questions"]:
            grounding = q.get("grounding") or []
            if not grounding:
                report.add(
                    CheckResult(
                        f"grounding_present:{q['id']}",
                        not grounded_mode,
                        "question carries no grounding/provenance"
                        if grounded_mode
                        else "no grounding recorded - paper was not generated in grounded mode (expected for API/test-mode runs)",
                    )
                )
                continue
            report.add(CheckResult(f"grounding_present:{q['id']}", True, f"{len(grounding)} evidence citation(s)"))

            bad_citations = [
                f"{g.get('document')} p.{g.get('page')}"
                for g in grounding
                if (g.get("document"), g.get("page")) not in valid_pages
            ]
            report.add(
                CheckResult(
                    f"grounding_pages_exist:{q['id']}",
                    not bad_citations,
                    "ok"
                    if not bad_citations
                    else f"cited page(s) not found in the ingested corpus - possible fabrication: {bad_citations}",
                )
            )

            question_text = _question_text(q)
            evidence_text = " ".join(g.get("passage", "") for g in grounding)
            overlap = cosine_similarity(question_text, evidence_text)
            min_ok = overlap >= security_config.grounding_min_overlap
            report.add(
                CheckResult(
                    f"grounding_overlap_sufficient:{q['id']}",
                    min_ok,
                    f"overlap={overlap:.3f} (minimum {security_config.grounding_min_overlap}) - "
                    + ("ok" if min_ok else "question text shows little relation to its cited evidence"),
                )
            )

            max_single = max((cosine_similarity(question_text, g.get("passage", "")) for g in grounding), default=0.0)
            not_copied = max_single <= security_config.grounding_max_overlap
            report.add(
                CheckResult(
                    f"grounding_not_near_copy:{q['id']}",
                    not_copied,
                    f"max single-passage overlap={max_single:.3f} (maximum {security_config.grounding_max_overlap}) - "
                    + (
                        "ok"
                        if not_copied
                        else "question text is too close to one cited passage - reads as copied, not transformed"
                    ),
                )
            )

    return report
