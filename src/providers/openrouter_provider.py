"""Real OpenRouter provider.

Only invoked when LLM_PROVIDER=openrouter AND OPENROUTER_API_KEY is set (see
src/config.py and src/providers/factory.py). A fourth alternative real
provider alongside src/providers/anthropic_provider.py,
src/providers/gemini_provider.py, and src/providers/groq_provider.py - the
rest of the pipeline (retrieval, grounding, novelty, validation, memo
generation) is entirely provider-agnostic and unaffected by which of the
four is configured.

OpenRouter (https://openrouter.ai) is a routing gateway in front of many
different underlying models (OpenAI, Anthropic, Google, open-weight
models, ...), exposed through ONE OpenAI-compatible chat-completions REST
endpoint (``POST https://openrouter.ai/api/v1/chat/completions``) - not a
proprietary request/response shape like Anthropic's Messages API or
Gemini's ``generate_content``. Unlike Groq/Anthropic/Gemini, there is no
project-specific OpenRouter Python SDK to depend on; this module talks to
that REST endpoint directly via ``httpx`` (already an installed dependency
of this project - transitively required by the ``groq`` and ``anthropic``
SDKs' own transport layer, and already directly imported in this project's
own test suite - see tests/test_groq_provider.py's httpx.Response fakes).
Making it an explicit, direct dependency (see pyproject.toml/
requirements.txt) rather than relying on it staying available only as a
transitive one is more robust, without adding any new package to the
installed environment.

IMPORTANT: because OpenRouter fronts many different backend models, this
provider deliberately sends only the UNIVERSALLY OpenAI-compatible request
fields (model, messages, max_tokens, temperature) - it does NOT send any
Groq-specific parameter (``reasoning_effort``, ``reasoning_format``, or any
Groq SDK behavior/headers). Groq's ``max_completion_tokens`` field name is
also deliberately NOT used here; ``max_tokens`` is the long-standing,
universally-supported OpenAI-compatible field name every backend OpenRouter
routes to is expected to understand, whereas ``max_completion_tokens`` is a
newer, model-specific OpenAI naming choice this project has only verified
against Groq's own SDK, not the general OpenAI-compatible surface.

Security notes (mirrors src/providers/anthropic_provider.py,
src/providers/gemini_provider.py, src/providers/groq_provider.py):
  - The API key is read once from LLMSettings (env var), never logged; sent
    only as the standard ``Authorization: Bearer <key>`` header OpenRouter's
    own API requires, never logged or included in any exception message
    (redact_secrets is applied as defense-in-depth regardless).
  - No prompt content or response content is ever printed with the key.
  - The reference-derived "task" payload is NOT sent as an instruction
    channel; it is only used by MockProvider. Here, only the explicit
    system_prompt / user_prompt strings (built by the generation layer from
    prompts/*.txt + the compact blueprint + retrieved evidence) are
    transmitted.

On JSON extraction: this provider returns raw response text exactly like
the other three real providers - it does not parse or validate the
GENERATED CONTENT as JSON itself (it does parse the outer HTTP response
envelope, which is a fixed, well-known OpenAI-compatible shape, not
provider output). src/generation/llm_utils.extract_json and every
downstream validator apply uniformly regardless of which provider produced
the text.
"""
from __future__ import annotations

from typing import Any

from src.config import LLMSettings
from src.providers.base import LLMProvider, LLMProviderError, is_retryable_status
from src.security.config import SecurityConfig
from src.security.redaction import redact_secrets

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _extract_status_code(exc: Exception) -> int | None:
    """``httpx.HTTPStatusError`` (unlike groq.APIStatusError/anthropic's
    equivalent) has no top-level ``.status_code`` shortcut - only nested
    under ``.response.status_code`` (confirmed directly against the
    installed httpx version's actual exception shape). A network/timeout
    error (``httpx.ConnectError``/``httpx.TimeoutException``) has no
    ``.response`` at all. Never raises: returns None for anything without
    a real HTTP response, which is_retryable_status treats as retryable -
    the safe default for a failure with no positive evidence it is
    permanent."""
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _extract_retry_after(exc: Exception) -> float | None:
    """Best-effort extraction of a 429/5xx response's ``Retry-After`` header
    (seconds), mirroring src.providers.groq_provider._extract_retry_after -
    same reasoning: honor what the server actually asked for instead of a
    fixed guess. ``httpx.HTTPStatusError`` (the exception this provider
    raises internally, see ``generate`` below) carries the real
    ``httpx.Response`` as ``.response``, headers included, exactly like the
    Groq SDK's own exception shape - the identical extraction logic applies
    unchanged. Never raises: returns None (falls back to the existing fixed
    backoff) for a missing response/header, a non-numeric value, or a
    non-positive value.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(self, settings: LLMSettings, security_config: SecurityConfig | None = None):
        if not settings.api_key:
            raise LLMProviderError(
                "LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is not set. "
                "Set it in your environment (see .env.example) or use "
                "LLM_PROVIDER=mock for offline/deterministic generation."
            )
        try:
            # Imported lazily (like `groq`/`anthropic`/`google.genai` in the
            # other three real providers) so mock-only usage never requires
            # httpx to be exercised for this purpose, and to keep this
            # provider's import cost paid only when actually selected.
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise LLMProviderError(
                "The 'httpx' package is not installed. Run: pip install httpx"
            ) from exc

        self._settings = settings
        self._security_config = security_config or SecurityConfig()
        # No SDK-level retry to disable here (unlike groq.Groq(max_retries=0)/
        # anthropic.Anthropic(max_retries=0)) - a plain httpx.Client never
        # retries on its own, so there is no second retry layer to compound
        # with src.generation.llm_utils.call_provider_with_retry in the
        # first place; that function remains the one place retry policy
        # lives, for this provider exactly as for the other three.
        self._client = httpx.Client(
            base_url=_OPENROUTER_BASE_URL,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=float(self._security_config.provider_timeout_seconds),
        )

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        try:
            response = self._client.post(
                "/chat/completions",
                json={
                    "model": self._settings.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": self._settings.max_tokens,
                    "temperature": self._settings.temperature,
                },
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:  # broad on purpose: surface as a provider error, never leak the key
            # Defense-in-depth: redact any credential-shaped substring
            # before it can reach a log line or CLI error message, even
            # though no known failure path echoes the API key today.
            raise LLMProviderError(
                f"OpenRouter API call failed: {redact_secrets(str(exc))}",
                retryable=is_retryable_status(_extract_status_code(exc)),
                retry_after=_extract_retry_after(exc),
            ) from exc

        choices = body.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
        if not content:
            raise LLMProviderError("OpenRouter response contained no text content.")
        return content
