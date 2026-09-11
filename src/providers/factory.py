"""Selects and constructs the configured LLM provider.

Never hard-codes a choice: reads LLMSettings (env-driven, see src/config.py).
Falls back to the deterministic MockProvider - with a clearly printed
warning, never a silent substitution - whenever real credentials are not
available, per the project's "no fake completion" rule (the fallback is
loud, not hidden).

REWORK (production hardening): "loud" used to mean only a stderr print - in
a real deployment whose logs are not actively watched, a misconfigured
GROQ_API_KEY (missing, blank, wrong variable name) would silently degrade
to serving MockProvider's fixed fixture content as if it were real,
learner-guide-grounded generation, with nothing louder than a log line
most operators would never see. ``security_config.require_real_provider``
(env: REQUIRE_REAL_PROVIDER, default false) turns that same condition into
an immediate ``LLMProviderError`` instead, for exactly the deployments that
need it, while leaving every existing local-dev/CLI/test call site (which
never sets this flag) completely unaffected.
"""
from __future__ import annotations

import sys

from src.config import LLMSettings
from src.providers.base import LLMProvider, LLMProviderError
from src.providers.mock_provider import MockProvider
from src.security.config import SecurityConfig

_REAL_PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def build_provider(settings: LLMSettings, security_config: SecurityConfig | None = None) -> LLMProvider:
    security_config = security_config or SecurityConfig()

    if settings.provider == "mock":
        if security_config.require_real_provider:
            raise LLMProviderError(
                "REQUIRE_REAL_PROVIDER is set but LLM_PROVIDER is 'mock' (or was left unset) - "
                "refusing to start/serve a request with fake fixture content in a deployment that "
                "requires real generation. Set LLM_PROVIDER=groq (or anthropic/gemini/openrouter) and "
                "its matching API key."
            )
        return MockProvider()

    if settings.provider not in _REAL_PROVIDER_ENV_VARS:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {settings.provider!r}. "
            "Supported: 'mock', 'anthropic', 'gemini', 'groq', 'openrouter'."
        )

    env_var = _REAL_PROVIDER_ENV_VARS[settings.provider]
    if not settings.api_key:
        if security_config.require_real_provider:
            raise LLMProviderError(
                f"REQUIRE_REAL_PROVIDER is set but LLM_PROVIDER={settings.provider} and {env_var} is not "
                f"set - refusing to start/serve a request with fake fixture content in a deployment "
                f"that requires real generation. Set {env_var} in your environment (see .env.example)."
            )
        print(
            f"WARNING: LLM_PROVIDER={settings.provider} but {env_var} is not set. "
            f"Falling back to the deterministic MockProvider. Set {env_var} "
            f"in your environment (see .env.example) to use the real provider.",
            file=sys.stderr,
        )
        return MockProvider()

    if settings.provider == "anthropic":
        from src.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    if settings.provider == "gemini":
        from src.providers.gemini_provider import GeminiProvider

        return GeminiProvider(settings)
    if settings.provider == "groq":
        from src.providers.groq_provider import GroqProvider

        return GroqProvider(settings)
    from src.providers.openrouter_provider import OpenRouterProvider

    return OpenRouterProvider(settings)
