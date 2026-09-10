"""Tests for Vercel-vs-local runtime filesystem path resolution.

Regression tests for a real production incident: a deployed Vercel
``POST /api/generate`` request failed with

    OSError: [Errno 30] Read-only file system:
    '/var/task/artifacts/blueprint.json'

because every runtime-WRITE path (blueprint, generation history,
validation/quality-review reports) resolved under the plain,
read-only-on-Vercel ``ARTIFACTS_DIR`` unconditionally. Vercel Functions run
from a read-only application filesystem with a writable ``/tmp`` scratch
directory only (Vercel's own docs: "Read-only filesystem with writable
/tmp scratch space").

Fix, exercised here: ``src.config._compute_runtime_root``/
``resolve_readable_artifact`` (pure, directly testable - no environment-
variable monkeypatching or module-reload tricks needed) and
``api.service``'s six module-level path constants, which now route every
runtime WRITE under ``RUNTIME_ARTIFACTS_DIR``/``OUTPUT_DIR`` (project
``artifacts``/``output`` locally, ``/tmp/zaio-mock-eisa/...`` on Vercel)
and only ever READ the deployed, prebuilt corpus/analysis from the plain
``ARTIFACTS_DIR``.
"""
from __future__ import annotations

import shutil
import stat
from pathlib import Path

import pytest

from src.config import PROJECT_ROOT, _compute_runtime_root, resolve_readable_artifact


# ---------------------------------------------------------------------------
# _compute_runtime_root - pure function, no monkeypatching needed at all.
# ---------------------------------------------------------------------------
def test_compute_runtime_root_is_project_root_when_not_on_vercel():
    """Local mode: runtime artifacts/output stay under the project checkout
    - exactly the pre-existing local-development behavior, unchanged."""
    assert _compute_runtime_root(is_vercel=False) == PROJECT_ROOT


def test_compute_runtime_root_is_tmp_scratch_space_on_vercel():
    """Vercel mode: runtime artifacts/output move to the one writable
    location Vercel's filesystem actually offers."""
    assert _compute_runtime_root(is_vercel=True) == Path("/tmp/zaio-mock-eisa")


# ---------------------------------------------------------------------------
# resolve_readable_artifact - dual-location resolution for artifacts that
# may be EITHER prebuilt/committed (ARTIFACTS_DIR) OR built fresh at
# runtime (RUNTIME_ARTIFACTS_DIR).
# ---------------------------------------------------------------------------
def test_resolve_readable_artifact_prefers_runtime_copy_when_both_exist(tmp_path, monkeypatch):
    from src import config

    runtime_dir = tmp_path / "runtime" / "artifacts"
    static_dir = tmp_path / "static" / "artifacts"
    runtime_dir.mkdir(parents=True)
    static_dir.mkdir(parents=True)
    (runtime_dir / "reference-analysis.json").write_text("runtime-copy")
    (static_dir / "reference-analysis.json").write_text("static-copy")

    monkeypatch.setattr(config, "RUNTIME_ARTIFACTS_DIR", runtime_dir)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", static_dir)

    resolved = config.resolve_readable_artifact("reference-analysis.json")
    assert resolved == runtime_dir / "reference-analysis.json"
    assert resolved.read_text() == "runtime-copy"


def test_resolve_readable_artifact_falls_back_to_static_prebuilt_copy(tmp_path, monkeypatch):
    """The normal Vercel case: nothing has been written to the (fresh, per-
    instance) runtime directory yet, so the deployed, prebuilt, read-only
    corpus/analysis under ARTIFACTS_DIR is what's actually used."""
    from src import config

    runtime_dir = tmp_path / "runtime" / "artifacts"  # deliberately never created
    static_dir = tmp_path / "static" / "artifacts"
    static_dir.mkdir(parents=True)
    (static_dir / "reference-corpus-chunks.json").write_text("prebuilt-corpus")

    monkeypatch.setattr(config, "RUNTIME_ARTIFACTS_DIR", runtime_dir)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", static_dir)

    resolved = config.resolve_readable_artifact("reference-corpus-chunks.json")
    assert resolved == static_dir / "reference-corpus-chunks.json"
    assert resolved.read_text() == "prebuilt-corpus"


def test_resolve_readable_artifact_falls_back_to_runtime_write_target_when_neither_exists(tmp_path, monkeypatch):
    """A fresh local clone before the first `analyze` run: neither copy
    exists yet, so the function returns the RUNTIME (writable) path - the
    correct target for a caller about to build and write it - never the
    static, read-only-on-Vercel path."""
    from src import config

    runtime_dir = tmp_path / "runtime" / "artifacts"
    static_dir = tmp_path / "static" / "artifacts"

    monkeypatch.setattr(config, "RUNTIME_ARTIFACTS_DIR", runtime_dir)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", static_dir)

    resolved = config.resolve_readable_artifact("reference-analysis.json")
    assert resolved == runtime_dir / "reference-analysis.json"
    assert not resolved.exists()


def test_resolve_readable_artifact_matches_the_real_module_constants():
    """Sanity check against the REAL (unpatched) module constants: locally
    RUNTIME_ARTIFACTS_DIR and ARTIFACTS_DIR are the same directory (see
    RUNTIME_ROOT), so this must resolve to the real, existing, committed
    corpus file - never silently invent a different path."""
    resolved = resolve_readable_artifact("reference-corpus-chunks.json")
    assert resolved == PROJECT_ROOT / "artifacts" / "reference-corpus-chunks.json"
    assert resolved.exists(), "the real committed reference-corpus-chunks.json must exist for this test to be meaningful"


# ---------------------------------------------------------------------------
# api.service.ensure_reference_analysis_ready - the exact function whose
# real production failure (OSError on /var/task/artifacts/blueprint.json)
# this whole fix addresses. Every real ingestion helper is monkeypatched to
# a lightweight fake here: this tests PATH ROUTING (where does it read
# from, where does it write to, does it ever touch sdev/ when it
# shouldn't) - not the analysis pipeline itself, which has its own separate
# coverage (tests/test_reference_analyzer.py).
# ---------------------------------------------------------------------------
def test_ensure_reference_analysis_ready_skips_ingestion_when_prebuilt_analysis_already_exists(tmp_path, monkeypatch):
    """The normal Vercel case: the deployed, prebuilt artifacts/reference-
    analysis.json already exists, so this returns immediately and sdev/ -
    intentionally not deployed - is never touched."""
    import api.service as service_module

    prebuilt_path = tmp_path / "reference-analysis.json"
    prebuilt_path.write_text('{"modules": []}')

    monkeypatch.setattr(service_module, "_REFERENCE_ANALYSIS_PATH", prebuilt_path)
    # Points somewhere that doesn't exist - if the function tried to use
    # it anyway, load_reference_material would be invoked and fail loudly
    # (it isn't monkeypatched here); a clean return proves it never was.
    monkeypatch.setattr(service_module, "SDEV_DIR", tmp_path / "sdev-does-not-exist")

    service_module.ensure_reference_analysis_ready()  # must not raise


def test_ensure_reference_analysis_ready_fails_clearly_when_neither_prebuilt_nor_sdev_available(tmp_path, monkeypatch):
    """A genuine misconfiguration (a deployment missing its committed
    corpus, with no sdev/ either) must fail loudly with an actionable
    message - never proceed into pdf_loader for a confusing raw error, and
    never silently generate from no evidence at all."""
    import api.service as service_module

    monkeypatch.setattr(service_module, "_REFERENCE_ANALYSIS_PATH", tmp_path / "missing-analysis.json")
    monkeypatch.setattr(service_module, "SDEV_DIR", tmp_path / "missing-sdev")

    with pytest.raises(FileNotFoundError, match="No reference analysis available"):
        service_module.ensure_reference_analysis_ready()


def test_ensure_reference_analysis_ready_builds_from_sdev_and_writes_only_to_the_runtime_dir(tmp_path, monkeypatch):
    """Local development before the first `analyze`: sdev/ is present, no
    prebuilt copy exists yet, so ingestion runs - and every write lands
    under RUNTIME_ARTIFACTS_DIR, never under a read-only static location."""
    import api.service as service_module

    fake_sdev = tmp_path / "sdev"
    fake_sdev.mkdir()
    runtime_dir = tmp_path / "runtime-artifacts"
    runtime_dir.mkdir()
    static_dir = tmp_path / "static-artifacts"  # deliberately never created
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    monkeypatch.setattr(service_module, "SDEV_DIR", fake_sdev)
    monkeypatch.setattr(service_module, "RUNTIME_ARTIFACTS_DIR", runtime_dir)
    monkeypatch.setattr(service_module, "_REFERENCE_ANALYSIS_PATH", runtime_dir / "reference-analysis.json")
    monkeypatch.setattr(service_module, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(service_module, "ensure_output_dirs", lambda: None)  # dirs already prepared above

    monkeypatch.setattr(service_module, "load_reference_material", lambda sdev_dir: "fake-report")
    monkeypatch.setattr(service_module, "analyze_reference_material", lambda report: {"modules": []})
    monkeypatch.setattr(service_module, "extract_corpus_chunks", lambda report: [])
    monkeypatch.setattr(service_module, "write_analysis_json", lambda analysis, path: path.write_text("{}"))
    monkeypatch.setattr(service_module, "write_analysis_markdown", lambda analysis, path: path.write_text("# md"))

    service_module.ensure_reference_analysis_ready()

    assert (runtime_dir / "reference-analysis.json").exists()
    assert (runtime_dir / "reference-corpus-chunks.json").exists()
    assert (docs_dir / "reference-analysis.md").exists()
    assert not static_dir.exists()  # never created, never written to


# ---------------------------------------------------------------------------
# Full end-to-end proof, against a GENUINELY read-only (chmod, not just
# "a directory this test happens not to write to") simulated Vercel
# filesystem: the exact real-world failure this whole fix addresses was an
# OSError raised by the OS itself when writing to a read-only mount, so
# this test reproduces that constraint for real rather than only asserting
# path strings. sdev/ is also pointed at a nonexistent directory - the
# real, deliberate Vercel condition ("sdev/ is not deployed") - proving
# generation succeeds from the prebuilt corpus alone.
# ---------------------------------------------------------------------------
def test_full_generation_succeeds_against_a_real_read_only_static_filesystem(tmp_path, monkeypatch):
    import api.service as service_module

    static_dir = tmp_path / "static-artifacts"  # simulates /var/task/artifacts
    static_dir.mkdir()
    shutil.copy(PROJECT_ROOT / "artifacts" / "reference-analysis.json", static_dir / "reference-analysis.json")
    shutil.copy(
        PROJECT_ROOT / "artifacts" / "reference-corpus-chunks.json", static_dir / "reference-corpus-chunks.json"
    )
    # Genuinely read-only, not merely untouched - r-xr-xr-x, matching what
    # actually raised the real production OSError this fixes.
    static_dir.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

    runtime_dir = tmp_path / "runtime-artifacts"  # simulates /tmp/zaio-mock-eisa/artifacts
    output_dir = tmp_path / "runtime-output"  # simulates /tmp/zaio-mock-eisa/output

    monkeypatch.setattr(service_module, "SDEV_DIR", tmp_path / "sdev-not-deployed")
    monkeypatch.setattr(service_module, "RUNTIME_ARTIFACTS_DIR", runtime_dir)
    monkeypatch.setattr(service_module, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(service_module, "_REFERENCE_ANALYSIS_PATH", static_dir / "reference-analysis.json")
    monkeypatch.setattr(service_module, "_CORPUS_CHUNKS_PATH", static_dir / "reference-corpus-chunks.json")
    monkeypatch.setattr(service_module, "_BLUEPRINT_PATH", runtime_dir / "blueprint.json")
    monkeypatch.setattr(service_module, "_VALIDATION_REPORT_PATH", runtime_dir / "validation-report.json")
    monkeypatch.setattr(service_module, "_QUALITY_REVIEW_PATH", runtime_dir / "quality-review.json")
    monkeypatch.setattr(service_module, "_GENERATION_HISTORY_PATH", runtime_dir / "generation-history.json")
    # ensure_output_dirs() itself still operates on the real (unpatched)
    # src.config module - harmless (those real directories already exist,
    # so mkdir(exist_ok=True) is a no-op) but doesn't create OUR fake
    # runtime_dir/output_dir, so create those explicitly here instead.
    runtime_dir.mkdir()
    output_dir.mkdir()

    try:
        result = service_module.generate_paper_and_memo(
            qualification="software_developer", paper_number=950, seed=1, want_pdf=False
        )
    finally:
        static_dir.chmod(stat.S_IRWXU)  # restore write access so pytest can clean up tmp_path

    assert result.validation_passed is True
    assert result.total_marks == 100
    # Every runtime artifact this call would have written landed under the
    # writable runtime dir, never under the read-only static one.
    assert (runtime_dir / "blueprint.json").exists()
    assert (runtime_dir / "generation-history.json").exists()
    assert (output_dir / "mock-eisa-paper-950.json").exists()
    assert (output_dir / "mock-eisa-memo-950.json").exists()
