"""End-to-end pipeline test using MockProvider - no API key required."""
from __future__ import annotations

from src.generation.blueprint import build_blueprint
from src.generation.memo_generator import generate_memo
from src.generation.question_generator import generate_paper
from src.providers.mock_provider import MockProvider
from src.validation.coverage_validator import validate_coverage
from src.validation.marks_validator import validate_marks
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
