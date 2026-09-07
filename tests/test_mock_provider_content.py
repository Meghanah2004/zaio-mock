"""Regression tests for specific content defects found during the Phase 1
quality audit and fixed afterwards:

  - Q-A1.4 used to claim a JavaScript snippet "raises a runtime error",
    which is true in Python but false in JavaScript (JS silently coerces
    the number to a string). The fix names Python explicitly and quotes the
    real error message, removing the ambiguity.
  - Q-B1.1 used to ask for HTML5 attributes that "perform built-in
    validation" for "at least one checkbox selected", which HTML5 cannot
    actually do. The fix asks the candidate to correctly distinguish what
    native HTML5 validation can and cannot do.
  - MockProvider used to declare a question's `outcomes` as the ENTIRE
    section outcome list, making outcome-coverage validation tautological.
    The fix requires an explicit, curated subset per section.
"""
from __future__ import annotations

import json

from src.config import load_qualification_config
from src.providers.mock_provider import MockProvider

_ALL_SECTION_IDS = ["A", "B", "C", "D", "E", "F"]


def _generate(section_id: str, seed: int) -> dict:
    provider = MockProvider()
    task = {"kind": "generate_section_question", "section": {"id": section_id}, "seed": seed}
    return json.loads(provider.generate("", "", task))


def test_section_a_sub_question_4_names_python_explicitly_for_both_variants():
    for seed in (0, 1):
        content = _generate("A", seed)
        sub4 = content["sub_questions"][3]
        assert "python" in sub4["prompt"].lower(), (
            f"seed={seed}: sub-question 4 must name a specific language, not leave it ambiguous"
        )
        # The literal, real Python error message must be quoted, not the old
        # vague/ambiguous "raises a runtime error" framing.
        assert "TypeError" in sub4["prompt"]
        assert "raises a runtime error" not in sub4["prompt"].lower()


def test_section_a_sub_question_4_gives_unambiguous_expected_output():
    for seed in (0, 1):
        content = _generate("A", seed)
        sub4 = content["sub_questions"][3]
        # The corrected question specifies the exact target output string,
        # removing any ambiguity about what "works correctly" means.
        assert "produces the string" in sub4["prompt"]


def test_section_b_sub_question_1_distinguishes_native_from_custom_validation():
    for seed in (0, 1):
        content = _generate("B", seed)
        sub1 = content["sub_questions"][0]
        prompt_lower = sub1["prompt"].lower()
        # Must explicitly ask about the native-validation limitation...
        assert "required" in prompt_lower and "checkbox" in prompt_lower
        assert "enforce" in prompt_lower
        # ...and must not claim native HTML5 attributes alone can enforce
        # "at least one checkbox selected" (the original defect).
        assert "at least one selected" not in prompt_lower
        assert "performs built-in validation without any javascript" not in prompt_lower


def test_section_b_sub_question_1_states_checkbox_requirement_unconditionally():
    """Regression test: the question must state the 'at least one checkbox
    selected' rule as an actual, unconditional requirement of the task, not
    a hypothetical ("...if that guarantee is actually required") - a
    candidate must never be left to guess whether the requirement exists at
    all before being asked to reason about how to enforce it."""
    for seed in (0, 1):
        content = _generate("B", seed)
        sub1 = content["sub_questions"][0]
        prompt_lower = sub1["prompt"].lower()
        assert "must be selected" in prompt_lower
        assert "if that guarantee is actually required" not in prompt_lower
        assert "is actually required" not in prompt_lower


def test_mock_provider_declares_curated_outcome_subset_not_full_section_list():
    """Core regression test for the tautological-coverage fix: MockProvider
    must declare a genuinely curated subset for every section, and that
    subset must exactly match (be a superset of) the corresponding
    required_outcomes in the real, shipped qualification config."""
    qual_config = load_qualification_config("software_developer")
    required_by_section = {s["id"]: set(s["required_outcomes"]) for s in qual_config["sections"]}

    for section_id in _ALL_SECTION_IDS:
        content = _generate(section_id, seed=0)
        declared = set(content["outcomes"])
        assert declared, f"section {section_id}: provider declared no outcomes at all"
        assert declared >= required_by_section[section_id], (
            f"section {section_id}: declared outcomes {declared} do not cover this "
            f"section's required_outcomes {required_by_section[section_id]}"
        )


def test_mock_provider_outcomes_are_identical_across_variants_for_same_section():
    """The scenario wording varies by seed, but the skills a section's
    question tests do not - both variants of a section must declare the
    same outcome subset."""
    for section_id in _ALL_SECTION_IDS:
        outcomes_seed_0 = set(_generate(section_id, seed=0)["outcomes"])
        outcomes_seed_1 = set(_generate(section_id, seed=1)["outcomes"])
        assert outcomes_seed_0 == outcomes_seed_1
