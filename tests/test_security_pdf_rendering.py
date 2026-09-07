"""Regression tests for the PDF markup-injection fix (docs/SECURITY-AUDIT.md
6.1). Before the fix, unescaped text passed to reportlab's Paragraph could
crash rendering (unterminated tag-like substring) or let recognized tags
pass through as real markup. Both are exercised here with content shaped
like what LLM/provider output could plausibly contain (comparison
operators, HTML-looking fragments)."""
from __future__ import annotations

from src.rendering.pdf_renderer import render_markdown_to_pdf


def test_unterminated_tag_like_text_does_not_crash_rendering(tmp_path):
    dangerous_md = "# Paper\nSome code uses `if a < b: pass` and this is unterminated <tag here.\n"
    out = tmp_path / "out.pdf"
    render_markdown_to_pdf(dangerous_md, out)  # must not raise
    assert out.exists()
    assert out.stat().st_size > 0


def test_comparison_operators_in_code_render_safely(tmp_path):
    dangerous_md = "# Paper\n```\nwhile n < 5:\n    if n % 2 == 0 and n > 0:\n        print(n)\n```\n"
    out = tmp_path / "out.pdf"
    render_markdown_to_pdf(dangerous_md, out)
    assert out.exists()


def test_html_script_like_text_does_not_break_rendering(tmp_path):
    dangerous_md = "# Paper\nTom & Jerry's <script>alert(1)</script> and <img src=x onerror=alert(1)>.\n"
    out = tmp_path / "out.pdf"
    render_markdown_to_pdf(dangerous_md, out)
    assert out.exists()


def test_intentional_bold_markup_still_renders_as_bold():
    from src.rendering.pdf_renderer import _safe_inline_markup

    result = _safe_inline_markup("This is **important** text")
    assert "<b>important</b>" in result


def test_raw_angle_brackets_are_escaped_not_interpreted_as_tags():
    from src.rendering.pdf_renderer import _safe_inline_markup

    result = _safe_inline_markup("while n < 5 and m > 2:")
    assert "<" not in result.replace("&lt;", "").replace("&gt;", "")
    assert "&lt;" in result
    assert "&gt;" in result


def test_ampersand_is_escaped():
    from src.rendering.pdf_renderer import _safe_inline_markup

    result = _safe_inline_markup("Tom & Jerry")
    assert "&amp;" in result
    assert "Tom & Jerry" not in result
