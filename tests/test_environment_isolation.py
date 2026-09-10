"""Regression tests for a real incident: a bare ``pytest -q`` hung for
>120 seconds because the developer's local ``.env`` had a real
``LLM_PROVIDER=groq`` and a real ``GROQ_API_KEY`` configured (for actual
`python -m src.cli generate` runs), and api/service.py's endpoint tests
build a provider from live environment settings with no mocking, by
design - they exercise the exact same real code path the CLI uses.

The fix is tests/conftest.py's ``pytest_configure`` hook, which calls
``force_offline_test_environment()`` before pytest collects a single test
module. These tests verify that mechanism directly - simulating exactly
the "real credentials in the environment" scenario that caused the hang -
rather than merely trusting that the session-level hook ran once.
"""
from __future__ import annotations

from pathlib import Path

from src.config import LLMSettings
from src.providers.factory import build_provider
from src.providers.mock_provider import MockProvider
from tests.conftest import force_offline_test_environment


def test_a_real_looking_groq_configuration_resolves_to_a_real_provider_selection_before_the_fix_runs(
    monkeypatch,
):
    """Sanity check that this test actually reproduces the dangerous
    starting state - without this, the next test would be proving nothing."""
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_real_looking_key_that_must_never_be_used_012345")

    settings = LLMSettings()
    assert settings.provider == "groq"
    assert settings.has_real_credentials() is True


def test_force_offline_test_environment_neutralizes_a_real_groq_configuration(monkeypatch):
    """The actual regression test: even when the environment looks exactly
    like a developer's real .env for live Groq generation,
    force_offline_test_environment() must make LLMSettings() resolve to
    mock, with no credentials, and build_provider() must return
    MockProvider - never construct a real, network-capable provider."""
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_real_looking_key_that_must_never_be_used_012345")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-looking-key-that-must-never-be-used")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyREALlookingKeyThatMustNeverBeUsed0123456789"[:39])

    force_offline_test_environment()

    settings = LLMSettings()
    assert settings.provider == "mock"
    assert not settings.api_key  # blanked to "" (see force_offline_test_environment), not necessarily None
    assert settings.has_real_credentials() is False

    provider = build_provider(settings)
    assert isinstance(provider, MockProvider)


def test_force_offline_test_environment_blanks_every_real_providers_api_key(monkeypatch):
    """Must SET each key to an explicit blank value, not merely delete it -
    see force_offline_test_environment's docstring: leaving a variable
    ABSENT lets src.config's lazy .env loader (which only fills a var that
    is "not already present") refill it from the real .env the first time
    src.config is imported, silently undoing the isolation. This was a
    real bug caught by this exact test during development."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")

    force_offline_test_environment()

    import os

    assert os.environ.get("ANTHROPIC_API_KEY") == ""
    assert os.environ.get("GEMINI_API_KEY") == ""
    assert os.environ.get("GROQ_API_KEY") == ""
    # Not merely blank when read directly - actually PRESENT as a key in
    # os.environ, which is the property that blocks the lazy .env loader.
    assert "ANTHROPIC_API_KEY" in os.environ
    assert "GEMINI_API_KEY" in os.environ
    assert "GROQ_API_KEY" in os.environ


def test_the_isolation_hook_has_already_run_for_this_test_session_by_default():
    """No monkeypatching here at all: this asserts the ACTUAL, ambient
    state of the current pytest session - proving pytest_configure really
    did run before collection, not just that the function works when
    called manually (the two tests above)."""
    settings = LLMSettings()
    assert settings.provider == "mock"
    assert not settings.api_key


def test_developers_local_env_provider_settings_are_never_read_as_is_during_this_session():
    """Directly reads the real .env file's OWN LLM_PROVIDER/*_API_KEY
    lines (never their values - only whether the key names are set, and
    never printed) and confirms the live os.environ for THIS session does
    not reflect them, proving the isolation is actually suppressing
    whatever is really in .env right now, not just testing a synthetic
    scenario."""
    import os

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return  # nothing to compare against in an environment with no .env at all

    real_provider = None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("LLM_PROVIDER="):
            real_provider = line.partition("=")[2].strip().strip('"').strip("'")
            break

    if real_provider and real_provider != "mock":
        # .env asks for a real provider - the live test session must not
        # have honoured that. The key env var may be present (blanked to
        # "") rather than absent - see force_offline_test_environment's
        # docstring for why that distinction matters - so check falsiness,
        # not absence.
        assert LLMSettings().provider == "mock"
        assert not os.environ.get(f"{real_provider.upper()}_API_KEY")


def test_force_offline_test_environment_is_never_referenced_by_the_production_cli():
    """Requirement: the isolation mechanism must not alter production CLI
    behavior. src/cli.py must have no knowledge of this test-only hook -
    a real ``python -m src.cli generate`` run's provider selection is
    driven purely by the real environment, exactly as before this fix."""
    cli_source = (Path(__file__).resolve().parent.parent / "src" / "cli.py").read_text(encoding="utf-8")
    assert "force_offline_test_environment" not in cli_source
    assert "tests.conftest" not in cli_source
