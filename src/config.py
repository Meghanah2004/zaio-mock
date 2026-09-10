"""Central configuration for the pipeline.

Configuration comes from three layers, lowest priority first:
  1. Hard-coded defaults in this module.
  2. A qualification config file under ``configs/<qualification>.json``.
  3. Environment variables (see ``.env.example``).

No secrets are hard-coded. API keys are only ever read from the environment.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Project root = two levels up from this file (src/config.py -> src -> root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

SDEV_DIR = PROJECT_ROOT / "sdev"
DOCS_DIR = PROJECT_ROOT / "docs"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

# Vercel deployments run from a read-only application filesystem (confirmed
# by the real, observed production traceback this fixes: "OSError: [Errno
# 30] Read-only file system: '/var/task/artifacts/blueprint.json'" - Vercel
# Functions docs: "Read-only filesystem with writable /tmp scratch space").
# ARTIFACTS_DIR keeps holding the deployed, read-only reference corpus
# (committed to git specifically for this - see .gitignore); everything
# this process WRITES at runtime (blueprint, generation history,
# validation/review reports, generated papers/memos/PDFs) goes under a
# separate, always-writable root instead.
#
# _compute_runtime_root is a plain function (not inlined into the module-
# level assignment below) specifically so it has a UNIT-TESTABLE surface -
# tests/test_deployment_paths.py calls it directly with an explicit
# ``is_vercel`` argument, rather than needing to monkeypatch os.environ and
# reload this module (fragile: other already-imported modules would keep
# stale references to the pre-reload PROJECT_ROOT-derived constants).
def _compute_runtime_root(is_vercel: bool) -> Path:
    return Path("/tmp/zaio-mock-eisa") if is_vercel else PROJECT_ROOT


IS_VERCEL = bool(os.environ.get("VERCEL"))
RUNTIME_ROOT = _compute_runtime_root(IS_VERCEL)
RUNTIME_ARTIFACTS_DIR = RUNTIME_ROOT / "artifacts"
OUTPUT_DIR = RUNTIME_ROOT / "output"

SCHEMAS_DIR = PROJECT_ROOT / "schemas"
CONFIGS_DIR = PROJECT_ROOT / "configs"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# Only this qualification is in scope for Phase 1. This is enforced, not just
# documented, so the CLI refuses to silently run against out-of-scope config.
SUPPORTED_QUALIFICATIONS = ("software_developer",)


def _load_dotenv_if_present() -> None:
    """Minimal .env loader (no third-party dependency).

    Only sets variables that are not already present in the environment, so
    real shell-exported secrets always win.
    """
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_if_present()


_REAL_PROVIDERS = ("anthropic", "gemini", "groq")
"""Providers backed by a real, billable API - as opposed to "mock". Used by
LLMSettings' provider-aware defaults below and by has_real_credentials()."""


def _default_model() -> str:
    """Picks the right *_MODEL env var for whichever LLM_PROVIDER is
    configured, so LLMSettings() alone (no explicit model=...) always
    resolves to the model for the ACTIVE provider, not always Anthropic's."""
    provider = os.environ.get("LLM_PROVIDER", "mock")
    if provider == "gemini":
        # "gemini-2.5-flash" was the originally documented default but is no
        # longer available to new Gemini API keys as of this project's most
        # recent real-API verification - confirmed by a live 404 response
        # naming "gemini-3.6-flash" as its replacement (see
        # docs/DESIGN_NOTE.md). GEMINI_MODEL always overrides this if set.
        return os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    if provider == "groq":
        return os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")


def _default_api_key() -> str | None:
    provider = os.environ.get("LLM_PROVIDER", "mock")
    if provider == "gemini":
        return os.environ.get("GEMINI_API_KEY")
    if provider == "groq":
        return os.environ.get("GROQ_API_KEY")
    return os.environ.get("ANTHROPIC_API_KEY")


@dataclass(frozen=True)
class LLMSettings:
    provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "mock"))
    model: str = field(default_factory=_default_model)
    api_key: str | None = field(default_factory=_default_api_key)
    max_tokens: int = field(default_factory=lambda: int(os.environ.get("LLM_MAX_TOKENS", "4096")))
    temperature: float = field(default_factory=lambda: float(os.environ.get("LLM_TEMPERATURE", "0.4")))

    def has_real_credentials(self) -> bool:
        return self.provider in _REAL_PROVIDERS and bool(self.api_key)


def load_qualification_config(qualification: str) -> dict[str, Any]:
    """Load ``configs/<qualification>.json``.

    Raises FileNotFoundError / ValueError with an explicit message rather than
    silently falling back, per the project's "no fake completion" rule.
    """
    if qualification not in SUPPORTED_QUALIFICATIONS:
        raise ValueError(
            f"Qualification '{qualification}' is out of scope for Phase 1. "
            f"Supported: {SUPPORTED_QUALIFICATIONS}"
        )
    config_path = CONFIGS_DIR / f"{qualification}.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing qualification config: {config_path}")
    with config_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def safe_path_within(base_dir: Path, candidate: str | Path) -> Path:
    """Resolve ``candidate`` and guarantee it stays inside ``base_dir``.

    Prevents path traversal (e.g. ``../../etc/passwd``) from user-supplied
    CLI arguments such as ``--paper``. Raises ValueError on escape attempts.
    """
    base_resolved = base_dir.resolve()
    candidate_path = Path(candidate)
    resolved = candidate_path.resolve() if candidate_path.is_absolute() else (base_dir / candidate_path).resolve()
    try:
        resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to access path outside of {base_resolved}: {resolved}"
        ) from exc
    return resolved


def ensure_output_dirs() -> None:
    """Creates every directory this process might WRITE to.

    Deliberately does NOT include ARTIFACTS_DIR: on Vercel that is the
    deployed, read-only application bundle (see RUNTIME_ROOT above) - a
    developer already has it locally (it's the project checkout), and
    creating it is never this process's job. DOCS_DIR stays harmless
    everywhere it's already committed (mkdir(exist_ok=True) is then a
    no-op); it's only ever actually WRITTEN to by a local ``analyze`` run
    (see ensure_reference_analysis_ready), which never executes on Vercel.
    """
    for d in (DOCS_DIR, RUNTIME_ARTIFACTS_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def resolve_readable_artifact(filename: str) -> Path:
    """Resolve a deployment-artifact filename to whichever real location
    holds it, for artifacts that may EITHER be prebuilt/committed (under
    ARTIFACTS_DIR - read-only on Vercel) OR built fresh at runtime from
    ``sdev/`` (under RUNTIME_ARTIFACTS_DIR - writable everywhere,
    including Vercel's ``/tmp``).

    A RUNTIME_ARTIFACTS_DIR copy (fresher, or the only copy when this
    process just built it from sdev/) takes priority over a prebuilt copy
    in ARTIFACTS_DIR. If neither exists yet, returns the
    RUNTIME_ARTIFACTS_DIR path anyway - not because it exists, but because
    it is the correct, always-writable target for a caller that is about
    to build and write it (see ensure_reference_analysis_ready in
    api/service.py, which always writes explicitly to RUNTIME_ARTIFACTS_DIR,
    never to this resolved path, specifically so a write attempt can never
    be misdirected at the read-only ARTIFACTS_DIR by this fallback).

    Locally, RUNTIME_ARTIFACTS_DIR and ARTIFACTS_DIR are the SAME directory
    (see RUNTIME_ROOT above) - this function's two-location search only
    matters on Vercel, where they diverge. Local behavior is unchanged.
    """
    runtime_path = RUNTIME_ARTIFACTS_DIR / filename
    if runtime_path.exists():
        return runtime_path
    static_path = ARTIFACTS_DIR / filename
    if static_path.exists():
        return static_path
    return runtime_path


# -- Effective seed derivation (per-paper evidence-rotation diversity) ------
SEED_PAPER_STRIDE = 2_147_483_647
"""2^31 - 1 (a Mersenne prime, and the same value as SecurityConfig.max_seed
- one full seed-space width). Multiplying paper_number by this gives every
paper_number its own non-overlapping block of the effective-seed space: for
any raw seed within its valid [min_seed, max_seed] range, no two distinct
paper_numbers can ever produce the same effective_seed. Primality is a
second, independent safeguard - it avoids introducing unwanted periodicity
into the small `% len(...)` rotations effective_seed later feeds (see
src/retrieval/evidence_selector.py's `rotation = seed % len(structural)`
and src/providers/mock_provider.py's `bank[seed % len(bank)]`), where a
composite stride sharing a small common factor with a small rotation base
could otherwise make two different paper_numbers land on the same rotation
by coincidence more often than chance alone would predict."""


def compute_effective_seed(seed: int, paper_number: int) -> int:
    """Combines a caller-supplied ``seed`` with ``paper_number`` into the
    ONE seed value used for every seed-dependent step of a generation run:
    question-side evidence rotation, answer-side evidence rotation, and the
    provider task seed. This is the fix for a real, observed production
    incident: src/cli.py's ``--seed`` default and frontend/src/components/
    GenerateForm.tsx's seed field default were both the same static literal
    (20260906), and NOTHING before this function ever combined ``seed``
    with ``paper_number`` - every generation's evidence retrieval
    (evidence_selector.py: ``rotation = seed % len(structural)``) depended
    on ``seed`` ALONE. A caller who generated Paper 1 and Paper 2 without
    manually picking a different seed each time therefore retrieved
    IDENTICAL evidence for both, and since no real provider (Groq/
    Anthropic/Gemini - confirmed directly, none of the three provider
    modules ever sends ``seed`` to the actual API call) uses ``seed`` for
    its own sampling either, a low-temperature real model given the same
    evidence and the same prompt on attempt 1 frequently reproduced
    near-identical or literally duplicate content - surfacing as frequent
    cross-paper novelty rejections, and, when accepted, still frequently
    near-duplicate. The existing within-paper retry diversification
    (question_generator.py's ``seed + attempt - 1`` across up to
    ``grounding_max_retries`` attempts) only ever varied a SMALL window
    around one already-collided starting point; it could not fix a
    collision that starts at the very first attempt of every paper.

    This function is the ONE centralized place that combination happens -
    every caller (api/service.py, src/cli.py) computes it ONCE per
    generation request and threads the RESULT through everywhere ``seed``
    was previously used directly (question-side evidence retrieval,
    generate_paper, generate_memo, and - inside generate_memo - answer-side
    evidence retrieval); nothing downstream computes its own variant of
    this combination, so there is exactly one formula to reason about.

    Explicitly NOT a knowledge source: this is pure integer arithmetic on
    two caller-supplied numbers. ``paper_number`` never becomes part of any
    prompt, evidence passage, or generated content here - it only changes
    WHICH already-real, already-page-cited learner-guide passages get
    selected (see evidence_selector.py), never WHAT the passages say. The
    supplied learner-guide PDFs remain the only knowledge source; previously
    generated papers remain usable only for cross-paper novelty comparison
    (src/validation/cross_paper_novelty.py), never as input to this
    function or to anything this function's output feeds into.

    Reproducibility is preserved, not weakened: this is a pure, deterministic
    function of its two integer inputs - the SAME (seed, paper_number) pair
    always produces the SAME effective_seed, and therefore the SAME
    retrieval conditions, exactly as before. What changes is that two
    DIFFERENT paper_numbers sharing the same raw seed no longer collide.
    """
    return seed + paper_number * SEED_PAPER_STRIDE
