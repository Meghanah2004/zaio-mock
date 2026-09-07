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
    ARTIFACTS_DIR,
    DOCS_DIR,
    OUTPUT_DIR,
    SDEV_DIR,
    LLMSettings,
    ensure_output_dirs,
    load_qualification_config,
)
from src.generation.blueprint import build_blueprint, write_blueprint
from src.generation.memo_generator import generate_memo, write_memo
from src.generation.question_generator import generate_paper, write_paper
from src.ingestion.pdf_loader import load_reference_material
from src.providers.factory import build_provider
from src.rendering.markdown_renderer import render_memo_markdown, render_paper_markdown
from src.rendering.pdf_renderer import PdfRenderingUnavailable, render_markdown_to_pdf
from src.validation.orchestrator import run_all_validators
from src.validation.quality_reviewer import run_quality_review
from src.validation.schema_validator import load_json_file

_REFERENCE_ANALYSIS_PATH = ARTIFACTS_DIR / "reference-analysis.json"
_CORPUS_CHUNKS_PATH = ARTIFACTS_DIR / "reference-corpus-chunks.json"
_BLUEPRINT_PATH = ARTIFACTS_DIR / "blueprint.json"
_VALIDATION_REPORT_PATH = ARTIFACTS_DIR / "validation-report.json"
_QUALITY_REVIEW_PATH = ARTIFACTS_DIR / "quality-review.json"


def ensure_reference_analysis_ready(force: bool = False) -> None:
    """Run the (slow, ~seconds-to-a-minute for the real sdev/ corpus)
    reference analysis step once, if its cached output isn't already on
    disk. Intended to be called from the API's startup lifespan, never per
    request - see docs/API.md, "Why analysis runs once at startup."

    ``sdev/`` is immutable supplied material for the lifetime of a
    deployment, so "already analyzed" is treated as "still valid," exactly
    like the existing CLI (`generate`/`validate` already assume `analyze`
    was run earlier and never re-run it themselves).
    """
    if _REFERENCE_ANALYSIS_PATH.exists() and not force:
        return
    ensure_output_dirs()
    report = load_reference_material(SDEV_DIR)
    analysis = analyze_reference_material(report)
    write_analysis_json(analysis, _REFERENCE_ANALYSIS_PATH)
    write_analysis_markdown(analysis, DOCS_DIR / "reference-analysis.md")
    chunks = extract_corpus_chunks(report)
    _CORPUS_CHUNKS_PATH.write_text(json.dumps(chunks), encoding="utf-8")


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
    """
    ensure_output_dirs()
    ensure_reference_analysis_ready()

    reference_analysis = load_json_file(_REFERENCE_ANALYSIS_PATH)
    qual_config = load_qualification_config(qualification)

    blueprint = build_blueprint(reference_analysis, qual_config, paper_number)
    write_blueprint(blueprint, _BLUEPRINT_PATH)
    blueprint_dict = blueprint.to_json_dict()

    settings = LLMSettings()
    provider = build_provider(settings)

    paper = generate_paper(blueprint_dict, provider, seed)
    memo = generate_memo(paper, provider, seed)

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
