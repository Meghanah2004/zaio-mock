"""Command-line entry point for the Mock EISA generation pipeline.

    python -m src.cli analyze
    python -m src.cli generate --qualification software_developer --paper-number 2 --seed 20260906
    python -m src.cli validate --paper output/mock-eisa-paper-02.json --memo output/mock-eisa-memo-02.json
    python -m src.cli render --paper output/mock-eisa-paper-02.json --memo output/mock-eisa-memo-02.json
    python -m src.cli review --paper output/mock-eisa-paper-02.json --memo output/mock-eisa-memo-02.json
    python -m src.cli pipeline --qualification software_developer --paper-number 2 --seed 20260906

Every subcommand fails loudly (non-zero exit, clear message) rather than
silently continuing - see docs/DESIGN.md "What the LLM should NOT be
trusted to do unsupervised" and the project's "no fake completion" rule.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    PROJECT_ROOT,
    SDEV_DIR,
    LLMSettings,
    ensure_output_dirs,
    load_qualification_config,
    safe_path_within,
)
from src.generation.blueprint import build_blueprint, write_blueprint
from src.generation.memo_generator import generate_memo, write_memo
from src.generation.question_generator import generate_paper, write_paper
from src.ingestion.pdf_loader import load_reference_material
from src.providers.factory import build_provider
from src.rendering.markdown_renderer import render_memo_markdown, render_paper_markdown
from src.rendering.pdf_renderer import PdfRenderingUnavailable, render_markdown_to_pdf
from src.security.config import SecurityConfig
from src.security.redaction import redact_secrets
from src.validation.orchestrator import run_all_validators
from src.validation.quality_reviewer import run_quality_review
from src.validation.schema_validator import load_json_file


def _bounded_int(min_value: int, max_value: int, label: str):
    """Build an argparse ``type=`` callable enforcing an inclusive range.

    Rejects out-of-range values at argument-parsing time with a normal
    argparse usage error - strict validation over silent coercion (a
    negative or absurd --paper-number/--seed is rejected outright rather
    than silently clamped or accepted and only failing later)."""

    def _parse(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{label} must be an integer, got {raw!r}") from exc
        if not (min_value <= value <= max_value):
            raise argparse.ArgumentTypeError(f"{label} must be between {min_value} and {max_value}, got {value}")
        return value

    return _parse


def _resolve_output_path(raw: str, default_dir: Path) -> Path:
    """Accept a bare filename (placed under default_dir) or an explicit path,
    always guarded against escaping the project root."""
    p = Path(raw)
    if not p.is_absolute() and len(p.parts) == 1:
        return safe_path_within(default_dir, p.name)
    return safe_path_within(PROJECT_ROOT, raw)


def cmd_analyze(args: argparse.Namespace) -> int:
    ensure_output_dirs()
    print(f"Analyzing reference material in {SDEV_DIR} (read-only) ...")
    report = load_reference_material(SDEV_DIR)
    if report.errors:
        print(f"WARNING: {len(report.errors)} extraction issue(s):")
        for e in report.errors:
            print(f"  - {e}")

    analysis = analyze_reference_material(report)

    json_path = ARTIFACTS_DIR / "reference-analysis.json"
    md_path = DOCS_DIR / "reference-analysis.md"
    write_analysis_json(analysis, json_path)
    write_analysis_markdown(analysis, md_path)

    chunks = extract_corpus_chunks(report)
    chunks_path = ARTIFACTS_DIR / "reference-corpus-chunks.json"
    chunks_path.write_text(json.dumps(chunks), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Wrote {chunks_path} ({len(chunks)} chunks, used by the novelty checker)")
    print(f"Modules analyzed: {len(analysis.modules)}; anomalies found: {len(analysis.anomalies)}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    ensure_output_dirs()
    analysis_path = ARTIFACTS_DIR / "reference-analysis.json"
    if not analysis_path.exists():
        print(f"ERROR: {analysis_path} not found. Run `python -m src.cli analyze` first.", file=sys.stderr)
        return 1

    reference_analysis = load_json_file(analysis_path)
    qual_config = load_qualification_config(args.qualification)

    blueprint = build_blueprint(reference_analysis, qual_config, args.paper_number)
    blueprint_path = ARTIFACTS_DIR / "blueprint.json"
    write_blueprint(blueprint, blueprint_path)
    print(f"Wrote {blueprint_path}")

    settings = LLMSettings()
    provider = build_provider(settings)
    print(f"Using LLM provider: {provider.name}"
          + (" (real API credentials configured)" if settings.has_real_credentials() else " (no live API key configured)"))

    blueprint_dict = blueprint.to_json_dict()
    try:
        paper = generate_paper(blueprint_dict, provider, args.seed)
        memo = generate_memo(paper, provider, args.seed)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: generation failed: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1

    paper_path = OUTPUT_DIR / f"mock-eisa-paper-{args.paper_number:02d}.json"
    memo_path = OUTPUT_DIR / f"mock-eisa-memo-{args.paper_number:02d}.json"
    write_paper(paper, paper_path)
    write_memo(memo, memo_path)
    print(f"Wrote {paper_path}")
    print(f"Wrote {memo_path}")
    print("Run `python -m src.cli validate` and `python -m src.cli render` next.")
    return 0


def _corpus_chunks_path() -> Path:
    path = ARTIFACTS_DIR / "reference-corpus-chunks.json"
    if not path.exists():
        print(f"WARNING: {path} not found; skipping novelty check. Run `analyze` first.", file=sys.stderr)
    return path


def cmd_validate(args: argparse.Namespace) -> int:
    ensure_output_dirs()
    paper_path = _resolve_output_path(args.paper, OUTPUT_DIR)
    memo_path = _resolve_output_path(args.memo, OUTPUT_DIR)

    try:
        paper = load_json_file(paper_path)
        memo = load_json_file(memo_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    blueprint = None
    blueprint_path = ARTIFACTS_DIR / "blueprint.json"
    if blueprint_path.exists():
        blueprint = load_json_file(blueprint_path)
    else:
        print(f"WARNING: {blueprint_path} not found; skipping outcome/competency coverage checks.", file=sys.stderr)

    report, novelty_result = run_all_validators(paper, memo, blueprint, _corpus_chunks_path())

    result_dict = report.to_json_dict()
    if novelty_result is not None:
        result_dict["novelty"] = novelty_result

    out_path = ARTIFACTS_DIR / "validation-report.json"
    out_path.write_text(json.dumps(result_dict, indent=2), encoding="utf-8")

    print(f"Validation {'PASSED' if report.passed else 'FAILED'} - {sum(1 for c in report.checks if c.passed)}/{len(report.checks)} checks passed")
    for c in report.checks:
        if not c.passed:
            print(f"  FAIL: {c.name} - {c.details}")
    print(f"Full report written to {out_path}")
    return 0 if report.passed else 1


def cmd_review(args: argparse.Namespace) -> int:
    paper_path = _resolve_output_path(args.paper, OUTPUT_DIR)
    memo_path = _resolve_output_path(args.memo, OUTPUT_DIR)
    try:
        paper = load_json_file(paper_path)
        memo = load_json_file(memo_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    settings = LLMSettings()
    provider = build_provider(settings)
    review = run_quality_review(paper, memo, provider)

    out_path = ARTIFACTS_DIR / "quality-review.json"
    out_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    print(f"Quality review approved={review['approved']}; wrote {out_path}")
    return 0 if review["approved"] else 1


def cmd_render(args: argparse.Namespace) -> int:
    ensure_output_dirs()
    paper_path = _resolve_output_path(args.paper, OUTPUT_DIR)
    memo_path = _resolve_output_path(args.memo, OUTPUT_DIR)
    try:
        paper = load_json_file(paper_path)
        memo = load_json_file(memo_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    paper_md = render_paper_markdown(paper)
    memo_md = render_memo_markdown(memo, paper)

    paper_md_path = paper_path.with_suffix(".md")
    memo_md_path = memo_path.with_suffix(".md")
    paper_md_path.write_text(paper_md, encoding="utf-8")
    memo_md_path.write_text(memo_md, encoding="utf-8")
    print(f"Wrote {paper_md_path}")
    print(f"Wrote {memo_md_path}")

    if args.pdf:
        for md_text, md_path in ((paper_md, paper_md_path), (memo_md, memo_md_path)):
            pdf_path = md_path.with_suffix(".pdf")
            try:
                render_markdown_to_pdf(md_text, pdf_path)
                print(f"Wrote {pdf_path}")
            except PdfRenderingUnavailable as exc:
                print(f"WARNING: {exc}", file=sys.stderr)
    return 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    steps = [
        ("analyze", lambda: cmd_analyze(args)),
        ("generate", lambda: cmd_generate(args)),
    ]
    for name, fn in steps:
        print(f"\n=== pipeline step: {name} ===")
        rc = fn()
        if rc != 0:
            print(f"Pipeline stopped: '{name}' failed.", file=sys.stderr)
            return rc

    paper_path = OUTPUT_DIR / f"mock-eisa-paper-{args.paper_number:02d}.json"
    memo_path = OUTPUT_DIR / f"mock-eisa-memo-{args.paper_number:02d}.json"

    validate_args = argparse.Namespace(paper=str(paper_path), memo=str(memo_path))
    print("\n=== pipeline step: validate ===")
    rc = cmd_validate(validate_args)
    if rc != 0:
        print("Pipeline stopped: validation failed.", file=sys.stderr)
        return rc

    print("\n=== pipeline step: review ===")
    rc = cmd_review(validate_args)
    if rc != 0:
        print("WARNING: quality review did not approve; artifacts kept for inspection.", file=sys.stderr)

    render_args = argparse.Namespace(paper=str(paper_path), memo=str(memo_path), pdf=args.pdf)
    print("\n=== pipeline step: render ===")
    return cmd_render(render_args)


def build_parser() -> argparse.ArgumentParser:
    security_config = SecurityConfig.from_env()
    paper_number_type = _bounded_int(security_config.min_paper_number, security_config.max_paper_number, "--paper-number")
    seed_type = _bounded_int(security_config.min_seed, security_config.max_seed, "--seed")

    parser = argparse.ArgumentParser(prog="python -m src.cli", description="Zaio Mock EISA generation pipeline (Phase 1 - Software Developer)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Analyze reference material under sdev/ (read-only)")
    p_analyze.set_defaults(func=cmd_analyze)

    p_generate = sub.add_parser("generate", help="Generate a Mock EISA paper + memo")
    p_generate.add_argument("--qualification", default="software_developer")
    p_generate.add_argument("--paper-number", type=paper_number_type, default=2)
    p_generate.add_argument("--seed", type=seed_type, default=20260906)
    p_generate.set_defaults(func=cmd_generate)

    p_validate = sub.add_parser("validate", help="Run all deterministic validators against a paper/memo")
    p_validate.add_argument("--paper", required=True)
    p_validate.add_argument("--memo", required=True)
    p_validate.set_defaults(func=cmd_validate)

    p_review = sub.add_parser("review", help="Run the LLM-based quality review stage")
    p_review.add_argument("--paper", required=True)
    p_review.add_argument("--memo", required=True)
    p_review.set_defaults(func=cmd_review)

    p_render = sub.add_parser("render", help="Render Markdown (and optionally PDF) from a paper/memo")
    p_render.add_argument("--paper", required=True)
    p_render.add_argument("--memo", required=True)
    p_render.add_argument("--pdf", action="store_true")
    p_render.set_defaults(func=cmd_render)

    p_pipeline = sub.add_parser("pipeline", help="Run analyze -> generate -> validate -> review -> render")
    p_pipeline.add_argument("--qualification", default="software_developer")
    p_pipeline.add_argument("--paper-number", type=paper_number_type, default=2)
    p_pipeline.add_argument("--seed", type=seed_type, default=20260906)
    p_pipeline.add_argument("--pdf", action="store_true")
    p_pipeline.set_defaults(func=cmd_pipeline)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, NotADirectoryError) as exc:
        print(f"ERROR: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        # Safety net for any exception type not explicitly handled above.
        # The CLI is a trusted local interface and may be more descriptive
        # than a public API boundary would be (see docs/SECURITY-AUDIT.md),
        # but it must never dump a raw Python traceback: that would expose
        # absolute filesystem paths and internal module names, which
        # section 9 of the security hardening pass explicitly forbids at
        # any user-facing boundary, CLI included. Print the exception type
        # and a secret-redacted message only - no traceback.
        print(f"ERROR: unexpected {type(exc).__name__}: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
