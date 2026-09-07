"""Single source of truth for security-relevant thresholds.

Every magic number that bounds an untrusted-input boundary (file sizes,
counts, string lengths, retry counts, rate limits, timeouts) lives here,
not scattered through the modules that use it. All values have safe
defaults and can be overridden by environment variables (see
.env.example), but security-critical bounds cannot be disabled entirely -
only widened or narrowed within `int`/`float` range, so a misconfigured
environment variable cannot silently turn a limit into "unlimited" by
setting it to a non-numeric value (invalid values raise at startup instead
of being coerced to something dangerous).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name}={raw!r} must be an integer.") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class SecurityConfig:
    # -- Reference ingestion bounds (src/ingestion/pdf_loader.py) -----------
    max_reference_file_size_mb: int = 100
    max_reference_file_count: int = 2000
    max_filename_length: int = 255

    # -- Provider / generation bounds (src/generation/llm_utils.py etc.) ---
    max_provider_response_chars: int = 200_000
    """Raw provider output larger than this is rejected before JSON parsing
    - a bound against a malformed or adversarial provider response causing
    unbounded memory/CPU use in the JSON parser."""
    max_reference_derived_text_length: int = 200
    """Cap applied to any single piece of reference-derived text (e.g. a
    Knowledge Topic title) before it can be interpolated into an LLM
    prompt - see src/analysis/reference_analyzer.py."""
    generation_max_retries: int = 3
    """Maximum attempts for a single provider call. Only transient
    provider-level failures are retried (see
    src/generation/llm_utils.call_provider_with_retry); deterministic
    content-validation failures are never retried."""
    generation_retry_backoff_seconds: float = 1.0
    """Base delay between retries; attempt N waits backoff * N seconds
    (simple linear backoff, configurable, no unbounded growth)."""
    provider_timeout_seconds: int = 60

    # -- CLI argument bounds (src/cli.py) -----------------------------------
    min_paper_number: int = 1
    max_paper_number: int = 9999
    min_seed: int = 0
    max_seed: int = 2_147_483_647  # 2^31 - 1

    # -- Rate limiting (src/security/rate_limiter.py) - prepared for a
    # future API layer; not wired to anything live in this CLI-only build.
    rate_limit_enabled: bool = True
    generation_rate_limit: int = 5
    """Max generation requests allowed per window, per limiter key (e.g.
    per-IP or per-API-key, once such a concept exists)."""
    generation_rate_window_seconds: int = 60
    generation_burst: int = 2
    """Extra requests allowed immediately on top of the steady-state rate,
    absorbed by the token bucket before throttling kicks in."""
    read_rate_limit: int = 60
    read_rate_window_seconds: int = 60

    # -- API layer (api/) ----------------------------------------------------
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:5173"
    """Comma-separated allow-list of origins for the future frontend. NEVER
    a bare "*" default - see api/app.py. Restrict to the real deployed
    frontend origin(s) in production via the CORS_ALLOWED_ORIGINS env var."""
    max_request_body_bytes: int = 16_384
    """Upper bound on the raw HTTP request body FastAPI/Starlette will read
    for any endpoint under api/ - rejects an oversized payload before it
    reaches Pydantic parsing. Generation requests are a handful of small
    fields; there is no legitimate reason for a large body."""

    @classmethod
    def from_env(cls) -> SecurityConfig:
        return cls(
            max_reference_file_size_mb=_int_env("MAX_REFERENCE_FILE_SIZE_MB", cls.max_reference_file_size_mb),
            max_reference_file_count=_int_env("MAX_REFERENCE_FILE_COUNT", cls.max_reference_file_count),
            max_filename_length=_int_env("MAX_FILENAME_LENGTH", cls.max_filename_length),
            max_provider_response_chars=_int_env(
                "MAX_PROVIDER_RESPONSE_CHARS", cls.max_provider_response_chars
            ),
            max_reference_derived_text_length=_int_env(
                "MAX_REFERENCE_DERIVED_TEXT_LENGTH", cls.max_reference_derived_text_length
            ),
            generation_max_retries=_int_env("GENERATION_MAX_RETRIES", cls.generation_max_retries),
            generation_retry_backoff_seconds=float(
                os.environ.get("GENERATION_RETRY_BACKOFF_SECONDS", cls.generation_retry_backoff_seconds)
            ),
            provider_timeout_seconds=_int_env("PROVIDER_TIMEOUT_SECONDS", cls.provider_timeout_seconds),
            min_paper_number=_int_env("MIN_PAPER_NUMBER", cls.min_paper_number),
            max_paper_number=_int_env("MAX_PAPER_NUMBER", cls.max_paper_number),
            min_seed=_int_env("MIN_SEED", cls.min_seed),
            max_seed=_int_env("MAX_SEED", cls.max_seed),
            rate_limit_enabled=_bool_env("RATE_LIMIT_ENABLED", cls.rate_limit_enabled),
            generation_rate_limit=_int_env("GENERATION_RATE_LIMIT", cls.generation_rate_limit),
            generation_rate_window_seconds=_int_env(
                "GENERATION_RATE_WINDOW_SECONDS", cls.generation_rate_window_seconds
            ),
            generation_burst=_int_env("GENERATION_BURST", cls.generation_burst),
            read_rate_limit=_int_env("READ_RATE_LIMIT", cls.read_rate_limit),
            read_rate_window_seconds=_int_env("READ_RATE_WINDOW_SECONDS", cls.read_rate_window_seconds),
            cors_allowed_origins=os.environ.get("CORS_ALLOWED_ORIGINS", cls.cors_allowed_origins),
            max_request_body_bytes=_int_env("MAX_REQUEST_BODY_BYTES", cls.max_request_body_bytes),
        )

    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]
