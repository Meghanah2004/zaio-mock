"""End-to-end pipeline test using MockProvider - no API key required."""
from __future__ import annotations

from src.generation.blueprint import build_blueprint
from src.generation.memo_generator import generate_memo
from src.generation.question_generator import generate_paper
from src.providers.mock_provider import MockProvider
from src.retrieval.evidence_selector import build_evidence_by_section
from src.security.config import SecurityConfig
from src.validation.answer_grounding_validator import validate_answer_grounding
from src.validation.coverage_validator import validate_coverage
from src.validation.grounding_validator import validate_grounding
from src.validation.marks_validator import validate_marks
from src.validation.novelty_checker import ReferenceCorpusIndex
from src.validation.schema_validator import validate_memo_schema, validate_paper_schema


def test_full_pipeline_with_mock_provider_produces_valid_paper_and_memo(fake_reference_analysis, fake_qual_config):
    blueprint = build_blueprint(fake_reference_analysis, fake_qual_config, paper_number=99)
    blueprint_dict = blueprint.to_json_dict()

    provider = MockProvider()
    paper = generate_paper(blueprint_dict, provider, seed=42)
    memo = generate_memo(paper, provider, seed=42)

    schema_result = validate_paper_schema(paper)
    assert schema_result.passed, schema_result.details
    memo_schema_result = validate_memo_schema(memo)
    assert memo_schema_result.passed, memo_schema_result.details

    marks_report = validate_marks(paper, memo)
    assert marks_report.passed, [c for c in marks_report.checks if not c.passed]

    coverage_report = validate_coverage(paper, blueprint_dict)
    assert coverage_report.passed, [c for c in coverage_report.checks if not c.passed]

    assert paper["total_marks"] == fake_qual_config["total_marks"]
    assert "MOCK" in paper["status_disclaimer"].upper()


def test_generation_is_deterministic_for_same_seed(fake_reference_analysis, fake_qual_config):
    blueprint = build_blueprint(fake_reference_analysis, fake_qual_config, paper_number=99).to_json_dict()
    provider = MockProvider()

    paper_1 = generate_paper(blueprint, provider, seed=7)
    paper_2 = generate_paper(blueprint, provider, seed=7)
    assert paper_1 == paper_2


def test_different_seeds_can_produce_different_scenarios(fake_reference_analysis, fake_qual_config):
    blueprint = build_blueprint(fake_reference_analysis, fake_qual_config, paper_number=99).to_json_dict()
    provider = MockProvider()

    paper_seed_0 = generate_paper(blueprint, provider, seed=0)
    paper_seed_1 = generate_paper(blueprint, provider, seed=1)

    scenario_0 = paper_seed_0["sections"][0]["questions"][0]["scenario"]
    scenario_1 = paper_seed_1["sections"][0]["questions"][0]["scenario"]
    assert scenario_0 != scenario_1


# ---------------------------------------------------------------------------
# REAL GENERATION MODE end-to-end (master prompt's central requirement): the
# same run as above, but with question-side AND answer-side RAG actually
# wired in - a small SYNTHETIC corpus (fast, isolated, no dependency on the
# real sdev/ corpus - same convention as fake_reference_analysis/
# fake_qual_config above) standing in for artifacts/reference-corpus-
# chunks.json. Exercises the exact call shape api/service.py's
# generate_paper_and_memo uses for a real Generate-button request:
# build_evidence_by_section (question-side) -> generate_paper(evidence_by_
# section=..., generation_history=...) -> generate_memo(retrieval_index=...,
# corpus_chunks=...) -> both independent re-validators
# (grounding_validator/answer_grounding_validator), never trusting the
# generation-time self-checks alone.
# ---------------------------------------------------------------------------
def _synthetic_corpus_chunks() -> list[dict]:
    topic_passages = {
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
    return [
        {"source": "Synthetic Learner Guide.pdf", "page": i + 1, "kt_code": code, "text": text}
        for i, (code, text) in enumerate(topic_passages.items())
    ]


def test_full_pipeline_in_real_generation_mode_produces_grounded_paper_and_memo(
    fake_reference_analysis, fake_qual_config
):
    blueprint = build_blueprint(fake_reference_analysis, fake_qual_config, paper_number=99)
    blueprint_dict = blueprint.to_json_dict()

    corpus_chunks = _synthetic_corpus_chunks()
    index = ReferenceCorpusIndex(corpus_chunks)
    security_config = SecurityConfig()
    evidence_by_section = build_evidence_by_section(blueprint_dict, index, corpus_chunks, security_config, seed=3)

    provider = MockProvider()
    paper = generate_paper(
        blueprint_dict, provider, seed=3, evidence_by_section=evidence_by_section,
        generation_history={}, security_config=security_config,
    )
    memo = generate_memo(paper, provider, seed=3, security_config=security_config, retrieval_index=index, corpus_chunks=corpus_chunks)

    assert validate_paper_schema(paper).passed
    assert validate_memo_schema(memo).passed
    assert validate_marks(paper, memo).passed
    assert validate_coverage(paper, blueprint_dict).passed

    # Question-side: every question carries real, page-cited grounding.
    assert paper["generation_meta"]["grounded"] is True
    for section in paper["sections"]:
        for question in section["questions"]:
            assert question["grounding"], f"{question['id']} has no question-side grounding"
    grounding_report = validate_grounding(paper, corpus_chunks)
    assert grounding_report.passed, [c for c in grounding_report.checks if not c.passed]

    # Answer-side: every memo entry carries real, page-cited grounding too -
    # this is the master-prompt requirement that answers, not just
    # questions, are generated from the supplied learner-guide evidence.
    assert memo["generation_meta"]["answer_grounded"] is True
    for section in memo["sections"]:
        for mq in section["questions"]:
            assert mq["grounding"], f"{mq['question_id']} has no answer-side grounding"
    answer_grounding_report = validate_answer_grounding(memo, corpus_chunks)
    assert answer_grounding_report.passed, [c for c in answer_grounding_report.checks if not c.passed]
