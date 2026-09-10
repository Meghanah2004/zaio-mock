"""Renders the paper and memo JSON into human-readable Markdown."""
from __future__ import annotations

from typing import Any


def render_paper_markdown(paper: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# {paper['qualification']}")
    lines.append("")
    lines.append(f"## {paper['paper_id']}")
    lines.append("")
    lines.append(f"> **{paper['status_disclaimer']}**")
    lines.append("")
    nqf = paper["nqf_level"]
    nqf_display = ", ".join(str(n) for n in nqf) if isinstance(nqf, list) else str(nqf)
    lines.append(f"- **NQF Level:** {nqf_display}")
    lines.append(f"- **Duration:** {paper['duration_minutes']} minutes")
    lines.append(f"- **Total Marks:** {paper['total_marks']}")
    lines.append("")
    lines.append("## Instructions to Candidates")
    lines.append("")
    for instr in paper["instructions"]:
        lines.append(f"1. {instr}")
    lines.append("")

    for section in paper["sections"]:
        lines.append(f"## Section {section['id']}: {section['title']} ({section['marks']} marks)")
        lines.append("")
        for q in section["questions"]:
            lines.append(f"### Question {q['question_number']} ({q['marks']} marks)")
            lines.append("")
            if q.get("scenario"):
                lines.append(f"*Scenario:* {q['scenario']}")
                lines.append("")
            lines.append(q["question"])
            lines.append("")
            for sq in q.get("sub_questions", []):
                lines.append(f"**({sq['id']})** {sq['prompt']} *[{sq['marks']} marks]*")
                lines.append("")
    return "\n".join(lines)


def render_memo_markdown(memo: dict[str, Any], paper: dict[str, Any] | None = None) -> str:
    question_lookup: dict[str, dict[str, Any]] = {}
    section_titles: dict[str, str] = {}
    if paper is not None:
        for section in paper["sections"]:
            section_titles[section["id"]] = section["title"]
            for q in section["questions"]:
                question_lookup[q["id"]] = q

    lines: list[str] = []
    lines.append(f"# Marking Memo - {memo['paper_id']}")
    lines.append("")
    lines.append(f"> **{memo['status_disclaimer']}**")
    lines.append("")
    lines.append(f"- **Total Marks:** {memo['total_marks']}")
    lines.append("")

    for section in memo["sections"]:
        title = section_titles.get(section["id"], section["id"])
        lines.append(f"## Section {section['id']}: {title}")
        lines.append("")
        for mq in section["questions"]:
            q = question_lookup.get(mq["question_id"])
            qnum = q["question_number"] if q else mq["question_id"]
            lines.append(f"### Question {qnum} ({mq['total_marks']} marks)")
            lines.append("")

            grounding = q.get("grounding") if q else None
            if grounding:
                lines.append("*Source grounding (assessor reference only):*")
                for g in grounding:
                    lines.append(f"- {g['document']}, page {g['page']} - {g['reason']}")
                lines.append("")

            if mq.get("sub_questions"):
                for msq in mq["sub_questions"]:
                    lines.append(f"**({msq['id']}) - {msq['total_marks']} marks**")
                    lines.append("")
                    lines.append(f"*Model answer:* {msq['model_answer']}")
                    lines.append("")
                    lines.append("Criteria:")
                    for c in msq["criteria"]:
                        lines.append(f"- {c['description']} ({c['marks']} mark(s))")
                    if msq.get("accepted_alternatives"):
                        lines.append("")
                        lines.append("Accepted alternatives:")
                        for alt in msq["accepted_alternatives"]:
                            lines.append(f"- {alt}")
                    lines.append("")
            else:
                lines.append(f"*Model answer:* {mq['model_answer']}")
                lines.append("")
                lines.append("Criteria:")
                for c in mq["criteria"]:
                    non_award = f" (does NOT earn marks: {c['non_awarding_notes']})" if c.get("non_awarding_notes") else ""
                    lines.append(f"- {c['description']} ({c['marks']} mark(s)){non_award}")
                if mq.get("accepted_alternatives"):
                    lines.append("")
                    lines.append("Accepted alternatives:")
                    for alt in mq["accepted_alternatives"]:
                        lines.append(f"- {alt}")
                if mq.get("partial_credit_guidance"):
                    lines.append("")
                    lines.append(f"*Partial credit guidance:* {mq['partial_credit_guidance']}")
                if mq.get("penalties"):
                    lines.append("")
                    lines.append(f"*Penalties:* {mq['penalties']}")
                lines.append("")
    return "\n".join(lines)
