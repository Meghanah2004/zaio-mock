from __future__ import annotations

import pytest

from src.config import LLMSettings, compute_effective_seed, load_qualification_config


# ---------------------------------------------------------------------------
# compute_effective_seed - regression tests for a real production incident:
# repeated/near-duplicate questions across Paper 1/2/3 because --seed's and
# the frontend's seed-field default were both the same static literal, and
# nothing combined the raw seed with paper_number before this fix. See
# src.config.compute_effective_seed's own docstring for the full root-cause
# analysis and api/service.py's REWORK docstring for how it's wired in.
# ---------------------------------------------------------------------------
def test_effective_seed_differs_for_different_paper_numbers_given_the_same_raw_seed():
    """The actual bug being fixed: two different paper_numbers sharing the
    same caller-supplied seed must no longer produce the same effective
    seed (and therefore no longer retrieve identical evidence)."""
    seed = 20260906  # the real static default both --seed and the frontend form used
    assert compute_effective_seed(seed, 1) != compute_effective_seed(seed, 2)
    assert compute_effective_seed(seed, 2) != compute_effective_seed(seed, 3)
    assert compute_effective_seed(seed, 1) != compute_effective_seed(seed, 3)


def test_effective_seed_is_deterministic_for_the_same_seed_and_paper_number():
    """Reproducibility is preserved, not weakened: the SAME (seed,
    paper_number) pair must always produce the SAME effective seed, and
    therefore the same retrieval conditions."""
    assert compute_effective_seed(20260906, 2) == compute_effective_seed(20260906, 2)
    assert compute_effective_seed(0, 1) == compute_effective_seed(0, 1)
    assert compute_effective_seed(2_147_483_647, 9999) == compute_effective_seed(2_147_483_647, 9999)


def test_effective_seed_formula_is_the_documented_stride():
    """Pins the exact, documented formula (not just "differs"/"same") so a
    future change to the constant or the formula shape is a deliberate,
    visible decision, not an accidental drift."""
    from src.config import SEED_PAPER_STRIDE

    assert SEED_PAPER_STRIDE == 2_147_483_647  # 2^31 - 1, a Mersenne prime
    assert compute_effective_seed(5, 3) == 5 + 3 * SEED_PAPER_STRIDE


def test_effective_seed_ranges_never_overlap_across_the_full_valid_paper_number_range():
    """SEED_PAPER_STRIDE equals SecurityConfig.max_seed + 1 (one full
    seed-space width), so for ANY raw seed within its valid bounds, no two
    distinct paper_numbers can ever collide - checked here across the
    project's actual configured bounds rather than assumed."""
    from src.security.config import SecurityConfig

    security_config = SecurityConfig()
    seed_low = security_config.min_seed
    seed_high = security_config.max_seed
    paper_a, paper_b = 1, security_config.max_paper_number

    # The highest effective seed paper_a can reach must still be lower than
    # the lowest effective seed paper_b can reach, for every raw seed in range.
    assert compute_effective_seed(seed_high, paper_a) < compute_effective_seed(seed_low, paper_b)


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
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-3.8-flash")

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert LLMSettings().model == "claude-sonnet-5"

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert LLMSettings().model == "gemini-3.6-flash"

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert LLMSettings().model == "openai/gpt-oss-120b"

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert LLMSettings().model == "google/gemini-3.8-flash"


def test_llm_settings_openrouter_model_and_api_key_env_vars(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-3.8-flash")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake0000000000000000000000000000000000000000")
    settings = LLMSettings()
    assert settings.model == "google/gemini-3.8-flash"
    assert settings.api_key == "sk-or-v1-fake0000000000000000000000000000000000000000"


def test_llm_settings_openrouter_has_no_hard_coded_default_model(monkeypatch):
    """Unlike anthropic/gemini/groq, OpenRouter routes to too broad a model
    catalog for one sensible fallback - OPENROUTER_MODEL is expected to
    always be set explicitly (see .env.example)."""
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert LLMSettings().model == ""


def test_has_real_credentials_true_for_openrouter_with_a_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fake0000000000000000000000000000000000000000")
    assert LLMSettings().has_real_credentials() is True


def test_has_real_credentials_false_for_openrouter_without_a_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert LLMSettings().has_real_credentials() is False
