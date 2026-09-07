"""Best-effort Markdown -> PDF rendering using reportlab.

PDF output is optional per the project spec ("do not make PDF the only
output"). If reportlab is not installed, render_markdown_to_pdf raises a
clear, caught-by-the-CLI error rather than crashing the whole pipeline -
the JSON and Markdown artifacts are always produced regardless of whether
PDF rendering succeeds.
"""
from __future__ import annotations

import re
from pathlib import Path

try:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        ListFlowable,
        ListItem,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    _REPORTLAB_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REPORTLAB_AVAILABLE = False


class PdfRenderingUnavailable(RuntimeError):
    pass


def _xml_escape(text: str) -> str:
    """Escape the 3 characters that are structurally significant to
    reportlab's mini-XML parser. Deliberately a plain string substitution,
    not a call into the ``xml`` parsing package (there is nothing to parse
    here - only text to escape - so a hand-rolled substitution avoids
    pulling in XML-parser-shaped machinery, and its associated XXE-class
    static-analysis noise, for a job that is not parsing).
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_inline_markup(text: str) -> str:
    """Render a line of paper/memo text as safe reportlab mini-XML.

    SECURITY: reportlab's ``Paragraph`` parses a mini-XML/HTML-like markup
    language. Text here ultimately originates from LLM/provider output
    (validated, but still free-form prose/code snippets) and must never be
    passed to ``Paragraph`` unescaped - verified empirically that
    unescaped ``<``/``&`` can either crash rendering (an unterminated
    tag-like substring raises ``ValueError`` inside reportlab's parser) or
    be silently interpreted as markup. Escaping FIRST, then applying our
    own controlled ``**bold**`` -> ``<b>...</b>`` substitution on the
    escaped string, guarantees the only real tags reportlab ever sees are
    ones this function inserted itself - see docs/SECURITY-AUDIT.md 6.1.
    """
    escaped = _xml_escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def render_markdown_to_pdf(markdown_text: str, output_path: Path) -> None:
    if not _REPORTLAB_AVAILABLE:
        raise PdfRenderingUnavailable(
            "reportlab is not installed; skipping PDF rendering. Run: pip install reportlab"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    quote_style = ParagraphStyle("Quote", parent=styles["BodyText"], leftIndent=10, textColor=HexColor("#444444"))

    story = []
    bullet_buffer: list[str] = []

    def flush_bullets():
        if bullet_buffer:
            items = [ListItem(Paragraph(_safe_inline_markup(b), styles["BodyText"])) for b in bullet_buffer]
            story.append(ListFlowable(items, bulletType="bullet"))
            story.append(Spacer(1, 4))
            bullet_buffer.clear()

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            flush_bullets()
            story.append(Spacer(1, 4))
            continue
        if line.startswith("### "):
            flush_bullets()
            story.append(Paragraph(_safe_inline_markup(line[4:]), styles["Heading3"]))
        elif line.startswith("## "):
            flush_bullets()
            story.append(Paragraph(_safe_inline_markup(line[3:]), styles["Heading2"]))
        elif line.startswith("# "):
            flush_bullets()
            story.append(Paragraph(_safe_inline_markup(line[2:]), styles["Heading1"]))
        elif line.startswith("> "):
            flush_bullets()
            story.append(Paragraph(_safe_inline_markup(line[2:]), quote_style))
        elif re.match(r"^[-*]\s+", line) or re.match(r"^\d+\.\s+", line):
            content = re.sub(r"^([-*]|\d+\.)\s+", "", line)
            bullet_buffer.append(content)
        else:
            flush_bullets()
            story.append(Paragraph(_safe_inline_markup(line), styles["BodyText"]))

    flush_bullets()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
    )
    doc.build(story)
