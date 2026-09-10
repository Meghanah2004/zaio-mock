from __future__ import annotations

from src.analysis.reference_analyzer import (
    _parse_header_fields,
    _parse_knowledge_topics,
    extract_corpus_chunks,
)
from src.ingestion.pdf_loader import IngestionReport, PageText, SourceDocument

SAMPLE_MODULE_TEXT = """
 \n1 | Page \n \n \nSAMPLE MODULE TITLE, NQF LEVEL 4, CREDITS 8 \n \nLEARNER GUIDE \n
Module # 251201-005-00-KM-99: \nNQF Level level 4 \nNotional hours 80 \nCredit(s) Cr 8 \n
Occupational \nCode \n251201005 \nSAQA QUAL ID 118707 \nQualification Title Occupational Certificate: Software Developer \n
Purpose \nThe main focus of this module is to build a sample skill. \nTopic elements to be covered include \n
The learning will enable learners to demonstrate an understanding of: \n
 KM-99-KT01: First Topic 60% \n KM-99-KT02: Second Topic 40% \n
Entry Requirements \nNQF 4 \n
SECTION 1: KM-99-KT01 : First Topic 60% \nLearning Outcome \n
SECTION 2: KM-99-KT02 : Second Topic 40% \nLearning Outcome \n
"""


def test_parse_header_fields_extracts_all_known_fields():
    header = _parse_header_fields(SAMPLE_MODULE_TEXT)
    assert header["module_code"] == "251201-005-00-KM-99"
    assert header["nqf_level"] == 4
    assert header["notional_hours"] == 80
    assert header["credits"] == 8
    assert header["occupational_code"] == "251201005"
    assert header["saqa_qual_id"] == "118707"
    assert header["qualification_title"] == "Occupational Certificate: Software Developer"
    assert header["display_title"] == "SAMPLE MODULE TITLE"
    assert header["entry_requirement"] == "NQF 4"


def test_parse_knowledge_topics_from_section_headers():
    topics = _parse_knowledge_topics(SAMPLE_MODULE_TEXT)
    codes = {t.code: t.weight_percent for t in topics}
    assert codes == {"KM-99-KT01": 60.0, "KM-99-KT02": 40.0}
    assert sum(codes.values()) == 100.0


def test_parse_knowledge_topics_falls_back_to_intro_summary_when_no_weight_in_body():
    text_without_body_weights = SAMPLE_MODULE_TEXT.replace(
        "SECTION 1: KM-99-KT01 : First Topic 60%", "SECTION 1: KM-99-KT01 : First Topic"
    )
    topics = _parse_knowledge_topics(text_without_body_weights)
    kt01 = next(t for t in topics if t.code == "KM-99-KT01")
    assert kt01.weight_percent == 60.0


def _module_doc(relative_path: str, pages: list[str]) -> SourceDocument:
    return SourceDocument(
        relative_path=relative_path,
        absolute_path=f"/fake/{relative_path}",
        extension=".pdf",
        size_bytes=1,
        page_count=len(pages),
        pages=[PageText(page_number=i, text=t) for i, t in enumerate(pages, start=1)],
    )


def test_extract_corpus_chunks_preserves_real_page_numbers():
    doc = _module_doc(
        "Module 99-Learner Guide.pdf",
        [
            "1 | P a g e front matter with at least eight distinct words in it",
            "SECTION 1: KM-99-KT01: First Topic 60%\nThis page explains the first topic in reasonable detail for a chunk.",
        ],
    )
    report = IngestionReport(base_dir="fake", documents=[doc])

    chunks = extract_corpus_chunks(report)

    pages_seen = {c["page"] for c in chunks if c["source"] == doc.relative_path}
    assert pages_seen == {1, 2}
    # No fabricated page numbers: every chunk's page must be one that
    # actually exists in the source document's extracted pages.
    assert pages_seen.issubset({p.page_number for p in doc.pages})


def test_extract_corpus_chunks_tags_kt_code_from_page_headers_and_carries_it_forward():
    doc = _module_doc(
        "Module 99-Learner Guide.pdf",
        [
            "SECTION 1: KM-99-KT01: First Topic 60%\nThis page introduces the first topic with enough words.",
            "Still discussing the first topic here since no new header has appeared on this page yet.",
            "SECTION 2: KM-99-KT02: Second Topic 40%\nThis page moves on to the second topic entirely now.",
        ],
    )
    report = IngestionReport(base_dir="fake", documents=[doc])

    chunks = extract_corpus_chunks(report)
    by_page = {c["page"]: c["kt_code"] for c in chunks}

    assert by_page[1] == "KM-99-KT01"
    assert by_page[2] == "KM-99-KT01"  # carried forward, no new header on this page
    assert by_page[3] == "KM-99-KT02"


def test_extract_corpus_chunks_leaves_kt_code_none_for_non_module_documents():
    slide_doc = _module_doc(
        "slides/slides km 06/KT0601 - HTML5 Overview.pdf",
        ["This is a slide deck page with enough distinct words to form a chunk."],
    )
    report = IngestionReport(base_dir="fake", documents=[slide_doc])

    chunks = extract_corpus_chunks(report)

    assert all(c["kt_code"] is None for c in chunks)
