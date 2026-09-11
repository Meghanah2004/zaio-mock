"""Integration tests for the grounding/cross-paper-novelty enforcement added
to src/generation/question_generator.generate_paper as part of the Phase 1
rework: a question must be derived from its supplied evidence (not invented,
not copied) and must not collapse into a question already used in an
earlier paper for the same section.

Uses a small scripted fake provider (not MockProvider, not a real API call)
so each scenario's provider output is fully controlled and deterministic -
this is the TEST MODE half of the split described in
src/generation/question_generator.py's module docstring.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from src.generation.llm_utils import GenerationError
from src.generation.question_generator import generate_paper
from src.providers.base import LLMProvider
from src.security.config import SecurityConfig

EVIDENCE_TEXT = (
    "HTML5 introduces new semantic elements such as header footer and section for structuring a page."
)

GROUNDED_TEXT = (
    "A developer at Acme Retail needs to rebuild a page using new semantic elements such as header "
    "and section for structuring content."
)

DIFFERENT_GROUNDED_TEXT = (
    "A team at Bright Bakery must update the site's about page - which semantic HTML5 elements like "
    "header and section would you use to organise the content, and why does that structure matter?"
)

THIRD_GROUNDED_TEXT = (
    "Coastal Traders wants a redesigned contact page - propose which semantic HTML5 elements such as "
    "header and section you would introduce and justify how they improve the page's structure."
)

UNGROUNDED_TEXT = (
    "A cashier needs to reconcile till totals using modulus and operator precedence rules on paper."
)


class ScriptedProvider(LLMProvider):
    """Returns each entry in ``responses`` in order, repeating the last one
    once exhausted, as raw JSON text. Records every user_prompt it was
    called with so a test can inspect what retry feedback a later attempt
    actually received."""

    name = "scripted"

    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = responses
        self.call_count = 0
        self.user_prompts: list[str] = []

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        self.user_prompts.append(user_prompt)
        content = self._responses[min(self.call_count, len(self._responses) - 1)]
        self.call_count += 1
        return json.dumps(content)


def _question(scenario: str, question: str) -> dict[str, Any]:
    return {
        "type": "scenario_short_answer",
        "scenario": scenario,
        "question": question,
        "expected_response_type": "short_answer",
        "outcomes": ["KM-06-KT06"],
    }


def _blueprint() -> dict[str, Any]:
    return {
        "paper_id": "test-paper",
        "qualification_title": "Test Qualification",
        "nqf_level": 5,
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "duration_minutes": 60,
        "total_marks": 10,
        "instructions": ["Answer all."],
        "sections": [
            {
                "id": "B",
                "title": "Front-End Web Development",
                "marks": 10,
                "outcomes": ["KM-06-KT06"],
                "competencies": ["HTML5"],
                "required_outcomes": ["KM-06-KT06"],
                "difficulty": "intermediate",
                "question_types": ["scenario_short_answer"],
                "occupational_context": "Front-end developer building a page for a client site.",
            }
        ],
    }


def _evidence_by_section() -> dict[str, list[dict[str, Any]]]:
    return {
        "B": [
            {
                "document": "Module 6-Learner Guide.pdf",
                "page": 62,
                "kt_code": "KM-06-KT06",
                "passage": EVIDENCE_TEXT,
                "reason": "Retrieved for KM-06-KT06 (HTML5)",
                "relevance": 0.42,
            }
        ]
    }


def test_grounded_question_is_accepted_and_carries_provenance():
    provider = ScriptedProvider([_question(GROUNDED_TEXT, "Which elements would you use and why?")])
    paper = generate_paper(
        _blueprint(), provider, seed=1, evidence_by_section=_evidence_by_section(), security_config=SecurityConfig()
    )
    question = paper["sections"][0]["questions"][0]
    assert question["grounding"] == [
        {
            "document": "Module 6-Learner Guide.pdf",
            "page": 62,
            "passage": EVIDENCE_TEXT,
            "reason": "Retrieved for KM-06-KT06 (HTML5)",
        }
    ]
    assert paper["generation_meta"]["grounded"] is True


def test_ungrounded_question_is_rejected_after_exhausting_retries():
    provider = ScriptedProvider([_question(UNGROUNDED_TEXT, "Compute 17 mod 5 and show your working.")])
    with pytest.raises(GenerationError, match="rejected"):
        generate_paper(
            _blueprint(),
            provider,
            seed=1,
            evidence_by_section=_evidence_by_section(),
            security_config=SecurityConfig(grounding_max_retries=2),
        )
    assert provider.call_count == 2  # actually retried, not rejected on the first attempt alone


def test_near_verbatim_copy_of_evidence_is_rejected():
    provider = ScriptedProvider([_question(EVIDENCE_TEXT, EVIDENCE_TEXT)])
    with pytest.raises(GenerationError, match="rejected"):
        generate_paper(
            _blueprint(),
            provider,
            seed=1,
            evidence_by_section=_evidence_by_section(),
            security_config=SecurityConfig(grounding_max_retries=2),
        )


def test_paper_1_can_be_generated_with_empty_history():
    """Requirement: "Paper 1 can be generated." No prior history exists yet
    - generation_history={} - so nothing is rejected on novelty grounds,
    only grounding is checked."""
    provider = ScriptedProvider([_question(GROUNDED_TEXT, "Which elements would you use and why?")])
    paper = generate_paper(
        _blueprint(),
        provider,
        seed=1,
        evidence_by_section=_evidence_by_section(),
        generation_history={},
        security_config=SecurityConfig(),
    )
    assert paper["sections"][0]["questions"][0]["scenario"] == GROUNDED_TEXT


def test_paper_2_is_rejected_for_duplicating_paper_1_then_accepted_once_genuinely_different():
    """Requirement: "Paper 2 differs meaningfully from Paper 1" - and
    specifically must be REJECTED, not silently accepted, if the model's
    first attempt duplicates Paper 1."""
    history = {"B": [{"paper_id": "paper-01", "question_id": "Q-B1", "text": f"{GROUNDED_TEXT} {GROUNDED_TEXT}"}]}
    provider = ScriptedProvider(
        [
            _question(GROUNDED_TEXT, GROUNDED_TEXT),  # duplicates paper-01 - must be rejected
            _question(DIFFERENT_GROUNDED_TEXT, "Justify your structural choices for the about page."),
        ]
    )
    paper = generate_paper(
        _blueprint(),
        provider,
        seed=1,
        evidence_by_section=_evidence_by_section(),
        generation_history=history,
        security_config=SecurityConfig(grounding_max_retries=3),
    )
    assert provider.call_count == 2
    assert paper["sections"][0]["questions"][0]["scenario"] == DIFFERENT_GROUNDED_TEXT


def test_paper_3_is_checked_against_both_paper_1_and_paper_2_not_just_the_latest():
    """Requirement: "Paper 3 is compared against BOTH previous papers," not
    only the immediately preceding one. History here holds TWO prior
    papers' questions for section B. The scripted provider's first attempt
    duplicates the OLDER paper (paper-01, not paper-02, the most recent) -
    if the novelty check only looked at "the latest" paper this would be
    wrongly accepted. Its second attempt duplicates paper-02. Only the
    third, genuinely novel attempt is accepted."""
    history = {
        "B": [
            {"paper_id": "paper-01", "question_id": "Q-B1", "text": f"{GROUNDED_TEXT} {GROUNDED_TEXT}"},
            {
                "paper_id": "paper-02",
                "question_id": "Q-B1",
                "text": f"{DIFFERENT_GROUNDED_TEXT} {DIFFERENT_GROUNDED_TEXT}",
            },
        ]
    }
    provider = ScriptedProvider(
        [
            _question(GROUNDED_TEXT, GROUNDED_TEXT),  # duplicates the OLDER paper-01
            _question(DIFFERENT_GROUNDED_TEXT, DIFFERENT_GROUNDED_TEXT),  # duplicates paper-02
            _question(THIRD_GROUNDED_TEXT, "Justify your structural choices for the contact page."),
        ]
    )
    paper = generate_paper(
        _blueprint(),
        provider,
        seed=1,
        evidence_by_section=_evidence_by_section(),
        generation_history=history,
        security_config=SecurityConfig(grounding_max_retries=4),
    )
    assert provider.call_count == 3
    assert paper["sections"][0]["questions"][0]["scenario"] == THIRD_GROUNDED_TEXT
    # paper_number is never referenced anywhere in generate_paper - this
    # scenario is indistinguishable, mechanically, from a hypothetical
    # "paper 37 vs papers 1..36" run with a longer history dict.


def test_question_too_similar_to_an_earlier_paper_is_rejected_and_regenerated():
    history = {"B": [{"paper_id": "paper-01", "question_id": "Q-B1", "text": f"{GROUNDED_TEXT} {GROUNDED_TEXT}"}]}
    provider = ScriptedProvider(
        [
            _question(GROUNDED_TEXT, GROUNDED_TEXT),  # duplicate of paper-01's question - must be rejected
            _question(DIFFERENT_GROUNDED_TEXT, "Justify your structural choices for the about page."),
        ]
    )
    paper = generate_paper(
        _blueprint(),
        provider,
        seed=1,
        evidence_by_section=_evidence_by_section(),
        generation_history=history,
        security_config=SecurityConfig(grounding_max_retries=3),
    )
    assert provider.call_count == 2
    accepted_scenario = paper["sections"][0]["questions"][0]["scenario"]
    assert accepted_scenario == DIFFERENT_GROUNDED_TEXT


def test_prompt_actually_contains_the_retrieved_evidence_text_and_page():
    from src.generation.question_generator import _build_question_prompt

    section = _blueprint()["sections"][0]
    evidence = _evidence_by_section()["B"]
    _, user_prompt = _build_question_prompt(section, evidence)

    assert EVIDENCE_TEXT in user_prompt
    assert "Module 6-Learner Guide.pdf" in user_prompt
    assert "page 62" in user_prompt


def test_no_evidence_supplied_for_a_section_in_evidence_map_fails_loudly_rather_than_inventing():
    blueprint = _blueprint()
    provider = ScriptedProvider([_question(GROUNDED_TEXT, "Which elements would you use and why?")])
    with pytest.raises(GenerationError, match="no learner-guide evidence"):
        generate_paper(blueprint, provider, seed=1, evidence_by_section={"B": []}, security_config=SecurityConfig())


def test_missing_top_level_expected_response_type_is_derived_from_sub_questions():
    """Regression test for a real production failure: a real Gemini call
    for a design_task question (which always carries sub_questions, see
    _SECTION_C_VARIANTS in src/providers/mock_provider.py) omitted the
    top-level 'expected_response_type' field. Root cause: the prompt
    template's own JSON example described that field as needed only "if no
    sub_questions", so a strict instruction-following model reasonably
    omitted it when sub_questions (each with their OWN
    expected_response_type) were present. The prompt now states the field
    is required unconditionally; this test locks in the code-side fallback
    that makes the pipeline robust regardless - see
    src.generation.question_generator._resolve_expected_response_type.
    Nothing here weakens schemas/paper.schema.json, which still requires
    'expected_response_type' on the FINAL question object - this only
    changes what the PROVIDER is trusted to supply directly.
    """
    raw_response = {
        "type": "design_task",
        "scenario": (
            "A developer at Acme Retail needs to rebuild a page using new semantic elements such as "
            "header and section for structuring content."
        ),
        "question": "Model the following aspects of the feature using UML.",
        "sub_questions": [
            {"id": "1", "prompt": "Describe a class diagram for this feature.", "marks": 6, "expected_response_type": "structured_uml_description"},
            {"id": "2", "prompt": "Describe the sequence of messages for this flow.", "marks": 4, "expected_response_type": "structured_uml_description"},
        ],
        "outcomes": ["KM-06-KT06"],
        # NOTE: no top-level "expected_response_type" - this is the exact
        # shape a real Gemini response had for Section C.
    }
    provider = ScriptedProvider([raw_response])

    paper = generate_paper(
        _blueprint(), provider, seed=1, evidence_by_section=_evidence_by_section(), security_config=SecurityConfig()
    )

    question = paper["sections"][0]["questions"][0]
    assert question["expected_response_type"] == "structured_uml_description"
    assert question["sub_questions"][0]["expected_response_type"] == "structured_uml_description"


def test_missing_expected_response_type_with_no_sub_questions_still_raises():
    """The fallback above is scoped exactly to the sub_questions-present
    case - it must NOT silently accept a response with no
    expected_response_type and no sub_questions to derive one from, which
    would be an actual validation weakening rather than a fix."""
    raw_response = {
        "type": "scenario_short_answer",
        "scenario": GROUNDED_TEXT,
        "question": "Which elements would you use and why?",
        "outcomes": ["KM-06-KT06"],
        # No "expected_response_type", no "sub_questions" - genuinely incomplete.
    }
    provider = ScriptedProvider([raw_response])

    with pytest.raises(GenerationError, match="expected_response_type"):
        generate_paper(
            _blueprint(),
            provider,
            seed=1,
            evidence_by_section=_evidence_by_section(),
            security_config=SecurityConfig(grounding_max_retries=1),
        )


def test_resolve_expected_response_type_unit_cases():
    from src.generation.question_generator import _resolve_expected_response_type

    # 1. Top-level field present - used as-is, nothing derived.
    assert _resolve_expected_response_type({"expected_response_type": "short_answer"}, [], "Q-A1") == "short_answer"

    # 2. Missing top-level, sub_questions declare a shared type - deduped and reused.
    sub_qs = [
        {"id": "1", "expected_response_type": "structured_uml_description"},
        {"id": "2", "expected_response_type": "structured_uml_description"},
    ]
    assert _resolve_expected_response_type({}, sub_qs, "Q-C1") == "structured_uml_description"

    # 3. Missing top-level, sub_questions declare DIFFERENT types - both preserved, deduped, joined.
    sub_qs_mixed = [
        {"id": "1", "expected_response_type": "sql_code"},
        {"id": "2", "expected_response_type": "short_answer"},
    ]
    assert _resolve_expected_response_type({}, sub_qs_mixed, "Q-D1") == "sql_code; short_answer"

    # 4. Missing top-level, sub_questions present but none declare a type - safe literal fallback.
    sub_qs_untyped = [{"id": "1"}, {"id": "2"}]
    assert _resolve_expected_response_type({}, sub_qs_untyped, "Q-E1") == "see sub_questions"

    # 5. Missing top-level, no sub_questions at all - genuinely unrecoverable, must raise.
    with pytest.raises(GenerationError, match="expected_response_type"):
        _resolve_expected_response_type({}, [], "Q-F1")


# ---------------------------------------------------------------------------
# Regression tests for a real production failure: a real Groq call for
# Section D ("Data, Databases and Querying", target 20 marks) returned
# "Q-D1: generated marks (25) do not equal section 'D' target marks (20)".
# Root cause: the section's target marks were stated once, generically,
# amid a lot of other prompt content (evidence, outcome codes) with no
# reinforced, individually-checkable budget - the same class of defect
# already fixed for memo criteria (src/generation/memo_generator.py). Fixed
# the same way: an explicit MARKS BUDGET block in the prompt
# (_build_question_marks_budget), plus making _normalize_question's marks
# check retry-eligible in generate_paper's existing grounding/novelty retry
# loop, instead of aborting the whole paper on one bad roll.
# ---------------------------------------------------------------------------
def _section_d_blueprint() -> dict[str, Any]:
    return {
        "paper_id": "test-paper",
        "qualification_title": "Test Qualification",
        "nqf_level": 5,
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "duration_minutes": 60,
        "total_marks": 20,
        "instructions": ["Answer all."],
        "sections": [
            {
                "id": "D",
                "title": "Data, Databases and Querying",
                "marks": 20,
                "outcomes": ["KM-08-KT01"],
                "competencies": ["Understanding core database concepts"],
                "required_outcomes": ["KM-08-KT01"],
                "difficulty": "intermediate",
                "question_types": ["code_writing"],
                "occupational_context": "Developer designing a relational database for an application.",
            }
        ],
    }


def _section_d_evidence_by_section() -> dict[str, list[dict[str, Any]]]:
    return {
        "D": [
            {
                "document": "Module 8-Learner Guide.pdf",
                "page": 10,
                "kt_code": "KM-08-KT01",
                "passage": "A primary key uniquely identifies each record in a relational database table without duplication.",
                "reason": "Retrieved for KM-08-KT01 (Understanding core database concepts)",
                "relevance": 0.4,
            }
        ]
    }


def _question_with_sub_marks(sub_marks: list[int]) -> dict[str, Any]:
    return {
        "type": "code_writing",
        "scenario": (
            "A developer at Acme Retail needs a small relational database to track products and "
            "suppliers, using primary keys to identify each product record without duplication."
        ),
        "question": "Complete the following database tasks.",
        "sub_questions": [
            {
                "id": str(i),
                "prompt": f"Sub-task {i}: write the relevant SQL.",
                "marks": m,
                "expected_response_type": "sql_code",
            }
            for i, m in enumerate(sub_marks, start=1)
        ],
        "outcomes": ["KM-08-KT01"],
    }


def test_section_marks_mismatch_is_rejected_then_corrected_on_retry():
    """Reproduces the exact real failure shape: sub-question marks sum to
    25 for a section whose target is 20. The second attempt corrects it to
    sum to exactly 20. The pipeline must recover, not just fail."""
    bad_response = _question_with_sub_marks([10, 15])  # sums to 25, not 20
    good_response = _question_with_sub_marks([10, 10])  # sums to 20
    provider = ScriptedProvider([bad_response, good_response])

    paper = generate_paper(
        _section_d_blueprint(),
        provider,
        seed=1,
        evidence_by_section=_section_d_evidence_by_section(),
        security_config=SecurityConfig(grounding_max_retries=3),
    )

    assert provider.call_count == 2
    question = paper["sections"][0]["questions"][0]
    assert question["marks"] == 20
    assert sum(sq["marks"] for sq in question["sub_questions"]) == 20


def test_section_marks_mismatch_never_silently_changed_to_pass():
    """The corrected question's marks must come from the model's OWN
    corrected sub-question values, never from silently overriding a bad
    total to match the section target."""
    bad_response = _question_with_sub_marks([10, 15])
    good_response = _question_with_sub_marks([12, 8])  # different split, still sums to 20
    provider = ScriptedProvider([bad_response, good_response])

    paper = generate_paper(
        _section_d_blueprint(),
        provider,
        seed=1,
        evidence_by_section=_section_d_evidence_by_section(),
        security_config=SecurityConfig(grounding_max_retries=3),
    )

    sub_marks = {sq["id"]: sq["marks"] for sq in paper["sections"][0]["questions"][0]["sub_questions"]}
    assert sub_marks == {"1": 12, "2": 8}


def test_section_marks_mismatch_persists_and_raises_a_clear_error_after_exhausting_retries():
    """If every attempt is wrong, the pipeline must still raise - never
    accept, and never silently correct, a bad marks total."""
    always_wrong = _question_with_sub_marks([10, 15])
    provider = ScriptedProvider([always_wrong])

    with pytest.raises(GenerationError, match="exhausted 2 generation attempt"):
        generate_paper(
            _section_d_blueprint(),
            provider,
            seed=1,
            evidence_by_section=_section_d_evidence_by_section(),
            security_config=SecurityConfig(grounding_max_retries=2),
        )
    assert provider.call_count == 2


def test_marks_budget_states_the_exact_target_for_the_section():
    from src.generation.question_generator import _build_question_marks_budget

    section = _section_d_blueprint()["sections"][0]
    budget = _build_question_marks_budget(section)
    assert "exactly 20 mark(s) in total" in budget
    assert "MUST sum to EXACTLY 20" in budget


def test_question_prompt_contains_the_marks_budget():
    from src.generation.question_generator import _build_question_prompt

    section = _section_d_blueprint()["sections"][0]
    evidence = _section_d_evidence_by_section()["D"]
    _, user_prompt = _build_question_prompt(section, evidence)
    assert "exactly 20 mark(s) in total" in user_prompt
    assert "MUST sum to EXACTLY 20" in user_prompt


# ---------------------------------------------------------------------------
# Regression tests for a real production failure: a real Paper 2 Groq
# generation exhausted all 3 retries for one section, every attempt
# rejected for the SAME reason - too similar to Paper 1's question for
# that section ("question is 0.659 similar to a question already used in
# paper 'mock-eisa-software_developer-paper-01'..."). Root cause: the
# retry note on a novelty rejection carried only the numeric similarity
# score, never what was actually similar - so the model had nothing
# concrete to change and its retries kept converging on the same
# scenario. Fixed by _derive_novelty_avoidance_brief + _build_retry_note:
# a novelty rejection now also carries a compact, structured summary of
# the REJECTED CANDIDATE's own scenario/task framing/sub-task shape, with
# an explicit instruction to change the domain while keeping the same
# required outcomes and evidence.
# ---------------------------------------------------------------------------
def test_derive_novelty_avoidance_brief_summarizes_scenario_framing_and_subtasks():
    from src.generation.question_generator import _derive_novelty_avoidance_brief

    candidate = {
        "scenario": "A member reserves a book that is on loan and joins a waitlist for the library system.",
        "question": "Model the reservation feature using UML.",
        "sub_questions": [
            {"id": "1", "prompt": "Describe a class diagram for Member, Book, and Reservation."},
            {"id": "2", "prompt": "Describe the sequence of messages when a book is reserved."},
        ],
    }
    brief = _derive_novelty_avoidance_brief(candidate)

    assert "member reserves a book" in brief.lower()
    assert "Model the reservation feature" in brief
    assert "Describe a class diagram" in brief
    assert "DIFFERENT organisation, domain, and entities" in brief
    # Deliberately compact - no marks/outcomes/ids, no full JSON dump.
    assert "marks" not in brief.lower()
    assert "outcomes" not in brief.lower()


def test_derive_novelty_avoidance_brief_is_generic_never_names_a_specific_domain():
    """Requirement: must not hard-code Section C, UML, reservation systems,
    or any particular scenario - this function only ever echoes back
    whatever fields the candidate itself happens to have, so it must
    produce an equally useful brief for a completely unrelated domain
    (database tasks, nothing to do with UML/reservations at all)."""
    from src.generation.question_generator import _derive_novelty_avoidance_brief

    candidate = {
        "scenario": "Acme Retail needs a database to track products and suppliers.",
        "question": "Complete the following database tasks.",
        "sub_questions": [{"id": "1", "prompt": "Write the CREATE TABLE statements."}],
    }
    brief = _derive_novelty_avoidance_brief(candidate)
    assert "Acme Retail" in brief
    assert "CREATE TABLE" in brief


def test_derive_novelty_avoidance_brief_truncates_long_fields():
    from src.generation.question_generator import _derive_novelty_avoidance_brief

    long_scenario = "A developer at Acme Retail " + ("needs to build a very long feature description. " * 20)
    candidate = {"scenario": long_scenario, "question": "Q?", "sub_questions": []}
    brief = _derive_novelty_avoidance_brief(candidate)
    # The scenario line itself must be bounded, not a verbatim full copy.
    scenario_line = next(line for line in brief.splitlines() if "Scenario/domain" in line)
    assert len(scenario_line) < len(long_scenario)


def test_build_retry_note_without_a_novelty_brief_uses_the_generic_instruction():
    from src.generation.question_generator import _build_retry_note

    note = _build_retry_note(2, 3, "question text has only 0.02 similarity to its supplied evidence", None)
    assert "REGENERATION NOTE (attempt 2/3)" in note
    assert "Write a genuinely different question." in note
    assert "NOVELTY AVOIDANCE BRIEF" not in note


def test_build_retry_note_with_a_novelty_brief_includes_it_and_the_explicit_instruction():
    from src.generation.question_generator import _build_retry_note

    brief = '- Scenario/domain used (choose a DIFFERENT organisation, domain, and entities): "A member reserves a book."'
    note = _build_retry_note(2, 3, "question is 0.659 similar to a question already used in paper 'paper-01'", brief)
    assert "NOVELTY AVOIDANCE BRIEF" in note
    assert brief in note
    assert "a different scenario, domain, and entities" in note
    assert "different task structure" in note
    assert "SAME GUIDE_EVIDENCE" in note  # evidence must still be used, per requirement 18
    assert "0.659" in note  # the original numeric reason is still stated, not replaced


def test_build_retry_note_returns_empty_string_on_the_first_attempt():
    from src.generation.question_generator import _build_retry_note

    assert _build_retry_note(1, 3, None, None) == ""


def test_novelty_rejection_gives_the_next_attempt_a_structured_brief_and_recovers():
    """The actual end-to-end regression: first candidate collides with
    history; the SECOND attempt's prompt must contain the structured
    novelty-avoidance brief (not just a bare number), and a substantively
    different second candidate must be accepted."""
    colliding = _question(GROUNDED_TEXT, GROUNDED_TEXT)  # duplicates paper-01 - grounded, but too similar
    genuinely_different = _question(DIFFERENT_GROUNDED_TEXT, "Justify your structural choices for the about page.")

    history = {"B": [{"paper_id": "paper-01", "question_id": "Q-B1", "text": f"{GROUNDED_TEXT} {GROUNDED_TEXT}"}]}
    provider = ScriptedProvider([colliding, genuinely_different])

    paper = generate_paper(
        _blueprint(),
        provider,
        seed=1,
        evidence_by_section=_evidence_by_section(),
        generation_history=history,
        security_config=SecurityConfig(grounding_max_retries=3),
    )

    assert provider.call_count == 2
    second_prompt = provider.user_prompts[1]
    assert "NOVELTY AVOIDANCE BRIEF" in second_prompt
    assert GROUNDED_TEXT.lower() in second_prompt.lower()
    assert paper["sections"][0]["questions"][0]["scenario"] == DIFFERENT_GROUNDED_TEXT


def test_grounding_rejection_does_not_carry_a_stale_novelty_brief_into_the_next_attempt():
    """A grounding rejection already names the specific numeric problem
    directly and must not be dressed up with an unrelated novelty brief -
    and a novelty brief from an EARLIER attempt must not leak into a LATER
    attempt's note once the rejection reason has changed."""
    provider = ScriptedProvider([_question(UNGROUNDED_TEXT, "Compute 17 mod 5 and show your working.")])
    with pytest.raises(GenerationError):
        generate_paper(
            _blueprint(),
            provider,
            seed=1,
            evidence_by_section=_evidence_by_section(),
            security_config=SecurityConfig(grounding_max_retries=2),
        )
    for prompt in provider.user_prompts:
        assert "NOVELTY AVOIDANCE BRIEF" not in prompt


def test_persistent_novelty_collision_still_raises_after_bounded_retries():
    """If every attempt keeps colliding with history (a persistent
    semantic pattern the model can't escape even with the brief), the
    pipeline must still fail loudly after the bounded number of retries -
    never accept a too-similar question, and never retry without limit."""
    colliding = _question(GROUNDED_TEXT, GROUNDED_TEXT)
    history = {"B": [{"paper_id": "paper-01", "question_id": "Q-B1", "text": f"{GROUNDED_TEXT} {GROUNDED_TEXT}"}]}
    provider = ScriptedProvider([colliding])  # always the same colliding content

    with pytest.raises(GenerationError, match="exhausted 3 generation attempt"):
        generate_paper(
            _blueprint(),
            provider,
            seed=1,
            evidence_by_section=_evidence_by_section(),
            generation_history=history,
            security_config=SecurityConfig(grounding_max_retries=3),
        )
    assert provider.call_count == 3
    # Every retry after the first must have received the structured brief.
    assert "NOVELTY AVOIDANCE BRIEF" in provider.user_prompts[1]
    assert "NOVELTY AVOIDANCE BRIEF" in provider.user_prompts[2]


def test_evidence_is_present_in_every_attempts_prompt_including_after_a_novelty_rejection():
    """Requirement: evidence/RAG passages must still be included in every
    generation attempt, novelty retries included - the fix must never
    cause a later attempt to silently drop its grounding evidence."""
    colliding = _question(GROUNDED_TEXT, GROUNDED_TEXT)
    genuinely_different = _question(DIFFERENT_GROUNDED_TEXT, "Justify your structural choices for the about page.")
    history = {"B": [{"paper_id": "paper-01", "question_id": "Q-B1", "text": f"{GROUNDED_TEXT} {GROUNDED_TEXT}"}]}
    provider = ScriptedProvider([colliding, genuinely_different])

    generate_paper(
        _blueprint(),
        provider,
        seed=1,
        evidence_by_section=_evidence_by_section(),
        generation_history=history,
        security_config=SecurityConfig(grounding_max_retries=3),
    )

    assert provider.call_count == 2
    for prompt in provider.user_prompts:
        assert EVIDENCE_TEXT in prompt
        assert "Module 6-Learner Guide.pdf" in prompt


# ---------------------------------------------------------------------------
# Regression tests for a real OpenRouter/Gemini production failure: a memo
# model_answer embedded JS code (e.g. console.log("...")) whose unescaped
# inner double-quote corrupted the surrounding JSON string, and
# extract_json's GenerationError ("Unterminated string starting at line
# 118 column 23") was raised OUTSIDE the per-attempt retry try/except in
# generate_paper, aborting the whole paper on one bad sample instead of
# getting the same bounded retry every other rejection class already gets.
# Fixed by moving extract_json inside the existing retry block - these
# tests use a scripted fake provider (never a real API call) to prove
# malformed JSON is now retried using the SAME grounding_max_retries budget
# and REGENERATION NOTE mechanism, not a new/separate retry loop.
# ---------------------------------------------------------------------------
class ScriptedRawProvider(LLMProvider):
    """Like ScriptedProvider, but returns each entry VERBATIM (not
    json.dumps'd), so a test can inject deliberately malformed raw provider
    text."""

    name = "scripted-raw"

    def __init__(self, responses: list[str]):
        self._responses = responses
        self.call_count = 0
        self.user_prompts: list[str] = []

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        self.user_prompts.append(user_prompt)
        content = self._responses[min(self.call_count, len(self._responses) - 1)]
        self.call_count += 1
        return content


_MALFORMED_JSON_EMBEDDED_QUOTE = (
    '{"type": "scenario_short_answer", "scenario": "Log output using console.log("ready") '
    'inside a handler.", "question": "What is printed?", "expected_response_type": "short_answer", '
    '"outcomes": ["KM-06-KT06"]}'
)


def test_malformed_json_on_first_attempt_is_retried_then_a_valid_response_succeeds():
    valid_response = _question(GROUNDED_TEXT, "Which elements would you use and why?")
    provider = ScriptedRawProvider([_MALFORMED_JSON_EMBEDDED_QUOTE, json.dumps(valid_response)])

    paper = generate_paper(
        _blueprint(),
        provider,
        seed=1,
        evidence_by_section=_evidence_by_section(),
        security_config=SecurityConfig(grounding_max_retries=3),
    )

    assert provider.call_count == 2
    assert paper["sections"][0]["questions"][0]["scenario"] == GROUNDED_TEXT


def test_malformed_json_retry_note_names_the_parse_failure():
    valid_response = _question(GROUNDED_TEXT, "Which elements would you use and why?")
    provider = ScriptedRawProvider([_MALFORMED_JSON_EMBEDDED_QUOTE, json.dumps(valid_response)])

    generate_paper(
        _blueprint(),
        provider,
        seed=1,
        evidence_by_section=_evidence_by_section(),
        security_config=SecurityConfig(grounding_max_retries=3),
    )

    assert len(provider.user_prompts) == 2
    assert "REGENERATION NOTE" in provider.user_prompts[1]
    assert "malformed JSON" in provider.user_prompts[1]


def test_malformed_json_on_every_attempt_still_fails_loudly_within_the_retry_bound():
    """The fix must not weaken the retry BOUND - persistent malformed JSON
    still fails loudly after exhausting the configured attempts, never
    retried indefinitely and never silently accepted."""
    provider = ScriptedRawProvider([_MALFORMED_JSON_EMBEDDED_QUOTE])

    with pytest.raises(GenerationError, match="exhausted 2 generation attempt"):
        generate_paper(
            _blueprint(),
            provider,
            seed=1,
            evidence_by_section=_evidence_by_section(),
            security_config=SecurityConfig(grounding_max_retries=2),
        )
    assert provider.call_count == 2
