from __future__ import annotations

from src.validation.answer_grounding_validator import validate_answer_grounding

_CORPUS_CHUNKS = [
    {
        "source": "Module 6-Learner Guide.pdf",
        "page": 62,
        "kt_code": "KM-06-KT06",
        "text": "HTML5 introduces new semantic elements such as header footer and section for structuring a page.",
    },
]

_EVIDENCE_PASSAGE = "HTML5 introduces new semantic elements such as header footer and section for structuring a page."


def _memo(memo_question: dict, answer_grounded: bool = True) -> dict:
    return {
        "sections": [{"id": "B", "questions": [memo_question]}],
        "generation_meta": {"answer_grounded": answer_grounded},
    }


def _base_memo_question(**overrides) -> dict:
    mq = {
        "question_id": "Q-B1",
        "model_answer": (
            "Use HTML5's semantic elements - header, footer, and section - to structure the registration "
            "page so each part of the form is clearly delimited for both users and assistive technology."
        ),
        "sub_questions": [],
        "grounding": [
            {
                "document": "Module 6-Learner Guide.pdf",
                "page": 62,
                "passage": _EVIDENCE_PASSAGE,
                "reason": "Retrieved for KM-06-KT06 (HTML5)",
            }
        ],
    }
    mq.update(overrides)
    return mq


def test_grounded_answer_with_real_page_and_reasonable_overlap_passes():
    memo = _memo(_base_memo_question())
    report = validate_answer_grounding(memo, _CORPUS_CHUNKS)
    assert report.passed, [c for c in report.checks if not c.passed]


def test_missing_answer_grounding_fails_when_memo_claims_answer_grounded_mode():
    memo = _memo(_base_memo_question(grounding=[]), answer_grounded=True)
    report = validate_answer_grounding(memo, _CORPUS_CHUNKS)
    assert not report.passed
    failing = [c.name for c in report.checks if not c.passed]
    assert "answer_grounding_present:Q-B1" in failing


def test_missing_answer_grounding_is_informational_when_memo_was_not_generated_answer_grounded():
    memo = _memo(_base_memo_question(grounding=[]), answer_grounded=False)
    report = validate_answer_grounding(memo, _CORPUS_CHUNKS)
    assert report.passed


def test_fabricated_page_number_in_answer_grounding_is_rejected():
    memo_question = _base_memo_question(
        grounding=[
            {
                "document": "Module 6-Learner Guide.pdf",
                "page": 9999,  # never ingested - a fabricated citation
                "passage": _EVIDENCE_PASSAGE,
                "reason": "Retrieved for KM-06-KT06 (HTML5)",
            }
        ]
    )
    memo = _memo(memo_question)
    report = validate_answer_grounding(memo, _CORPUS_CHUNKS)
    assert not report.passed
    failing = {c.name: c.details for c in report.checks if not c.passed}
    assert "answer_grounding_pages_exist:Q-B1" in failing
    assert "9999" in failing["answer_grounding_pages_exist:Q-B1"]


def test_answer_unrelated_to_its_cited_evidence_fails_overlap_check():
    memo_question = _base_memo_question(
        model_answer=(
            "17 % 5 = 2; 2 * 3 = 6; 2 + 6 = 8; 8 - 1 = 7. The total therefore ends up being 7 once every "
            "operator's precedence is applied in the correct order."
        ),
    )
    memo = _memo(memo_question)
    report = validate_answer_grounding(memo, _CORPUS_CHUNKS)
    assert not report.passed
    failing = [c.name for c in report.checks if not c.passed]
    assert "answer_grounding_overlap_sufficient:Q-B1" in failing


def test_answer_grounding_has_no_near_copy_ceiling_unlike_question_grounding():
    # Unlike grounding_validator's question-side check, a model answer that
    # closely echoes its cited evidence is CORRECT, not a violation - see
    # src/validation/answer_grounding_validator.py's module docstring.
    memo_question = _base_memo_question(model_answer=_EVIDENCE_PASSAGE)
    memo = _memo(memo_question)
    report = validate_answer_grounding(memo, _CORPUS_CHUNKS)
    assert report.passed, [c for c in report.checks if not c.passed]


def test_sub_question_model_answers_are_included_in_the_overlap_check():
    memo_question = _base_memo_question(
        model_answer="See per-part model answers below.",
        sub_questions=[
            {
                "id": "1",
                "model_answer": (
                    "HTML5 introduces new semantic elements such as header, footer, and section for "
                    "structuring a page - use them to lay out the registration form's regions."
                ),
            }
        ],
    )
    memo = _memo(memo_question)
    report = validate_answer_grounding(memo, _CORPUS_CHUNKS)
    assert report.passed, [c for c in report.checks if not c.passed]
