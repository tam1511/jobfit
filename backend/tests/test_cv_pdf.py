"""Unit tests for the pure PDF-building module.

These functions are deliberately dependency-free so they can be tested
without spinning up FastAPI or the DB. The round-trip via pypdf proves
the substitutions land in the rendered document.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from app.cv_pdf import apply_rewrites, content_disposition, render_cv_pdf, sanitize_filename


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


CV = "\n".join(
    [
        "Jane Doe",
        "",
        "Experience",
        "- Ran Google Ads campaigns.",
        "- Wrote landing page copy.",
        "",
        "Skills",
        "SEO, GA4.",
    ]
)


def test_apply_rewrites_replaces_original_bullet() -> None:
    rewrites = [
        {
            "action": "rewrite",
            "original_bullet": "- Ran Google Ads campaigns.",
            "rewritten_bullet": "- Ran Google Ads campaigns spending 60k EUR quarterly.",
        }
    ]
    out = apply_rewrites(CV, rewrites)
    assert "- Ran Google Ads campaigns spending 60k EUR quarterly." in out
    assert "- Ran Google Ads campaigns.\n" not in out


def test_apply_rewrites_only_first_occurrence() -> None:
    doubled = "- foo\n- foo\n"
    rewrites = [{"action": "rewrite", "original_bullet": "- foo", "rewritten_bullet": "- bar"}]
    out = apply_rewrites(doubled, rewrites)
    assert out == "- bar\n- foo\n"


def test_apply_rewrites_ignores_non_rewrite_actions() -> None:
    rewrites = [
        {"action": "add", "original_bullet": None, "rewritten_bullet": "- New bullet."},
        {"action": "skip", "original_bullet": None, "rewritten_bullet": None},
    ]
    assert apply_rewrites(CV, rewrites) == CV


def test_apply_rewrites_skips_missing_original_or_rewritten() -> None:
    rewrites = [
        {"action": "rewrite", "original_bullet": None, "rewritten_bullet": "- x"},
        {"action": "rewrite", "original_bullet": "- Ran Google Ads campaigns.", "rewritten_bullet": None},
        {"action": "rewrite", "original_bullet": "", "rewritten_bullet": "- y"},
    ]
    assert apply_rewrites(CV, rewrites) == CV


def test_apply_rewrites_handles_multiline_original() -> None:
    text = "- Ran campaigns\nspanning three quarters.\nEnd."
    rewrites = [
        {
            "action": "rewrite",
            "original_bullet": "- Ran campaigns\nspanning three quarters.",
            "rewritten_bullet": "- Ran 3 quarterly campaigns.",
        }
    ]
    out = apply_rewrites(text, rewrites)
    assert out == "- Ran 3 quarterly campaigns.\nEnd."


def test_render_cv_pdf_returns_valid_pdf_bytes() -> None:
    pdf_bytes = render_cv_pdf(CV)
    assert pdf_bytes.startswith(b"%PDF-")


def test_render_cv_pdf_round_trips_text_via_pypdf() -> None:
    pdf_bytes = render_cv_pdf(CV)
    reader = PdfReader(BytesIO(pdf_bytes))
    extracted = reader.pages[0].extract_text()
    assert "Jane Doe" in extracted
    assert "Ran Google Ads campaigns." in extracted
    assert "Skills" in extracted


def _extracted_text(pdf_bytes: bytes) -> str:
    """Concatenate every page's extracted text into one string."""
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


_TD_RE = re.compile(rb"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+T[dm]")


def _text_x_positions(pdf_bytes: bytes) -> list[tuple[int, float, float]]:
    """Return (page_index, x, y) for every Td/Tm text-positioning op.

    fpdf2 emits one ``Td`` (or ``Tm``) per rendered visual line. If any
    x lands beyond the right margin the renderer has drawn text off the
    page, which is the exact failure mode of ticket #12's initial cut.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    positions: list[tuple[int, float, float]] = []
    for i, page in enumerate(reader.pages):
        raw = page.get_contents().get_data()
        for m in _TD_RE.finditer(raw):
            positions.append((i, float(m.group(1)), float(m.group(2))))
    return positions


def test_render_cv_pdf_draws_every_visual_line_within_page_bounds() -> None:
    """Every text-positioning op must land inside the printable area.

    Prior to the wrapping fix, each ``multi_cell`` call left the cursor
    at the previous cell's right edge, so subsequent short lines were
    drawn further and further off the right side of the page. pypdf's
    ``extract_text`` didn't notice (it walks text objects regardless of
    position), but the rendered PDF was visibly broken.
    """
    lines = "\n".join(f"Line {i}: some short content" for i in range(1, 12))
    pdf_bytes = render_cv_pdf(lines)
    reader = PdfReader(BytesIO(pdf_bytes))
    page_width = float(reader.pages[0].mediabox.width)
    for page_index, x, _ in _text_x_positions(pdf_bytes):
        assert 0 <= x <= page_width, (
            f"text drawn off-page on page {page_index}: x={x}, page_width={page_width}"
        )


def test_render_cv_pdf_round_trips_case02_fixture_intact() -> None:
    """Every section header and every bullet from the case-02 CV must survive.

    Extract text from the fixture PDF (what a real upload gives us),
    render that text back through ``render_cv_pdf``, and re-extract.
    No word may be truncated at the end.
    """
    source_text = _extracted_text((FIXTURES / "case-02-marketing-partial" / "cv.pdf").read_bytes())
    rendered = render_cv_pdf(source_text)
    out = " ".join(_extracted_text(rendered).split())

    for header in ("Summary", "Experience", "Skills", "Education"):
        assert header in out, f"section header missing: {header!r}"

    for bullet in (
        "Owned the SEO roadmap for the company blog, running monthly keyword",
        "research and on-page optimisation across 60 published articles",
        "Grew organic sessions from 8k to 26k per month over 18 months",
        "Ran the editorial calendar in Notion and briefed three freelance",
        "writers per month",
        "Built the marketing dashboard in Google Analytics 4, reporting weekly",
        "to the head of marketing",
        "Ran paid campaigns on Google Ads, managing a monthly budget of USD 4k",
        "Wrote 40 long-form articles for the company blog and coordinated",
        "distribution across email and social",
        "Coordinated with the design team on landing page updates for four",
        "seasonal campaigns",
        "Reported campaign performance to the marketing manager in a monthly",
        "review",
    ):
        assert bullet in out, f"bullet fragment missing / truncated: {bullet!r}"

    reader = PdfReader(BytesIO(rendered))
    page_width = float(reader.pages[0].mediabox.width)
    for page_index, x, _ in _text_x_positions(rendered):
        assert 0 <= x <= page_width, (
            f"case-02 render placed text off-page on page {page_index}: x={x}"
        )


def test_render_cv_pdf_wraps_extremely_long_bullet_without_truncation() -> None:
    """A single ~400-char bullet must round-trip through the PDF intact."""
    long_bullet = (
        "- Collaborated with the design team on the Technical Design, "
        "Solution Architecture, and Product Requirements Documents for the "
        "Mediciso platform in Seoul, South Korea, identifying integration "
        "gaps and proposing measurable improvements to the workflow across "
        "three offices over eighteen months of continuous delivery, running "
        "monthly reviews with the head of engineering and quarterly demos "
        "to the wider organisation"
    )
    assert len(long_bullet) >= 400, f"expected 400+ chars, got {len(long_bullet)}"

    pdf_bytes = render_cv_pdf(long_bullet)
    out = " ".join(_extracted_text(pdf_bytes).split())
    expected = " ".join(long_bullet.split())

    assert expected in out, (
        f"long bullet was mutated in the round-trip.\nWanted: {expected!r}\nGot:    {out!r}"
    )

    reader = PdfReader(BytesIO(pdf_bytes))
    page_width = float(reader.pages[0].mediabox.width)
    for page_index, x, _ in _text_x_positions(pdf_bytes):
        assert 0 <= x <= page_width, (
            f"long bullet placed text off-page on page {page_index}: x={x}"
        )


def test_render_cv_pdf_renders_diacritics() -> None:
    pdf_bytes = render_cv_pdf("Nguyễn Văn A\nKỹ sư phần mềm.")
    reader = PdfReader(BytesIO(pdf_bytes))
    extracted = reader.pages[0].extract_text()
    assert "Nguyễn" in extracted
    assert "Kỹ" in extracted


def test_sanitize_filename_basic() -> None:
    assert (
        sanitize_filename("Jane Smith", "Acme Corp", "Senior Engineer")
        == "Jane_Smith-Acme_Corp-Senior_Engineer.pdf"
    )


def test_sanitize_filename_strips_unsafe_characters() -> None:
    result = sanitize_filename('Jane "J" Smith', "Ac/me", "Eng: Lead")
    assert '"' not in result
    assert "/" not in result
    assert ":" not in result
    assert result.endswith(".pdf")


def test_sanitize_filename_preserves_diacritics() -> None:
    result = sanitize_filename("Nguyễn Văn A", "Acme", "Kỹ sư")
    assert "Nguyễn" in result
    assert "Văn" in result
    assert "Kỹ" in result


def test_sanitize_filename_falls_back_when_all_empty() -> None:
    assert sanitize_filename("", "  ", "///") == "cv.pdf"


def test_content_disposition_ascii_only_uses_plain_filename() -> None:
    header = content_disposition("Jane_Smith-Acme-Engineer.pdf")
    assert header == 'attachment; filename="Jane_Smith-Acme-Engineer.pdf"'


def test_content_disposition_non_ascii_uses_rfc5987() -> None:
    header = content_disposition("Nguyễn_Văn_A-Acme-Kỹ_sư.pdf")
    assert 'filename="Nguyen_Van_A-Acme-Ky_su.pdf"' in header
    assert "filename*=UTF-8''" in header
    assert "Nguy%E1%BB%85n" in header
