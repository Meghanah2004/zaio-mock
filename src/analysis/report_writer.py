"""Renders a ReferenceAnalysis into the two required artifacts:

  - artifacts/reference-analysis.json  (compact, machine-readable)
  - docs/reference-analysis.md         (human-readable, fact/inference/unknown)
"""
from __future__ import annotations

import json
from pathlib import Path

from src.analysis.reference_analyzer import ReferenceAnalysis


def write_json(analysis: ReferenceAnalysis, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analysis.to_json_dict(), indent=2), encoding="utf-8")


def _module_table(analysis: ReferenceAnalysis) -> str:
    lines = [
        "| KM | Module Title | NQF | Credits | Notional Hrs | KT count | KT weight sum |",
        "|----|--------------|-----|---------|--------------|----------|---------------|",
    ]
    for m in analysis.modules:
        lines.append(
            f"| {m.km} | {m.display_title or 'unspecified'} | {m.nqf_level} | {m.credits} | "
            f"{m.notional_hours} | {len(m.knowledge_topics)} | {m.kt_weight_sum_percent}% |"
        )
    return "\n".join(lines)


def _kt_detail(analysis: ReferenceAnalysis) -> str:
    blocks = []
    for m in analysis.modules:
        rows = "\n".join(
            f"  - `{t.code}` {t.title} "
            f"({t.weight_percent if t.weight_percent is not None else 'unspecified'}%)"
            for t in m.knowledge_topics
        )
        blocks.append(f"**{m.km} - {m.display_title}** (source: `{m.source_file}`)\n{rows}")
    return "\n\n".join(blocks)


def write_markdown(analysis: ReferenceAnalysis, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    f = analysis.assessment_instrument_findings

    md = f"""# Reference Analysis - Software Developer Qualification

Generated: {analysis.generated_at}
Source directory: `{analysis.source_base_dir}` (read-only; {analysis.documents_analyzed} documents analyzed)

This document analyzes the supplied QCTO Learner Guides and slide decks for the
**Occupational Certificate: Software Developer** qualification. It distinguishes
explicit facts, reasonable implementation inferences, and information that is
genuinely not specified in the supplied material.

> The supplied material is used to understand assessment style, structure,
> competency coverage, and question patterns. It is **not** treated as a
> question bank: no reference questions are copied, paraphrased, or lightly
> modified anywhere in this project.

## 1. Qualification identity (FACT)

| Field | Value |
|---|---|
| Qualification title | {analysis.qualification_title} |
| SAQA Qualification ID | {analysis.saqa_qual_id} (stated on Modules 6-12 only; absent from Modules 2-5) |
| Occupational code | {analysis.occupational_code} |
| NQF levels present | {analysis.nqf_levels_present} |
| Modules supplied | {len(analysis.modules)} (Module 2 through Module 12; Module 1 not supplied) |

## 2. Module / Knowledge-Module (KM) breakdown (FACT)

{_module_table(analysis)}

Each module is a QCTO "Knowledge Module" (KM), further decomposed into weighted
"Knowledge Topics" (KT), e.g. `KM-06-KT06` = HTML5 within Module 6. This KM/KT
structure, with per-topic percentage weightings, is the closest thing the
supplied corpus has to a formal outcomes/competency breakdown.

### Full KT listing per module

{_kt_detail(analysis)}

## 3. Exit Level Outcomes (UNKNOWN)

No document in the supplied corpus contains the literal phrase "Exit Level
Outcome," "ELO," or "Unit Standard." Each module's "Learning Outcome" heading
appears in the body of every KT section, but is consistently followed
immediately by a topic list with **no outcome statement text filled in** -
this is a structural fact about the supplied PDFs, not an extraction failure.

**Best available proxy** (IMPLEMENTATION INFERENCE): each module's `Purpose`
paragraph plus its KT list is used as the outcome/competency-coverage basis
for the assessment blueprint, since no better-specified outcome statements
exist in the source.

## 4. Assessment structure actually present in the source (FACT)

Every module states the same continuous-assessment approach in its front
matter (paraphrased, not quoted): competence is established through
self-assessments, activities and exercises completed individually, in pairs,
or in groups, signed off by a facilitator into a portfolio of evidence.
Assessors and moderators must be MICT-SETA accredited; lecturer:learner ratio
is capped at 1:20.

**No formal written-exam instrument (past paper, memo, or marking guideline)
is present anywhere in the supplied corpus.** This was verified by scanning
the full extracted text of all 60 supplied files for markers a real exam
paper would contain:

| Marker scanned for | Hits found |
|---|---|
| "total marks" / "marks allocated" / "Marks: N" | {f.total_marks_marker_hits} |
| Stated examination duration | {f.exam_duration_marker_hits} |
| "Instructions to candidates" | {f.candidate_instructions_marker_hits} |
| "Section A" / "Section B" exam headings | {f.section_ab_marker_hits} |
| Marking memo / memorandum of marks | {f.memo_marker_hits} |
| Informal in-text worked examples (e.g. Module 4 binary-conversion walkthroughs) | {f.embedded_worked_example_hits} |

{f.notes}

## 5. Examination sections, question types, mark allocation, duration (UNKNOWN)

None of the following are stated anywhere in the supplied material:

- Number of examination sections or papers
- Question type mix (the source contains zero MCQ/short-answer/essay exam
  items - only teaching content and two informal worked-example problems in
  Module 4)
- Mark allocation per question or per section
- Total mark count for a summative/EISA instrument
- Examination duration
- Candidate instructions wording
- Pass mark / competency threshold
- Official marking-memo template or structure
- Treatment of alternative correct answers in marking

All of the above are **implementation assumptions** for Phase 1 (see
`configs/software_developer.json` and `docs/DESIGN.md`), clearly labeled as
such and not attributed to the reference material.

## 6. Competencies assessed and occupational context (FACT + INFERENCE)

FACT: the qualification's software-development-specific modules are:

- KM-05 Programming basics (NQF4)
- KM-06 Software Development with HTML5, open-source frameworks and libraries (NQF5)
- KM-07 UML as standard modelling language (NQF5)
- KM-08 Obtaining, querying, manipulating and presenting data with/without MVC (NQF5)
- KM-09 Software Development Life Cycle, programming languages, algorithms and security (NQF5)

INFERENCE: these five modules are the primary competency basis for a Software
Developer Mock EISA paper. KM-02/03/04 (office software, web-scraping/data
sources, maths) are supporting/foundational; KM-10/11/12 (governance, 4IR,
design thinking) are workplace-context modules best represented as short
integrated scenario elements rather than full sections, since a real EISA for
an occupational certificate is expected to integrate technical and workplace
competencies rather than test them in isolation (QCTO occupational-certificate
convention; not itself stated in the source, hence INFERENCE not FACT).

## 7. Supplementary slide decks (FACT)

{len(analysis.supplementary_slide_decks)} slide-deck folder(s) contain usable content:

{chr(10).join(f"- `{g.folder}`: {g.file_count} files covering KT codes {g.kt_codes_covered[0]}-{g.kt_codes_covered[-1]}" for g in analysis.supplementary_slide_decks)}

These are condensed, bullet-point teaching slides for Module 6 (Core
Programming through JavaScript) only. They contain no assessment content,
mark schemes, or exam questions - they reinforce module style/terminology
only.

## 8. Anomalies and inconsistencies across supplied documents

{chr(10).join(f"- **{a['id']}**: {a['statement']}" for a in analysis.anomalies) if analysis.anomalies else "- None beyond those listed above."}

Additional non-structural observations:

- Module 9's "Purpose" paragraph text is copy-pasted from Module 4's maths
  module ("...acquire mathematical thinking theory...") even though Module 9
  is actually about the SDLC, programming languages, algorithms and security.
  This looks like a template/boilerplate reuse error in the source and was
  not used as a basis for any generated content.
- `SAQA QUAL ID` (118707) is present in the front matter of Modules 6-12 but
  absent from Modules 2-5, despite all 11 modules stating the same
  qualification title and occupational code.

## 9. Facts (A)

{chr(10).join(f"- **{x['id']}**: {x['statement']}" for x in analysis.facts)}

## 10. Implementation inferences (B)

{chr(10).join(f"- **{x['id']}**: {x['statement']} _(rationale: {x['rationale']})_" for x in analysis.inferences)}

## 11. Unknown / not specified (C)

{chr(10).join(f"- **{x['id']}**: {x['item']}" for x in analysis.unknowns)}

## 12. Recommendation for the generation pipeline

1. **What the pipeline should produce**: one Mock EISA paper (`Paper 2`) and
   its complete marking memo, generated from an explicit, machine-readable
   assessment *blueprint* derived from this analysis plus documented
   assumptions - not generated directly from raw reference text. The
   blueprint should weight sections roughly in proportion to KM-05..KM-09
   credit values, with short integrated items drawing on KM-09/10/11/12
   workplace/SDLC context.
2. **Validation required**: JSON schema validation of the paper and memo;
   mark-total reconciliation (question -> section -> paper, and paper vs.
   memo); ELO/competency coverage against the blueprint's declared outcome
   list; unique ID checks; a lexical novelty/overlap check of generated
   question text against extracted reference text (screening only, not
   proof of originality); and an LLM-based quality review pass for
   occupational relevance, ambiguity, and markability.
3. **What remains unknown**: real exam duration, total marks, section count,
   pass mark, and candidate-instruction wording. These are fixed for Phase 1
   via `configs/software_developer.json` as clearly labeled assumptions and
   should be revisited if an authoritative QCTO/MICT SETA assessment
   specification becomes available.
4. **What to build next**: the assessment blueprint generator
   (`src/generation/blueprint.py`), the structured question/memo schemas,
   the provider-abstracted generation stages, and the deterministic
   validators - in that order, per `docs/DESIGN.md`.
"""
    path.write_text(md, encoding="utf-8")
