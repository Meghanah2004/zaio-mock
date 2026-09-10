from __future__ import annotations

import pytest

from src.config import LLMSettings, load_qualification_config


def test_load_qualification_config_rejects_out_of_scope():
    with pytest.raises(ValueError, match="out of scope"):
        load_qualification_config("cybersecurity")


def test_load_qualification_config_rejects_unknown_data_science():
    with pytest.raises(ValueError, match="out of scope"):
        load_qualification_config("data_science")


def test_load_qualification_config_loads_software_developer():
    config = load_qualification_config("software_developer")
    assert config["qualification_key"] == "software_developer"
    assert sum(s["marks"] for s in config["sections"]) == config["total_marks"]


def test_software_developer_nqf_level_is_a_single_fixed_value_not_a_module_span():
    # Regression test: the paper cover used to show "NQF Level(s): [4, 5]"
    # (the raw span of per-module NQF levels across all 11 supplied Learner
    # Guides - see docs/reference-analysis.md fact F4) instead of the
    # qualification's actual assessed level. See src/generation/blueprint.py.
    config = load_qualification_config("software_developer")
    assert config["nqf_level"] == 5
    assert isinstance(config["nqf_level"], int)


def test_llm_settings_default_gemini_model_is_the_current_available_one(monkeypatch):
    # Regression test: "gemini-2.5-flash" (this project's originally
    # documented default) started 404-ing for new Gemini API keys with a
    # live "no longer available to new users" response naming
    # "gemini-3.6-flash" as the replacement - confirmed against the real
    # API, not assumed. GEMINI_MODEL always overrides this if the user sets
    # it explicitly (see the next test).
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert LLMSettings().model == "gemini-3.6-flash"


def test_llm_settings_gemini_model_env_var_overrides_the_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "some-future-model")
    assert LLMSettings().model == "some-future-model"


def test_llm_settings_default_groq_model_and_api_key_env_vars(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert LLMSettings().model == "openai/gpt-oss-120b"

    monkeypatch.setenv("GROQ_MODEL", "some-future-groq-model")
    assert LLMSettings().model == "some-future-groq-model"

    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake0000000000000000000000000000test")
    assert LLMSettings().api_key == "gsk_fake0000000000000000000000000000test"


def test_llm_settings_provider_selects_which_model_env_var_is_read(monkeypatch):
    # LLM_PROVIDER=anthropic must never pick up GEMINI_MODEL/GROQ_MODEL,
    # and vice versa, even if all three happen to be set in the environment.
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.6-flash")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert LLMSettings().model == "claude-sonnet-5"

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert LLMSettings().model == "gemini-3.6-flash"

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert LLMSettings().model == "openai/gpt-oss-120b"
