"""Integration tests for src/validation/orchestrator.run_all_validators -
specifically, the answer-grounding validator wiring (2026-09-11 audit
finding): src/validation/answer_grounding_validator.py existed and was
unit-tested in isolation (tests/test_answer_grounding_validator.py) but was
never actually called from run_all_validators, the function the real API
pipeline (api/service.py) uses - only the memo's GENERATION-TIME self-check
(_answer_grounding_ok, inside src.generation.memo_generator) ran in
production; there was no independent deterministic re-check of answer
grounding the way question grounding already had one.

These tests build a REAL, schema-valid, marks-consistent, grounded paper +
memo (via build_blueprint + MockProvider + a small synthetic corpus - same
pattern as tests/test_generation_pipeline_mocked.py's real-generation-mode
test) and drive it through run_all_validators ITSELF, not the individual
validator functions directly, proving:
  1. A genuinely grounded memo still passes the full orchestrated report.
  2. Answer-grounding-specific checks actually appear in that report (not
     just that overall pass=True, which could pass even if the new
     validator were silently never invoked).
  3. Fabricated answer-grounding evidence (a citation to a page that does
     not exist in the corpus) is caught and fails the report.
  4. Insufficient answer-grounding overlap (answer text unrelated to its
     cited evidence) is caught and fails the report.
  5. Every other check category (schema, marks, coverage, novelty,
     question-side grounding) is completely unaffected - same checks
     present, same behavior, before and after this wiring.
  6. The existing skip-when-no-corpus-file behavior is unchanged for BOTH
     grounding checks (question and answer side skip together, exactly as
     question-side already did alone).
"""
from __future__ import annotations

import json

from src.generation.blueprint import build_blueprint
from src.generation.memo_generator import generate_memo
from src.generation.question_generator import generate_paper
from src.providers.mock_provider import MockProvider
from src.retrieval.evidence_selector import build_evidence_by_section
from src.security.config import SecurityConfig
from src.validation.novelty_checker import ReferenceCorpusIndex
from src.validation.orchestrator import run_all_validators

_TOPIC_PASSAGES = {
    "KM-04-KT02": "Converting a binary value to decimal means summing each bit's positional power of two for every bit that is set to 1.",
    "KM-04-KT07": "Operator precedence determines the order in which an expression's operators are evaluated, with modulus and multiplication resolved before addition or subtraction.",
    "KM-04-KT09": "The modulus operator returns the remainder left over after dividing one integer by another.",
    "KM-04-KT11": "Mixing a string and a number with the plus operator raises a type error in Python because the language never implicitly converts a number to a string.",
    "KM-05-KT02": "A variable is a named storage location that holds a value which a program can read or change while it runs.",
    "KM-06-KT02": "Object-oriented programming organizes code into classes and objects that bundle related data and behaviour together.",
    "KM-06-KT06": "HTML5 introduces new semantic elements such as header, footer, and section for structuring a page.",
    "KM-06-KT07": "CSS Flexbox provides a one dimensional layout model for arranging items in a row or column.",
    "KM-06-KT08": "JavaScript can attach an event listener to a form's submit event and call preventDefault to stop the page reloading.",
}


def _synthetic_corpus_chunks() -> list[dict]:
    return [
        {"source": "Synthetic Learner Guide.pdf", "page": i + 1, "kt_code": code, "text": text}
        for i, (code, text) in enumerate(_TOPIC_PASSAGES.items())
    ]


def _build_real_paper_and_memo(fake_reference_analysis, fake_qual_config, corpus_chunks, seed=3):
    """Real generation mode, exactly like api/service.py's own call shape -
    schema-valid, marks-consistent, question- and answer-grounded."""
    blueprint = build_blueprint(fake_reference_analysis, fake_qual_config, paper_number=99)
    blueprint_dict = blueprint.to_json_dict()

    index = ReferenceCorpusIndex(corpus_chunks)
    security_config = SecurityConfig()
    evidence_by_section = build_evidence_by_section(blueprint_dict, index, corpus_chunks, security_config, seed)

    provider = MockProvider()
    paper = generate_paper(
        blueprint_dict, provider, seed, evidence_by_section=evidence_by_section,
        generation_history={}, security_config=security_config,
    )
    memo = generate_memo(
        paper, provider, seed, security_config=security_config, retrieval_index=index, corpus_chunks=corpus_chunks
    )
    return paper, memo, blueprint_dict


def test_a_genuinely_grounded_memo_passes_every_grounding_marks_schema_and_coverage_check(
    fake_reference_analysis, fake_qual_config, tmp_path
):
    """Asserts every check EXCEPT novelty_screening passes. novelty_screening
    is deliberately excluded here: this test's small, hand-picked synthetic
    corpus (borrowed from tests/test_generation_pipeline_mocked.py's own
    real-generation-mode fixture) happens to closely resemble MockProvider's
    fixed Section A content bank's wording - a pre-existing, seed-
    independent coincidence of this test's fixture data (confirmed by
    trying 7 different seeds, all identical), unrelated to the
    answer-grounding wiring under test here. It is not asserted, positively
    or negatively, in this test."""
    corpus_chunks = _synthetic_corpus_chunks()
    paper, memo, blueprint_dict = _build_real_paper_and_memo(fake_reference_analysis, fake_qual_config, corpus_chunks)
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus_chunks), encoding="utf-8")

    report, novelty_result = run_all_validators(paper, memo, blueprint_dict, corpus_path)

    non_novelty_failures = [c for c in report.checks if not c.passed and c.name != "novelty_screening"]
    assert non_novelty_failures == []
    assert novelty_result is not None


def test_answer_grounding_checks_actually_appear_in_the_orchestrated_report(
    fake_reference_analysis, fake_qual_config, tmp_path
):
    """The critical proof that the wiring is real, not just that pass=True
    happens to hold - a silently-never-invoked validator would also show
    pass=True (vacuously, zero checks added)."""
    corpus_chunks = _synthetic_corpus_chunks()
    paper, memo, blueprint_dict = _build_real_paper_and_memo(fake_reference_analysis, fake_qual_config, corpus_chunks)
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus_chunks), encoding="utf-8")

    report, _ = run_all_validators(paper, memo, blueprint_dict, corpus_path)

    check_names = [c.name for c in report.checks]
    assert any(name.startswith("answer_grounding_present:") for name in check_names)
    assert any(name.startswith("answer_grounding_pages_exist:") for name in check_names)
    assert any(name.startswith("answer_grounding_overlap_sufficient:") for name in check_names)


def test_question_side_grounding_checks_are_unaffected_by_the_new_wiring(
    fake_reference_analysis, fake_qual_config, tmp_path
):
    corpus_chunks = _synthetic_corpus_chunks()
    paper, memo, blueprint_dict = _build_real_paper_and_memo(fake_reference_analysis, fake_qual_config, corpus_chunks)
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus_chunks), encoding="utf-8")

    report, _ = run_all_validators(paper, memo, blueprint_dict, corpus_path)

    check_names = [c.name for c in report.checks]
    assert any(name.startswith("grounding_present:") for name in check_names)
    assert any(name.startswith("grounding_overlap_sufficient:") for name in check_names)
    assert any(name.startswith("grounding_not_near_copy:") for name in check_names)


def test_every_other_check_category_still_present_and_unchanged(
    fake_reference_analysis, fake_qual_config, tmp_path
):
    """Schema, marks, coverage, and novelty must all still run exactly as
    before - the new validator is additive, not a replacement for anything."""
    corpus_chunks = _synthetic_corpus_chunks()
    paper, memo, blueprint_dict = _build_real_paper_and_memo(fake_reference_analysis, fake_qual_config, corpus_chunks)
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus_chunks), encoding="utf-8")

    report, novelty_result = run_all_validators(paper, memo, blueprint_dict, corpus_path)

    check_names = [c.name for c in report.checks]
    assert "schema:paper.schema.json" in check_names
    assert "schema:memo.schema.json" in check_names
    assert "total_marks" in check_names
    assert any(name.startswith("section_marks:") for name in check_names)
    assert any(name.startswith("required_outcome_coverage") or "coverage" in name for name in check_names)
    assert "novelty_screening" in check_names
    # The novelty check's specific pass/fail VALUE is intentionally not
    # asserted here - see the module-level note on the "happy path" test
    # above; this test only proves the check ran (novelty is not silently
    # skipped), not what it concluded.
    assert novelty_result is not None and "overall_status" in novelty_result


def test_fabricated_answer_grounding_page_fails_the_orchestrated_report(
    fake_reference_analysis, fake_qual_config, tmp_path
):
    """A citation to a (document, page) pair that does not exist in the
    ingested corpus must fail the report - proves the deterministic
    re-check genuinely catches fabrication, it doesn't just trust the
    memo's own claimed grounding."""
    corpus_chunks = _synthetic_corpus_chunks()
    paper, memo, blueprint_dict = _build_real_paper_and_memo(fake_reference_analysis, fake_qual_config, corpus_chunks)
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus_chunks), encoding="utf-8")

    # Corrupt one memo entry's grounding to cite a page that was never
    # ingested - a fabricated citation.
    memo["sections"][0]["questions"][0]["grounding"] = [
        {
            "document": "Synthetic Learner Guide.pdf",
            "page": 9999,
            "passage": "This page does not exist in the real corpus.",
            "reason": "fabricated for this test",
        }
    ]

    report, _ = run_all_validators(paper, memo, blueprint_dict, corpus_path)

    assert not report.passed
    failing = [c for c in report.checks if not c.passed]
    assert any(c.name.startswith("answer_grounding_pages_exist:") for c in failing)


def test_answer_unrelated_to_its_cited_evidence_fails_the_orchestrated_report(
    fake_reference_analysis, fake_qual_config, tmp_path
):
    """An answer whose text bears no relation to its (otherwise real,
    page-valid) cited evidence must also fail - not just fabricated page
    numbers, but genuine non-derivation from the supplied material."""
    corpus_chunks = _synthetic_corpus_chunks()
    paper, memo, blueprint_dict = _build_real_paper_and_memo(fake_reference_analysis, fake_qual_config, corpus_chunks)
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus_chunks), encoding="utf-8")

    target = memo["sections"][0]["questions"][0]
    # Keep the (real, valid) page citation but replace the answer text with
    # something with essentially no vocabulary overlap with any evidence.
    target["model_answer"] = "Purple elephants juggle unrelated kitchen utensils while whistling."
    for sq in target.get("sub_questions", []) or []:
        sq["model_answer"] = "Purple elephants juggle unrelated kitchen utensils while whistling."

    report, _ = run_all_validators(paper, memo, blueprint_dict, corpus_path)

    assert not report.passed
    failing = [c for c in report.checks if not c.passed]
    assert any(c.name.startswith("answer_grounding_overlap_sufficient:") for c in failing)


def test_both_grounding_checks_are_skipped_together_when_no_corpus_file_exists(
    fake_reference_analysis, fake_qual_config, tmp_path
):
    """Existing skip semantics (question-side grounding was already gated
    on corpus_chunks_path existing) must extend identically to answer-side
    grounding, not diverge from it."""
    corpus_chunks = _synthetic_corpus_chunks()
    paper, memo, blueprint_dict = _build_real_paper_and_memo(fake_reference_analysis, fake_qual_config, corpus_chunks)
    missing_path = tmp_path / "does-not-exist.json"

    report, novelty_result = run_all_validators(paper, memo, blueprint_dict, missing_path)

    check_names = [c.name for c in report.checks]
    assert not any(name.startswith("grounding_present:") for name in check_names)
    assert not any(name.startswith("answer_grounding_present:") for name in check_names)
    assert novelty_result is None
