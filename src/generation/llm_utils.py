"""Shared helpers for provider prompt construction and output parsing."""
from __future__ import annotations

import json
import re
import time
from typing import Any

from src.config import PROMPTS_DIR
from src.providers.base import LLMProvider, LLMProviderError
from src.security.config import SecurityConfig

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

MAX_RETRY_AFTER_SECONDS = 30.0
"""Upper bound on how long call_provider_with_retry will ever sleep for one
retry, even when a provider-supplied LLMProviderError.retry_after asks for
longer (see GroqProvider's Retry-After extraction) - caps a malformed or
unusually large server-suggested wait so one retry can never dominate a
request's total latency in a serverless function with its own execution
time limit. 30s is comfortably above the ~1-5s Retry-After values Groq has
been observed to send for a single-request-sized 429, while still bounded."""

_JSON_STRING_CONTROL_ESCAPES = {
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}
"""RFC 8259 requires every control character (U+0000-U+001F) inside a JSON
string literal to be escaped; these are the named short-form escapes for
the common ones. Any other control character falls back to a \\u00XX
escape in _escape_raw_control_chars_in_json_strings below - the mapping
here is a readability optimization for the common cases, not a
completeness requirement (the \\uXXXX fallback covers all 32 codes)."""


class GenerationError(RuntimeError):
    """Raised when provider output cannot be parsed or fails structural checks.

    Never retried automatically (see call_provider_with_retry below):
    it means the provider returned SOMETHING but it was invalid, and
    MockProvider is deterministic (a retry would return byte-identical
    invalid output), while a real provider's transient issues surface as
    LLMProviderError instead - retrying a real content/schema defect
    wastes API budget without any chance of succeeding.
    """


def _escape_raw_control_chars_in_json_strings(text: str) -> str:
    """Replace every RAW (unescaped) control character found INSIDE a JSON
    string literal with its proper JSON escape sequence, leaving everything
    else - including control characters OUTSIDE any string literal, e.g.
    ordinary newlines between object members, which are already legal
    JSON whitespace there - completely untouched.

    Why this is needed: a real Gemini response for this pipeline failed to
    parse with "Invalid control character at: line 31 column 148" - Gemini
    had written a multi-line code sample into a "prompt"/"question" string
    value using a literal newline byte instead of the two-character JSON
    escape "\\n". RFC 8259 requires every control character (U+0000-U+001F)
    inside a string literal to be escaped; Python's ``json`` module (like
    every strict JSON parser) correctly rejects the unescaped byte rather
    than guessing what was meant. This is a known, common LLM output defect
    (multi-line code/text pasted "as-is" into a JSON string) - not
    something the schema/validators should paper over, and not something
    worth relaxing Python's parser for, since a genuinely malformed
    document (missing quote, trailing comma, truncated output, etc.) must
    still fail loudly.

    This is a single left-to-right scan (linear time, no backtracking,
    same complexity class as the regex work already done in extract_json)
    that tracks whether the current position is inside a string literal
    (toggling on an unescaped '"') and whether the previous character was
    an unconsumed backslash (so an escaped quote/backslash never wrongly
    ends/re-enters a string). It is a NORMALIZATION of the JSON's own
    serialization, not a change to meaning: once parsed, the control
    character survives as the exact same byte in the resulting Python
    string (a literal newline escaped to "\\n" decodes back to a literal
    newline) - see the "lossless round-trip" test in
    tests/test_llm_utils_json_extraction.py.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\":
                out.append(ch)
                escaped = True
            elif ch == '"':
                in_string = False
                out.append(ch)
            elif ord(ch) < 0x20:
                out.append(_JSON_STRING_CONTROL_ESCAPES.get(ch, f"\\u{ord(ch):04x}"))
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


def _parse_json_object(candidate: str) -> dict[str, Any]:
    """Parse one JSON-object candidate, tolerating raw control characters
    inside string literals as a targeted fallback (see
    _escape_raw_control_chars_in_json_strings) - never for any other
    parse failure, which is re-raised unchanged so a genuinely malformed
    document is never silently accepted.
    """
    try:
        return json.loads(candidate)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        if "Invalid control character" not in exc.msg:
            raise
        sanitized = _escape_raw_control_chars_in_json_strings(candidate)
        return json.loads(sanitized)  # type: ignore[no-any-return]  # a second failure propagates as-is


def extract_json(raw: str, security_config: SecurityConfig | None = None) -> dict[str, Any]:
    """Parse a JSON object out of raw provider text, tolerating markdown
    fences and raw control characters inside string literals (see
    _parse_json_object) - the latter is a normalization of a real, observed
    LLM output defect, never a relaxation that accepts a document broken
    for any other reason.

    SECURITY: bounds the input size before running any regex or parser over
    it - a malformed or adversarial provider response must not be allowed
    to cause unbounded CPU/memory use in this parsing step (see
    docs/SECURITY-AUDIT.md 6.7). Provider output is untrusted regardless of
    which provider produced it.
    """
    security_config = security_config or SecurityConfig()
    if len(raw) > security_config.max_provider_response_chars:
        raise GenerationError(
            f"Provider output is {len(raw)} characters, exceeding the "
            f"{security_config.max_provider_response_chars}-character bound "
            f"(MAX_PROVIDER_RESPONSE_CHARS) - rejected before parsing."
        )
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return _parse_json_object(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        raise GenerationError(f"Provider output did not contain a JSON object: {raw[:300]!r}")
    try:
        return _parse_json_object(match.group(0))
    except json.JSONDecodeError as exc:
        # REWORK (production incident, 2026-09-10): a real Groq response
        # failed with "Expecting ',' delimiter: line 69 column 10 (char
        # 4496)" and the resulting GenerationError - all this branch used
        # to raise - carried only that parser message, never the text that
        # actually failed to parse. That message alone is undiagnosable:
        # it names a position but not what was there, and by the time
        # anyone reads the log the only way to see the actual malformed
        # output would be paying for a fresh real API call to try to
        # reproduce it. This is server-log-only content (see
        # api/errors.handle_generation_error - a GenerationError's str() is
        # logged via sanitize_for_public but the client only ever receives
        # a fixed generic message + request_id, never this text), so a
        # bounded snippet of the actual candidate around the failure
        # position is safe to include and genuinely diagnostic. Bounded
        # (not the full candidate) so one adversarial-or-just-huge
        # response can't blow up a log line.
        candidate = match.group(0)
        context_start = max(0, exc.pos - 200)
        context_end = min(len(candidate), exc.pos + 200)
        context = candidate[context_start:context_end]
        raise GenerationError(
            f"Provider output contained malformed JSON: {exc}. Context around the failure "
            f"(candidate chars {context_start}-{context_end}): {context!r}"
        ) from exc


def load_prompt_template(name: str) -> str:
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing prompt template: {path}")
    return path.read_text(encoding="utf-8")


def call_provider_with_retry(
    provider: LLMProvider,
    system_prompt: str,
    user_prompt: str,
    task: dict[str, Any],
    security_config: SecurityConfig | None = None,
) -> str:
    """Call ``provider.generate`` with a bounded number of attempts.

    Only retries ``LLMProviderError`` (a transient provider/network-shaped
    failure, e.g. a real API timeout or 5xx). Never retries on any other
    exception - a bug in this pipeline's own code should fail immediately,
    not be silently retried into a longer, harder-to-diagnose failure.
    After the configured maximum attempts, the last error is re-raised
    unchanged so generation terminates safely (no unbounded retry loop) and
    the failure is visible to the caller exactly as it would be without
    this wrapper.

    Within that, ``exc.retryable`` (see LLMProviderError) is checked before
    looping again: a PERMANENT failure (e.g. a 401/403 bad API key, or a
    400/404/422 malformed request - see src/providers/groq_provider.py and
    anthropic_provider.py's classification) fails identically on every
    attempt, so it is re-raised immediately on the FIRST attempt rather
    than burning the full retry budget's worth of latency on a foregone
    conclusion. A TRANSIENT failure (429 rate limit, 5xx, timeout/network -
    the default when a provider does not classify its exception, or cannot)
    still retries up to ``max_attempts`` exactly as before.

    The wait before the next attempt prefers ``exc.retry_after`` (a
    server-suggested wait in seconds, e.g. from a 429's ``Retry-After``
    header - see GroqProvider) over the fixed ``backoff * attempt`` formula,
    capped at MAX_RETRY_AFTER_SECONDS. Real incident: a Groq 429 said "try
    again in 4.71s" while the old fixed formula waited at most 2s before
    retrying - guaranteed to hit the same still-exhausted per-minute token
    budget again. When no provider-supplied wait is available (any other
    provider, or a Groq error without a usable header), behavior is
    byte-identical to before this field existed.
    """
    security_config = security_config or SecurityConfig()
    max_attempts = max(1, security_config.generation_max_retries)
    backoff = security_config.generation_retry_backoff_seconds

    last_error: LLMProviderError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return provider.generate(system_prompt, user_prompt, task)
        except LLMProviderError as exc:
            last_error = exc
            if not exc.retryable:
                break
            if attempt < max_attempts:
                delay = backoff * attempt
                if exc.retry_after is not None:
                    delay = min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
                time.sleep(delay)

    if last_error is None:  # pragma: no cover - defensive only, not reachable
        raise LLMProviderError("Provider call failed with no error captured.")
    raise last_error
