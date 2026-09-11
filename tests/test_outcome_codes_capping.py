"""Tests for the question-generation prompt's outcome-codes cap (token
audit, 2026-09-11).

Measured directly against the real blueprint (artifacts/blueprint.json):
Section F alone carries 49 full outcome codes for a 5-mark section, costing
~477 tokens on the {outcome_codes} prompt line alone - the single largest
concrete per-paper token reduction found in the audit (~560 tokens/paper
across all 6 real sections, cap=10).

These tests prove: (1) the cap actually shrinks what is shown, (2) every
required outcome is still shown in full regardless of the cap, (3) small
sections (at or under the cap) are completely unaffected - no truncation
marker, identical content to before, (4) MOST IMPORTANTLY: capping what is
SHOWN in the prompt has zero effect on what is ACCEPTED -
_normalize_question's hallucination check still validates against the
real, full, uncapped section["outcomes"], so a model that legitimately
declares a valid code outside its shown sample is still accepted, not
incorrectly rejected. This is the property that makes the cap a pure
token-efficiency change, not a validation change.
"""
from __future__ import annotations

from typing import Any

from src.generation.question_generator import (
    MAX_OUTCOME_CODES_SHOWN,
    _build_question_prompt,
    _normalize_question,
    _outcome_codes_line,
)


def _section(full_outcome_count: int, required_count: int) -> dict[str, Any]:
    outcomes = [f"KM-09-KT{i:02d}" for i in range(1, full_outcome_count + 1)]
    competencies = [f"Competency {i}" for i in range(1, full_outcome_count + 1)]
    required_outcomes = outcomes[:required_count]
    return {
        "id": "F",
        "title": "Governance, Ethics and Professional Practice",
        "marks": 5,
        "outcomes": outcomes,
        "competencies": competencies,
        "required_outcomes": required_outcomes,
        "difficulty": "foundational",
        "question_types": ["short_answer"],
        "occupational_context": "A junior developer handling a governance/compliance task.",
    }


def test_outcome_codes_line_caps_a_large_section():
    """The real-world shape this fix targets: 49 codes, 3 required (matches
    the actual Section F measured in artifacts/blueprint.json)."""
    section = _section(full_outcome_count=49, required_count=3)

    line = _outcome_codes_line(section)

    shown_codes = [part.split(" ", 1)[0] for part in line.split("; ") if part.startswith("KM-")]
    assert len(shown_codes) <= MAX_OUTCOME_CODES_SHOWN
    assert len(shown_codes) < 49  # genuinely capped, not a no-op


def test_outcome_codes_line_always_shows_every_required_code():
    """Required outcomes must never be truncated, even though they count
    against the cap budget - the model must always see the codes it is
    actually required to cover."""
    section = _section(full_outcome_count=49, required_count=3)
    required = set(section["required_outcomes"])

    line = _outcome_codes_line(section)

    for code in required:
        assert code in line


def test_outcome_codes_line_leaves_small_sections_unaffected():
    """A section with fewer codes than the cap must be shown in full, with
    no truncation marker - the fix must not change behavior where there is
    nothing to save."""
    section = _section(full_outcome_count=8, required_count=4)

    line = _outcome_codes_line(section)

    for code in section["outcomes"]:
        assert code in line
    assert "further valid codes" not in line


def test_outcome_codes_line_notes_how_many_were_omitted():
    section = _section(full_outcome_count=49, required_count=3)

    line = _outcome_codes_line(section)

    assert "further valid codes" in line


def test_capped_prompt_still_contains_the_full_required_outcome_codes_block():
    """The SEPARATE {required_outcome_codes} line (always required, never
    capped - see _build_question_prompt) must still carry every required
    code regardless of this cap, which only affects the FULL/optional
    outcome-codes line."""
    section = _section(full_outcome_count=49, required_count=5)

    _system_prompt, user_prompt = _build_question_prompt(section, evidence=[])

    for code in section["required_outcomes"]:
        assert code in user_prompt


def test_capping_the_displayed_codes_does_not_weaken_the_hallucination_check():
    """THE critical safety-preserving property: _normalize_question's
    validation reads section["outcomes"] directly (the real, full, uncapped
    universe) - never whatever subset _outcome_codes_line chose to display.
    A model that declares a real, valid code from OUTSIDE its shown sample
    must still be ACCEPTED, proving the cap is purely a prompt-display
    change, not a validation weakening."""
    section = _section(full_outcome_count=49, required_count=3)
    required = section["required_outcomes"]

    line = _outcome_codes_line(section)
    shown_codes = {part.split(" ", 1)[0] for part in line.split("; ") if part.startswith("KM-")}
    # Find a code that is valid (in the real full universe) but NOT shown -
    # must exist, since the section has 49 codes and only <=10 are shown.
    unshown_valid_code = next(code for code in section["outcomes"] if code not in shown_codes)
    assert unshown_valid_code not in shown_codes  # sanity: test setup is meaningful

    raw_content = {
        "type": "short_answer",
        "question": "Explain the governance implication.",
        "expected_response_type": "short_answer",
        "outcomes": [*required, unshown_valid_code],
    }

    # Must NOT raise - a real, valid (if unshown) code is still accepted.
    question = _normalize_question(raw_content, section, "F.1", "Q-F1", grounding=[])
    assert unshown_valid_code in question["outcomes"]


def test_declaring_a_genuinely_invented_code_is_still_rejected():
    """The opposite direction of the same property: the hallucination check
    must still reject a code that isn't in the real full universe at all -
    the cap must not have loosened this in either direction."""
    from src.generation.llm_utils import GenerationError

    section = _section(full_outcome_count=49, required_count=3)
    required = section["required_outcomes"]

    raw_content = {
        "type": "short_answer",
        "question": "Explain the governance implication.",
        "outcomes": [*required, "KM-99-INVENTED"],
    }

    try:
        _normalize_question(raw_content, section, "F.1", "Q-F1", grounding=[])
        raised = False
    except GenerationError:
        raised = True
    assert raised, "a genuinely invented outcome code must still be rejected"
