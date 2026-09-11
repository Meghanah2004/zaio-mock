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

import logging
from typing import Any

from src.config import LLMSettings
from src.providers.base import LLMProvider, LLMProviderError, is_retryable_status
from src.security.config import SecurityConfig
from src.security.redaction import redact_secrets

_logger = logging.getLogger(__name__)

_REASONING_EFFORT_MODEL_PREFIXES = ("openai/gpt-oss-",)
"""Model families confirmed (installed Groq SDK's own
completion_create_params.CompletionCreateParamsBase.reasoning_effort
docstring, 2026-09-11) to accept the ``reasoning_effort`` chat-completion
parameter: "openai/gpt-oss-20b and openai/gpt-oss-120b support 'low',
'medium', or 'high'. 'medium' is the default value." (qwen3 models also
support it under a different prefix/scheme, deliberately not included here
- this project's supported/tested model is the gpt-oss family; adding
qwen3 support later needs its own verification, not a speculative guess.)

TOKEN AUDIT FINDING (2026-09-11), the single largest-potential lever found:
every call before this change left ``reasoning_effort`` unset, so Groq
defaulted openai/gpt-oss-120b to 'medium' reasoning for EVERY call -
including well-specified, schema-constrained JSON-generation tasks (one
exam question against explicit hard constraints; one memo against an
explicit mark budget) that are answer-instructions-correctly tasks, not
open-ended multi-step reasoning problems. Reasoning tokens are billed as
part of completion_tokens/total_tokens (see CompletionUsage in the SDK)
but are INVISIBLE in every char-based prompt/output estimate this audit
otherwise relies on - they are the most plausible explanation for real
production TPD usage (197,802/200,000 tokens observed exhausted after only
a handful of real attempts) being far higher than visible-content-only
estimates would predict.

Set to 'low' here: this pipeline's own retry-with-explicit-correction-note
architecture (grounding/novelty/marks rejections all regenerate with a
note naming exactly what was wrong - see question_generator.py and
memo_generator.py) is a deterministic safety net independent of reasoning
depth, making a lower default a reasonable, bounded-risk choice rather
than a blind one. UNVERIFIED IN THIS SESSION: no real Groq call was made
to measure the actual before/after reasoning_tokens delta (out of scope -
"do not consume Groq quota" was an explicit constraint on this audit) -
the _log_usage diagnostic added in this same change will show the real
reasoning_tokens count (previously always logged as None/absent, since it
was never requested) on the next real generation, so this is a testable,
evidence-verifiable claim, not an assumed one.
"""


def _model_supports_reasoning_effort(model: str) -> bool:
    return model.startswith(_REASONING_EFFORT_MODEL_PREFIXES)


def _log_usage(task: dict[str, Any], response: Any) -> None:
    """Dev-diagnostic only (token audit, 2026-09-11): logs the REAL
    prompt_tokens/completion_tokens/total_tokens/reasoning_tokens Groq
    reports for this call, at DEBUG level - invisible under this project's
    default logging.basicConfig(level=logging.INFO) (see api/app.py), so
    this adds zero production log noise unless an operator explicitly
    raises the log level for local diagnostics. Never logs prompt/response
    CONTENT, never the API key - only the numeric usage counters and the
    call's ``kind`` (e.g. "generate_section_question"), already a plain,
    non-secret label the caller supplies via ``task``. Real numbers here
    replace the char/4 estimates used throughout the token audit that
    motivated this - see MAX_OUTCOME_CODES_SHOWN's docstring in
    src/generation/question_generator.py for the audit itself.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    reasoning_tokens = None
    details = getattr(usage, "completion_tokens_details", None)
    if details is not None:
        reasoning_tokens = getattr(details, "reasoning_tokens", None)
    _logger.debug(
        "groq usage kind=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s reasoning_tokens=%s",
        task.get("kind"),
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        getattr(usage, "total_tokens", None),
        reasoning_tokens,
    )


def _extract_retry_after(exc: Exception) -> float | None:
    """Best-effort extraction of a 429/5xx response's ``Retry-After`` header
    (seconds) from a Groq SDK exception, for src.generation.llm_utils.
    call_provider_with_retry to wait the amount of time the server actually
    asked for instead of a fixed guess (see that function's docstring for
    the real incident this fixes - a Groq 429 said "try again in 4.71s" and
    the old fixed backoff retried after 2s).

    groq.APIStatusError (the base of RateLimitError etc. - confirmed
    directly against the installed SDK's src/groq/_exceptions.py) carries
    the real ``httpx.Response`` as ``.response``, headers included. Never
    raises: returns None (falls back to the existing fixed backoff, exactly
    as before this function existed) for a missing response/header, a
    non-numeric value, or a non-positive value - a malformed or absent
    header must never break retry behavior, only fail to improve it.
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
        messages: list[Any] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            # Two explicit call shapes (never a **kwargs spread of a plain
            # dict) so reasoning_effort/reasoning_format keep the SDK's own
            # Literal[...] typing under mypy, instead of widening to a
            # generic dict[str, str] that can't match the overloaded
            # Completions.create signature statically.
            if _model_supports_reasoning_effort(self._settings.model):
                response = self._client.chat.completions.create(
                    model=self._settings.model,
                    messages=messages,
                    max_completion_tokens=self._settings.max_tokens,
                    temperature=self._settings.temperature,
                    reasoning_effort="low",
                    reasoning_format="hidden",
                )
            else:
                response = self._client.chat.completions.create(
                    model=self._settings.model,
                    messages=messages,
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
                retry_after=_extract_retry_after(exc),
            ) from exc

        _log_usage(task, response)

        choices = response.choices
        if not choices or not choices[0].message.content:
            raise LLMProviderError("Groq response contained no text content.")
        return choices[0].message.content
