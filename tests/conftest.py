"""Shared pytest fixtures.

Fixtures build a small SYNTHETIC reference-analysis + qualification config
so generation/validation tests do not depend on parsing the real sdev/
corpus (faster, isolated, and unaffected by future changes to the real
reference material).

TEST-ENVIRONMENT ISOLATION (pytest_configure below): a developer's local
``.env`` is EXACTLY as real when pytest imports src.config as it is when
``python -m src.cli generate`` does - src.config.LLMSettings resolves
provider/model/api_key from os.environ, populated from .env by
src.config._load_dotenv_if_present() (which only sets a var if it is not
ALREADY present in os.environ). api/service.py's endpoint tests build a
provider from those live settings with NO mocking, by design - they
exercise the exact same real code path the CLI uses. With a real
LLM_PROVIDER=groq and a real GROQ_API_KEY configured for actual generation
work, a bare ``pytest -q`` therefore constructed a REAL GroqProvider and
attempted a REAL network call - observed directly as a >120s hang. See
tests/test_environment_isolation.py for the regression test.
"""
from __future__ import annotations

import os

import pytest

_REAL_PROVIDER_API_KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY")


def force_offline_test_environment() -> None:
    """Force LLM_PROVIDER=mock and blank every real provider's API key in
    os.environ, so nothing in this process can ever resolve to a real,
    network-capable provider - no matter what the developer's local .env
    contains. Exported (not a private/underscore name) specifically so
    tests/test_environment_isolation.py can call it directly to verify its
    effect, rather than re-implementing the same logic to check it.

    Every touched variable is SET to a value (LLM_PROVIDER to "mock", each
    API key to ""), never deleted/popped-to-absent. This matters and was
    caught by a failing regression test during development: src.config's
    module-level ``_load_dotenv_if_present()`` only loads a var FROM .env
    when it is not ALREADY present in os.environ. This hook runs from
    pytest_configure, before any test module - and so before src.config -
    is ever imported; if a variable were left ABSENT here instead of being
    set to an explicit value, src.config's lazy .env loader would see "not
    present yet" the first time something later imports it (e.g. during
    test collection) and dutifully fill it back in from the real .env,
    silently undoing this function for that one variable. Setting an
    explicit (blank) value up front is what makes the "already present"
    check correctly block that later load, regardless of import order.

    Does NOT touch the real .env file, and does not run outside a pytest
    process - src/cli.py never imports or calls this, so a real
    ``python -m src.cli generate`` run's provider selection is completely
    unaffected (see tests/test_environment_isolation.py for the check that
    src/cli.py itself has no reference to it).

    Individual provider tests (tests/test_anthropic_provider.py,
    tests/test_gemini_provider.py, tests/test_groq_provider.py) are
    unaffected by this: they construct LLMSettings with an explicit fake
    api_key argument, which always overrides whatever default_factory
    would otherwise read from the environment.
    """
    os.environ["LLM_PROVIDER"] = "mock"
    for env_var in _REAL_PROVIDER_API_KEY_ENV_VARS:
        os.environ[env_var] = ""


def pytest_configure(config: pytest.Config) -> None:
    """Runs once, before test collection - and therefore before any test
    module, including src.config, is ever imported (see
    force_offline_test_environment's docstring for why that ordering is
    what makes this effective)."""
    force_offline_test_environment()


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


@pytest.fixture(scope="module", autouse=True)
def _isolate_generation_history(tmp_path_factory):
    """api/service.py's generate_paper_and_memo now performs real
    cross-paper novelty checking against artifacts/generation-history.json
    - the SAME file a real ``python -m src.cli generate`` run writes to
    (this is the real fix for "the API must invoke the actual grounded
    pipeline," not a test-only concern - see that function's REWORK
    docstring). Without isolation here, one api/test_api_*.py test's
    MockProvider-generated fixture content would pollute another test's
    novelty check (MockProvider only has 2 content variants per section,
    so two tests whose seeds land on the same variant would legitimately
    collide and fail), AND every test run would permanently pollute the
    real project's generation history with throwaway fixture content.

    MODULE-scoped (not function-scoped) and NOT built on the built-in
    ``monkeypatch`` fixture, for a subtle but important reason: pytest sets
    up higher-scoped fixtures before lower-scoped ones for the first test
    in a scope, and ``monkeypatch`` is itself function-scoped only (pytest
    raises a ScopeMismatch if a module-scoped fixture requests it). A
    test_api_results.py-style module with its own ``scope="module"``
    autouse seeding fixture (e.g. one real `generate()` call reused by
    every test in that module) would otherwise run its one-time setup
    BEFORE a function-scoped isolation fixture ever activated - which is
    exactly how this fixture, in an earlier function-scoped form, once let
    a test-only paper leak into and permanently pollute the real project's
    artifacts/generation-history.json. Redirects api.service's module-level
    history path to a fresh per-TEST-MODULE temp file (shared by every test
    within that one module, isolated from every other module) for the
    duration of that module - a no-op for every module that never imports
    api.service, which is every non-API test module. Restores the original
    path afterwards so this process's own module-level state never leaks
    across unrelated test modules either."""
    import api.service as service_module

    original_path = service_module._GENERATION_HISTORY_PATH
    service_module._GENERATION_HISTORY_PATH = tmp_path_factory.mktemp("generation_history") / "generation-history.json"
    yield
    service_module._GENERATION_HISTORY_PATH = original_path


@pytest.fixture(autouse=True)
def _reset_generation_history_between_tests():
    """Deletes the (already-isolated, never the real - see
    _isolate_generation_history above) history file before every single
    test function, so each test's own real generation always starts from
    an empty cross-paper history - src.validation.cross_paper_novelty.
    load_history treats a missing file as ``{}``, exactly like a brand new
    project.

    This matters even WITH per-module isolation above: a module can share
    one isolated file across many test functions (test_api_results.py's
    module-scoped ``_seed_one_result`` seeds one paper that every test in
    that module reuses), and MockProvider's real fixture content is
    deliberately narrow - exactly 2 hand-written variants per section (see
    src/providers/mock_provider.py) - close enough in wording to each other
    (same numeric/logic structure, only cosmetic scenario details differ)
    that two DIFFERENT real generations landing in the SAME history file
    can legitimately exceed the real, non-negotiable 0.6 cross-paper
    novelty threshold against EACH OTHER, not just against themselves. That
    is a MockProvider content-bank limitation (see its module docstring,
    "genuine new scenario variety requires... switching to a real
    provider"), not a defect in the novelty check, which must stay strict.
    Resetting between tests removes that accidental cross-test coupling
    without touching the threshold or the real project history file."""
    import api.service as service_module

    service_module._GENERATION_HISTORY_PATH.unlink(missing_ok=True)
    yield


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
        "nqf_level": 5,
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
