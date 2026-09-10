"""Regression tests for the repeated-questions production incident.

Root cause (see src.config.compute_effective_seed's docstring for the full
analysis): --seed's default (src/cli.py) and the frontend's seed field
default (frontend/src/components/GenerateForm.tsx) were both the same
static literal, and NOTHING before this fix combined the raw seed with
paper_number - every seed-dependent step (question-side evidence rotation,
answer-side evidence rotation, the provider task seed) depended on the raw
seed ALONE. A caller who generated Paper 1 and Paper 2 without manually
picking a different seed retrieved IDENTICAL evidence for both, which a
real low-temperature provider frequently turned into near-duplicate
questions - triggering frequent cross-paper novelty rejections, and, when
accepted anyway, still frequently near-duplicate content.

tests/test_config.py and tests/test_evidence_selector.py cover
compute_effective_seed's own formula and its effect on retrieval directly.
This file covers the INTEGRATION point this task is actually about: does
the real production code path (api/service.py's generate_paper_and_memo)
actually compute and thread the effective seed all the way through to
BOTH question-side and answer-side evidence retrieval - not just in
isolation, but as actually wired into the real, MockProvider-backed
pipeline against the real committed corpus.
"""
from __future__ import annotations

from src.config import compute_effective_seed
from src.security.config import SecurityConfig


def test_generate_paper_and_memo_threads_the_effective_seed_to_both_evidence_retrieval_calls(monkeypatch):
    """The direct proof requested: answer/memo evidence selection receives
    the EFFECTIVE seed, not the raw one - and so does question-side
    evidence selection, in the same real call.

    Spies wrap (never replace) the real functions, so this still exercises
    genuine RAG retrieval against the real committed corpus and genuine
    MockProvider-backed generation/validation end to end - only the seed
    argument each call received is additionally recorded.
    """
    import api.service as service_module
    import src.generation.memo_generator as memo_generator_module

    captured_seeds: dict[str, int] = {}

    real_build_evidence_by_section = service_module.build_evidence_by_section

    def spy_build_evidence_by_section(blueprint_dict, retrieval_index, corpus_chunks, security_config, seed):
        captured_seeds["question_side"] = seed
        return real_build_evidence_by_section(blueprint_dict, retrieval_index, corpus_chunks, security_config, seed)

    monkeypatch.setattr(service_module, "build_evidence_by_section", spy_build_evidence_by_section)

    real_select_answer_evidence = memo_generator_module.select_answer_evidence

    def spy_select_answer_evidence(retrieval_index, corpus_chunks, question, seed, security_config):
        # Every call within one generation shares the same seed - record it
        # once, don't overwrite with a later (identical) call's value.
        captured_seeds.setdefault("answer_side", seed)
        return real_select_answer_evidence(retrieval_index, corpus_chunks, question, seed, security_config)

    monkeypatch.setattr(memo_generator_module, "select_answer_evidence", spy_select_answer_evidence)

    raw_seed = 1
    paper_number = 902  # test-only range (900+), never the canonical paper-01/02
    result = service_module.generate_paper_and_memo(
        qualification="software_developer", paper_number=paper_number, seed=raw_seed, want_pdf=False
    )

    expected_effective_seed = compute_effective_seed(raw_seed, paper_number)
    assert captured_seeds["question_side"] == expected_effective_seed
    assert captured_seeds["answer_side"] == expected_effective_seed
    # Sanity: the effective seed actually differs from the raw one supplied
    # (paper_number=902 != 0), proving this was a real transformation, not
    # a no-op that happened to pass the raw seed through unchanged.
    assert expected_effective_seed != raw_seed
    assert result.validation_passed is True


def test_generate_paper_and_memo_gives_different_paper_numbers_different_effective_seeds_end_to_end(monkeypatch):
    """The same proof as above, but comparing TWO different paper_numbers
    generated with the SAME raw seed - the exact scenario that used to
    collide.

    History is reset between the two calls (real API/CLI usage generates
    each paper in its OWN process invocation, never two in a row sharing
    unflushed in-memory state the way two calls in one test function
    would) - this test's purpose is proving effective_seed differs and
    reaches evidence retrieval for each call, not re-proving cross-paper
    novelty behavior (already covered by tests/test_cross_paper_novelty.py
    and tests/test_question_generator_grounding.py). Without the reset,
    this would instead exercise a real, already-documented, UNRELATED
    MockProvider limitation - its fixture bank holds only 2 hand-written
    variants per section, close enough in wording to legitimately exceed
    the real 0.6 novelty threshold against EACH OTHER (see
    tests/conftest.py's `_reset_generation_history_between_tests` for the
    same reasoning applied between separate tests)."""
    import api.service as service_module

    captured_seeds: list[int] = []
    real_build_evidence_by_section = service_module.build_evidence_by_section

    def spy_build_evidence_by_section(blueprint_dict, retrieval_index, corpus_chunks, security_config, seed):
        captured_seeds.append(seed)
        return real_build_evidence_by_section(blueprint_dict, retrieval_index, corpus_chunks, security_config, seed)

    monkeypatch.setattr(service_module, "build_evidence_by_section", spy_build_evidence_by_section)

    raw_seed = 20260906  # the real static default both --seed and the frontend form used
    service_module.generate_paper_and_memo(
        qualification="software_developer", paper_number=903, seed=raw_seed, want_pdf=False
    )
    service_module._GENERATION_HISTORY_PATH.unlink(missing_ok=True)
    service_module.generate_paper_and_memo(
        qualification="software_developer", paper_number=904, seed=raw_seed, want_pdf=False
    )

    assert len(captured_seeds) == 2
    assert captured_seeds[0] != captured_seeds[1]
    assert captured_seeds[0] == compute_effective_seed(raw_seed, 903)
    assert captured_seeds[1] == compute_effective_seed(raw_seed, 904)


# ---------------------------------------------------------------------------
# Requirements 5 & 6: this fix must not touch cross-paper novelty or
# grounding validation in any way - not their logic (see
# tests/test_cross_paper_novelty.py, tests/test_grounding_validator.py,
# tests/test_answer_grounding_validator.py, tests/test_question_generator_
# grounding.py, all unchanged by this task and still fully passing), and
# explicitly not their configured thresholds either - pinned directly here
# as an extra, task-specific regression guard.
# ---------------------------------------------------------------------------
def test_cross_paper_novelty_threshold_is_unchanged_by_the_effective_seed_fix():
    assert SecurityConfig().cross_paper_max_similarity == 0.6


def test_grounding_thresholds_are_unchanged_by_the_effective_seed_fix():
    security_config = SecurityConfig()
    assert security_config.grounding_min_overlap == 0.08
    assert security_config.grounding_max_overlap == 0.75


def test_answer_grounding_threshold_is_unchanged_by_the_effective_seed_fix():
    security_config = SecurityConfig()
    assert security_config.answer_grounding_min_overlap == 0.08
    assert security_config.answer_relevance_min_overlap == 0.05


def test_retry_attempt_bounds_are_unchanged_by_the_effective_seed_fix():
    """This task explicitly did not touch retry/attempt safety limits -
    pinned here so a future change to them is a deliberate, visible
    decision made elsewhere, not an accidental side effect of this one."""
    security_config = SecurityConfig()
    assert security_config.grounding_max_retries == 3
    assert security_config.memo_max_retries == 3
    assert security_config.generation_max_retries == 3
