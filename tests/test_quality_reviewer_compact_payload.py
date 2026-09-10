"""Tests for the compact quality-review payload (production incident fix).

REWORK (production incident, 2026-09-10): a real Groq 429
("rate_limit_exceeded", TPM limit 8000) traced back to
src.validation.quality_reviewer.run_quality_review serializing the ENTIRE
paper + ENTIRE memo verbatim - including every question's full grounding/
answer-grounding evidence arrays, already independently validated
elsewhere - into a single ~17,900-token prompt, over double the entire
per-minute token budget by itself. Fixed by _compact_paper_for_review/
_compact_memo_for_review, which cap (never remove) question-side grounding
and drop memo-side grounding entirely (unused by any review.txt criterion -
answer grounding is already re-checked deterministically by
src.validation.answer_grounding_validator, which never calls an LLM).

These tests prove: (1) the compaction functions themselves behave exactly
as documented, (2) run_quality_review actually sends the COMPACT
representation to the provider - not the full one, (3) the REAL paper/memo
objects (and what MockProvider's fixture selection sees via `task`) are
never mutated or reduced by this - only what is RE-SENT to the LLM for this
one call changes.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from src.providers.base import LLMProvider
from src.validation.quality_reviewer import (
    _compact_memo_for_review,
    _compact_paper_for_review,
    run_quality_review,
)

_LONG_PASSAGE = (
    "A binary number system uses only two digits, 0 and 1, to represent values. " * 10
)  # well over 300 chars, to exercise truncation


def _sample_paper() -> dict[str, Any]:
    return {
        "paper_id": "mock-eisa-software_developer-paper-03",
        "qualification": "Occupational Certificate: Software Developer",
        "nqf_level": 5,
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "duration_minutes": 180,
        "total_marks": 15,
        "instructions": ["Answer all questions."],
        "sections": [
            {
                "id": "A",
                "title": "Foundational Computing",
                "marks": 15,
                "outcomes": ["KM-04-KT02"],
                "competencies": ["Binary conversion"],
                "difficulty": "foundational",
                "question_types": ["scenario_short_answer"],
                "questions": [
                    {
                        "id": "Q-A1",
                        "section_id": "A",
                        "question_number": "1",
                        "type": "scenario_short_answer",
                        "scenario": "A developer at Acme needs to convert values for a legacy system.",
                        "question": "Convert 200 to binary and explain your method.",
                        "marks": 15,
                        "difficulty": "foundational",
                        "outcomes": ["KM-04-KT02"],
                        "competencies": ["Binary conversion"],
                        "expected_response_type": "short_answer",
                        "grounding": [
                            {
                                "document": "Module 4-Learner Guide.pdf",
                                "page": 22,
                                "passage": _LONG_PASSAGE,
                                "reason": "Retrieved for KM-04-KT02 (Binary conversion)",
                            },
                            {
                                "document": "Module 4-Learner Guide.pdf",
                                "page": 23,
                                "passage": "A second, different passage about binary arithmetic and carries.",
                                "reason": "Retrieved for KM-04-KT02 (Binary conversion)",
                            },
                            {
                                "document": "Module 4-Learner Guide.pdf",
                                "page": 24,
                                "passage": "A third passage that should be dropped entirely by the cap.",
                                "reason": "Retrieved for KM-04-KT02 (Binary conversion)",
                            },
                        ],
                    }
                ],
            }
        ],
        "generation_meta": {"provider": "groq", "seed": 1, "blueprint_paper_id": "x", "grounded": True},
    }


def _sample_memo() -> dict[str, Any]:
    return {
        "memo_id": "mock-eisa-memo-software_developer-paper-03",
        "paper_id": "mock-eisa-software_developer-paper-03",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 15,
        "sections": [
            {
                "id": "A",
                "questions": [
                    {
                        "question_id": "Q-A1",
                        "total_marks": 15,
                        "model_answer": "200 in binary is 11001000, derived via successive division by 2.",
                        "criteria": [{"description": "Correct binary value given.", "marks": 15}],
                        "accepted_alternatives": ["11001000₂"],
                        "partial_credit_guidance": "Award partial marks for a correct method with an arithmetic slip.",
                        "penalties": "",
                        "grounding": [
                            {
                                "document": "Module 4-Learner Guide.pdf",
                                "page": 22,
                                "passage": _LONG_PASSAGE,
                                "reason": "Retrieved to answer Q-A1",
                            }
                        ],
                    }
                ],
            }
        ],
        "generation_meta": {"provider": "groq", "seed": 1, "answer_grounded": True},
    }


class _CapturingProvider(LLMProvider):
    name = "capturing"

    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "task": task})
        return self.response


# ---------------------------------------------------------------------------
# _compact_paper_for_review
# ---------------------------------------------------------------------------
def test_compact_paper_caps_grounding_passages_per_question():
    paper = _sample_paper()
    compact = _compact_paper_for_review(paper)
    grounding = compact["sections"][0]["questions"][0]["grounding"]
    assert len(grounding) == 2  # capped from 3 to _REVIEW_GROUNDING_MAX_PASSAGES_PER_QUESTION


def test_compact_paper_truncates_long_grounding_passages():
    paper = _sample_paper()
    compact = _compact_paper_for_review(paper)
    truncated = compact["sections"][0]["questions"][0]["grounding"][0]["passage"]
    assert len(truncated) <= 320  # 300-char cap plus "..." and word-boundary slack
    assert truncated.endswith("...")


def test_compact_paper_preserves_document_and_page_citations():
    """Citation identity (which document/page) must survive compaction even
    though passage TEXT is capped/truncated - a reviewer still needs to know
    WHAT was cited, only not the full verbatim text."""
    paper = _sample_paper()
    compact = _compact_paper_for_review(paper)
    grounding = compact["sections"][0]["questions"][0]["grounding"]
    assert grounding[0]["document"] == "Module 4-Learner Guide.pdf"
    assert grounding[0]["page"] == 22


def test_compact_paper_preserves_all_review_relevant_question_fields():
    paper = _sample_paper()
    compact = _compact_paper_for_review(paper)
    question = compact["sections"][0]["questions"][0]
    assert question["scenario"] == paper["sections"][0]["questions"][0]["scenario"]
    assert question["question"] == paper["sections"][0]["questions"][0]["question"]
    assert question["marks"] == 15
    assert question["outcomes"] == ["KM-04-KT02"]
    assert question["expected_response_type"] == "short_answer"


def test_compact_paper_preserves_nqf_level_needed_for_difficulty_review():
    """review.txt's difficulty_appropriate criterion explicitly checks
    against "the qualification's NQF Level (stated on the paper)" - this
    must survive compaction."""
    paper = _sample_paper()
    compact = _compact_paper_for_review(paper)
    assert compact["nqf_level"] == 5


def test_compact_paper_does_not_mutate_the_original_paper():
    paper = _sample_paper()
    original = copy.deepcopy(paper)
    _compact_paper_for_review(paper)
    assert paper == original
    assert len(paper["sections"][0]["questions"][0]["grounding"]) == 3  # untouched, still all 3


# ---------------------------------------------------------------------------
# _compact_memo_for_review
# ---------------------------------------------------------------------------
def test_compact_memo_drops_grounding_entirely():
    memo = _sample_memo()
    compact = _compact_memo_for_review(memo)
    question = compact["sections"][0]["questions"][0]
    assert "grounding" not in question


def test_compact_memo_preserves_every_review_relevant_field():
    memo = _sample_memo()
    compact = _compact_memo_for_review(memo)
    question = compact["sections"][0]["questions"][0]
    original = memo["sections"][0]["questions"][0]
    assert question["model_answer"] == original["model_answer"]
    assert question["criteria"] == original["criteria"]
    assert question["accepted_alternatives"] == original["accepted_alternatives"]
    assert question["partial_credit_guidance"] == original["partial_credit_guidance"]
    assert question["total_marks"] == original["total_marks"]


def test_compact_memo_does_not_mutate_the_original_memo():
    memo = _sample_memo()
    original = copy.deepcopy(memo)
    _compact_memo_for_review(memo)
    assert memo == original
    assert "grounding" in memo["sections"][0]["questions"][0]  # untouched


# ---------------------------------------------------------------------------
# run_quality_review: proves the COMPACT representation is what is actually
# sent to the provider, and that the real objects/task are unaffected.
# ---------------------------------------------------------------------------
def test_run_quality_review_sends_the_compact_representation_not_the_full_one():
    paper = _sample_paper()
    memo = _sample_memo()
    provider = _CapturingProvider('{"approved": true, "issues": [], "question_reviews": []}')

    run_quality_review(paper, memo, provider)

    assert len(provider.calls) == 1
    sent_prompt = provider.calls[0]["user_prompt"]
    # The 3rd (capped) grounding passage's distinguishing text must be ABSENT.
    assert "third passage that should be dropped entirely" not in sent_prompt
    # The full, untruncated long passage (repeated 10x) must be ABSENT verbatim.
    assert _LONG_PASSAGE not in sent_prompt
    # But the question/answer substance a reviewer needs must be PRESENT.
    assert "Convert 200 to binary and explain your method." in sent_prompt
    assert "200 in binary is 11001000" in sent_prompt
    assert "Correct binary value given." in sent_prompt


def test_run_quality_review_prompt_is_meaningfully_smaller_than_the_full_serialization():
    paper = _sample_paper()
    memo = _sample_memo()
    provider = _CapturingProvider('{"approved": true, "issues": [], "question_reviews": []}')

    run_quality_review(paper, memo, provider)

    sent_prompt = provider.calls[0]["user_prompt"]
    full_serialization_size = len(json.dumps(paper)) + len(json.dumps(memo))
    # The compact prompt (paper+memo portion) must be substantially smaller
    # than naively serializing both objects in full - proves the compaction
    # is actually wired into run_quality_review, not just defined and unused.
    assert len(sent_prompt) < full_serialization_size * 0.7


def test_run_quality_review_task_still_carries_the_full_uncompacted_objects():
    """task is MockProvider-only (never sent to a real provider - see
    src/providers/base.py's module docstring) and must stay exactly what it
    was before this change: the real, full paper/memo, so MockProvider's
    deterministic fixture selection is unaffected by this review-only
    compaction."""
    paper = _sample_paper()
    memo = _sample_memo()
    provider = _CapturingProvider('{"approved": true, "issues": [], "question_reviews": []}')

    run_quality_review(paper, memo, provider)

    sent_task = provider.calls[0]["task"]
    assert sent_task["paper"] is paper
    assert sent_task["memo"] is memo
    assert len(sent_task["paper"]["sections"][0]["questions"][0]["grounding"]) == 3


def test_run_quality_review_result_shape_is_unchanged():
    paper = _sample_paper()
    memo = _sample_memo()
    provider = _CapturingProvider(
        '{"approved": false, "issues": ["paper-level note"], '
        '"question_reviews": [{"question_id": "Q-A1", "markability": "pass"}]}'
    )

    review = run_quality_review(paper, memo, provider)

    assert review["approved"] is False
    assert review["issues"] == ["paper-level note"]
    assert review["question_reviews"][0]["question_id"] == "Q-A1"
