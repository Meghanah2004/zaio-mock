"""LLM provider abstraction.

Every generation stage talks to this interface only - never to a concrete
SDK. This is what lets Phase 1 run end-to-end without a paid API key (via
MockProvider) while still demonstrating exactly how a real Anthropic call
would be wired in (AnthropicProvider).

``task`` carries a small structured spec (kind + parameters) alongside the
natural-language system/user prompts. AnthropicProvider ignores it and
sends only the text prompts to the real API - a real LLM must work from the
prompt alone, matching production behaviour. MockProvider uses it to
synthesize deterministic, reproducible output without any network access.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProviderError(RuntimeError):
    """Raised for any provider-level failure (missing key, API error, etc.)."""


class LLMProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        """Return raw text expected to contain a single JSON object.

        Callers are responsible for parsing and validating the result -
        provider output is always treated as untrusted until it passes
        schema validation (see src/validation/schema_validator.py).
        """
        raise NotImplementedError
