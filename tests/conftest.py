"""Shared pytest fixtures.

Fixtures build a small SYNTHETIC reference-analysis + qualification config
so generation/validation tests do not depend on parsing the real sdev/
corpus (faster, isolated, and unaffected by future changes to the real
reference material).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_api_rate_limits():
    """Every api/test_api_*.py test shares one process-wide rate-limiter
    singleton (api.dependencies.RATE_LIMITER, by design - see its
    docstring). Reset the bucket used by FastAPI's TestClient (whose
    request.client.host is always "testclient") before and after every
    test, so token consumption in one test can never make an unrelated
    later test flaky. A no-op (cheap dict.pop-with-default) for every
    non-API test, which never touches these buckets."""
    from api.dependencies import RATE_LIMITER

    RATE_LIMITER.generation.reset("testclient")
    RATE_LIMITER.read.reset("testclient")
    yield
    RATE_LIMITER.generation.reset("testclient")
    RATE_LIMITER.read.reset("testclient")


@pytest.fixture
def fake_reference_analysis() -> dict:
    def module(km: str, topics: list[tuple[str, str, int]]) -> dict:
        return {
            "km": km,
            "knowledge_topics": [
                {"code": f"KM-{km}-KT{n}", "title": t, "weight_percent": w, "source": "section_header"}
                for n, t, w in topics
            ],
        }

    return {
        "qualification_title": "Occupational Certificate: Software Developer",
        "nqf_levels_present": [4, 5],
        "modules": [
            # KM-04/05/06 topic subsets realistic enough to match what
            # MockProvider's real "A"/"B" content banks declare as their
            # genuinely-covered outcomes (see src/providers/mock_provider.py
            # _SECTION_OUTCOMES) - these tests exercise the real content
            # bank end-to-end, so the outcome universe must actually contain
            # the codes that bank declares.
            module(
                "04",
                [
                    ("02", "Conversion between decimal and binary systems", 25),
                    ("07", "Operator precedence", 25),
                    ("09", "Modulus", 25),
                    ("11", "Mixing types", 25),
                ],
            ),
            module("05", [("02", "Programming basics", 100)]),
            module(
                "06",
                [
                    ("02", "Object-Oriented Programming", 25),
                    ("06", "HTML5", 25),
                    ("07", "CSS", 25),
                    ("08", "JavaScript", 25),
                ],
            ),
            # KM-07/08/09/10 subsets covering exactly the codes referenced by
            # the REAL configs/software_developer.json's required_outcomes,
            # so tests/test_blueprint.py can build the actual shipped config
            # (not a synthetic stand-in for it) against this fixture.
            module(
                "07",
                [
                    ("04", "Classes and class diagrams", 50),
                    ("07", "Sequence diagrams", 50),
                ],
            ),
            module(
                "08",
                [
                    ("01", "Understanding core database concepts", 20),
                    ("02", "Creating database", 20),
                    ("03", "Manipulating data", 20),
                    ("04", "Understanding Data", 20),
                    ("05", "Administering a database", 20),
                ],
            ),
            module(
                "09",
                [
                    ("02", "Software Development Life Cycle", 25),
                    ("09", "Phase 5: Testing", 25),
                    ("16", "Algorithms", 25),
                    ("18", "Security topics every software developer must", 25),
                ],
            ),
            module(
                "10",
                [
                    ("01", "Governance", 34),
                    ("02", "Legislation governing workplaces", 33),
                    ("04", "Ethics at work", 33),
                ],
            ),
        ],
    }


@pytest.fixture
def fake_qual_config() -> dict:
    return {
        "qualification_key": "test_qual",
        "_assumption_notice": "test fixture - not a real assumption notice",
        "paper_title": "Test Paper",
        "duration_minutes": 60,
        "total_marks": 45,
        "pass_mark_percent": 50,
        "candidate_instructions": ["This is a mock/practice test fixture paper.", "Answer all questions."],
        "sections": [
            {
                "id": "A",
                "title": "Programming Basics",
                "km_refs": ["KM-04", "KM-05"],
                # Matches MockProvider's real "A" content bank mark total AND
                # declared outcomes (see src/providers/mock_provider.py
                # _SECTION_OUTCOMES) - this test exercises the actual content
                # bank end-to-end rather than a synthetic one.
                "marks": 15,
                "difficulty": "foundational",
                "question_types": ["short_answer"],
                "required_outcomes": ["KM-04-KT02", "KM-04-KT07", "KM-04-KT09", "KM-04-KT11", "KM-05-KT02"],
            },
            {
                "id": "B",
                "title": "Front-End Basics",
                "km_refs": ["KM-06"],
                "marks": 30,
                "difficulty": "intermediate",
                "question_types": ["code_writing"],
                "required_outcomes": ["KM-06-KT02", "KM-06-KT06", "KM-06-KT07", "KM-06-KT08"],
            },
        ],
        "questions_per_section": 1,
        "llm": {"default_provider": "mock", "anthropic_model": "claude-sonnet-5"},
        "novelty": {"similarity_warn_threshold": 0.35, "similarity_flag_threshold": 0.55},
    }


@pytest.fixture
def valid_paper() -> dict:
    return {
        "paper_id": "mock-eisa-test-paper-01",
        "qualification": "Occupational Certificate: Software Developer",
        "nqf_level": [4, 5],
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY. Not an official EISA.",
        "duration_minutes": 60,
        "total_marks": 10,
        "instructions": ["Answer all questions."],
        "sections": [
            {
                "id": "A",
                "title": "Section A",
                "marks": 10,
                "outcomes": ["KM-05-KT01"],
                "competencies": ["Programming basics"],
                "difficulty": "foundational",
                "question_types": ["short_answer"],
                "questions": [
                    {
                        "id": "Q-A1",
                        "section_id": "A",
                        "question_number": "A1",
                        "type": "short_answer",
                        "scenario": "A junior developer at Acme Corp needs to explain a concept.",
                        "question": "Explain what a variable is and give one example.",
                        "marks": 10,
                        "difficulty": "foundational",
                        "outcomes": ["KM-05-KT01"],
                        "competencies": ["Programming basics"],
                        "expected_response_type": "short_answer",
                    }
                ],
            }
        ],
    }


@pytest.fixture
def valid_memo(valid_paper) -> dict:
    return {
        "memo_id": "mock-eisa-memo-test-paper-01",
        "paper_id": valid_paper["paper_id"],
        "status_disclaimer": valid_paper["status_disclaimer"],
        "total_marks": 10,
        "sections": [
            {
                "id": "A",
                "questions": [
                    {
                        "question_id": "Q-A1",
                        "total_marks": 10,
                        "model_answer": "A variable is a named storage location for a value, e.g. `age = 30`.",
                        "criteria": [
                            {"description": "Correct definition of a variable", "marks": 5},
                            {"description": "Valid example given", "marks": 5},
                        ],
                        "accepted_alternatives": [],
                        "partial_credit_guidance": "Award 5 marks independently for definition and example.",
                    }
                ],
            }
        ],
    }


@pytest.fixture
def fake_blueprint() -> dict:
    return {
        "paper_id": "mock-eisa-test-paper-01",
        "sections": [
            {
                "id": "A",
                "title": "Section A",
                "marks": 10,
                "outcomes": ["KM-05-KT01"],
                "competencies": ["Programming basics"],
                "required_outcomes": ["KM-05-KT01"],
                "difficulty": "foundational",
                "question_types": ["short_answer"],
                "questions_planned": 1,
            }
        ],
    }


@pytest.fixture
def fake_blueprint_with_slack() -> dict:
    """A section whose full thematic `outcomes` list (3 codes) is broader
    than its `required_outcomes` (1 code) - used to exercise the
    tautological-coverage regression guard, which only fires when there is
    genuine "slack" between the two lists.
    """
    return {
        "paper_id": "mock-eisa-test-paper-01",
        "sections": [
            {
                "id": "A",
                "title": "Section A",
                "marks": 10,
                "outcomes": ["KM-05-KT01", "KM-05-KT02", "KM-05-KT03"],
                "competencies": ["Programming basics", "Software applications", "Intro to programming"],
                "required_outcomes": ["KM-05-KT01"],
                "difficulty": "foundational",
                "question_types": ["short_answer"],
                "questions_planned": 1,
            }
        ],
    }
