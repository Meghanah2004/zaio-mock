from __future__ import annotations

from src.validation.grounding_validator import validate_grounding

_CORPUS_CHUNKS = [
    {
        "source": "Module 6-Learner Guide.pdf",
        "page": 62,
        "kt_code": "KM-06-KT06",
        "text": "HTML5 introduces new semantic elements such as header footer and section for structuring a page.",
    },
]

_EVIDENCE_PASSAGE = "HTML5 introduces new semantic elements such as header footer and section for structuring a page."


def _paper(question: dict, grounded_mode: bool = True) -> dict:
    return {
        "sections": [{"id": "B", "questions": [question]}],
        "generation_meta": {"grounded": grounded_mode},
    }


def _base_question(**overrides) -> dict:
    q = {
        "id": "Q-B1",
        "scenario": "A team at Acme Retail is rebuilding their internal staff portal's registration page.",
        "question": "Explain how the new portal's registration form should structure its sections for staff to navigate cleanly.",
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
    q.update(overrides)
    return q


def test_grounded_question_with_real_page_and_reasonable_overlap_passes():
    paper = _paper(_base_question())
    report = validate_grounding(paper, _CORPUS_CHUNKS)
    assert report.passed, [c for c in report.checks if not c.passed]


def test_missing_grounding_fails_when_paper_claims_grounded_mode():
    paper = _paper(_base_question(grounding=[]), grounded_mode=True)
    report = validate_grounding(paper, _CORPUS_CHUNKS)
    assert not report.passed
    failing = [c.name for c in report.checks if not c.passed]
    assert "grounding_present:Q-B1" in failing


def test_missing_grounding_is_informational_when_paper_was_not_generated_grounded():
    paper = _paper(_base_question(grounding=[]), grounded_mode=False)
    report = validate_grounding(paper, _CORPUS_CHUNKS)
    assert report.passed


def test_fabricated_page_number_is_rejected():
    question = _base_question(
        grounding=[
            {
                "document": "Module 6-Learner Guide.pdf",
                "page": 9999,  # never ingested - a fabricated citation
                "passage": _EVIDENCE_PASSAGE,
                "reason": "Retrieved for KM-06-KT06 (HTML5)",
            }
        ]
    )
    paper = _paper(question)
    report = validate_grounding(paper, _CORPUS_CHUNKS)
    assert not report.passed
    failing = {c.name: c.details for c in report.checks if not c.passed}
    assert "grounding_pages_exist:Q-B1" in failing
    assert "9999" in failing["grounding_pages_exist:Q-B1"]


def test_question_unrelated_to_its_cited_evidence_fails_overlap_check():
    question = _base_question(
        scenario="A team needs to reconcile till receipts using binary arithmetic and modulus operators.",
        question="Convert the binary value 1101 to decimal and show your working step by step.",
    )
    paper = _paper(question)
    report = validate_grounding(paper, _CORPUS_CHUNKS)
    assert not report.passed
    failing = [c.name for c in report.checks if not c.passed]
    assert "grounding_overlap_sufficient:Q-B1" in failing


def test_near_verbatim_copy_of_evidence_fails_the_anti_copying_check():
    question = _base_question(
        scenario=_EVIDENCE_PASSAGE,
        question=_EVIDENCE_PASSAGE,
    )
    paper = _paper(question)
    report = validate_grounding(paper, _CORPUS_CHUNKS)
    assert not report.passed
    failing = [c.name for c in report.checks if not c.passed]
    assert "grounding_not_near_copy:Q-B1" in failing
