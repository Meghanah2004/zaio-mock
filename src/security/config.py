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
    max_evidence_passage_chars: int = 900
    """Cap applied to a single retrieved learner-guide passage
    (src/retrieval/evidence_selector.py) before it is interpolated into
    prompts/generate_questions.txt's GUIDE_EVIDENCE block. Wider than
    max_reference_derived_text_length (which bounds short KT titles) because
    a real passage needs enough content for the model to ground a question
    in, but still bounded - never the full page, never unbounded."""
    evidence_passages_per_section: int = 4
    """How many retrieved passages are handed to the LLM per blueprint
    section. Small on purpose - see docs/DESIGN.md prompt-size discipline."""
    grounding_min_overlap: float = 0.08
    """Minimum TF-IDF cosine similarity between a generated question's text
    and the UNION of evidence passages it was given, below which the
    question is treated as ungrounded (general-knowledge invention rather
    than evidence-derived) and regenerated - see
    src/generation/question_generator.py and
    src/validation/grounding_validator.py. Deliberately low: the model is
    instructed to TRANSFORM evidence into a workplace scenario, not quote
    it, so overlap is expected to be modest, not high."""
    grounding_max_overlap: float = 0.75
    """Maximum overlap between a generated question and any single cited
    passage, above which the question is treated as too close to a
    near-verbatim copy of the guide (rather than a transformed question)
    and rejected - the anti-copying half of the same check."""
    cross_paper_max_similarity: float = 0.6
    """Maximum TF-IDF cosine similarity allowed between a newly generated
    section question and any earlier paper's question for the same section
    (src/validation/cross_paper_novelty.py) before it is treated as too
    similar and regenerated with a resampled evidence set - this is what
    keeps Paper 2/3 genuinely different from Paper 1, not just relabeled."""
    grounding_max_retries: int = 3
    """Maximum regeneration attempts for a single section's question when it
    fails grounding or cross-paper novelty (separate from
    generation_max_retries, which only covers transient provider errors)."""
    memo_max_retries: int = 3
    """Maximum regeneration attempts for a single question's marking memo
    when its criteria marks fail to reconcile with the question's/sub-
    question's actual assigned marks, OR when its answer fails answer-side
    grounding (see answer_grounding_min_overlap below) -
    src/generation/memo_generator.py. Marks-reconciliation was a real,
    observed failure mode where the model's free-text criteria list
    arithmetic drifts from the (already fixed, non-negotiable) marks it
    was given. Same bounded-retry-then-fail-loudly shape as
    grounding_max_retries, kept as a separate knob because it governs a
    different generation stage with a different failure cause."""
    answer_grounding_min_overlap: float = 0.08
    """Minimum TF-IDF-free cosine similarity between a generated memo's
    model answer and its retrieved answer-side evidence
    (src/retrieval/evidence_selector.select_answer_evidence), below which
    the answer is treated as unsupported invention rather than
    evidence-derived and rejected/regenerated - see
    src/generation/memo_generator._answer_grounding_ok. Deliberately has NO
    matching maximum-overlap ceiling the way question grounding does
    (grounding_max_overlap): a question must be an ORIGINAL scenario, so
    reading like the source passage is a copying defect; a memo's model
    answer is a CORRECT TECHNICAL EXPLANATION, so closely reflecting what
    the guide actually states is the intended, desired outcome, not a
    defect - see that function's docstring."""
    answer_relevance_min_overlap: float = 0.05
    """Minimum cosine similarity a memo's model answer must have with the
    question it is answering, and a low sanity floor for how related a
    question's marking criteria must be to its own model answer - both are
    loose "not obviously disconnected" checks (see
    src/generation/memo_generator._answer_grounding_ok), deliberately set
    lower than answer_grounding_min_overlap since criteria descriptions are
    terse/keyword-based rather than full prose and would otherwise false-
    reject correct, well-written criteria."""
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

    # -- Rate limiting (src/security/rate_limiter.py) - ACTIVELY ENFORCED on
    # every api/ endpoint (see api/dependencies.py); irrelevant to the CLI.
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
    cors_allowed_origins: str = (
        "http://localhost:3000,http://localhost:5173,"
        "https://zaio-sable.vercel.app,https://zaio-qwertyuiop12.vercel.app,"
        "https://zaio-git-main-qwertyuiop12.vercel.app"
    )
    """Comma-separated allow-list of origins for the deployed frontend. NEVER
    a bare "*" default - see api/app.py. Restrict to the real deployed
    frontend origin(s) in production via the CORS_ALLOWED_ORIGINS env var.

    REWORK (locked Phase 1 architecture, 2026-09-11): the canonical
    deployment is Vercel React frontend + LOCAL Python backend (see
    docs/DEPLOYMENT.md) - the browser at https://zaio-sable.vercel.app must
    be able to call http://127.0.0.1:8000 directly. The three zaio-*.vercel.app
    entries are this project's own STABLE Vercel aliases (production,
    project, and git-branch - confirmed via `vercel inspect`; unlike a
    per-deployment preview URL, these do not change on every push), added
    alongside the pre-existing local dev-port defaults, never replacing
    them. A local operator whose own .env already sets CORS_ALLOWED_ORIGINS
    must add these same origins there too - an env var override replaces
    this default entirely rather than extending it."""
    max_request_body_bytes: int = 16_384
    """Upper bound on the raw HTTP request body FastAPI/Starlette will read
    for any endpoint under api/ - rejects an oversized payload before it
    reaches Pydantic parsing. Generation requests are a handful of small
    fields; there is no legitimate reason for a large body."""

    # -- Production safety ---------------------------------------------------
    require_real_provider: bool = False
    """When true, src.providers.factory.build_provider REFUSES to fall back
    to MockProvider - it raises LLMProviderError immediately instead -
    whenever LLM_PROVIDER resolves to "mock" (including by having been left
    unset) or a real provider is configured but its API key is missing.

    Defaults to False so every existing local-dev/CLI/test code path (which
    legitimately wants a silent-but-loud-on-stderr MockProvider fallback
    when no key is configured - see build_provider's own docstring) is
    completely unaffected. Set REQUIRE_REAL_PROVIDER=true in a production
    deployment's environment to turn a misconfiguration (a missing/blank
    GROQ_API_KEY, a forgotten LLM_PROVIDER, a typo'd variable name) into a
    hard startup/request failure instead of the previous behavior: printing
    one warning to stderr and then silently serving MockProvider's fixed
    fixture content as if it were real, learner-guide-grounded generation -
    a real risk for a deployment whose logs are not being watched."""

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
            max_evidence_passage_chars=_int_env("MAX_EVIDENCE_PASSAGE_CHARS", cls.max_evidence_passage_chars),
            evidence_passages_per_section=_int_env(
                "EVIDENCE_PASSAGES_PER_SECTION", cls.evidence_passages_per_section
            ),
            grounding_min_overlap=float(
                os.environ.get("GROUNDING_MIN_OVERLAP", cls.grounding_min_overlap)
            ),
            grounding_max_overlap=float(
                os.environ.get("GROUNDING_MAX_OVERLAP", cls.grounding_max_overlap)
            ),
            cross_paper_max_similarity=float(
                os.environ.get("CROSS_PAPER_MAX_SIMILARITY", cls.cross_paper_max_similarity)
            ),
            grounding_max_retries=_int_env("GROUNDING_MAX_RETRIES", cls.grounding_max_retries),
            memo_max_retries=_int_env("MEMO_MAX_RETRIES", cls.memo_max_retries),
            answer_grounding_min_overlap=float(
                os.environ.get("ANSWER_GROUNDING_MIN_OVERLAP", cls.answer_grounding_min_overlap)
            ),
            answer_relevance_min_overlap=float(
                os.environ.get("ANSWER_RELEVANCE_MIN_OVERLAP", cls.answer_relevance_min_overlap)
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
            require_real_provider=_bool_env("REQUIRE_REAL_PROVIDER", cls.require_real_provider),
        )

    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]
