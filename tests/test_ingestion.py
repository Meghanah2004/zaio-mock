from __future__ import annotations

import pytest

from src.ingestion.pdf_loader import load_reference_material


def _make_pdf(path, text: str) -> None:
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    c.drawString(72, 720, text)
    c.save()


def test_load_reference_material_extracts_supported_files(tmp_path):
    _make_pdf(tmp_path / "doc1.pdf", "Hello reference world")
    (tmp_path / "notes.txt").write_text("Plain text notes", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / ".DS_Store").write_bytes(b"\x00\x00")

    report = load_reference_material(tmp_path)

    names = {d.relative_path for d in report.documents}
    assert "doc1.pdf" in names
    assert "notes.txt" in names
    assert "image.png" in report.skipped_files
    assert ".DS_Store" not in names and ".DS_Store" not in report.skipped_files

    pdf_doc = next(d for d in report.documents if d.relative_path == "doc1.pdf")
    assert "Hello reference world" in pdf_doc.full_text
    assert pdf_doc.extraction_error is None


def test_load_reference_material_never_writes_into_source(tmp_path):
    _make_pdf(tmp_path / "doc1.pdf", "content")
    before = sorted(p.name for p in tmp_path.iterdir())
    load_reference_material(tmp_path)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


def test_load_reference_material_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_reference_material(tmp_path / "does-not-exist")


def test_load_reference_material_reports_corrupt_pdf_without_crashing(tmp_path):
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4 not a real pdf body")
    _make_pdf(tmp_path / "good.pdf", "still readable")

    report = load_reference_material(tmp_path)

    names = {d.relative_path for d in report.documents}
    assert "good.pdf" in names
    assert any("broken.pdf" in e for e in report.errors)
