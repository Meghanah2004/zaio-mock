from __future__ import annotations

from src.analysis.reference_analyzer import (
    _parse_header_fields,
    _parse_knowledge_topics,
)

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
