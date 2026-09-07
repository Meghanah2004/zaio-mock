"""Safe mapping from a public ``result_id`` to server-controlled output files.

No client-supplied string is ever used to build a filesystem path. A
``result_id`` is always an ``int`` by the time it reaches these functions -
enforced structurally by FastAPI's path-parameter/Pydantic-field typing
before a request handler ever runs, so it cannot contain ``/``, ``..``, or
any other traversal-shaped character. ``result_id`` reuses the SAME
``paper_number`` identity the existing CLI already uses for output
filenames (``mock-eisa-paper-{NN}.json``) - deliberately, so a paper
generated via the CLI and one generated via the API share one identity
scheme and neither a database nor a separate ID registry is needed.

``safe_path_within`` is applied anyway, as defense-in-depth consistent
with the rest of the codebase, even though the int-typed result_id already
makes traversal structurally impossible here.
"""
from __future__ import annotations

from pathlib import Path

from src.config import OUTPUT_DIR, safe_path_within


def _output_path(filename: str) -> Path:
    return safe_path_within(OUTPUT_DIR, filename)


def paper_json_path(result_id: int) -> Path:
    return _output_path(f"mock-eisa-paper-{result_id:02d}.json")


def memo_json_path(result_id: int) -> Path:
    return _output_path(f"mock-eisa-memo-{result_id:02d}.json")


def paper_pdf_path(result_id: int) -> Path:
    return _output_path(f"mock-eisa-paper-{result_id:02d}.pdf")


def memo_pdf_path(result_id: int) -> Path:
    return _output_path(f"mock-eisa-memo-{result_id:02d}.pdf")


def result_exists(result_id: int) -> bool:
    """A result "exists" once both its paper and memo JSON have been
    written - matching what /api/generate guarantees before responding."""
    return paper_json_path(result_id).is_file() and memo_json_path(result_id).is_file()


def available_formats(result_id: int) -> list[str]:
    formats = ["json"]
    if paper_json_path(result_id).with_suffix(".md").is_file():
        formats.append("md")
    if paper_pdf_path(result_id).is_file():
        formats.append("pdf")
    return formats
