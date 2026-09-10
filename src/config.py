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
