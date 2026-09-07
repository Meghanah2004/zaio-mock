"""Reference-material ingestion.

Recursively walks a read-only source directory (``sdev/``), extracts text
from supported documents, and returns a normalized in-memory representation.

This module NEVER writes into the source directory. It only reads.

Security notes:
  - All paths are validated to stay inside the configured base directory.
  - File extensions are checked against an allow-list before parsing.
  - Extraction failures are captured per-file and reported, never raised as
    a hard crash that aborts the whole ingestion run (one corrupt file must
    not block analysis of the other 60 files).
  - Extracted text is later treated as UNTRUSTED DATA by every downstream
    stage (see docs/DESIGN.md, "Prompt-Injection Defense").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.security.config import SecurityConfig

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - exercised only if dependency missing
    PdfReader = None  # type: ignore[assignment,misc]

try:
    import docx  # python-docx
except ImportError:  # pragma: no cover
    docx = None  # type: ignore[assignment]

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


@dataclass
class PageText:
    page_number: int
    text: str


@dataclass
class SourceDocument:
    relative_path: str
    absolute_path: str
    extension: str
    size_bytes: int
    page_count: int
    pages: list[PageText] = field(default_factory=list)
    extraction_error: str | None = None

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)


@dataclass
class IngestionReport:
    base_dir: str
    documents: list[SourceDocument] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _extract_pdf(path: Path) -> tuple[list[PageText], str | None]:
    if PdfReader is None:
        return [], "pypdf is not installed"
    try:
        reader = PdfReader(str(path))
        pages: list[PageText] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001 - per-page resilience
                text = ""
                if not pages:
                    return [], f"failed extracting page {i}: {exc}"
            pages.append(PageText(page_number=i, text=text))
        return pages, None
    except Exception as exc:  # noqa: BLE001 - report, don't crash ingestion
        return [], f"failed to open/parse PDF: {exc}"


def _extract_docx(path: Path) -> tuple[list[PageText], str | None]:
    if docx is None:
        return [], "python-docx is not installed"
    try:
        d = docx.Document(str(path))
        text = "\n".join(p.text for p in d.paragraphs)
        # docx has no reliable page boundaries; treat as a single logical page.
        return [PageText(page_number=1, text=text)], None
    except Exception as exc:  # noqa: BLE001
        return [], f"failed to open/parse DOCX: {exc}"


def _extract_txt(path: Path) -> tuple[list[PageText], str | None]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return [PageText(page_number=1, text=text)], None
    except Exception as exc:  # noqa: BLE001
        return [], f"failed to read TXT: {exc}"


def load_reference_material(
    base_dir: Path,
    max_file_size_mb: int | None = None,
    security_config: SecurityConfig | None = None,
) -> IngestionReport:
    """Walk ``base_dir`` read-only and extract text from every supported file.

    ``base_dir`` must exist; this function never creates, deletes, or
    modifies anything under it.

    SECURITY: bounded against a pathological input directory - per-file size
    (``max_file_size_mb``, or ``security_config.max_reference_file_size_mb``
    if not given explicitly), total file count, and filename length are all
    capped (see src/security/config.py). Files over any bound are skipped
    and reported, never silently dropped and never causing unbounded
    processing time/memory.
    """
    security_config = security_config or SecurityConfig()
    if max_file_size_mb is None:
        max_file_size_mb = security_config.max_reference_file_size_mb

    base_dir = base_dir.resolve()
    if not base_dir.exists():
        raise FileNotFoundError(f"Reference directory does not exist: {base_dir}")
    if not base_dir.is_dir():
        raise NotADirectoryError(f"Reference path is not a directory: {base_dir}")

    report = IngestionReport(base_dir=str(base_dir))
    max_bytes = max_file_size_mb * 1024 * 1024
    max_files = security_config.max_reference_file_count
    max_filename_length = security_config.max_filename_length
    files_seen = 0

    for path in sorted(base_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue  # skip .DS_Store and other OS metadata

        files_seen += 1
        if files_seen > max_files:
            report.errors.append(
                f"Reference directory contains more than {max_files} files; "
                f"processing stopped early (MAX_REFERENCE_FILE_COUNT). Remaining files were not read."
            )
            break

        ext = path.suffix.lower()
        rel = str(path.relative_to(base_dir))

        if len(path.name) > max_filename_length:
            report.errors.append(f"{rel}: skipped, filename exceeds {max_filename_length} characters")
            continue

        if ext not in SUPPORTED_EXTENSIONS:
            report.skipped_files.append(rel)
            continue

        size = path.stat().st_size
        if size > max_bytes:
            report.errors.append(f"{rel}: skipped, exceeds {max_file_size_mb}MB size bound")
            continue

        if ext == ".pdf":
            pages, err = _extract_pdf(path)
        elif ext == ".docx":
            pages, err = _extract_docx(path)
        else:
            pages, err = _extract_txt(path)

        doc = SourceDocument(
            relative_path=rel,
            absolute_path=str(path),
            extension=ext,
            size_bytes=size,
            page_count=len(pages),
            pages=pages,
            extraction_error=err,
        )
        report.documents.append(doc)
        if err:
            report.errors.append(f"{rel}: {err}")

    return report
