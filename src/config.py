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
OUTPUT_DIR = PROJECT_ROOT / "output"
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


@dataclass(frozen=True)
class LLMSettings:
    provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "mock"))
    model: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"))
    api_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY"))
    max_tokens: int = field(default_factory=lambda: int(os.environ.get("LLM_MAX_TOKENS", "4096")))
    temperature: float = field(default_factory=lambda: float(os.environ.get("LLM_TEMPERATURE", "0.4")))

    def has_real_credentials(self) -> bool:
        return self.provider == "anthropic" and bool(self.api_key)


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
    for d in (DOCS_DIR, ARTIFACTS_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
