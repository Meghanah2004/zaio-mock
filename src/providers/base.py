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
    """Raised for any provider-level failure (missing key, API error, etc.).

    ``retryable`` (default True, preserving the prior blanket-retry
    behavior for anything not explicitly classified) lets a concrete
    provider tell src.generation.llm_utils.call_provider_with_retry whether
    retrying is worth attempting at all. A permanent, input-shaped failure
    (e.g. a 401/403 - a bad or revoked API key - or a 400/404/422 - a
    malformed request) will fail identically on every retry; looping
    through the full retry budget for one is pure wasted latency, not
    resilience. A transient failure (429 rate limit, 5xx, network/timeout)
    genuinely might succeed on a later attempt, so stays retryable=True -
    this is deliberately NOT "never retry a 429": a rate limit can still
    clear within the bounded retry window, unlike a wrong credential."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


_PERMANENT_HTTP_STATUS_CODES = frozenset({400, 401, 403, 404, 422})
"""HTTP statuses whose failure is a property of the REQUEST/credential, not
a transient condition - retrying with the exact same request will fail
identically every time. Deliberately excludes 429 (rate limit - a real,
observed daily-quota case that eventually clears) and every 5xx (server-
side, genuinely may be transient) - both of those stay retryable. Shared by
every real provider's exception classification (see is_retryable_status
below) so the same policy applies uniformly regardless of which SDK raised
the underlying error."""


def is_retryable_status(status_code: int | None) -> bool:
    """True unless ``status_code`` is a known-permanent client error (see
    _PERMANENT_HTTP_STATUS_CODES). ``None`` (no HTTP status available at
    all - a network error, a timeout, or an SDK exception that doesn't
    carry one) defaults to retryable=True, the safe/conservative choice:
    never assume a failure is permanent without positive evidence that it
    is."""
    if status_code is None:
        return True
    return status_code not in _PERMANENT_HTTP_STATUS_CODES


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
