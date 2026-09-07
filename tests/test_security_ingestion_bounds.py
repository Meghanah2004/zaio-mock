"""Ingestion-boundary security tests: file size, file count, filename
length, and unsupported file types."""
from __future__ import annotations

from src.ingestion.pdf_loader import load_reference_material
from src.security.config import SecurityConfig


def test_oversized_file_is_skipped_not_processed(tmp_path):
    big_file = tmp_path / "huge.txt"
    big_file.write_text("x" * 1000)
    config = SecurityConfig(max_reference_file_size_mb=0)  # 0MB -> everything is "oversized"
    # 0MB * 1024*1024 = 0 bytes, so even this tiny file exceeds the bound.
    report = load_reference_material(tmp_path, security_config=config)
    assert not any(d.relative_path == "huge.txt" for d in report.documents)
    assert any("exceeds" in e and "huge.txt" in e for e in report.errors)


def test_file_count_above_limit_is_bounded(tmp_path):
    for i in range(10):
        (tmp_path / f"doc{i}.txt").write_text("content")
    config = SecurityConfig(max_reference_file_count=3)
    report = load_reference_material(tmp_path, security_config=config)
    assert len(report.documents) <= 3
    assert any("more than 3 files" in e for e in report.errors)


def test_filename_exceeding_max_length_is_rejected(tmp_path):
    # 200 chars is within OS filename limits (~255 bytes) but exceeds a
    # deliberately stricter application-level bound configured below.
    long_name = ("a" * 196) + ".txt"
    (tmp_path / long_name).write_text("content")
    config = SecurityConfig(max_filename_length=100)
    report = load_reference_material(tmp_path, security_config=config)
    assert not any(d.relative_path == long_name for d in report.documents)
    assert any("filename exceeds" in e for e in report.errors)


def test_unsupported_extension_is_skipped_not_processed(tmp_path):
    (tmp_path / "notes.exe").write_bytes(b"MZ\x90\x00")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    report = load_reference_material(tmp_path)
    assert "notes.exe" in report.skipped_files
    assert "image.png" in report.skipped_files
    assert not any(d.relative_path in ("notes.exe", "image.png") for d in report.documents)


def test_default_security_config_used_when_none_provided(tmp_path):
    (tmp_path / "doc.txt").write_text("content")
    report = load_reference_material(tmp_path)  # no security_config passed
    assert any(d.relative_path == "doc.txt" for d in report.documents)
