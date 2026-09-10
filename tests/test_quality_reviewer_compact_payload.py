"""Tests for the quality-review token-budget fixes (production incident,
2026-09-10, real Groq 429s - TPM limit 8000):

1. Compact payload: question-side grounding capped (not removed), memo-side
   grounding dropped entirely (unused by any review.txt criterion - answer
   grounding is independently, deterministically re-checked elsewhere).
2. Grouped review: sections reviewed in positional groups of 2 instead of
   one whole-paper call - the whole-paper call was proven to exceed 8000
   TPM unconditionally (~11,435 tokens, a single request that can never
   succeed regardless of retries).
3. Deterministic official-status check: the one review.txt criterion that
   is a clean pattern match, moved out of the LLM prompt entirely.

These tests prove: (1) the compaction functions behave exactly as
documented, (2) run_quality_review actually sends the COMPACT, GROUP-
SCOPED representation to the provider (one call per group, never the whole
paper in one call), (3) results from every group are aggregated into the
same overall shape run_quality_review has always returned, (4) a failure in
any group propagates rather than being silently swallowed into a false
"approved" result, (5) the deterministic official-status check is
conservative (catches obvious violations, not ordinary contextual
mentions), and (6) the REAL paper/memo objects are never mutated or
persisted by any of this - only what is RE-SENT to the LLM changes.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from src.providers.base import LLMProvider, LLMProviderError
from src.providers.mock_provider import MockProvider
from src.validation.quality_reviewer import (
    _check_official_status_claims,
    _chunk_sections,
    _compact_memo_for_review,
    _compact_paper_for_review,
    _text_makes_an_official_status_claim,
    run_quality_review,
)

_SECTION_IDS = ("A", "B", "C", "D", "E", "F")
_LONG_PASSAGE_TEMPLATE = "A binary number system uses only two digits, 0 and 1, for section {sid}. " * 10


def _make_paper(section_ids: tuple[str, ...] = _SECTION_IDS) -> dict[str, Any]:
    return {
        "paper_id": "mock-eisa-software_developer-paper-03",
        "qualification": "Occupational Certificate: Software Developer",
        "nqf_level": 5,
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "duration_minutes": 180,
        "total_marks": 15 * len(section_ids),
        "instructions": ["Answer all questions."],
        "sections": [
            {
                "id": sid,
                "title": f"Section {sid} Title",
                "marks": 15,
                "outcomes": [f"KM-0{i + 1}-KT01"],
                "competencies": [f"Competency {sid}"],
                "difficulty": "foundational",
                "question_types": ["scenario_short_answer"],
                "questions": [
                    {
                        "id": f"Q-{sid}1",
                        "section_id": sid,
                        "question_number": "1",
                        "type": "scenario_short_answer",
                        "scenario": f"UNIQUE_SCENARIO_MARKER_{sid} - a developer at Acme handles a task.",
                        "question": f"UNIQUE_QUESTION_MARKER_{sid} - explain your approach.",
                        "marks": 15,
                        "difficulty": "foundational",
                        "outcomes": [f"KM-0{i + 1}-KT01"],
                        "competencies": [f"Competency {sid}"],
                        "expected_response_type": "short_answer",
                        "grounding": [
                            {
                                "document": "Module 4-Learner Guide.pdf",
                                "page": 20 + i,
                                "passage": _LONG_PASSAGE_TEMPLATE.format(sid=sid),
                                "reason": f"Retrieved for KM-0{i + 1}-KT01",
                            },
                            {
                                "document": "Module 4-Learner Guide.pdf",
                                "page": 21 + i,
                                "passage": f"A second passage for section {sid}.",
                                "reason": f"Retrieved for KM-0{i + 1}-KT01",
                            },
                            {
                                "document": "Module 4-Learner Guide.pdf",
                                "page": 22 + i,
                                "passage": f"UNIQUE_THIRD_PASSAGE_MARKER_{sid} - should be capped/dropped.",
                                "reason": f"Retrieved for KM-0{i + 1}-KT01",
                            },
                        ],
                    }
                ],
            }
            for i, sid in enumerate(section_ids)
        ],
        "generation_meta": {"provider": "groq", "seed": 1, "blueprint_paper_id": "x", "grounded": True},
    }


def _make_memo(section_ids: tuple[str, ...] = _SECTION_IDS) -> dict[str, Any]:
    return {
        "memo_id": "mock-eisa-memo-software_developer-paper-03",
        "paper_id": "mock-eisa-software_developer-paper-03",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 15 * len(section_ids),
        "sections": [
            {
                "id": sid,
                "questions": [
                    {
                        "question_id": f"Q-{sid}1",
                        "total_marks": 15,
                        "model_answer": f"UNIQUE_MODEL_ANSWER_MARKER_{sid}.",
                        "criteria": [{"description": f"Criterion for {sid}.", "marks": 15}],
                        "accepted_alternatives": [],
                        "partial_credit_guidance": "Award partial marks per criterion.",
                        "penalties": "",
                        "grounding": [
                            {
                                "document": "Module 4-Learner Guide.pdf",
                                "page": 20,
                                "passage": f"UNIQUE_MEMO_GROUNDING_MARKER_{sid} - must never reach the review prompt.",
                                "reason": f"Retrieved to answer Q-{sid}1",
                            }
                        ],
                    }
                ],
            }
            for sid in section_ids
        ],
        "generation_meta": {"provider": "groq", "seed": 1, "answer_grounded": True},
    }


class _CapturingProvider(LLMProvider):
    name = "capturing"

    def __init__(self, responses: list[str]):
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "task": task})
        return self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]


_APPROVED_EMPTY_RESPONSE = json.dumps({"approved": True, "issues": [], "question_reviews": []})


def _review_response(question_ids: list[str], approved: bool = True) -> str:
    return json.dumps(
        {
            "approved": approved,
            "issues": [],
            "question_reviews": [{"question_id": qid, "markability": "pass"} for qid in question_ids],
        }
    )


# ---------------------------------------------------------------------------
# _chunk_sections
# ---------------------------------------------------------------------------
def test_chunk_sections_groups_six_sections_into_three_pairs_in_order():
    sections = [{"id": sid} for sid in _SECTION_IDS]
    groups = _chunk_sections(sections, 2)
    assert [[s["id"] for s in group] for group in groups] == [["A", "B"], ["C", "D"], ["E", "F"]]


def test_chunk_sections_handles_an_odd_remainder():
    sections = [{"id": sid} for sid in ("A", "B", "C")]
    groups = _chunk_sections(sections, 2)
    assert [[s["id"] for s in group] for group in groups] == [["A", "B"], ["C"]]


# ---------------------------------------------------------------------------
# _compact_paper_for_review / _compact_memo_for_review (now group-scoped)
# ---------------------------------------------------------------------------
def test_compact_paper_for_review_includes_only_the_given_sections():
    paper = _make_paper()
    group = [s for s in paper["sections"] if s["id"] in ("C", "D")]
    compact = _compact_paper_for_review(paper, group)
    assert [s["id"] for s in compact["sections"]] == ["C", "D"]


def test_compact_paper_for_review_caps_grounding_to_two_passages():
    paper = _make_paper()
    group = [paper["sections"][0]]  # section A, has 3 grounding entries
    compact = _compact_paper_for_review(paper, group)
    grounding = compact["sections"][0]["questions"][0]["grounding"]
    assert len(grounding) == 2
    assert not any("UNIQUE_THIRD_PASSAGE_MARKER" in g["passage"] for g in grounding)


def test_compact_paper_for_review_preserves_nqf_level_for_any_group():
    paper = _make_paper()
    group = [paper["sections"][-1]]  # section F only
    compact = _compact_paper_for_review(paper, group)
    assert compact["nqf_level"] == 5


def test_compact_memo_for_review_includes_only_the_given_sections_and_drops_grounding():
    memo = _make_memo()
    group = [s for s in memo["sections"] if s["id"] in ("E", "F")]
    compact = _compact_memo_for_review(memo, group)
    assert [s["id"] for s in compact["sections"]] == ["E", "F"]
    for section in compact["sections"]:
        for question in section["questions"]:
            assert "grounding" not in question


def test_compact_functions_do_not_mutate_the_original_objects():
    paper = _make_paper()
    memo = _make_memo()
    original_paper = copy.deepcopy(paper)
    original_memo = copy.deepcopy(memo)

    _compact_paper_for_review(paper, [paper["sections"][0]])
    _compact_memo_for_review(memo, [memo["sections"][0]])

    assert paper == original_paper
    assert memo == original_memo


# ---------------------------------------------------------------------------
# run_quality_review: grouping, scoping, aggregation, failure propagation
# ---------------------------------------------------------------------------
def test_run_quality_review_makes_exactly_three_calls_for_six_sections():
    paper = _make_paper()
    memo = _make_memo()
    provider = _CapturingProvider([_APPROVED_EMPTY_RESPONSE] * 3)

    run_quality_review(paper, memo, provider)

    assert len(provider.calls) == 3


def test_run_quality_review_scopes_each_call_to_only_its_own_group():
    """Each of the 3 calls' prompt must contain ONLY that group's own
    section markers - never another group's scenario/question/model-answer
    text. This directly proves the grouping is real, not just a re-labeled
    whole-paper call."""
    paper = _make_paper()
    memo = _make_memo()
    provider = _CapturingProvider([_APPROVED_EMPTY_RESPONSE] * 3)

    run_quality_review(paper, memo, provider)

    expected_groups = [("A", "B"), ("C", "D"), ("E", "F")]
    for call, group_ids in zip(provider.calls, expected_groups):
        prompt = call["user_prompt"]
        for sid in group_ids:
            assert f"UNIQUE_SCENARIO_MARKER_{sid}" in prompt
            assert f"UNIQUE_MODEL_ANSWER_MARKER_{sid}" in prompt
        other_ids = [sid for sid in _SECTION_IDS if sid not in group_ids]
        for sid in other_ids:
            assert f"UNIQUE_SCENARIO_MARKER_{sid}" not in prompt
            assert f"UNIQUE_MODEL_ANSWER_MARKER_{sid}" not in prompt


def test_run_quality_review_never_sends_memo_grounding_to_any_group():
    paper = _make_paper()
    memo = _make_memo()
    provider = _CapturingProvider([_APPROVED_EMPTY_RESPONSE] * 3)

    run_quality_review(paper, memo, provider)

    for call in provider.calls:
        assert "UNIQUE_MEMO_GROUNDING_MARKER" not in call["user_prompt"]


def test_run_quality_review_passes_section_ids_in_task_for_each_group():
    paper = _make_paper()
    memo = _make_memo()
    provider = _CapturingProvider([_APPROVED_EMPTY_RESPONSE] * 3)

    run_quality_review(paper, memo, provider)

    assert [call["task"]["section_ids"] for call in provider.calls] == [["A", "B"], ["C", "D"], ["E", "F"]]
    # task still carries the REAL, full paper/memo (MockProvider-only) -
    # unaffected by the per-group compaction above.
    for call in provider.calls:
        assert call["task"]["paper"] is paper
        assert call["task"]["memo"] is memo


def test_run_quality_review_aggregates_question_reviews_from_every_group():
    paper = _make_paper()
    memo = _make_memo()
    provider = _CapturingProvider(
        [
            _review_response(["Q-A1", "Q-B1"]),
            _review_response(["Q-C1", "Q-D1"]),
            _review_response(["Q-E1", "Q-F1"]),
        ]
    )

    review = run_quality_review(paper, memo, provider)

    reviewed_ids = {qr["question_id"] for qr in review["question_reviews"]}
    assert reviewed_ids == {"Q-A1", "Q-B1", "Q-C1", "Q-D1", "Q-E1", "Q-F1"}
    assert len(review["question_reviews"]) == 6  # every question reviewed exactly once


def test_run_quality_review_approved_is_false_if_any_group_disapproves():
    paper = _make_paper()
    memo = _make_memo()
    provider = _CapturingProvider(
        [
            _review_response(["Q-A1", "Q-B1"], approved=True),
            _review_response(["Q-C1", "Q-D1"], approved=False),  # group 2 disapproves
            _review_response(["Q-E1", "Q-F1"], approved=True),
        ]
    )

    review = run_quality_review(paper, memo, provider)

    assert review["approved"] is False


def test_run_quality_review_aggregates_issues_from_every_group():
    paper = _make_paper()
    memo = _make_memo()
    provider = _CapturingProvider(
        [
            json.dumps({"approved": True, "issues": ["issue from group 1"], "question_reviews": []}),
            json.dumps({"approved": True, "issues": ["issue from group 2"], "question_reviews": []}),
            json.dumps({"approved": True, "issues": [], "question_reviews": []}),
        ]
    )

    review = run_quality_review(paper, memo, provider)

    assert "issue from group 1" in review["issues"]
    assert "issue from group 2" in review["issues"]


class _FailsOnSecondGroupProvider(LLMProvider):
    """Simulates a real provider failure specifically on the SECOND group's
    call - proves a mid-loop failure propagates rather than being silently
    swallowed into a false "approved" result.

    retryable=False (e.g. a permanent failure like a malformed request)
    makes this a clean, single-attempt failure - a retryable=True error
    would instead be retried by call_provider_with_retry and likely
    succeed on a later attempt (that IS the correct, desired behavior for a
    transient error; it just isn't what this test is checking), so using a
    non-retryable failure here isolates the property under test: a group
    failure that genuinely exhausts/aborts must propagate, not vanish."""

    name = "fails-on-group-2"

    def __init__(self):
        self.call_count = 0

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        self.call_count += 1
        if self.call_count == 2:
            raise LLMProviderError(
                "simulated permanent failure on group 2 (e.g. a malformed request)", retryable=False
            )
        return _APPROVED_EMPTY_RESPONSE


def test_a_failure_in_group_two_propagates_and_is_never_reported_as_success():
    paper = _make_paper()
    memo = _make_memo()
    provider = _FailsOnSecondGroupProvider()

    try:
        run_quality_review(paper, memo, provider)
        raised = False
    except LLMProviderError:
        raised = True

    assert raised, "a group failure must propagate, never be swallowed into a returned result"
    # The failing call was indeed the second one (group C+D), and no fourth
    # call was ever attempted after the failure.
    assert provider.call_count == 2


# ---------------------------------------------------------------------------
# Deterministic official-status check
# ---------------------------------------------------------------------------
def test_official_status_claim_is_detected_for_an_obvious_violation():
    assert _text_makes_an_official_status_claim(
        "This assessment is an official QCTO EISA instrument for this qualification."
    )


def test_official_status_claim_detected_for_a_second_obvious_phrasing():
    assert _text_makes_an_official_status_claim(
        "This document constitutes the authentic, official EISA examination."
    )


def test_official_status_claim_not_detected_for_ordinary_qcto_mentions():
    assert not _text_makes_an_official_status_claim(
        "In line with QCTO's official curriculum standards, the developer must document the API."
    )


def test_official_status_claim_not_detected_for_a_reference_to_official_material():
    assert not _text_makes_an_official_status_claim(
        "The official QCTO learner guide explains binary conversion using successive division."
    )


def test_official_status_claim_not_detected_for_the_pipelines_own_disclaimer():
    assert not _text_makes_an_official_status_claim(
        "This is a MOCK / PRACTICE ASSESSMENT ONLY, not an official QCTO instrument."
    )


def test_official_status_claim_not_detected_for_a_mock_format_reference():
    assert not _text_makes_an_official_status_claim(
        "This mock paper follows the official EISA format for structure and marks allocation."
    )


def test_official_status_claim_not_detected_when_words_appear_independently():
    assert not _text_makes_an_official_status_claim(
        "The assessment covers EISA-relevant outcomes and references QCTO's official skill standards "
        "separately, with no claim about this paper's own status."
    )


def test_check_official_status_claims_flags_the_offending_question_id():
    paper = _make_paper(section_ids=("A",))
    paper["sections"][0]["questions"][0]["scenario"] = (
        "This assessment is an official QCTO EISA instrument, not a practice paper."
    )
    memo = _make_memo(section_ids=("A",))

    issues = _check_official_status_claims(paper, memo)

    assert len(issues) == 1
    assert "Q-A1" in issues[0]


def test_check_official_status_claims_returns_empty_for_ordinary_content():
    paper = _make_paper(section_ids=("A", "B"))
    memo = _make_memo(section_ids=("A", "B"))

    assert _check_official_status_claims(paper, memo) == []


def test_run_quality_review_sets_approved_false_when_official_status_claim_found():
    paper = _make_paper(section_ids=("A", "B"))
    paper["sections"][0]["questions"][0]["question"] = (
        "This exam represents a genuine, official EISA assessment instrument."
    )
    memo = _make_memo(section_ids=("A", "B"))
    provider = _CapturingProvider([_APPROVED_EMPTY_RESPONSE])

    review = run_quality_review(paper, memo, provider)

    assert review["approved"] is False
    assert any("Q-A1" in issue for issue in review["issues"])


# ---------------------------------------------------------------------------
# Regression tests for two edge cases found during final diff review
# (2026-09-10) and fixed in the same change:
#
# FALSE NEGATIVE: the original regex required a noun immediately after
# "this" ("this PAPER is...") and so missed the single most natural
# phrasing of this exact violation - bare "this IS an official X" with no
# noun in between.
#
# FALSE POSITIVE: the original regex did not distinguish a claim that the
# generated paper/question/assessment ITSELF is official from an ordinary,
# legitimate statement that SOURCE MATERIAL the paper draws on is official
# ("this question is BASED ON an official QCTO scenario") - the latter is
# exactly the kind of honest provenance statement a correctly-grounded
# question should be able to make, and must never be flagged.
# ---------------------------------------------------------------------------
def test_official_status_claim_detected_without_a_noun_after_this():
    """The exact false negative found in final diff review: no noun
    ("paper"/"assessment"/etc.) sits between "this" and "is"."""
    assert _text_makes_an_official_status_claim("This is an official QCTO EISA instrument.")


def test_official_status_claim_detected_for_authentic_without_a_noun():
    assert _text_makes_an_official_status_claim("This is an authentic QCTO EISA assessment.")


def test_official_status_claim_detected_for_official_examination_without_a_noun():
    assert _text_makes_an_official_status_claim("This is an official EISA examination.")


def test_official_status_claim_not_detected_for_a_based_on_provenance_statement():
    """The exact false positive found in final diff review."""
    assert not _text_makes_an_official_status_claim(
        "This examination question is based on an official QCTO scenario used in the learner "
        "guide, adapted for this assessment."
    )


def test_official_status_claim_not_detected_for_a_derived_from_provenance_statement():
    assert not _text_makes_an_official_status_claim(
        "The question is derived from an official EISA example in the learner guide."
    )


def test_official_status_claim_not_detected_for_an_adapted_from_provenance_statement():
    assert not _text_makes_an_official_status_claim(
        "The scenario was adapted from an official QCTO source."
    )


def test_official_status_claim_not_detected_for_based_on_even_with_noun_immediately_before_verb():
    """Proves the provenance-phrase filter is load-bearing on its own, not
    merely redundant with the tightened subject pattern: here the noun
    ("paper") sits directly before the verb ("is") - the subject pattern
    alone would match - so only the provenance-phrase check prevents this
    from being flagged."""
    assert not _text_makes_an_official_status_claim("This paper is based on an official QCTO scenario.")


def test_official_status_claim_not_detected_for_random_noun_subject():
    """The fix (making the noun optional) must not become so loose that ANY
    noun before "is" counts as referring to the paper itself - only the six
    recognized nouns (or bare "this") do."""
    assert not _text_makes_an_official_status_claim(
        "This concept is officially part of the QCTO curriculum, unrelated to this paper's own status."
    )


# ---------------------------------------------------------------------------
# MockProvider's own quality-review fixture: must scope to section_ids too,
# or 3 grouped calls would triple-count every question in every
# MockProvider-backed test elsewhere in this suite.
# ---------------------------------------------------------------------------
def test_mock_provider_quality_review_scopes_to_section_ids():
    paper = _make_paper()
    provider = MockProvider()

    raw = provider.generate(
        "sys",
        "user",
        {"kind": "quality_review", "paper": paper, "memo": _make_memo(), "section_ids": ["C", "D"]},
    )
    review = json.loads(raw)

    reviewed_ids = {qr["question_id"] for qr in review["question_reviews"]}
    assert reviewed_ids == {"Q-C1", "Q-D1"}


def test_mock_provider_quality_review_reviews_every_section_when_no_section_ids_given():
    """Backward-compatible default: an absent section_ids key means "all
    sections" - preserves the original single-call behavior for any other
    caller."""
    paper = _make_paper()
    provider = MockProvider()

    raw = provider.generate("sys", "user", {"kind": "quality_review", "paper": paper, "memo": _make_memo()})
    review = json.loads(raw)

    reviewed_ids = {qr["question_id"] for qr in review["question_reviews"]}
    assert reviewed_ids == {f"Q-{sid}1" for sid in _SECTION_IDS}


def test_run_quality_review_with_mock_provider_end_to_end_reviews_every_question_once():
    """Full integration: run_quality_review's 3 real grouped calls through
    the REAL MockProvider (not a test double) must still review every
    question exactly once, not 3x."""
    paper = _make_paper()
    memo = _make_memo()
    provider = MockProvider()

    review = run_quality_review(paper, memo, provider)

    reviewed_ids = [qr["question_id"] for qr in review["question_reviews"]]
    assert sorted(reviewed_ids) == sorted(f"Q-{sid}1" for sid in _SECTION_IDS)
    assert len(reviewed_ids) == 6  # exactly once each, not tripled
    assert review["approved"] is True
