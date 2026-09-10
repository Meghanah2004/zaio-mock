"""Independent, deterministic re-check of a memo's ANSWER-side grounding.

src/validation/grounding_validator.py answers "was this QUESTION derived
from real learner-guide evidence." This module answers the other half of
the same requirement: "was this ANSWER (the memo's model_answer content)
derived from real learner-guide evidence, not the model's own unsupported
general knowledge." Both are independently re-derived from the finished
JSON plus the ingested corpus - this module never trusts that
src.generation.memo_generator's generation-time check
(_answer_grounding_ok) ran or passed, exactly like grounding_validator.py
never trusts question_generator.py's generation-time check.

Checks performed, all deterministic (no LLM call):
  1. answer_grounding_present - every question's memo entry must carry a
     non-empty ``grounding`` provenance list (same shape as question-side
     grounding: document/page/passage/reason per citation).
  2. answer_grounding_pages_exist - every cited (document, page) pair must
     actually exist in the ingested corpus - "do not fabricate page
     numbers," same as the question side.
  3. answer_grounding_overlap_sufficient - the model answer's text must
     share enough vocabulary with its cited evidence to plausibly be
     DERIVED from it, not pure invention.

Deliberately NOT checked here (see docs/DESIGN_NOTE.md's answer-grounding
section for the full reasoning): whether the answer semantically
CONTRADICTS the evidence, or whether every individual substantive claim is
independently supported. Those require real language understanding, not
lexical overlap - the same class of limitation
src.validation.novelty_checker's docstring already states plainly for its
own lexical screen ("catches close wording overlap only... not a
certification"). A deterministic overlap floor is a real, useful signal
(an answer entirely unrelated to its cited evidence IS caught), but it is
not a semantic-correctness guarantee, and this module does not claim to be
one.

Unlike question grounding, there is NO maximum-overlap ("not a near-copy")
ceiling here - see src.generation.memo_generator._answer_grounding_ok's
docstring for why: a model answer is supposed to closely reflect what the
guide actually states, unlike a question, which must be an original
scenario.
"""
from __future__ import annotations

from typing import Any

from src.retrieval.text_similarity import cosine_similarity
from src.security.config import SecurityConfig
from src.validation.types import CheckResult, ValidationReport


def _answer_text(memo_question: dict[str, Any]) -> str:
    parts = [memo_question.get("model_answer") or ""]
    parts.extend(sq.get("model_answer", "") for sq in memo_question.get("sub_questions", []) or [])
    return " ".join(parts)


def validate_answer_grounding(
    memo: dict[str, Any],
    corpus_chunks: list[dict[str, Any]],
    security_config: SecurityConfig | None = None,
) -> ValidationReport:
    """Independently re-check answer-side grounding for every question's
    memo entry in ``memo``.

    Like grounding_validator.validate_grounding, a missing ``grounding``
    list is a hard failure only when ``memo["generation_meta"]["answer_
    grounded"]`` is true (set by src.generation.memo_generator.generate_memo
    whenever it was called with real answer-retrieval inputs - i.e. REAL
    GENERATION MODE); otherwise it is informational, since TEST MODE and
    the API layer (per Phase 1 scope) may legitimately produce a memo with
    no answer-retrieval evidence attached.
    """
    security_config = security_config or SecurityConfig()
    report = ValidationReport.empty()
    valid_pages = {(c["source"], c["page"]) for c in corpus_chunks if "page" in c}
    answer_grounded_mode = bool(memo.get("generation_meta", {}).get("answer_grounded"))

    for section in memo["sections"]:
        for mq in section["questions"]:
            qid = mq.get("question_id", "?")
            grounding = mq.get("grounding") or []
            if not grounding:
                report.add(
                    CheckResult(
                        f"answer_grounding_present:{qid}",
                        not answer_grounded_mode,
                        "memo entry carries no answer-side grounding/provenance"
                        if answer_grounded_mode
                        else "no answer grounding recorded - memo was not generated in answer-grounded mode (expected for API/test-mode runs)",
                    )
                )
                continue
            report.add(CheckResult(f"answer_grounding_present:{qid}", True, f"{len(grounding)} evidence citation(s)"))

            bad_citations = [
                f"{g.get('document')} p.{g.get('page')}"
                for g in grounding
                if (g.get("document"), g.get("page")) not in valid_pages
            ]
            report.add(
                CheckResult(
                    f"answer_grounding_pages_exist:{qid}",
                    not bad_citations,
                    "ok"
                    if not bad_citations
                    else f"cited page(s) not found in the ingested corpus - possible fabrication: {bad_citations}",
                )
            )

            answer_text = _answer_text(mq)
            evidence_text = " ".join(g.get("passage", "") for g in grounding)
            overlap = cosine_similarity(answer_text, evidence_text)
            min_ok = overlap >= security_config.answer_grounding_min_overlap
            report.add(
                CheckResult(
                    f"answer_grounding_overlap_sufficient:{qid}",
                    min_ok,
                    f"overlap={overlap:.3f} (minimum {security_config.answer_grounding_min_overlap}) - "
                    + ("ok" if min_ok else "model answer shows little relation to its cited evidence"),
                )
            )

    return report
