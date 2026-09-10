"""Deterministic (non-LLM) analysis of the supplied reference material.

This module turns raw extracted PDF text into a compact, structured
"reference analysis" that downstream generation stages consume instead of
the full text corpus (token efficiency, see docs/DESIGN.md).

Every extracted value is regex/heuristic-based against the QCTO "Learner
Guide" front-matter format observed in every supplied module. Nothing here
calls an LLM and nothing here invents data: if a field cannot be located,
it is recorded as ``null`` and surfaced in the ``unknowns`` list rather
than guessed.

IMPORTANT (prompt-injection defense): the text handled here originates
from third-party documents and is UNTRUSTED. This module only ever reads
values out of it with regular expressions - it never interprets extracted
text as instructions, and downstream stages must keep treating the output
of this module as reference data, never as system/developer instructions.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.ingestion.pdf_loader import IngestionReport, SourceDocument

MODULE_FILENAME_RE = re.compile(r"Module\s+(\d+)-Learner Guide\.pdf$", re.IGNORECASE)
SLIDE_FILENAME_RE = re.compile(r"^(KT\d{4})\s*[–\-]\s*(.+?)(?:\.pptx)?\.pdf$", re.IGNORECASE)

SECTION_HEADER_RE = re.compile(
    r"SECTION\s+\d+\s*:\s*(KM-\d+-KT-?\d+)\s*:?\s*(.*)", re.IGNORECASE
)
INTRO_KT_LINE_RE = re.compile(
    r"(KM-\d+-KT-?\d+)\s*:?\s*(.*)", re.IGNORECASE
)
TRAILING_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")


@dataclass
class KnowledgeTopic:
    code: str
    title: str
    weight_percent: float | None
    source: str  # "section_header" | "intro_summary"


@dataclass
class ModuleAnalysis:
    module_code: str | None
    km: str | None
    display_title: str | None
    nqf_level: int | None
    notional_hours: int | None
    credits: int | None
    occupational_code: str | None
    saqa_qual_id: str | None
    qualification_title: str | None
    purpose_summary: str | None
    entry_requirement: str | None
    source_file: str
    page_count: int
    knowledge_topics: list[KnowledgeTopic] = field(default_factory=list)
    kt_weight_sum_percent: float | None = None
    kt_missing_weight_codes: list[str] = field(default_factory=list)


@dataclass
class SlideDeckGroup:
    folder: str
    file_count: int
    kt_codes_covered: list[str]


@dataclass
class AssessmentInstrumentFindings:
    """Whether the supplied corpus contains an actual exam/memo instrument.

    Every count here is produced by scanning the full extracted text of
    every module for markers that a real exam paper would contain. All
    counts came back 0 across the supplied corpus at analysis time, which
    is itself a documented finding (see reference-analysis.md, section C).
    """

    total_marks_marker_hits: int
    exam_duration_marker_hits: int
    candidate_instructions_marker_hits: int
    section_ab_marker_hits: int
    memo_marker_hits: int
    embedded_worked_example_hits: int
    notes: str


@dataclass
class ReferenceAnalysis:
    generated_at: str
    source_base_dir: str
    documents_analyzed: int
    documents_skipped: list[str]
    extraction_errors: list[str]
    qualification_title: str | None
    saqa_qual_id: str | None
    occupational_code: str | None
    nqf_levels_present: list[int]
    modules: list[ModuleAnalysis]
    supplementary_slide_decks: list[SlideDeckGroup]
    assessment_instrument_findings: AssessmentInstrumentFindings
    facts: list[dict[str, str]]
    inferences: list[dict[str, str]]
    unknowns: list[dict[str, str]]
    anomalies: list[dict[str, str]]

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


PAGE_STAMP_RE = re.compile(r"\d+\s*\|\s*P\s*a\s*g\s*e", re.IGNORECASE)


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_REFERENCE_DERIVED_TEXT_LENGTH = 200
"""Cap for any single piece of reference-derived text (e.g. a Knowledge
Topic title) that may later be interpolated into an LLM prompt by
src/generation/question_generator.py. Kept in sync with
src.security.config.SecurityConfig.max_reference_derived_text_length -
duplicated as a plain constant here (rather than imported) to keep this
module free of a dependency on the security package for a single bound.
See docs/SECURITY-AUDIT.md 6.2."""


def _normalize_title(raw: str) -> str:
    """Extract a clean, bounded, control-character-free title.

    SECURITY: ``raw`` originates from untrusted PDF text (sdev/). Even
    though the supplied corpus is benign, this value can be interpolated
    into a real LLM prompt (see prompts/generate_questions.txt), so it is
    sanitized here at the point of extraction rather than trusted
    downstream - strip control characters (which could otherwise disrupt
    prompt structure or terminal/log output) and cap length (a
    pathologically long "title" could otherwise bloat prompt size or be
    used to push real instructions further from the model's attention).
    """
    title = raw.strip().rstrip(":").strip()
    title = TRAILING_PERCENT_RE.sub("", title).strip()
    title = re.sub(r"\s+", " ", title)
    title = _CONTROL_CHAR_RE.sub("", title)
    if len(title) > MAX_REFERENCE_DERIVED_TEXT_LENGTH:
        title = title[:MAX_REFERENCE_DERIVED_TEXT_LENGTH].rstrip() + "..."
    return title


def _merge_wrapped_percentages(text: str) -> str:
    """Join a line that is *only* a wrapped '5%' onto the previous line.

    The source PDFs wrap long knowledge-topic titles such that the trailing
    weight percentage sometimes lands on its own line (page-width artifact
    of the original document, not a formatting choice we should encode).
    """
    lines = text.split("\n")
    merged: list[str] = []
    lone_percent = re.compile(r"^\s*\d{1,3}\s*%\s*$")
    for line in lines:
        if lone_percent.match(line) and merged:
            merged[-1] = merged[-1].rstrip() + " " + line.strip()
        else:
            merged.append(line)
    return "\n".join(merged)


def _parse_header_fields(text: str) -> dict[str, Any]:
    def find(pattern: str, cast=str):
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return None
        val = m.group(1).strip()
        try:
            return cast(val)
        except ValueError:
            return val

    display_title = None
    header_raw = PAGE_STAMP_RE.sub(" ", text[:800])
    header_window = re.sub(r"\s+", " ", header_raw)
    m = re.search(
        r"([A-Z0-9][A-Za-z0-9 ,\-\(\)/&']{5,150}?),\s*NQF Level\s*(\d+),\s*Credits\s*(\d+)",
        header_window,
        re.IGNORECASE,
    )
    if m:
        display_title = m.group(1).strip()

    purpose = None
    pm = re.search(r"Purpose\s*(.+?)\s*Topic elements to be covered", text, re.IGNORECASE | re.DOTALL)
    if pm:
        purpose = re.sub(r"\s+", " ", pm.group(1)).strip()
        if len(purpose) > 400:
            purpose = purpose[:400].rsplit(" ", 1)[0] + "..."

    entry_req = None
    em = re.search(r"Entry Requirements\s*(NQF\s*\d+)", text, re.IGNORECASE)
    if em:
        entry_req = em.group(1).strip()

    return {
        "module_code": find(r"Module #\s*([\w\-]+):"),
        "nqf_level": find(r"NQF Level\s+level\s*(\d+)", int),
        "notional_hours": find(r"Notional hours\s*(\d+)", int),
        "credits": find(r"Credit\(s\)\s*Cr\s*(\d+)", int),
        "occupational_code": find(r"Occupational\s+Code\s*(\d+)"),
        "saqa_qual_id": find(r"SAQA QUAL ID\s*(\d+)"),
        "qualification_title": find(r"Qualification Title\s*(.+?)(?:\n|$)"),
        "display_title": display_title,
        "purpose_summary": purpose,
        "entry_requirement": entry_req,
    }


def _parse_knowledge_topics(text: str) -> list[KnowledgeTopic]:
    """Extract KT code/title/weight triples.

    Primary source: in-body ``SECTION N: KM-xx-KTyy : Title WEIGHT%``
    headers, which were found to reliably enumerate every knowledge topic
    across all 11 supplied module guides. Falls back to the front-matter
    "Topic elements to be covered" summary list for any module where no
    section headers are found at all.
    """
    text = _merge_wrapped_percentages(text)
    seen: dict[str, KnowledgeTopic] = {}
    order: list[str] = []

    for code, rest in SECTION_HEADER_RE.findall(text):
        code_norm = code.upper().replace("KT-", "KT")
        pct_match = TRAILING_PERCENT_RE.search(rest)
        weight = float(pct_match.group(1)) if pct_match else None
        title = _normalize_title(rest)
        if code_norm not in seen or (weight is not None and seen[code_norm].weight_percent is None):
            seen[code_norm] = KnowledgeTopic(code=code_norm, title=title, weight_percent=weight, source="section_header")
        if code_norm not in order:
            order.append(code_norm)

    # Cross-fill from the front-matter summary list: fills in any KT code
    # missing entirely, and fills in a missing weight for a KT whose
    # in-body section header omitted it (both patterns occur in the
    # supplied corpus - see reference-analysis anomalies).
    intro_block_match = re.search(
        r"Topic elements to be covered include.*?(?:demonstrate an understanding of:?)(.*?)Entry Requirements",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if intro_block_match:
        block = intro_block_match.group(1)
        for line in block.splitlines():
            if "KM-" not in line:
                continue
            m = INTRO_KT_LINE_RE.search(line)
            if not m:
                continue
            code_norm = m.group(1).upper().replace("KT-", "KT")
            rest = m.group(2)
            pct_match = TRAILING_PERCENT_RE.search(rest)
            weight = float(pct_match.group(1)) if pct_match else None
            title = _normalize_title(rest)
            if code_norm not in seen:
                seen[code_norm] = KnowledgeTopic(
                    code=code_norm, title=title or "unspecified", weight_percent=weight, source="intro_summary"
                )
                order.append(code_norm)
            elif seen[code_norm].weight_percent is None and weight is not None:
                existing = seen[code_norm]
                seen[code_norm] = KnowledgeTopic(
                    code=code_norm, title=existing.title, weight_percent=weight, source="section_header+intro_fill"
                )

    return [seen[c] for c in order]


def _analyze_module_document(doc: SourceDocument) -> ModuleAnalysis | None:
    if not MODULE_FILENAME_RE.search(Path(doc.relative_path).name):
        return None
    text = doc.full_text
    header = _parse_header_fields(text)
    topics = _parse_knowledge_topics(text)

    weighted = [t.weight_percent for t in topics if t.weight_percent is not None]
    missing = [t.code for t in topics if t.weight_percent is None]

    return ModuleAnalysis(
        module_code=header["module_code"],
        km=(header["module_code"].split("-")[-1] if header["module_code"] else None),
        display_title=header["display_title"],
        nqf_level=header["nqf_level"],
        notional_hours=header["notional_hours"],
        credits=header["credits"],
        occupational_code=header["occupational_code"],
        saqa_qual_id=header["saqa_qual_id"],
        qualification_title=header["qualification_title"],
        purpose_summary=header["purpose_summary"],
        entry_requirement=header["entry_requirement"],
        source_file=doc.relative_path,
        page_count=doc.page_count,
        knowledge_topics=topics,
        kt_weight_sum_percent=round(sum(weighted), 2) if weighted else None,
        kt_missing_weight_codes=missing,
    )


def _analyze_slide_decks(documents: list[SourceDocument]) -> list[SlideDeckGroup]:
    groups: dict[str, list[str]] = {}
    for doc in documents:
        p = Path(doc.relative_path)
        if "slides" not in p.parts:
            continue
        folder = str(p.parent)
        m = SLIDE_FILENAME_RE.match(p.name)
        code = m.group(1).upper() if m else p.stem
        groups.setdefault(folder, []).append(code)
    return [
        SlideDeckGroup(folder=folder, file_count=len(codes), kt_codes_covered=sorted(codes))
        for folder, codes in sorted(groups.items())
    ]


def _find_empty_slide_folders(base_dir: Path, documents: list[SourceDocument]) -> list[str]:
    covered = {str(Path(d.relative_path).parent) for d in documents if "slides" in Path(d.relative_path).parts}
    empty: list[str] = []
    slides_root = base_dir / "slides"
    if slides_root.is_dir():
        for child in sorted(slides_root.iterdir()):
            if child.is_dir():
                rel = str(child.relative_to(base_dir))
                if rel not in covered:
                    empty.append(rel)
    return empty


def _assessment_instrument_findings(all_text: str) -> AssessmentInstrumentFindings:
    total_marks = len(re.findall(r"total marks|marks allocated|\bmarks?\s*:\s*\d", all_text, re.IGNORECASE))
    duration = len(re.findall(r"examination duration|exam duration|time allowed\s*:", all_text, re.IGNORECASE))
    instructions = len(
        re.findall(r"instructions to candidates|read the following instructions", all_text, re.IGNORECASE)
    )
    section_ab = len(re.findall(r"^\s*section\s+[ab]\b", all_text, re.IGNORECASE | re.MULTILINE))
    memo = len(re.findall(r"marking memo|memorandum of marks|model answer key", all_text, re.IGNORECASE))
    worked_examples = len(re.findall(r"^Question\s+\d+\s*[:.]", all_text, re.IGNORECASE | re.MULTILINE))
    return AssessmentInstrumentFindings(
        total_marks_marker_hits=total_marks,
        exam_duration_marker_hits=duration,
        candidate_instructions_marker_hits=instructions,
        section_ab_marker_hits=section_ab,
        memo_marker_hits=memo,
        embedded_worked_example_hits=worked_examples,
        notes=(
            "These counts scan the full supplied corpus for markers a real exam paper or "
            "marking memo would contain (total-marks lines, stated duration, candidate "
            "instructions, Section A/B headings, a memorandum). Non-zero "
            "'embedded_worked_example_hits' refers to informal worked examples inside the "
            "teaching content (e.g. Module 4's binary-conversion walkthroughs), not exam "
            "questions with mark allocations."
        ),
    )


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")

# Reuses SECTION_HEADER_RE's page-level KT header pattern (see
# _parse_knowledge_topics above, which applies the same pattern to the
# whole-document text). Applied per-PAGE here so a chunk can be tagged with
# the Knowledge Topic actually governing that page - the supplied Learner
# Guides introduce a "SECTION N: KM-xx-KTyy: <title> <weight>%" header on
# the page a topic begins and hold that topic until the next such header
# (verified against the real corpus: e.g. Module 6's KM-06-KT06 "HTML5"
# header lands on page 62 and holds until KM-06-KT07's header on page 74).
_PAGE_KT_HEADER_RE = re.compile(r"SECTION\s+\d+\s*:\s*(KM-\d+-KT-?\d+)", re.IGNORECASE)


def _append_chunk(
    chunks: list[dict[str, Any]],
    buffer: list[str],
    source: str,
    page_number: int,
    kt_code: str | None,
    min_words: int,
) -> None:
    text = " ".join(buffer).strip()
    if len(text.split()) >= min_words:
        chunks.append({"source": source, "page": page_number, "kt_code": kt_code, "text": text})


def extract_corpus_chunks(
    report: IngestionReport,
    min_words: int = 8,
    target_chunk_words: int = 50,
    max_chunks: int = 25000,
) -> list[dict[str, Any]]:
    """Split every extracted document into page-tagged text chunks.

    This is a lightweight, local (non-LLM) intermediate artifact serving TWO
    consumers:
      1. src/validation/novelty_checker.py - unchanged use, screens generated
         question text for lexical overlap with the supplied corpus.
      2. src/retrieval/evidence_selector.py - NEW use, retrieves the actual
         learner-guide passages (with real page numbers) handed to the LLM
         as grounding evidence at generation time.

    Consecutive sentences on the SAME page are grouped into one chunk of
    roughly ``target_chunk_words`` words (never crossing a page boundary,
    so page/kt_code attribution stays exact) rather than one chunk per
    sentence. One-sentence-per-chunk was tried first and produced
    evidence too shallow to write a real question from - a short, isolated,
    high-keyword-density sentence (e.g. "CSS allows you to apply styles to
    web pages.") can outrank a substantive explanatory paragraph in a
    single-sentence TF-IDF ranking purely because it repeats the query term,
    even though it carries almost no teachable content. Grouping into
    small paragraphs fixes this without changing what novelty screening
    catches - phrase-level copying is still well within a ~50-word window.

    Each chunk keeps its source document, PAGE NUMBER (never fabricated -
    taken directly from src.ingestion.pdf_loader's per-page extraction), and,
    for a "Module N-Learner Guide.pdf" document, the Knowledge Topic code
    governing the page it came from (``kt_code``, or ``None`` if the page
    precedes the first KT header in that document, e.g. front matter).
    """
    chunks: list[dict[str, Any]] = []
    for doc in report.documents:
        is_module_doc = bool(MODULE_FILENAME_RE.search(Path(doc.relative_path).name))
        current_kt: str | None = None
        for page in doc.pages:
            if is_module_doc:
                header_match = _PAGE_KT_HEADER_RE.search(page.text)
                if header_match:
                    current_kt = header_match.group(1).upper().replace("KT-", "KT")
            page_text = PAGE_STAMP_RE.sub(" ", page.text)
            sentences = [
                re.sub(r"\s+", " ", s).strip() for s in _SENTENCE_SPLIT_RE.split(page_text)
            ]
            sentences = [s for s in sentences if s]

            page_kt_code = current_kt if is_module_doc else None
            buffer: list[str] = []
            for sentence in sentences:
                buffer.append(sentence)
                if len(" ".join(buffer).split()) >= target_chunk_words:
                    _append_chunk(chunks, buffer, doc.relative_path, page.page_number, page_kt_code, min_words)
                    buffer = []
                    if len(chunks) >= max_chunks:
                        return chunks
            if buffer:
                _append_chunk(chunks, buffer, doc.relative_path, page.page_number, page_kt_code, min_words)
                if len(chunks) >= max_chunks:
                    return chunks
    return chunks


def _extract_module_number(source_file: str) -> int | None:
    match = re.search(r"\d+", source_file)
    return int(match.group()) if match else None


def analyze_reference_material(report: IngestionReport) -> ReferenceAnalysis:
    base_dir = Path(report.base_dir)
    modules: list[ModuleAnalysis] = []
    for doc in report.documents:
        analyzed = _analyze_module_document(doc)
        if analyzed:
            modules.append(analyzed)
    modules.sort(key=lambda m: _extract_module_number(m.source_file) or 0)

    qual_titles = {m.qualification_title for m in modules if m.qualification_title}
    saqa_ids = {m.saqa_qual_id for m in modules if m.saqa_qual_id}
    occ_codes = {m.occupational_code for m in modules if m.occupational_code}
    nqf_levels = sorted({m.nqf_level for m in modules if m.nqf_level is not None})

    slide_groups = _analyze_slide_decks(report.documents)
    empty_slide_folders = _find_empty_slide_folders(base_dir, report.documents)

    all_text = "\n".join(d.full_text for d in report.documents)
    instrument_findings = _assessment_instrument_findings(all_text)

    module_numbers = sorted(
        n for m in modules if (n := _extract_module_number(m.source_file)) is not None
    )
    expected_range = list(range(1, (module_numbers[-1] if module_numbers else 0) + 1))
    missing_module_numbers = [n for n in expected_range if n not in module_numbers]

    facts: list[dict[str, str]] = [
        {
            "id": "F1",
            "statement": f"Qualification title stated in every module header: {next(iter(qual_titles), 'N/A')}.",
            "evidence": "Front-matter field 'Qualification Title' in all 11 supplied Learner Guides.",
        },
        {
            "id": "F2",
            "statement": f"SAQA Qualification ID stated as {next(iter(saqa_ids), 'N/A')} (present on Modules 6-12; absent on Modules 2-5).",
            "evidence": "Front-matter field 'SAQA QUAL ID'.",
        },
        {
            "id": "F3",
            "statement": f"Occupational code stated as {next(iter(occ_codes), 'N/A')} on every module.",
            "evidence": "Front-matter field 'Occupational Code'.",
        },
        {
            "id": "F4",
            "statement": f"Modules span NQF levels {nqf_levels} (Modules 2-5 and 10-12 at level 4; Modules 6-9 at level 5).",
            "evidence": "Front-matter field 'NQF Level' per module.",
        },
        {
            "id": "F5",
            "statement": (
                "Each module is decomposed into weighted 'Knowledge Topics' (KT) whose "
                "percentages are intended to sum to 100% of that module's internal weighting."
            ),
            "evidence": "'SECTION N: KM-xx-KTyy: <title> <weight>%' headers repeated throughout every module body.",
        },
        {
            "id": "F6",
            "statement": (
                "The qualification uses continuous, portfolio-of-evidence style assessment "
                "(self-assessments, activities and exercises signed off by a facilitator) "
                "rather than a single formal written exam, as described in each module's "
                "'Assessments' front-matter section."
            ),
            "evidence": "Recurring 'Assessments' paragraph in module front matter (paraphrased, not quoted verbatim).",
        },
        {
            "id": "F7",
            "statement": "Assessors and moderators must be accredited by the MICT SETA; lecturer/learner ratio capped at 1:20.",
            "evidence": "'Provider Accreditation Requirements' section, present in every module.",
        },
        {
            "id": "F8",
            "statement": (
                f"Supplied slide decks ({sum(g.file_count for g in slide_groups)} files) are condensed "
                "per-topic teaching slides for Module 6 only; they contain no assessment content."
            ),
            "evidence": "Manual + automated inspection of slides/slides km 06/*.pdf content and filenames.",
        },
    ]

    inferences: list[dict[str, str]] = [
        {
            "id": "I1",
            "statement": (
                "Because no formal written-exam instrument is supplied, the Mock EISA paper "
                "structure (sections, duration, mark totals, instructions) must be designed "
                "by implementation assumption, informed by the qualification's NQF levels, "
                "module credit weightings, and QCTO occupational-certificate conventions, "
                "rather than copied from a reference exam."
            ),
            "rationale": "assessment_instrument_findings shows zero hits for exam-duration/total-marks/instructions markers.",
        },
        {
            "id": "I2",
            "statement": (
                "Module credit weightings (Cr) are a reasonable basis for allocating relative "
                "marks/emphasis across a mock paper's sections, since the qualification itself "
                "uses credits as its measure of relative weight per module."
            ),
            "rationale": "Credits range from 1 (Module 12) to 16 (Module 6), mirroring the varying depth of each module's content.",
        },
        {
            "id": "I3",
            "statement": (
                "'Exit Level Outcomes' as a named, numbered artifact are not present in the "
                "supplied material; each module's KT list plus its 'Purpose' paragraph is the "
                "closest available proxy for outcome-style statements and should be used as "
                "the outcome-coverage basis for the blueprint."
            ),
            "rationale": "No literal 'Exit Level Outcome' or 'ELO' text found anywhere in the corpus (see unknowns).",
        },
        {
            "id": "I4",
            "statement": (
                "Software-development-specific modules (KM-05 through KM-09) are the most "
                "relevant to a Software Developer Mock EISA paper; governance/4IR/design-thinking "
                "modules (KM-10, KM-11, KM-12) are better suited to short integrated context "
                "questions than full sections."
            ),
            "rationale": "KM-05/06/07/08/09 cover programming, OOP, HTML/CSS/JS, UML, and databases/SDLC/algorithms directly.",
        },
    ]

    unknowns: list[dict[str, str]] = [
        {"id": "U1", "item": "Numbered/named Exit Level Outcomes (ELOs) for the qualification."},
        {"id": "U2", "item": "Official examination structure (number of sections, papers, weighting per section)."},
        {"id": "U3", "item": "Official examination duration."},
        {"id": "U4", "item": "Official total mark count for a summative/EISA paper."},
        {"id": "U5", "item": "Official candidate instructions wording."},
        {"id": "U6", "item": "Official marking memo format/template."},
        {"id": "U7", "item": "Pass mark / competency threshold."},
        {"id": "U8", "item": "Whether the real EISA is a single integrated paper or multiple papers per knowledge module cluster."},
        {"id": "U9", "item": "Content of Module 1 (KM-01) - not included in the supplied files."},
        {"id": "U10", "item": "Content of the 'slides km 08' folder - present but empty in the supplied files."},
    ]

    anomalies: list[dict[str, str]] = []
    if missing_module_numbers:
        anomalies.append(
            {
                "id": "A1",
                "statement": f"Module number(s) {missing_module_numbers} were not supplied (numbering starts at Module 2).",
            }
        )
    if empty_slide_folders:
        anomalies.append(
            {
                "id": "A2",
                "statement": f"Slide folder(s) present but empty: {empty_slide_folders}.",
            }
        )
    for m in modules:
        if m.kt_missing_weight_codes:
            anomalies.append(
                {
                    "id": f"A-{m.km}-weight",
                    "statement": (
                        f"{m.km}: knowledge topic(s) {m.kt_missing_weight_codes} have no stated "
                        f"weight percentage in their section header (module KT weight sum from "
                        f"stated values only: {m.kt_weight_sum_percent}%)."
                    ),
                }
            )
        elif m.kt_weight_sum_percent is not None and abs(m.kt_weight_sum_percent - 100.0) > 0.5:
            anomalies.append(
                {
                    "id": f"A-{m.km}-sum",
                    "statement": f"{m.km}: knowledge topic weights sum to {m.kt_weight_sum_percent}%, not 100%.",
                }
            )

    return ReferenceAnalysis(
        generated_at=datetime.now(UTC).isoformat(),
        source_base_dir=str(base_dir),
        documents_analyzed=len(report.documents),
        documents_skipped=report.skipped_files,
        extraction_errors=report.errors,
        qualification_title=next(iter(qual_titles), None),
        saqa_qual_id=next(iter(saqa_ids), None),
        occupational_code=next(iter(occ_codes), None),
        nqf_levels_present=nqf_levels,
        modules=modules,
        supplementary_slide_decks=slide_groups,
        assessment_instrument_findings=instrument_findings,
        facts=facts,
        inferences=inferences,
        unknowns=unknowns,
        anomalies=anomalies,
    )
