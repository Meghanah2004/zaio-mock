from __future__ import annotations

from src.validation.cross_paper_novelty import (
    load_history,
    max_similarity_to_history,
    record_paper,
    write_history,
)


def _paper(paper_id: str, question_text: str) -> dict:
    return {
        "paper_id": paper_id,
        "sections": [
            {
                "id": "B",
                "questions": [
                    {
                        "id": "Q-B1",
                        "scenario": None,
                        "question": question_text,
                        "sub_questions": [],
                    }
                ],
            }
        ],
    }


def test_record_paper_adds_entries_per_section():
    history = record_paper({}, _paper("paper-01", "Design a validation strategy for a signup form."))
    assert "B" in history
    assert history["B"][0]["paper_id"] == "paper-01"
    assert "validation strategy" in history["B"][0]["text"]


def test_max_similarity_to_history_finds_a_near_identical_prior_question():
    history = record_paper({}, _paper("paper-01", "Design a validation strategy for a customer signup form."))
    score, source_paper = max_similarity_to_history(
        "Design a validation strategy for a customer signup form.", "B", history
    )
    assert score > 0.9
    assert source_paper == "paper-01"


def test_max_similarity_to_history_is_low_for_a_genuinely_different_question():
    history = record_paper({}, _paper("paper-01", "Design a validation strategy for a customer signup form."))
    score, _ = max_similarity_to_history(
        "Write a SQL query joining products and suppliers ordered by stock level.", "B", history
    )
    assert score < 0.2


def test_max_similarity_to_history_ignores_unrelated_sections():
    history = record_paper({}, _paper("paper-01", "Design a validation strategy for a customer signup form."))
    score, source_paper = max_similarity_to_history(
        "Design a validation strategy for a customer signup form.", "C", history
    )
    assert score == 0.0
    assert source_paper is None


def test_history_round_trips_through_disk(tmp_path):
    path = tmp_path / "generation-history.json"
    history = record_paper({}, _paper("paper-01", "Design a validation strategy for a customer signup form."))
    write_history(history, path)

    reloaded = load_history(path)
    assert reloaded == history


def test_load_history_returns_empty_dict_when_file_does_not_exist(tmp_path):
    assert load_history(tmp_path / "does-not-exist.json") == {}


def test_third_paper_is_checked_against_both_prior_papers_not_just_the_latest():
    """Regression test for the "not a two-paper special case" requirement:
    max_similarity_to_history must find a match against ANY accumulated
    prior paper, including one that is NOT the most recently recorded one -
    proving the check scans the whole history, not just "the last paper"."""
    history = record_paper({}, _paper("paper-01", "Design a validation strategy for a customer signup form."))
    history = record_paper(history, _paper("paper-02", "Write a SQL query joining products and suppliers."))

    # A paper-03 candidate that resembles paper-01 (the OLDER paper, not the
    # immediately preceding paper-02) must still be caught.
    score, source_paper = max_similarity_to_history(
        "Design a validation strategy for a customer signup form.", "B", history
    )
    assert score > 0.9
    assert source_paper == "paper-01"


def test_fourth_paper_history_accumulates_across_three_prior_papers_with_no_special_casing():
    """Same mechanism, one more generation deep, with no paper-number-aware
    code anywhere - proves the design generalizes to N without needing new
    logic per requirement 11."""
    history: dict = {}
    for i, text in enumerate(
        [
            "Design a validation strategy for a customer signup form.",
            "Write a SQL query joining products and suppliers.",
            "Refactor a plain object into an encapsulated class with a setter.",
        ],
        start=1,
    ):
        history = record_paper(history, _paper(f"paper-0{i}", text))

    assert len(history["B"]) == 3
    # A paper-04 candidate matching ANY of the three (here, the middle one)
    # is still caught.
    score, source_paper = max_similarity_to_history(
        "Write a SQL query joining products and suppliers.", "B", history
    )
    assert score > 0.9
    assert source_paper == "paper-02"

    # A genuinely different paper-04 candidate is not flagged against any of them.
    score, _ = max_similarity_to_history(
        "Explain the difference between the testing phase and the design phase of the SDLC.", "B", history
    )
    assert score < 0.2


def test_record_paper_caps_entries_per_section():
    history: dict = {}
    for i in range(60):
        history = record_paper(history, _paper(f"paper-{i:02d}", f"Question variant number {i} about something."))
    from src.validation.cross_paper_novelty import MAX_HISTORY_ENTRIES_PER_SECTION

    assert len(history["B"]) == MAX_HISTORY_ENTRIES_PER_SECTION
    # Oldest entries are dropped, newest kept.
    assert history["B"][-1]["paper_id"] == "paper-59"
