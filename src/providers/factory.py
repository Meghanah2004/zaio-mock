"""Selects and constructs the configured LLM provider.

Never hard-codes a choice: reads LLMSettings (env-driven, see src/config.py).
Falls back to the deterministic MockProvider - with a clearly printed
warning, never a silent substitution - whenever real credentials are not
available, per the project's "no fake completion" rule (the fallback is
loud, not hidden).
"""
from __future__ import annotations

import sys

from src.config import LLMSettings
from src.providers.base import LLMProvider
from src.providers.mock_provider import MockProvider


def build_provider(settings: LLMSettings) -> LLMProvider:
    if settings.provider == "mock":
        return MockProvider()

    if settings.provider == "anthropic":
        if not settings.api_key:
            print(
                "WARNING: LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set. "
                "Falling back to the deterministic MockProvider. Set ANTHROPIC_API_KEY "
                "in your environment (see .env.example) to use the real provider.",
                file=sys.stderr,
            )
            return MockProvider()
        from src.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)

    raise ValueError(f"Unknown LLM_PROVIDER: {settings.provider!r}. Supported: 'mock', 'anthropic'.")
