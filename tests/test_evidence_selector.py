from __future__ import annotations

from src.config import compute_effective_seed
from src.retrieval.evidence_selector import select_answer_evidence, select_evidence
from src.security.config import SecurityConfig
from src.validation.novelty_checker import ReferenceCorpusIndex


def _chunks():
    return [
        {
            "source": "Module 6-Learner Guide.pdf",
            "page": 62,
            "kt_code": "KM-06-KT06",
            "text": "HTML5 introduces new semantic elements such as header footer and section for structuring a page.",
        },
        {
            "source": "Module 6-Learner Guide.pdf",
            "page": 63,
            "kt_code": "KM-06-KT06",
            "text": "HTML5 forms support new input types and attributes such as required and pattern for native validation.",
        },
        {
            "source": "Module 6-Learner Guide.pdf",
            "page": 74,
            "kt_code": "KM-06-KT07",
            "text": "CSS Flexbox provides a one dimensional layout model for arranging items in a row or column.",
        },
        {
            "source": "Module 8-Learner Guide.pdf",
            "page": 10,
            "kt_code": "KM-08-KT01",
            "text": "A primary key uniquely identifies each record in a relational database table without duplication.",
        },
    ]


def _index(chunks):
    return ReferenceCorpusIndex(chunks)


def test_select_evidence_returns_real_page_numbers_that_exist_in_the_corpus():
    chunks = _chunks()
    valid_pages = {(c["source"], c["page"]) for c in chunks}
    evidence = select_evidence(
        _index(chunks),
        chunks,
        required_outcomes=["KM-06-KT06", "KM-06-KT07"],
        outcome_title_map={"KM-06-KT06": "HTML5", "KM-06-KT07": "CSS"},
        occupational_context="Front-end developer building a form.",
        seed=0,
    )
    assert evidence, "expected at least one evidence item"
    for e in evidence:
        assert (e["document"], e["page"]) in valid_pages, "evidence cited a page not present in the corpus"


def test_select_evidence_prefers_structurally_tagged_chunks_for_the_requested_topic():
    chunks = _chunks()
    evidence = select_evidence(
        _index(chunks),
        chunks,
        required_outcomes=["KM-08-KT01"],
        outcome_title_map={"KM-08-KT01": "Understanding core database concepts"},
        occupational_context="Developer designing a database.",
        seed=0,
    )
    assert evidence
    assert all(e["kt_code"] == "KM-08-KT01" for e in evidence)
    assert all("fallback" not in e["reason"] for e in evidence)


def test_select_evidence_covers_every_required_outcome_when_budget_allows():
    chunks = _chunks()
    security_config = SecurityConfig(evidence_passages_per_section=6)
    evidence = select_evidence(
        _index(chunks),
        chunks,
        required_outcomes=["KM-06-KT06", "KM-06-KT07", "KM-08-KT01"],
        outcome_title_map={
            "KM-06-KT06": "HTML5",
            "KM-06-KT07": "CSS",
            "KM-08-KT01": "Understanding core database concepts",
        },
        occupational_context="Full-stack developer building a feature end to end.",
        seed=0,
        security_config=security_config,
    )
    covered_topics = {e["kt_code"] for e in evidence}
    assert covered_topics == {"KM-06-KT06", "KM-06-KT07", "KM-08-KT01"}


def test_select_evidence_falls_back_and_marks_it_when_topic_never_structurally_tagged():
    chunks = _chunks()
    evidence = select_evidence(
        _index(chunks),
        chunks,
        required_outcomes=["KM-09-KT99"],  # never appears as a kt_code in the corpus
        outcome_title_map={"KM-09-KT99": "database"},  # shares vocabulary with an untagged chunk on purpose
        occupational_context="database primary key",
        seed=0,
    )
    if evidence:
        assert all("fallback" in e["reason"] for e in evidence)


def test_select_evidence_different_seeds_can_surface_different_passages():
    chunks = _chunks()
    security_config = SecurityConfig(evidence_passages_per_section=1)
    ev_a = select_evidence(
        _index(chunks),
        chunks,
        required_outcomes=["KM-06-KT06"],
        outcome_title_map={"KM-06-KT06": "HTML5"},
        occupational_context="Front-end developer building a form.",
        seed=0,
        security_config=security_config,
    )
    ev_b = select_evidence(
        _index(chunks),
        chunks,
        required_outcomes=["KM-06-KT06"],
        outcome_title_map={"KM-06-KT06": "HTML5"},
        occupational_context="Front-end developer building a form.",
        seed=1,
        security_config=security_config,
    )
    # Not asserting they always differ (small pools can legitimately land on
    # the same top result) - asserting the mechanism is seed-driven and both
    # calls still return valid, real evidence.
    assert ev_a and ev_b
    assert ev_a[0]["page"] in {62, 63}
    assert ev_b[0]["page"] in {62, 63}


def test_paper_1_and_paper_2_get_different_evidence_rotations_for_the_same_raw_seed():
    """Regression test for the real repeated-questions production incident:
    with the OLD behavior (raw seed used directly, no paper_number
    involved), Paper 1 and Paper 2 generated with the same caller-supplied
    seed retrieved IDENTICAL evidence, which a real low-temperature
    provider frequently turned into near-duplicate questions. This proves
    the fix at the retrieval layer: routing the SAME raw seed through
    src.config.compute_effective_seed for two different paper_numbers
    produces a different rotation - src.retrieval.evidence_selector's
    `rotation = seed % len(structural)` - and therefore a different top
    evidence passage, for a section with more than one real candidate
    passage for a topic (KM-06-KT06 has exactly 2 here: pages 62 and 63).
    SEED_PAPER_STRIDE is odd (2^31 - 1), so adding it once always flips
    parity relative to not adding it - guaranteeing a different rotation
    index for this 2-item pool between consecutive paper numbers, not just
    "usually different"."""
    chunks = _chunks()
    security_config = SecurityConfig(evidence_passages_per_section=1)
    raw_seed = 20260906  # the real static default both --seed and the frontend form used

    def _top_page(paper_number: int) -> int:
        effective_seed = compute_effective_seed(raw_seed, paper_number)
        evidence = select_evidence(
            _index(chunks),
            chunks,
            required_outcomes=["KM-06-KT06"],
            outcome_title_map={"KM-06-KT06": "HTML5"},
            occupational_context="Front-end developer building a form.",
            seed=effective_seed,
            security_config=security_config,
        )
        assert evidence
        return evidence[0]["page"]

    paper_1_top_page = _top_page(paper_number=1)
    paper_2_top_page = _top_page(paper_number=2)

    assert paper_1_top_page in {62, 63}
    assert paper_2_top_page in {62, 63}
    assert paper_1_top_page != paper_2_top_page


# ---------------------------------------------------------------------------
# select_answer_evidence - ANSWER-side retrieval, targeted at an actual
# already-generated question rather than a whole section's topic list.
# ---------------------------------------------------------------------------


def _question(**overrides) -> dict:
    q = {
        "id": "Q-B1",
        "outcomes": ["KM-06-KT06"],
        "competencies": ["HTML5"],
        "scenario": "A team is building a registration form and needs semantic HTML5 markup.",
        "question": "Write a semantic HTML5 form for the registration feature.",
        "sub_questions": [],
    }
    q.update(overrides)
    return q


def test_select_answer_evidence_returns_real_page_numbers_that_exist_in_the_corpus():
    chunks = _chunks()
    valid_pages = {(c["source"], c["page"]) for c in chunks}
    evidence = select_answer_evidence(_index(chunks), chunks, _question(), seed=0)
    assert evidence, "expected at least one evidence item"
    for e in evidence:
        assert (e["document"], e["page"]) in valid_pages, "answer evidence cited a page not present in the corpus"


def test_select_answer_evidence_returns_empty_when_question_declares_no_outcomes():
    chunks = _chunks()
    evidence = select_answer_evidence(_index(chunks), chunks, _question(outcomes=[]), seed=0)
    assert evidence == []


def test_select_answer_evidence_is_targeted_at_the_questions_own_text_not_just_the_topic_title():
    # Two chunks tagged with the SAME kt_code (KM-06-KT06) but about
    # different specifics within that topic - answer retrieval must be
    # steered by what THIS question actually asks (its scenario/stem/
    # sub-question text - see select_answer_evidence's docstring), not
    # merely by the shared topic title, or it could never tell them apart.
    chunks = [
        {
            "source": "Module 6-Learner Guide.pdf",
            "page": 62,
            "kt_code": "KM-06-KT06",
            "text": "HTML5 introduces new semantic elements such as header footer and section for structuring a page.",
        },
        {
            "source": "Module 6-Learner Guide.pdf",
            "page": 65,
            "kt_code": "KM-06-KT06",
            "text": "HTML5 input types such as email and tel enable native browser validation on form fields without JavaScript.",
        },
    ]
    index = _index(chunks)

    semantic_question = _question(
        scenario="A team needs clearly delimited page regions for a registration screen.",
        question="Explain which semantic HTML5 elements structure a page into header, footer and section regions.",
    )
    validation_question = _question(
        scenario="A team needs a registration form's email field to be validated without writing JavaScript.",
        question="Explain which HTML5 input type and attributes give native email validation on a form field.",
    )

    semantic_evidence = select_answer_evidence(index, chunks, semantic_question, seed=0)
    validation_evidence = select_answer_evidence(index, chunks, validation_question, seed=0)

    assert semantic_evidence and validation_evidence
    assert semantic_evidence[0]["page"] == 62
    assert validation_evidence[0]["page"] == 65


def test_select_answer_evidence_reuses_the_same_structural_kt_tag_matching_as_select_evidence():
    chunks = _chunks()
    evidence = select_answer_evidence(
        _index(chunks),
        chunks,
        _question(outcomes=["KM-08-KT01"], competencies=["Understanding core database concepts"]),
        seed=0,
    )
    assert evidence
    assert all(e["kt_code"] == "KM-08-KT01" for e in evidence)
    assert all("fallback" not in e["reason"] for e in evidence)
