"""Real Google Gemini provider (Google GenAI SDK).

Only invoked when LLM_PROVIDER=gemini AND GEMINI_API_KEY is set (see
src/config.py and src/providers/factory.py). This is an alternative real
provider to src/providers/anthropic_provider.py for environments whose only
available paid credential is a Gemini API key rather than an Anthropic one
- the rest of the pipeline (retrieval, grounding, novelty, validation,
memo generation) is entirely provider-agnostic and unaffected by which of
the two is configured.

Security notes (mirrors src/providers/anthropic_provider.py):
  - The API key is read once from LLMSettings (env var), never logged.
  - No prompt content or response content is ever printed with the key.
  - The reference-derived "task" payload is NOT sent as an instruction
    channel; it is only used by MockProvider. Here, only the explicit
    system_prompt / user_prompt strings (built by the generation layer from
    prompts/*.txt + the compact blueprint + retrieved evidence) are
    transmitted.

On NOT using Gemini's server-side structured-output mode
(``response_mime_type="application/json"`` + ``response_schema``):
considered deliberately after a real call produced a JSON object missing
a required field (see src/generation/question_generator.py's
``_resolve_expected_response_type`` for the actual fix and root cause).
Server-side schema enforcement WOULD prevent that whole class of defect,
but Gemini's structured-output dialect only supports a constrained subset
of JSON Schema, and getting that dialect exactly right for this pipeline's
question contract cannot be verified without spending a real API call
against the live service - which this project's "no fake completion" rule
and its test-safety requirements both rule out doing speculatively. The
prompt-plus-deterministic-derivation fix below is fully verifiable offline
and directly resolves the reported defect; switching to structured output
is a reasonable follow-up once it can be validated against a real key, not
adopted here without that verification.
"""
from __future__ import annotations

from typing import Any

from src.config import LLMSettings
from src.providers.base import LLMProvider, LLMProviderError, is_retryable_status
from src.security.config import SecurityConfig
from src.security.redaction import redact_secrets


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, settings: LLMSettings, security_config: SecurityConfig | None = None):
        if not settings.api_key:
            raise LLMProviderError(
                "LLM_PROVIDER=gemini but GEMINI_API_KEY is not set. "
                "Set it in your environment (see .env.example) or use "
                "LLM_PROVIDER=mock for offline/deterministic generation."
            )
        try:
            # Imported lazily (like `anthropic` in anthropic_provider.py) so
            # MockProvider/AnthropicProvider-only usage never requires this
            # SDK to be installed.
            from google import genai
            from google.genai import types as genai_types
        except ImportError as exc:  # pragma: no cover
            raise LLMProviderError(
                "The 'google-genai' package is not installed. Run: pip install google-genai"
            ) from exc

        self._settings = settings
        self._security_config = security_config or SecurityConfig()
        self._client = genai.Client(
            api_key=settings.api_key,
            # HttpOptions.timeout is in MILLISECONDS (verified against the
            # installed SDK's field description - see docs/DESIGN_NOTE.md);
            # provider_timeout_seconds is the same bound AnthropicProvider
            # passes to its own SDK call, in the unit each SDK expects.
            http_options=genai_types.HttpOptions(timeout=self._security_config.provider_timeout_seconds * 1000),
        )

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        from google.genai import types as genai_types

        try:
            response = self._client.models.generate_content(
                model=self._settings.model,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=self._settings.max_tokens,
                    temperature=self._settings.temperature,
                    # This pipeline never supplies `tools` - every call asks
                    # for plain JSON text, nothing is ever invoked as a
                    # function. The SDK enables Automatic Function Calling
                    # by default regardless of whether any tools are given
                    # (verified against the installed SDK's
                    # _extra_utils.should_disable_afc: AFC is only disabled
                    # when explicitly told to be), which is why a real call
                    # logged "Direct use of automatic function calling (AFC)
                    # ... is not recommended" even though nothing here uses
                    # function calling at all. Explicitly disabling it here
                    # is config hygiene for an SDK feature this pipeline has
                    # no use for - it changes no business logic.
                    automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
        except Exception as exc:  # broad on purpose: surface as a provider error, never leak the key
            # Defense-in-depth: redact any credential-shaped substring
            # before it can reach a log line or CLI error message, even
            # though no known SDK exception echoes the API key today.
            # Gemini's SDK exposes the HTTP status as `.code`, not the
            # `.status_code` attribute Groq's/Anthropic's SDKs use (both
            # verified directly against the installed SDKs, never assumed
            # to share a naming convention just because they're all
            # OpenAI-shaped) - see src/providers/base.py's
            # is_retryable_status for the shared permanent-vs-transient
            # classification policy this feeds.
            raise LLMProviderError(
                f"Gemini API call failed: {redact_secrets(str(exc))}",
                retryable=is_retryable_status(getattr(exc, "code", None)),
            ) from exc

        text = response.text
        if not text:
            raise LLMProviderError("Gemini response contained no text content.")
        return text
