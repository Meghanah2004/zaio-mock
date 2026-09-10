"""Real Groq provider (official Groq Python SDK).

Only invoked when LLM_PROVIDER=groq AND GROQ_API_KEY is set (see
src/config.py and src/providers/factory.py). This is a third alternative
real provider alongside src/providers/anthropic_provider.py and
src/providers/gemini_provider.py, for environments whose available paid
credential is a Groq API key - the rest of the pipeline (retrieval,
grounding, novelty, validation, memo generation) is entirely
provider-agnostic and unaffected by which of the three is configured.

Groq's API is OpenAI-compatible chat completions (``client.chat.
completions.create(messages=[...], model=..., ...)``), not a proprietary
shape like Anthropic's Messages API or Gemini's ``generate_content`` - the
request/response plumbing below reflects that, verified against the
installed SDK's actual signatures rather than assumed.

Security notes (mirrors src/providers/anthropic_provider.py and
src/providers/gemini_provider.py):
  - The API key is read once from LLMSettings (env var), never logged.
  - No prompt content or response content is ever printed with the key.
  - The reference-derived "task" payload is NOT sent as an instruction
    channel; it is only used by MockProvider. Here, only the explicit
    system_prompt / user_prompt strings (built by the generation layer from
    prompts/*.txt + the compact blueprint + retrieved evidence) are
    transmitted.

On JSON extraction: this provider returns raw response text exactly like
the other two real providers - it does not parse or validate JSON itself.
src/generation/llm_utils.extract_json (fence-stripping, control-character
normalization) and every downstream validator (schema/marks/coverage/
grounding/novelty) apply uniformly regardless of which provider produced
the text, per the existing provider-agnostic architecture. No JSON-specific
Groq response mode (e.g. its OpenAI-compatible ``response_format={"type":
"json_object"}``) is used here, for the same reason GeminiProvider does not
use Gemini's structured-output mode: adopting a provider-native JSON
enforcement mode is a real behavior change that should be validated against
a live call before being relied on, not adopted speculatively. The
prompt's existing "return ONLY a single JSON object, escape every control
character" instruction plus the deterministic downstream parsing already
cover every defect class observed so far.
"""
from __future__ import annotations

from typing import Any

from src.config import LLMSettings
from src.providers.base import LLMProvider, LLMProviderError, is_retryable_status
from src.security.config import SecurityConfig
from src.security.redaction import redact_secrets


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, settings: LLMSettings, security_config: SecurityConfig | None = None):
        if not settings.api_key:
            raise LLMProviderError(
                "LLM_PROVIDER=groq but GROQ_API_KEY is not set. "
                "Set it in your environment (see .env.example) or use "
                "LLM_PROVIDER=mock for offline/deterministic generation."
            )
        try:
            # Imported lazily (like `anthropic`/`google.genai` in the other
            # two real providers) so mock-only usage never requires this
            # SDK to be installed.
            import groq
        except ImportError as exc:  # pragma: no cover
            raise LLMProviderError(
                "The 'groq' package is not installed. Run: pip install groq"
            ) from exc

        self._settings = settings
        self._security_config = security_config or SecurityConfig()
        # Groq's client-level `timeout` is in SECONDS (unlike Gemini's
        # HttpOptions.timeout, which is milliseconds - verified per-SDK,
        # never assumed to be the same unit across providers).
        # max_retries=0: see src/providers/anthropic_provider.py's identical
        # setting for the full reasoning - this SDK retries internally by
        # default (max_retries=2), which is what compounded with our own
        # src.generation.llm_utils.call_provider_with_retry to turn one
        # daily-quota 429 (guaranteed not to succeed again until the quota
        # resets) into several minutes of doomed nested retrying before
        # /api/generate finally returned a 502 - the real, observed
        # production incident this fixes (request_id
        # 7748bf00-f2bc-4f56-9280-0a74001da161, backend log 2026-09-10
        # 12:14:55: a 321-second /api/generate call). Retry policy now
        # lives in exactly one place: call_provider_with_retry.
        self._client = groq.Groq(
            api_key=settings.api_key,
            timeout=float(self._security_config.provider_timeout_seconds),
            max_retries=0,
        )

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._settings.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=self._settings.max_tokens,
                temperature=self._settings.temperature,
            )
        except Exception as exc:  # broad on purpose: surface as a provider error, never leak the key
            # Defense-in-depth: redact any credential-shaped substring
            # before it can reach a log line or CLI error message, even
            # though no known SDK exception echoes the API key today.
            raise LLMProviderError(
                f"Groq API call failed: {redact_secrets(str(exc))}",
                retryable=is_retryable_status(getattr(exc, "status_code", None)),
            ) from exc

        choices = response.choices
        if not choices or not choices[0].message.content:
            raise LLMProviderError("Groq response contained no text content.")
        return choices[0].message.content
