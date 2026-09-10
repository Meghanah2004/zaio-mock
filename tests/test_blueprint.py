"""Tests for src/generation/blueprint.py, including a regression test for
the Section F occupational_context copy-paste bug found during the Phase 1
quality audit (blueprint.py used to derive occupational_context from
km_refs[0], which for Section F was "KM-09" - silently reusing Section E's
SDLC/secure-coding description for a workplace-governance/ethics question).
"""
from __future__ import annotations

import pytest

from src.config import load_qualification_config
from src.generation.blueprint import build_blueprint


@pytest.fixture
def real_software_developer_blueprint(fake_reference_analysis):
    """Builds the blueprint from the REAL configs/software_developer.json
    (not a test fixture) so this regression test actually exercises the
    shipped config, not a synthetic stand-in for it. fake_reference_analysis
    only needs to supply enough KM data for required_outcomes validation to
    pass for the sections under test; sections whose modules aren't present
    in the fixture are still buildable since outcomes/competencies default
    to an empty list for missing modules (see _outcomes_and_competencies_for).
    """
    real_config = load_qualification_config("software_developer")
    return build_blueprint(fake_reference_analysis, real_config, paper_number=2)


def _section(blueprint, section_id: str) -> dict:
    return next(s for s in blueprint.sections if s.id == section_id)


def test_section_f_context_is_not_copied_from_section_e(real_software_developer_blueprint):
    section_e = _section(real_software_developer_blueprint, "E")
    section_f = _section(real_software_developer_blueprint, "F")
    assert section_f.occupational_context != section_e.occupational_context


def test_section_f_context_mentions_governance_not_sdlc(real_software_developer_blueprint):
    section_f = _section(real_software_developer_blueprint, "F")
    context_lower = section_f.occupational_context.lower()
    assert any(word in context_lower for word in ("governance", "ethic", "legislat", "workplace"))
    assert "sdlc" not in context_lower
    assert "secure-coding" not in context_lower


def test_every_section_has_a_distinct_occupational_context(real_software_developer_blueprint):
    contexts = [s.occupational_context for s in real_software_developer_blueprint.sections]
    assert len(contexts) == len(set(contexts)), "two sections share an identical occupational_context"


def test_blueprint_nqf_level_comes_from_config_not_reference_analysis_span(real_software_developer_blueprint):
    # fake_reference_analysis (used to build this fixture) sets
    # nqf_levels_present=[4, 5] (see tests/conftest.py) - the blueprint must
    # NOT reflect that raw per-module span; it must use the qualification's
    # fixed nqf_level from configs/software_developer.json.
    assert real_software_developer_blueprint.nqf_level == 5


def test_build_blueprint_requires_nqf_level_in_config(fake_reference_analysis, fake_qual_config):
    bad_config = dict(fake_qual_config)
    del bad_config["nqf_level"]
    with pytest.raises(ValueError, match="nqf_level"):
        build_blueprint(fake_reference_analysis, bad_config, paper_number=2)


def test_required_outcomes_must_be_subset_of_full_outcomes(fake_reference_analysis, fake_qual_config):
    bad_config = dict(fake_qual_config)
    bad_config["sections"] = [dict(fake_qual_config["sections"][0])]
    bad_config["sections"][0]["required_outcomes"] = ["KM-99-KT99-DOES-NOT-EXIST"]
    bad_config["total_marks"] = bad_config["sections"][0]["marks"]

    with pytest.raises(ValueError, match="required_outcomes"):
        build_blueprint(fake_reference_analysis, bad_config, paper_number=2)


def test_blueprint_section_carries_required_outcomes_field(fake_reference_analysis, fake_qual_config):
    blueprint = build_blueprint(fake_reference_analysis, fake_qual_config, paper_number=2)
    section_a = _section(blueprint, "A")
    assert section_a.required_outcomes == [
        "KM-04-KT02",
        "KM-04-KT07",
        "KM-04-KT09",
        "KM-04-KT11",
        "KM-05-KT02",
    ]
    # The fixture's required list is contained in its full thematic list
    # (equal here since the fixture's synthetic KM-04/05 modules only define
    # exactly the required topics; production data has real "slack" - see
    # test_tautological_full_list_copy_is_detected for that scenario).
    assert set(section_a.required_outcomes) <= set(section_a.outcomes)
