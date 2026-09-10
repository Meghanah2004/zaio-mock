"""Orchestrates the existing engine (``src/``) for the API layer.

Every step here calls a real function already used by ``src/cli.py`` - see
docs/API.md, "Reuse over duplication." This module adds no
assessment-generation, validation, novelty, or rendering logic of its own;
it only sequences existing calls and shapes their output into the API's
response models.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from src.analysis.reference_analyzer import (
    analyze_reference_material,
    extract_corpus_chunks,
)
from src.analysis.report_writer import write_json as write_analysis_json
from src.analysis.report_writer import write_markdown as write_analysis_markdown
from src.config import (
    DOCS_DIR,
    OUTPUT_DIR,
    RUNTIME_ARTIFACTS_DIR,
    SDEV_DIR,
    LLMSettings,
    compute_effective_seed,
    ensure_output_dirs,
    load_qualification_config,
    resolve_readable_artifact,
)
from src.generation.blueprint import build_blueprint, write_blueprint
from src.generation.memo_generator import generate_memo, write_memo
from src.generation.question_generator import generate_paper, write_paper
from src.ingestion.pdf_loader import load_reference_material
from src.providers.factory import build_provider
from src.rendering.markdown_renderer import render_memo_markdown, render_paper_markdown
from src.rendering.pdf_renderer import PdfRenderingUnavailable, render_markdown_to_pdf
from src.retrieval.evidence_selector import (
    build_evidence_by_section,
    load_retrieval_index,
)
from src.security.config import SecurityConfig
from src.validation.cross_paper_novelty import load_history, record_paper, write_history
from src.validation.orchestrator import run_all_validators
from src.validation.quality_reviewer import run_quality_review
from src.validation.schema_validator import load_json_file

# _REFERENCE_ANALYSIS_PATH / _CORPUS_CHUNKS_PATH: resolved to WHICHEVER
# real location currently holds them - a prebuilt, committed copy under
# ARTIFACTS_DIR (the deployed, read-only corpus/analysis - the normal case
# on Vercel, see docs/DEPLOYMENT.md), or a copy this process itself built
# from sdev/ under RUNTIME_ARTIFACTS_DIR (the normal case on a fresh local
# clone before ever running `analyze`). See
# src.config.resolve_readable_artifact's docstring for the full reasoning.
#
# Every OTHER path below is always purely runtime-written (never prebuilt/
# committed) and always lives under RUNTIME_ARTIFACTS_DIR - writable
# everywhere, including Vercel's `/tmp` - never under the plain,
# read-only-on-Vercel ARTIFACTS_DIR. This is the direct fix for the real
# production incident this module now documents: a real Vercel `/api/
# generate` request failed with "OSError: [Errno 30] Read-only file
# system: '/var/task/artifacts/blueprint.json'" because this file used to
# resolve _BLUEPRINT_PATH (and every path below it) under the plain,
# read-only ARTIFACTS_DIR unconditionally.
_REFERENCE_ANALYSIS_PATH = resolve_readable_artifact("reference-analysis.json")
_CORPUS_CHUNKS_PATH = resolve_readable_artifact("reference-corpus-chunks.json")
_BLUEPRINT_PATH = RUNTIME_ARTIFACTS_DIR / "blueprint.json"
_VALIDATION_REPORT_PATH = RUNTIME_ARTIFACTS_DIR / "validation-report.json"
_QUALITY_REVIEW_PATH = RUNTIME_ARTIFACTS_DIR / "quality-review.json"
_GENERATION_HISTORY_PATH = RUNTIME_ARTIFACTS_DIR / "generation-history.json"
"""Cross-paper novelty memory (src.validation.cross_paper_novelty). LOCAL /
CLI / a long-lived server: durable for the process's lifetime, exactly as
before. VERCEL: written under /tmp, which is per-instance scratch space,
not shared across concurrently-scaled instances and not guaranteed to
survive a cold start (see docs/DEPLOYMENT.md, "Generation history
persistence on Vercel," and Vercel's own docs: "Read-only filesystem with
writable /tmp scratch space"). This is a REAL, DOCUMENTED limitation of
the current deployment, not a silently-accepted regression: within one
warm Vercel Function instance's lifetime (the common case for consecutive
requests, per Vercel's Fluid compute instance reuse), novelty checking
works exactly as designed; across a cold start or a request routed to a
different concurrent instance, that instance's history starts empty, so a
new paper is only checked against papers already generated on THAT
instance. This never produces incorrect output or a crash - at worst, an
individual instance's cross-paper comparison window is narrower on Vercel
than it is for a long-lived local/CLI process. Closing this gap
completely requires an external durable store (e.g. Vercel Blob/KV), which
is intentionally NOT implemented here without explicit approval, per this
Vercel deployment's minimal-footprint requirement."""


def ensure_reference_analysis_ready(force: bool = False) -> None:
    """Run the (slow, ~seconds-to-a-minute for the real sdev/ corpus)
    reference analysis step once, if its cached output isn't already on
    disk. Intended to be called from the API's startup lifespan, never per
    request - see docs/API.md, "Why analysis runs once at startup."

    ``sdev/`` is immutable supplied material for the lifetime of a
    deployment, so "already analyzed" is treated as "still valid," exactly
    like the existing CLI (`generate`/`validate` already assume `analyze`
    was run earlier and never re-run it themselves).

    REWORK (Vercel): ``sdev/`` is intentionally NOT part of a Vercel
    deployment (see .gitignore, docs/DEPLOYMENT.md) - only the PREBUILT
    ``artifacts/reference-analysis.json`` / ``reference-corpus-chunks.json``
    are. The normal Vercel path is therefore the very first check below:
    those prebuilt files already exist (committed, read-only), so this
    function returns immediately and sdev/ is never touched. Ingestion from
    sdev/ only ever runs when neither a prebuilt nor a previously-built-
    this-instance copy exists AND sdev/ itself is actually present -
    i.e. local development before the first `analyze`, never a real Vercel
    deployment. If neither a prebuilt artifact nor sdev/ is available (a
    genuine misconfiguration - a deployment missing its committed corpus),
    this fails loudly with an actionable message instead of proceeding
    into pdf_loader and failing there with a confusing raw error, and
    instead of silently generating from no evidence at all.
    """
    if _REFERENCE_ANALYSIS_PATH.exists() and not force:
        return
    if not SDEV_DIR.exists():
        raise FileNotFoundError(
            f"No reference analysis available: {_REFERENCE_ANALYSIS_PATH} was not found, and "
            f"{SDEV_DIR} is not present to build one from (expected on a deployment - sdev/ is "
            f"intentionally not deployed, see docs/DEPLOYMENT.md). This deployment is missing its "
            f"prebuilt artifacts/reference-analysis.json and/or artifacts/reference-corpus-chunks.json - "
            f"commit them (see README.md) before deploying."
        )
    ensure_output_dirs()
    report = load_reference_material(SDEV_DIR)
    analysis = analyze_reference_material(report)
    # Always written explicitly under RUNTIME_ARTIFACTS_DIR - never reuse
    # the resolved _REFERENCE_ANALYSIS_PATH/_CORPUS_CHUNKS_PATH constants
    # as write targets here, since a partially-deployed environment could
    # have resolved one of them to the read-only ARTIFACTS_DIR while the
    # other is genuinely missing; this write must never be able to target
    # that read-only location under any circumstance.
    write_analysis_json(analysis, RUNTIME_ARTIFACTS_DIR / "reference-analysis.json")
    write_analysis_markdown(analysis, DOCS_DIR / "reference-analysis.md")
    chunks = extract_corpus_chunks(report)
    (RUNTIME_ARTIFACTS_DIR / "reference-corpus-chunks.json").write_text(json.dumps(chunks), encoding="utf-8")


@dataclass
class GenerationResult:
    result_id: int
    paper_id: str
    qualification: str
    total_marks: int
    validation_passed: bool
    deterministic_checks_passed: int
    deterministic_checks_total: int
    novelty_status: str | None
    quality_review_approved: bool
    pdf_available: bool


def generate_paper_and_memo(qualification: str, paper_number: int, seed: int, want_pdf: bool) -> GenerationResult:
    """Runs generate -> validate -> review -> render, exactly the sequence
    `python -m src.cli pipeline` runs, and writes the same output files to
    the same locations - so a result is inspectable identically whether it
    was produced via the CLI or the API. Raises whatever the underlying
    engine functions raise (GenerationError, LLMProviderError, ValueError,
    FileNotFoundError); the API's error handlers (api/errors.py) translate
    those into safe responses - this function does not catch or reshape
    them, to avoid a second error-handling layer duplicating that logic.

    REWORK: this used to call generate_paper/generate_memo with NO
    retrieval evidence and NO generation history at all - every API-
    triggered generation was silently ungrounded (topic-name-only
    question generation, no answer-side grounding, no cross-paper novelty
    checking whatsoever), even though the exact same real evidence/history
    plumbing already existed and was already used by src/cli.py's
    `generate` command. Fixed by calling the SAME shared retrieval/history
    functions the CLI uses (src.retrieval.evidence_selector.
    load_retrieval_index/build_evidence_by_section,
    src.validation.cross_paper_novelty.load_history/record_paper/
    write_history) - this is the real fix behind "the frontend Generate
    button must invoke the actual, fully-grounded generation pipeline,"
    not a frontend change; the frontend already called this function
    correctly, this function just wasn't doing real RAG.

    REWORK (repeated-questions incident): ``seed`` alone used to drive
    every seed-dependent step below (question-side evidence rotation,
    answer-side evidence rotation, the provider task seed) with no
    dependence on ``paper_number`` at all - and both real entry points'
    seed DEFAULTS (src/cli.py's ``--seed``, frontend/src/components/
    GenerateForm.tsx's seed field) were the same static literal, so a
    caller generating Paper 1 then Paper 2 without manually picking a new
    seed retrieved IDENTICAL evidence for both, which a real low-
    temperature provider frequently turned into near-identical or
    literally duplicate questions - see src.config.compute_effective_seed's
    docstring for the full root-cause analysis. Fixed here, once, by
    computing ``effective_seed`` immediately below and threading THAT
    (never the raw ``seed``) through every call that used to receive
    ``seed`` directly. ``paper_number`` never becomes prompt/evidence
    content anywhere downstream of this - it only changes WHICH real,
    page-cited learner-guide passages get selected, never what they say.
    """
    ensure_output_dirs()
    ensure_reference_analysis_ready()

    effective_seed = compute_effective_seed(seed, paper_number)

    reference_analysis = load_json_file(_REFERENCE_ANALYSIS_PATH)
    qual_config = load_qualification_config(qualification)

    blueprint = build_blueprint(reference_analysis, qual_config, paper_number)
    write_blueprint(blueprint, _BLUEPRINT_PATH)
    blueprint_dict = blueprint.to_json_dict()

    settings = LLMSettings()
    security_config = SecurityConfig.from_env()
    provider = build_provider(settings, security_config)

    retrieval_index, corpus_chunks = load_retrieval_index(_CORPUS_CHUNKS_PATH)
    evidence_by_section = build_evidence_by_section(
        blueprint_dict, retrieval_index, corpus_chunks, security_config, effective_seed
    )
    generation_history = load_history(_GENERATION_HISTORY_PATH)

    paper = generate_paper(
        blueprint_dict,
        provider,
        effective_seed,
        evidence_by_section=evidence_by_section,
        generation_history=generation_history,
        security_config=security_config,
    )
    memo = generate_memo(
        paper,
        provider,
        effective_seed,
        security_config=security_config,
        retrieval_index=retrieval_index,
        corpus_chunks=corpus_chunks,
    )

    write_history(record_paper(generation_history, paper), _GENERATION_HISTORY_PATH)

    paper_path = OUTPUT_DIR / f"mock-eisa-paper-{paper_number:02d}.json"
    memo_path = OUTPUT_DIR / f"mock-eisa-memo-{paper_number:02d}.json"
    write_paper(paper, paper_path)
    write_memo(memo, memo_path)

    report, novelty_result = run_all_validators(paper, memo, blueprint_dict, _CORPUS_CHUNKS_PATH)
    result_dict = report.to_json_dict()
    if novelty_result is not None:
        result_dict["novelty"] = novelty_result
    _VALIDATION_REPORT_PATH.write_text(json.dumps(result_dict, indent=2), encoding="utf-8")

    review = run_quality_review(paper, memo, provider)
    _QUALITY_REVIEW_PATH.write_text(json.dumps(review, indent=2), encoding="utf-8")

    paper_md = render_paper_markdown(paper)
    memo_md = render_memo_markdown(memo, paper)
    paper_path.with_suffix(".md").write_text(paper_md, encoding="utf-8")
    memo_path.with_suffix(".md").write_text(memo_md, encoding="utf-8")

    pdf_available = False
    if want_pdf:
        try:
            render_markdown_to_pdf(paper_md, paper_path.with_suffix(".pdf"))
            render_markdown_to_pdf(memo_md, memo_path.with_suffix(".pdf"))
            pdf_available = True
        except PdfRenderingUnavailable:
            pdf_available = False

    return GenerationResult(
        result_id=paper_number,
        paper_id=paper["paper_id"],
        qualification=qualification,
        total_marks=paper["total_marks"],
        validation_passed=report.passed,
        deterministic_checks_passed=sum(1 for c in report.checks if c.passed),
        deterministic_checks_total=len(report.checks),
        novelty_status=novelty_result["overall_status"] if novelty_result else None,
        quality_review_approved=bool(review.get("approved")),
        pdf_available=pdf_available,
    )
