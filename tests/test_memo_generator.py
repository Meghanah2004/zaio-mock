"""Regression tests for a real production failure during a live Groq
generation run: "Q-E1 sub-question 1: memo criteria sum to 5, expected 4."

Root cause: the memo prompt only ever embedded the question's full JSON
verbatim and stated the "marks must reconcile" requirement as a single
whole-question constraint, so a model composing several paragraphs of
model-answer/criteria text per part could lose track of one specific
part's exact target number. Fixed on two sides, mirroring the
grounding/novelty retry pattern already used in
src/generation/question_generator.py:
  1. _build_marks_budget renders each part's exact mark target as an
     explicit, individually-checkable line the prompt puts front and
     center (see prompts/generate_memo.txt).
  2. generate_memo retries a REJECTED memo (bounded by
     SecurityConfig.memo_max_retries) with a note naming exactly what was
     wrong, before failing loudly.

Nothing here weakens _validate_memo_marks, which runs unchanged on every
attempt and must still reject a genuinely bad sum every time it sees one -
see test_memo_generation_fails_loudly_after_exhausting_retries below.

Uses a small scripted fake provider (not MockProvider, not a real API
call) so each attempt's response is fully controlled and deterministic.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from src.generation.llm_utils import GenerationError
from src.generation.memo_generator import (
    _answer_grounding_ok,
    _build_marks_budget,
    _build_memo_prompt,
    generate_memo,
)
from src.providers.base import LLMProvider
from src.security.config import SecurityConfig
from src.validation.novelty_checker import ReferenceCorpusIndex


class ScriptedMemoProvider(LLMProvider):
    """Returns each entry in ``responses`` in order, repeating the last one
    once exhausted, as raw JSON text. Records every user_prompt it was
    called with so a test can inspect the retry note."""

    name = "scripted-memo"

    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = responses
        self.call_count = 0
        self.user_prompts: list[str] = []

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        self.user_prompts.append(user_prompt)
        content = self._responses[min(self.call_count, len(self._responses) - 1)]
        self.call_count += 1
        return json.dumps(content)


def _question() -> dict[str, Any]:
    return {
        "id": "Q-E1",
        "section_id": "E",
        "marks": 10,
        "question": "Answer the following questions about SDLC and security.",
        "sub_questions": [
            {"id": "1", "prompt": "Identify the SDLC phase.", "marks": 4},
            {"id": "2", "prompt": "Fix the vulnerability.", "marks": 6},
        ],
    }


def _memo_response(sub1_criteria_marks: list[int], sub2_criteria_marks: list[int]) -> dict[str, Any]:
    return {
        "question_id": "Q-E1",
        "total_marks": 10,
        "model_answer": "See per-part model answers below.",
        "criteria": [{"description": "see sub_questions", "marks": 10}],
        "accepted_alternatives": [],
        "sub_questions": [
            {
                "id": "1",
                "total_marks": 4,
                "model_answer": "Testing.",
                "criteria": [{"description": f"criterion {i}", "marks": m} for i, m in enumerate(sub1_criteria_marks)],
                "accepted_alternatives": [],
            },
            {
                "id": "2",
                "total_marks": 6,
                "model_answer": "Use parameterised queries.",
                "criteria": [{"description": f"criterion {i}", "marks": m} for i, m in enumerate(sub2_criteria_marks)],
                "accepted_alternatives": [],
            },
        ],
    }


def test_memo_with_criteria_sum_mismatch_is_rejected_then_corrected_on_retry():
    """Reproduces the exact real failure shape: sub-question 1's criteria
    (2 + 3 = 5) do not match its own 4 marks. The second attempt corrects
    it (2 + 2 = 4). The pipeline must recover, not just fail."""
    bad_response = _memo_response(sub1_criteria_marks=[2, 3], sub2_criteria_marks=[3, 3])
    good_response = _memo_response(sub1_criteria_marks=[2, 2], sub2_criteria_marks=[3, 3])
    provider = ScriptedMemoProvider([bad_response, good_response])

    paper = {
        "paper_id": "test-paper",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 10,
        "sections": [{"id": "E", "questions": [_question()]}],
    }

    memo = generate_memo(paper, provider, seed=1, security_config=SecurityConfig(memo_max_retries=3))

    assert provider.call_count == 2
    memo_sub1 = memo["sections"][0]["questions"][0]["sub_questions"][0]
    assert sum(c["marks"] for c in memo_sub1["criteria"]) == 4
    assert memo_sub1["total_marks"] == 4


def test_memo_generation_fails_loudly_after_exhausting_retries_on_persistent_mismatch():
    """The fix must NOT silently accept or "correct" a bad sum - if every
    attempt is wrong, it must still raise, not paper over the defect."""
    always_bad = _memo_response(sub1_criteria_marks=[2, 3], sub2_criteria_marks=[3, 3])
    provider = ScriptedMemoProvider([always_bad])

    paper = {
        "paper_id": "test-paper",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 10,
        "sections": [{"id": "E", "questions": [_question()]}],
    }

    with pytest.raises(GenerationError, match="exhausted 2 memo generation attempt"):
        generate_memo(paper, provider, seed=1, security_config=SecurityConfig(memo_max_retries=2))
    assert provider.call_count == 2


def test_retry_note_names_the_specific_discrepancy_from_the_previous_attempt():
    bad_response = _memo_response(sub1_criteria_marks=[2, 3], sub2_criteria_marks=[3, 3])
    good_response = _memo_response(sub1_criteria_marks=[2, 2], sub2_criteria_marks=[3, 3])
    provider = ScriptedMemoProvider([bad_response, good_response])

    paper = {
        "paper_id": "test-paper",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 10,
        "sections": [{"id": "E", "questions": [_question()]}],
    }
    generate_memo(paper, provider, seed=1, security_config=SecurityConfig(memo_max_retries=3))

    assert len(provider.user_prompts) == 2
    second_prompt = provider.user_prompts[1]
    assert "REGENERATION NOTE" in second_prompt
    assert "sum to 5" in second_prompt
    assert "expected 4" in second_prompt


def test_marks_budget_states_the_exact_target_for_every_sub_question():
    budget = _build_marks_budget(_question())
    assert "Sub-question 1: exactly 4 mark(s)" in budget
    assert "Sub-question 2: exactly 6 mark(s)" in budget


def test_marks_budget_handles_a_question_with_no_sub_questions():
    question = {"id": "Q-F1", "marks": 5, "question": "Explain the principle."}
    budget = _build_marks_budget(question)
    assert "exactly 5 mark(s)" in budget


def test_memo_prompt_contains_the_marks_budget_and_the_raw_question_json():
    question = _question()
    _, user_prompt = _build_memo_prompt(question, [])
    assert "Sub-question 1: exactly 4 mark(s)" in user_prompt
    assert "Sub-question 2: exactly 6 mark(s)" in user_prompt
    assert '"id": "Q-E1"' in user_prompt


def test_memo_generation_still_rejects_mismatched_question_id_with_retry():
    """A structurally wrong response (wrong question_id) must also go
    through the same retry-then-fail path, not be treated differently."""
    wrong_id_response = {
        "question_id": "Q-WRONG",
        "total_marks": 10,
        "model_answer": "x",
        "criteria": [{"description": "d", "marks": 10}],
    }
    provider = ScriptedMemoProvider([wrong_id_response])

    single_question = {"id": "Q-A1", "section_id": "A", "marks": 10, "question": "Q?"}
    paper = {
        "paper_id": "test-paper",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 10,
        "sections": [{"id": "A", "questions": [single_question]}],
    }

    with pytest.raises(GenerationError, match="exhausted 2 memo generation attempt"):
        generate_memo(paper, provider, seed=1, security_config=SecurityConfig(memo_max_retries=2))
    assert provider.call_count == 2


# ---------------------------------------------------------------------------
# Regression tests for a real production failure: the first real Groq
# generation for Paper 1 produced a schema-invalid memo -
# schemas/memo.schema.json requires questions[].criteria to be non-empty
# unconditionally, but Groq returned questions[].criteria = [] for every
# question that had sub_questions (even though sub_questions[].criteria
# was correctly populated and its marks reconciled exactly). Root cause:
# _validate_memo_marks never inspected the top-level criteria field at all
# when sub_questions were present, so nothing caught or filled in the gap
# before the memo was written to disk and later failed schema validation.
# Intended contract (confirmed from every src.providers.mock_provider memo
# builder, which has always done this): when sub_questions are present,
# the top-level criteria array must contain exactly one summary/placeholder
# entry - {"description": "See per-part criteria in sub_questions.",
# "marks": question["marks"]} - pointing to the real per-part breakdown,
# never a second independent marks breakdown.
# ---------------------------------------------------------------------------
def test_ensure_top_level_criteria_present_fills_in_an_empty_list():
    from src.generation.memo_generator import _ensure_top_level_criteria_present

    question = _question()  # has sub_questions, marks=10
    memo_question = {"question_id": "Q-E1", "criteria": []}

    _ensure_top_level_criteria_present(memo_question, question)

    assert memo_question["criteria"] == [
        {"description": "See per-part criteria in sub_questions.", "marks": 10}
    ]


def test_ensure_top_level_criteria_present_fills_in_a_missing_key():
    from src.generation.memo_generator import _ensure_top_level_criteria_present

    question = _question()
    memo_question = {"question_id": "Q-E1"}  # "criteria" key absent entirely

    _ensure_top_level_criteria_present(memo_question, question)

    assert memo_question["criteria"] == [
        {"description": "See per-part criteria in sub_questions.", "marks": 10}
    ]


def test_ensure_top_level_criteria_present_never_overwrites_a_non_empty_value():
    """Must never clobber content the provider actually supplied - only
    fill in the gap when it is genuinely empty."""
    from src.generation.memo_generator import _ensure_top_level_criteria_present

    question = _question()
    memo_question = {
        "question_id": "Q-E1",
        "criteria": [{"description": "A provider-supplied summary.", "marks": 10}],
    }

    _ensure_top_level_criteria_present(memo_question, question)

    assert memo_question["criteria"] == [{"description": "A provider-supplied summary.", "marks": 10}]


def test_ensure_top_level_criteria_present_does_nothing_without_sub_questions():
    """This field is only ever a placeholder-for-sub-questions convention.
    A question with no sub_questions relies on its OWN top-level criteria
    as the real (and already validated) marking content - this function
    must not touch it."""
    from src.generation.memo_generator import _ensure_top_level_criteria_present

    question = {"id": "Q-F1", "marks": 5, "question": "Explain the principle."}
    memo_question = {"question_id": "Q-F1", "criteria": []}

    _ensure_top_level_criteria_present(memo_question, question)

    assert memo_question["criteria"] == []


def test_real_groq_shaped_empty_top_level_criteria_is_normalized_end_to_end():
    """Reproduces the exact real failure shape through generate_memo:
    sub_questions[].criteria is correctly populated and reconciles exactly,
    but the top-level criteria is []. The final memo must have a non-empty
    top-level criteria and must pass schema validation."""
    from src.validation.schema_validator import validate_memo_schema

    groq_shaped_response = {
        "question_id": "Q-E1",
        "total_marks": 10,
        "model_answer": "See per-part model answers below.",
        "criteria": [],  # the exact real defect
        "accepted_alternatives": [],
        "sub_questions": [
            {
                "id": "1",
                "total_marks": 4,
                "model_answer": "Testing.",
                "criteria": [{"description": "c0", "marks": 2}, {"description": "c1", "marks": 2}],
                "accepted_alternatives": [],
            },
            {
                "id": "2",
                "total_marks": 6,
                "model_answer": "Use parameterised queries.",
                "criteria": [{"description": "c0", "marks": 6}],
                "accepted_alternatives": [],
            },
        ],
    }
    provider = ScriptedMemoProvider([groq_shaped_response])

    paper = {
        "paper_id": "test-paper",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 10,
        "sections": [{"id": "E", "questions": [_question()]}],
    }

    memo = generate_memo(paper, provider, seed=1)

    assert provider.call_count == 1  # fixed the FIRST time, no retry needed - purely structural, always derivable
    memo_question = memo["sections"][0]["questions"][0]
    assert memo_question["criteria"] == [
        {"description": "See per-part criteria in sub_questions.", "marks": 10}
    ]
    # The detailed per-sub-question criteria (the real fix from the
    # previous incident) must still be intact and unaffected.
    assert sum(c["marks"] for c in memo_question["sub_questions"][0]["criteria"]) == 4
    assert sum(c["marks"] for c in memo_question["sub_questions"][1]["criteria"]) == 6

    schema_result = validate_memo_schema(
        {
            "memo_id": "m",
            "paper_id": "p",
            "status_disclaimer": "MOCK / PRACTICE.",
            "total_marks": 10,
            "sections": memo["sections"],
        }
    )
    assert schema_result.passed, schema_result.details


def test_schema_validation_rejects_empty_top_level_criteria_directly():
    """Sanity check that the schema itself is unchanged and still strict -
    this fix works around the schema, it does not weaken it."""
    from src.validation.schema_validator import validate_memo_schema

    memo = {
        "memo_id": "m",
        "paper_id": "p",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 10,
        "sections": [
            {
                "id": "E",
                "questions": [
                    {
                        "question_id": "Q-E1",
                        "total_marks": 10,
                        "model_answer": "See per-part model answers below.",
                        "criteria": [],
                        "sub_questions": [
                            {
                                "id": "1",
                                "total_marks": 10,
                                "model_answer": "x",
                                "criteria": [{"description": "c0", "marks": 10}],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    result = validate_memo_schema(memo)
    assert not result.passed
    assert "criteria" in result.details


# ---------------------------------------------------------------------------
# Answer-side RAG (master-prompt REWORK): the memo prompt now embeds real,
# question-targeted learner-guide evidence (src.retrieval.evidence_selector.
# select_answer_evidence) and _answer_grounding_ok checks the generated
# answer against it before acceptance. Unit tests exercise
# _answer_grounding_ok's three deterministic checks directly (by tuning
# SecurityConfig's thresholds to isolate each branch, rather than hoping
# hand-written prose happens to land on the right side of a floor);
# integration tests exercise the same behaviour end-to-end through
# generate_memo with a real (tiny, synthetic) retrieval index.
# ---------------------------------------------------------------------------

_EVIDENCE_PASSAGE = (
    "Parameterised queries prevent SQL injection because user input is sent to the database "
    "separately from the query structure and can never be interpreted as executable SQL code."
)

_ANSWER_EVIDENCE = [
    {
        "document": "Module 9-Learner Guide.pdf",
        "page": 120,
        "kt_code": "KM-09-KT18",
        "passage": _EVIDENCE_PASSAGE,
        "reason": "Retrieved for KM-09-KT18 (Security topics every software developer must)",
    }
]

# Real CORPUS CHUNK shape (source/page/kt_code/text - see
# src.analysis.reference_analyzer.extract_corpus_chunks), for building a
# ReferenceCorpusIndex/corpus_chunks in the generate_memo integration tests
# below - distinct from _ANSWER_EVIDENCE above, which is already in the
# EVIDENCE shape (document/page/passage/reason) select_answer_evidence
# returns, used directly by the _answer_grounding_ok unit tests.
_ANSWER_CORPUS_CHUNKS = [
    {
        "source": "Module 9-Learner Guide.pdf",
        "page": 120,
        "kt_code": "KM-09-KT18",
        "text": _EVIDENCE_PASSAGE,
    }
]


def _security_question() -> dict[str, Any]:
    return {
        "id": "Q-E1",
        "section_id": "E",
        "marks": 6,
        "outcomes": ["KM-09-KT18"],
        "competencies": ["Security topics every software developer must know"],
        "scenario": "A colleague's code builds a SQL query by concatenating user input directly into the string.",
        "question": "Identify the vulnerability and rewrite the query safely using a parameterised query.",
        "sub_questions": [],
    }


def _grounded_memo_question(
    model_answer: str,
    criteria_description: str = "Correctly identifies SQL injection and rewrites the query using a parameterised query that separates user input from the query structure",
) -> dict[str, Any]:
    return {
        "question_id": "Q-E1",
        "total_marks": 6,
        "model_answer": model_answer,
        "criteria": [{"description": criteria_description, "marks": 6}],
        "accepted_alternatives": [],
    }


def test_answer_grounding_ok_returns_none_without_any_evidence():
    """TEST MODE (no retrieval evidence supplied at all) must not enforce
    answer grounding - see generate_memo's module docstring."""
    memo_question = _grounded_memo_question("Anything at all.")
    assert _answer_grounding_ok(memo_question, _security_question(), [], SecurityConfig()) is None


def test_answer_grounding_ok_accepts_a_well_grounded_relevant_answer():
    memo_question = _grounded_memo_question(
        "This is vulnerable to SQL injection. Parameterised queries prevent SQL injection because "
        "user input is sent to the database separately from the query structure, so it can never be "
        "interpreted as executable SQL code."
    )
    assert _answer_grounding_ok(memo_question, _security_question(), _ANSWER_EVIDENCE, SecurityConfig()) is None


def test_answer_grounding_ok_rejects_an_answer_unrelated_to_its_cited_evidence():
    memo_question = _grounded_memo_question(
        "This is a classic race condition. Use a mutex or lock to guard the critical section so two "
        "threads can never modify the shared counter at the same time."
    )
    reason = _answer_grounding_ok(memo_question, _security_question(), _ANSWER_EVIDENCE, SecurityConfig())
    assert reason is not None
    assert "similarity to its supplied answer evidence" in reason


def test_answer_grounding_ok_rejects_an_answer_that_does_not_address_the_question():
    # Passes the evidence-overlap floor (shares the evidence's own
    # vocabulary) but never engages with what THIS question actually asked
    # (a SQL-injection/parameterised-query scenario) - the relevance floor
    # must catch this independently of the evidence-overlap floor.
    memo_question = _grounded_memo_question(
        "Parameterised queries separate user input from the query structure so it is never executable "
        "SQL code, which is a general database security concept worth knowing in any application."
    )
    off_topic_question = {
        "id": "Q-E1",
        "section_id": "E",
        "marks": 6,
        "scenario": "A vehicle's onboard unit reports an odometer delta as the binary value 10110.",
        "question": "Determine the decimal equivalent and show the contribution of each bit position.",
        "sub_questions": [],
    }
    security_config = SecurityConfig(answer_grounding_min_overlap=0.0)
    reason = _answer_grounding_ok(memo_question, off_topic_question, _ANSWER_EVIDENCE, security_config)
    assert reason is not None
    assert "similarity to the question it claims to answer" in reason


def test_answer_grounding_ok_rejects_criteria_disconnected_from_the_model_answer():
    memo_question = {
        "question_id": "Q-E1",
        "total_marks": 6,
        "model_answer": (
            "This is vulnerable to SQL injection. Parameterised queries prevent SQL injection because "
            "user input is sent to the database separately from the query structure."
        ),
        "criteria": [{"description": "Correct binary-to-decimal conversion with working shown", "marks": 6}],
        "accepted_alternatives": [],
    }
    security_config = SecurityConfig(answer_grounding_min_overlap=0.0, answer_relevance_min_overlap=0.2)
    reason = _answer_grounding_ok(memo_question, _security_question(), _ANSWER_EVIDENCE, security_config)
    assert reason is not None
    assert "marking criteria have only" in reason


def test_generate_memo_retries_an_ungrounded_answer_then_accepts_a_grounded_one():
    ungrounded = _grounded_memo_question(
        "This is a classic race condition. Use a mutex to guard the critical section from concurrent access."
    )
    grounded = _grounded_memo_question(
        "This is vulnerable to SQL injection. Parameterised queries prevent SQL injection because user "
        "input is sent to the database separately from the query structure and can never be interpreted "
        "as executable SQL code."
    )
    provider = ScriptedMemoProvider([ungrounded, grounded])
    paper = {
        "paper_id": "test-paper",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 6,
        "sections": [{"id": "E", "questions": [_security_question()]}],
    }
    index = ReferenceCorpusIndex(_ANSWER_CORPUS_CHUNKS)

    memo = generate_memo(
        paper, provider, seed=1, security_config=SecurityConfig(memo_max_retries=3),
        retrieval_index=index, corpus_chunks=_ANSWER_CORPUS_CHUNKS,
    )

    assert provider.call_count == 2
    memo_question = memo["sections"][0]["questions"][0]
    assert memo_question["grounding"]
    assert memo_question["grounding"][0]["document"] == "Module 9-Learner Guide.pdf"
    assert memo["generation_meta"]["answer_grounded"] is True


def test_generate_memo_fails_loudly_when_answer_grounding_never_succeeds():
    always_ungrounded = _grounded_memo_question(
        "This is a classic race condition. Use a mutex to guard the critical section from concurrent access."
    )
    provider = ScriptedMemoProvider([always_ungrounded])
    paper = {
        "paper_id": "test-paper",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 6,
        "sections": [{"id": "E", "questions": [_security_question()]}],
    }
    index = ReferenceCorpusIndex(_ANSWER_CORPUS_CHUNKS)

    with pytest.raises(GenerationError, match="exhausted 2 memo generation attempt"):
        generate_memo(
            paper, provider, seed=1, security_config=SecurityConfig(memo_max_retries=2),
            retrieval_index=index, corpus_chunks=_ANSWER_CORPUS_CHUNKS,
        )
    assert provider.call_count == 2


def test_generate_memo_refuses_to_generate_when_no_answer_evidence_is_retrievable():
    """The non-negotiable source-of-truth rule (master prompt section 4):
    if the learner guides contain nothing to support answering a question,
    generation must be REJECTED, never silently produced from the model's
    own general knowledge."""
    provider = ScriptedMemoProvider([_grounded_memo_question("Anything.")])
    paper = {
        "paper_id": "test-paper",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 6,
        "sections": [{"id": "E", "questions": [_security_question()]}],
    }
    empty_index = ReferenceCorpusIndex([])

    with pytest.raises(GenerationError, match="no learner-guide evidence could be retrieved"):
        generate_memo(paper, provider, seed=1, retrieval_index=empty_index, corpus_chunks=[])
    assert provider.call_count == 0


def test_generate_memo_skips_answer_grounding_entirely_in_test_mode():
    """When retrieval_index/corpus_chunks are omitted (the existing unit-
    test call pattern used throughout the rest of this file), behaviour
    must be byte-identical to before the answer-RAG rework: no grounding
    requirement, an empty (not missing) grounding list, and
    generation_meta.answer_grounded is False."""
    response = _grounded_memo_question(
        "This is a classic race condition, unrelated to any retrieved evidence since none was supplied."
    )
    provider = ScriptedMemoProvider([response])
    paper = {
        "paper_id": "test-paper",
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "total_marks": 6,
        "sections": [{"id": "E", "questions": [_security_question()]}],
    }

    memo = generate_memo(paper, provider, seed=1)

    assert provider.call_count == 1
    memo_question = memo["sections"][0]["questions"][0]
    assert memo_question["grounding"] == []
    assert memo["generation_meta"]["answer_grounded"] is False
