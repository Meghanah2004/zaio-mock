from __future__ import annotations

from src.validation.novelty_checker import ReferenceCorpusIndex, check_paper_novelty


def _chunks():
    return [
        {"source": "Module 6-Learner Guide.pdf", "text": "Object oriented programming organizes software design around data or objects rather than functions and logic encapsulation abstraction inheritance polymorphism"},
        {"source": "Module 8-Learner Guide.pdf", "text": "A primary key uniquely identifies each record in a database table and a foreign key links one table to another table"},
    ]


def test_near_identical_text_scores_high_similarity():
    index = ReferenceCorpusIndex(_chunks())
    score, nearest = index.max_similarity(
        "Object oriented programming organizes software design around data or objects rather than functions and logic"
    )
    assert score > 0.7
    assert nearest["source"] == "Module 6-Learner Guide.pdf"


def test_unrelated_text_scores_low_similarity():
    index = ReferenceCorpusIndex(_chunks())
    score, _ = index.max_similarity("The volunteer sign-up form needs an email input and a submit button styled with flexbox")
    assert score < 0.35


def test_empty_corpus_returns_zero():
    index = ReferenceCorpusIndex([])
    score, nearest = index.max_similarity("anything at all")
    assert score == 0.0
    assert nearest is None


def test_check_paper_novelty_flags_high_overlap(valid_paper):
    index = ReferenceCorpusIndex(
        [{"source": "Module X.pdf", "text": "Explain what a variable is and give one example please"}]
    )
    result = check_paper_novelty(valid_paper, index, warn_threshold=0.35, flag_threshold=0.55)
    q_result = result["question_results"][0]
    assert q_result["status"] in ("flag_for_review", "regenerate")
    assert result["passed"] is (result["overall_status"] == "pass")


def test_check_paper_novelty_passes_when_dissimilar(valid_paper):
    index = ReferenceCorpusIndex(
        [{"source": "Module X.pdf", "text": "The quarterly financial audit revealed unrelated logistics warehouse inventory discrepancies"}]
    )
    result = check_paper_novelty(valid_paper, index, warn_threshold=0.35, flag_threshold=0.55)
    assert result["overall_status"] == "pass"
