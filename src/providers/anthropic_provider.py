"""Real Anthropic provider.

Only invoked when LLM_PROVIDER=anthropic AND ANTHROPIC_API_KEY is set (see
src/config.py and src/providers/factory.py). This module demonstrates the
production call path; Phase 1's shipped artifacts were generated with
MockProvider because no API key is available in this environment (see
README "Known limitations").

Security notes:
  - The API key is read once from LLMSettings (env var), never logged.
  - No prompt content or response content is ever printed with the key.
  - The reference-derived "task" payload is NOT sent as an instruction
    channel; it is only used by MockProvider. Here, only the explicit
    system_prompt / user_prompt strings (built by the generation layer from
    prompts/*.txt + the compact blueprint) are transmitted.
"""
from __future__ import annotations

from typing import Any

from src.config import LLMSettings
from src.providers.base import LLMProvider, LLMProviderError
from src.security.config import SecurityConfig
from src.security.redaction import redact_secrets


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: LLMSettings, security_config: SecurityConfig | None = None):
        if not settings.api_key:
            raise LLMProviderError(
                "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set. "
                "Set it in your environment (see .env.example) or use "
                "LLM_PROVIDER=mock for offline/deterministic generation."
            )
        try:
            import anthropic  # imported lazily so mock-only usage never needs the SDK installed
        except ImportError as exc:  # pragma: no cover
            raise LLMProviderError(
                "The 'anthropic' package is not installed. Run: pip install anthropic"
            ) from exc
        self._client = anthropic.Anthropic(api_key=settings.api_key)
        self._settings = settings
        self._security_config = security_config or SecurityConfig()

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        # Imported lazily (like `anthropic` itself in __init__) rather than at
        # module level, so MockProvider-only usage never requires the SDK to
        # be installed. `response.content` is a union of many block types
        # (tool-use, thinking, tool-result, ...); isinstance narrowing here
        # lets mypy - and a human reader - see precisely which blocks carry a
        # `.text` attribute, instead of a runtime-only `getattr(...) == "text"`
        # string comparison mypy cannot statically verify.
        from anthropic.types import TextBlock

        try:
            # NOTE: the installed anthropic SDK's Messages.create() does not
            # accept a top-level `temperature` argument (verified against the
            # live method signature - see docs/SECURITY-AUDIT.md 6.5). It is
            # intentionally NOT passed here; LLMSettings.temperature is kept
            # in configuration for forward-compatibility with SDK versions
            # that do support it, rather than removed from the config surface.
            response = self._client.messages.create(
                model=self._settings.model,
                max_tokens=self._settings.max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                timeout=self._security_config.provider_timeout_seconds,
            )
        except Exception as exc:  # broad on purpose: surface as a provider error, never leak the key
            # Defense-in-depth: redact any credential-shaped substring before
            # it can reach a log line or CLI error message, even though no
            # known SDK exception echoes the API key today.
            raise LLMProviderError(f"Anthropic API call failed: {redact_secrets(str(exc))}") from exc

        parts = [block.text for block in response.content if isinstance(block, TextBlock)]
        if not parts:
            raise LLMProviderError("Anthropic response contained no text content.")
        return "\n".join(parts)
