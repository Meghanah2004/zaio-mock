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


class GenerationError(RuntimeError):
    """Raised when provider output cannot be parsed or fails structural checks.

    Never retried automatically (see call_provider_with_retry below):
    it means the provider returned SOMETHING but it was invalid, and
    MockProvider is deterministic (a retry would return byte-identical
    invalid output), while a real provider's transient issues surface as
    LLMProviderError instead - retrying a real content/schema defect
    wastes API budget without any chance of succeeding.
    """


def extract_json(raw: str, security_config: SecurityConfig | None = None) -> dict[str, Any]:
    """Parse a JSON object out of raw provider text, tolerating markdown fences.

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
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        raise GenerationError(f"Provider output did not contain a JSON object: {raw[:300]!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise GenerationError(f"Provider output contained malformed JSON: {exc}") from exc


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
            if attempt < max_attempts:
                time.sleep(backoff * attempt)

    if last_error is None:  # pragma: no cover - defensive only, not reachable
        raise LLMProviderError("Provider call failed with no error captured.")
    raise last_error
