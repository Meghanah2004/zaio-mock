"""LLM-based quality review stage.

Runs AFTER the deterministic validators (schema/marks/coverage) have already
passed - this stage is for the judgement calls a schema can't make
(ambiguity, occupational realism, whether a "fix" is actually safe), not for
structural checks, which stay deterministic per docs/DESIGN.md.

The reviewer's ``approved: false`` or per-question issues are a signal for
*targeted* regeneration of the affected question/memo only - never a reason
to regenerate the whole paper.
"""
from __future__ import annotations

import json
from typing import Any

from src.generation.llm_utils import (
    call_provider_with_retry,
    extract_json,
    load_prompt_template,
)
from src.providers.base import LLMProvider

_REVIEW_GROUNDING_MAX_PASSAGES_PER_QUESTION = 2
_REVIEW_GROUNDING_PASSAGE_MAX_CHARS = 300
"""Bounds on how much question-side grounding evidence is RE-embedded in the
quality-review prompt specifically (see _compact_paper_for_review below) -
independent of, and much smaller than, security_config.
evidence_passages_per_section/max_evidence_passage_chars, which govern the
evidence actually used to GENERATE the question (unaffected by this).

REWORK (production incident, 2026-09-10): a real Groq 429
("rate_limit_exceeded", TPM limit 8000) traced back to this call's prompt -
serializing the ENTIRE paper + ENTIRE memo verbatim, including every
question's full grounding array (up to evidence_passages_per_section=4
passages x max_evidence_passage_chars=900 chars each) AND every memo
entry's full answer-grounding array of the same shape - measured at
~15,800-17,900 tokens combined for a representative paper+memo, over double
the entire per-minute budget in a single request, on top of the ~30,000-
42,000 tokens the paper's other 12 real generation/memo calls already need
in the same window. review.txt's guide_grounding/reads_as_copied criteria
genuinely need to SEE some of each question's grounding text to judge it -
this is not removed, only capped to a small, still-representative sample
(2 passages, 300 chars each) instead of the full retrieval set repeated
verbatim. The memo's OWN grounding/citation array is dropped entirely from
this prompt: no review.txt criterion inspects it (answer-side grounding
correctness is already independently, deterministically re-checked by
src.validation.answer_grounding_validator, which never calls an LLM), so
resending it here is pure duplication with no corresponding review value."""


def _compact_grounding_for_review(grounding: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for entry in (grounding or [])[:_REVIEW_GROUNDING_MAX_PASSAGES_PER_QUESTION]:
        passage = entry.get("passage", "")
        if len(passage) > _REVIEW_GROUNDING_PASSAGE_MAX_CHARS:
            passage = passage[:_REVIEW_GROUNDING_PASSAGE_MAX_CHARS].rsplit(" ", 1)[0] + "..."
        compact.append({"document": entry.get("document"), "page": entry.get("page"), "passage": passage})
    return compact


def _compact_paper_for_review(paper: dict[str, Any]) -> dict[str, Any]:
    """Builds the paper representation sent to the quality-review LLM ONLY -
    the real, full ``paper`` (with every question's complete grounding
    array) is untouched and is what actually gets written to
    artifacts/blueprint-adjacent output, validated by the deterministic
    grounding validator, and returned to the API/frontend. This function's
    output is never persisted or returned - see run_quality_review below."""
    return {
        "paper_id": paper["paper_id"],
        "qualification": paper["qualification"],
        "nqf_level": paper["nqf_level"],
        "total_marks": paper["total_marks"],
        "sections": [
            {
                "id": section["id"],
                "title": section["title"],
                "marks": section["marks"],
                "difficulty": section["difficulty"],
                "questions": [
                    {
                        "id": question["id"],
                        "type": question.get("type"),
                        "scenario": question.get("scenario"),
                        "question": question.get("question"),
                        "marks": question.get("marks"),
                        "outcomes": question.get("outcomes"),
                        "expected_response_type": question.get("expected_response_type"),
                        "sub_questions": question.get("sub_questions"),
                        "grounding": _compact_grounding_for_review(question.get("grounding")),
                    }
                    for question in section["questions"]
                ],
            }
            for section in paper["sections"]
        ],
    }


def _compact_memo_for_review(memo: dict[str, Any]) -> dict[str, Any]:
    """Same purpose as _compact_paper_for_review, for the memo side: drops
    only the per-question ``grounding`` (citation) array - unused by any
    review.txt criterion (answer grounding is independently, deterministically
    re-checked elsewhere - see the module-level constants' docstring above).
    Every field a reviewer actually needs to judge markability/technical_
    correctness/consistency (model_answer, criteria, accepted_alternatives,
    partial_credit_guidance, penalties, sub_questions) is preserved exactly."""
    return {
        "memo_id": memo["memo_id"],
        "paper_id": memo["paper_id"],
        "total_marks": memo["total_marks"],
        "sections": [
            {
                "id": section["id"],
                "questions": [
                    {key: value for key, value in question.items() if key != "grounding"}
                    for question in section["questions"]
                ],
            }
            for section in memo["sections"]
        ],
    }


def run_quality_review(paper: dict[str, Any], memo: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
    template = load_prompt_template("review.txt")
    system_part, _, user_part = template.partition("USER (templated at call time):")
    system_prompt = system_part.replace("SYSTEM:", "", 1).strip()
    review_paper = _compact_paper_for_review(paper)
    review_memo = _compact_memo_for_review(memo)
    user_prompt = (
        user_part.replace("{paper_json}", json.dumps(review_paper))
        .replace("{memo_json}", json.dumps(review_memo))
        .strip()
    )
    # task carries the REAL, full paper/memo (MockProvider-only, see
    # src/providers/base.py's module docstring - never sent to a real
    # provider) so fixture selection is unaffected by the review-only
    # compaction above.
    task = {"kind": "quality_review", "paper": paper, "memo": memo}
    raw = call_provider_with_retry(provider, system_prompt, user_prompt, task)
    review = extract_json(raw)

    review.setdefault("approved", False)
    review.setdefault("issues", [])
    review.setdefault("question_reviews", [])
    return review
