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

from app.cv_pdf import (
    apply_rewrites,
    classify_lines,
    content_disposition,
    render_cv_pdf,
    sanitize_filename,
)


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


def test_apply_rewrites_ignores_skip_action() -> None:
    """Skip rows must not change the CV — they represent gaps the user
    chose to move past, not content to render."""
    rewrites = [
        {"action": "skip", "original_bullet": None, "rewritten_bullet": None},
    ]
    assert apply_rewrites(CV, rewrites) == CV


def test_apply_rewrites_appends_add_action_under_dedicated_section() -> None:
    """Add rows land under an ``ADDITIONAL HIGHLIGHTS`` section at the
    end of the document. We can't infer which job header owns an added
    bullet from the flat text stream, so the exported PDF surfaces the
    additions in a dedicated trailing section rather than dropping them.
    """
    rewrites = [
        {
            "action": "add",
            "original_bullet": None,
            "rewritten_bullet": "Delivered 3 A/B tests lifting signup conversion by 18%.",
        },
        {
            "action": "add",
            "original_bullet": None,
            "rewritten_bullet": "Coached two junior marketers on brief writing.",
        },
    ]
    out = apply_rewrites(CV, rewrites)
    assert "ADDITIONAL HIGHLIGHTS" in out
    assert "Delivered 3 A/B tests lifting signup conversion by 18%." in out
    assert "Coached two junior marketers on brief writing." in out
    # Original CV content still present.
    assert "Ran Google Ads campaigns." in out


def test_apply_rewrites_add_section_renders_as_section_and_bullets() -> None:
    """The appended block must classify as a section title plus bullets
    when the classifier processes the merged text — otherwise the export
    would print the highlights as an unstyled tail on the previous section.
    """
    rewrites = [
        {
            "action": "add",
            "original_bullet": None,
            "rewritten_bullet": "Delivered 3 A/B tests lifting signup conversion by 18%.",
        },
    ]
    out = apply_rewrites(CV, rewrites)
    elements = classify_lines(out)
    section_titles = [e.text for e in elements if e.kind == "section_title"]
    assert "ADDITIONAL HIGHLIGHTS" in section_titles
    trailing_bullets = [e.text for e in elements if e.kind == "bullet"]
    assert "Delivered 3 A/B tests lifting signup conversion by 18%." in trailing_bullets


def test_apply_rewrites_skips_add_rows_without_rewritten_bullet() -> None:
    rewrites = [
        {"action": "add", "original_bullet": None, "rewritten_bullet": None},
        {"action": "add", "original_bullet": None, "rewritten_bullet": ""},
    ]
    assert apply_rewrites(CV, rewrites) == CV


def test_apply_rewrites_mixes_rewrite_and_add() -> None:
    rewrites = [
        {
            "action": "rewrite",
            "original_bullet": "- Ran Google Ads campaigns.",
            "rewritten_bullet": "- Ran Google Ads campaigns spending 60k EUR quarterly.",
        },
        {
            "action": "add",
            "original_bullet": None,
            "rewritten_bullet": "Coached two junior marketers on brief writing.",
        },
    ]
    out = apply_rewrites(CV, rewrites)
    assert "Ran Google Ads campaigns spending 60k EUR quarterly." in out
    assert "ADDITIONAL HIGHLIGHTS" in out
    assert "Coached two junior marketers on brief writing." in out


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


def _kinds(elements) -> list[str]:
    return [e.kind for e in elements]


def test_classify_lines_names_line_zero_and_folds_subheader() -> None:
    text = "\n".join(
        [
            "Mai Nguyen",
            "Digital Marketing Specialist",
            "mai.nguyen@example.com | Hanoi",
            "Summary",
            "Digital marketer with three years of experience.",
        ]
    )
    elements = classify_lines(text)
    assert _kinds(elements)[:3] == ["name", "subheader", "section_title"]
    assert elements[0].text == "Mai Nguyen"
    subheader = elements[1].text
    assert "Digital Marketing Specialist" in subheader
    assert "mai.nguyen@example.com" in subheader
    assert " \u00b7 " in subheader


def test_classify_lines_recognises_known_section_titles_case_insensitive() -> None:
    text = "\n".join(
        [
            "Jane Doe",
            "Engineer",
            "summary",
            "Body line.",
            "EXPERIENCE",
            "Senior Engineer, Acme (2020 - present)",
        ]
    )
    elements = classify_lines(text)
    assert elements[2].kind == "section_title"
    assert elements[2].text == "SUMMARY"
    assert elements[4].kind == "section_title"
    assert elements[4].text == "EXPERIENCE"


def test_classify_lines_uppercase_short_line_reads_as_section_title() -> None:
    text = "\n".join(
        [
            "Jane Doe",
            "Engineer",
            "PROFESSIONAL EXPERIENCE",
            "Senior Engineer, Acme (2020 - present)",
        ]
    )
    elements = classify_lines(text)
    assert elements[2].kind == "section_title"
    assert elements[2].text == "PROFESSIONAL EXPERIENCE"


def test_classify_lines_single_uppercase_token_is_not_a_section_title() -> None:
    """Company acronyms alone on a line must not be promoted to section titles.

    The ALL-CAPS fallback exists for ``PROFESSIONAL EXPERIENCE``-style
    headers, but a lone ``IBM`` or ``NASA`` matches the same shape.
    Requiring 2+ words keeps the heuristic narrow enough to skip these.
    """
    text = "\n".join(
        [
            "Jane Doe",
            "Engineer",
            "Experience",
            "Senior Engineer, IBM (2020 - 2023)",
            "IBM",
            "Built the platform.",
        ]
    )
    elements = classify_lines(text)
    kinds = _kinds(elements)
    assert kinds.count("section_title") == 1
    assert "IBM" not in [e.text for e in elements if e.kind == "section_title"]


def test_classify_lines_splits_job_entry_into_role_and_dates() -> None:
    text = "\n".join(
        [
            "Jane Doe",
            "Engineer",
            "Experience",
            "Senior Backend Engineer, PayLoop (2022 - present)",
        ]
    )
    elements = classify_lines(text)
    job = elements[-1]
    assert job.kind == "job_entry"
    assert job.text == "Senior Backend Engineer, PayLoop"
    assert job.dates == "2022 - present"


def test_classify_lines_job_entry_accepts_location_before_dates() -> None:
    """`Role, Company, Location (year - year)` must classify as a job entry.

    Real CVs commonly list a location as a third comma-separated segment.
    Rejecting these lines misclassifies them as bullets and prevents
    ``in_bullet_zone`` from flipping, so every subsequent unmarked line
    in the section folds into a paragraph instead of a bullet.
    """
    text = "\n".join(
        [
            "Jane Doe",
            "Engineer",
            "Experience",
            "Senior Backend Engineer, PayLoop, London (2020 - 2023)",
            "Built the payments service.",
        ]
    )
    elements = classify_lines(text)
    assert elements[-2].kind == "job_entry"
    assert elements[-2].text == "Senior Backend Engineer, PayLoop, London"
    assert elements[-2].dates == "2020 - 2023"
    assert elements[-1].kind == "bullet"


def test_classify_lines_job_entry_accepts_summer_date_ranges() -> None:
    text = "\n".join(
        [
            "Duc Pham",
            "Data Analyst",
            "Experience",
            "Business Analyst Intern, Northline Trading (Summer 2022)",
        ]
    )
    elements = classify_lines(text)
    assert elements[-1].kind == "job_entry"
    assert elements[-1].dates == "Summer 2022"


def test_classify_lines_treats_unmarked_lines_after_job_entry_as_bullets() -> None:
    text = "\n".join(
        [
            "Jane Doe",
            "Engineer",
            "Experience",
            "Senior Engineer, Acme (2020 - present)",
            "Built the payments service.",
            "Ran the on-call rotation.",
        ]
    )
    elements = classify_lines(text)
    kinds = _kinds(elements)
    assert kinds[-2:] == ["bullet", "bullet"]


def test_classify_lines_folds_summary_paragraph_into_one_element() -> None:
    text = "\n".join(
        [
            "Jane Doe",
            "Engineer",
            "Summary",
            "Digital marketer with three years of experience across SEO and",
            "content for consumer brands. Comfortable running the calendar.",
        ]
    )
    elements = classify_lines(text)
    paras = [e for e in elements if e.kind == "paragraph"]
    assert len(paras) == 1
    assert "Digital marketer" in paras[0].text
    assert "Comfortable running the calendar" in paras[0].text


def test_classify_lines_folds_continuation_indent_into_previous_bullet() -> None:
    text = "\n".join(
        [
            "Jane Doe",
            "Engineer",
            "Experience",
            "Senior Engineer, Acme (2020 - present)",
            "Owned the roadmap for the platform, running monthly reviews",
            "  and quarterly demos to the wider organisation.",
        ]
    )
    elements = classify_lines(text)
    bullet = elements[-1]
    assert bullet.kind == "bullet"
    assert "monthly reviews and quarterly demos" in bullet.text


def test_classify_lines_marked_bullet_wins_even_in_paragraph_section() -> None:
    text = "\n".join(
        [
            "Jane Doe",
            "Engineer",
            "Summary",
            "- Bullet even in the summary section.",
        ]
    )
    elements = classify_lines(text)
    assert elements[-1].kind == "bullet"
    assert elements[-1].text == "Bullet even in the summary section."


def test_classify_lines_blank_line_becomes_blank_element() -> None:
    text = "\n".join(["Jane Doe", "Engineer", "", "Summary", "Body."])
    kinds = _kinds(classify_lines(text))
    assert "blank" in kinds


def test_classify_lines_case_02_fixture_produces_expected_shape() -> None:
    """The case-02 fixture must classify into a full CV shape."""
    source = _extracted_text(
        (FIXTURES / "case-02-marketing-partial" / "cv.pdf").read_bytes()
    )
    elements = classify_lines(source)
    kinds = _kinds(elements)

    assert kinds[0] == "name"
    assert elements[0].text == "Mai Nguyen"

    section_titles = [e.text for e in elements if e.kind == "section_title"]
    assert section_titles == ["SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION"]

    job_entries = [e for e in elements if e.kind == "job_entry"]
    assert len(job_entries) == 2
    assert job_entries[0].text == "Digital Marketing Specialist, Verano Studio"
    assert job_entries[0].dates == "2023 - present"
    assert job_entries[1].dates == "2022 - 2023"

    bullets = [e for e in elements if e.kind == "bullet"]
    assert len(bullets) >= 8  # 5 + 3 across the two roles

    # Summary content is a single folded paragraph.
    summary_paras = []
    seen_summary = False
    for e in elements:
        if e.kind == "section_title" and e.text == "SUMMARY":
            seen_summary = True
            continue
        if e.kind == "section_title" and seen_summary:
            break
        if seen_summary and e.kind == "paragraph":
            summary_paras.append(e)
    assert len(summary_paras) == 1
    assert "Digital marketer" in summary_paras[0].text
    assert "marketing lead" in summary_paras[0].text


def test_render_cv_pdf_returns_valid_pdf_bytes() -> None:
    pdf_bytes = render_cv_pdf(CV)
    assert pdf_bytes.startswith(b"%PDF-")


def test_render_cv_pdf_round_trips_text_via_pypdf() -> None:
    pdf_bytes = render_cv_pdf(CV)
    reader = PdfReader(BytesIO(pdf_bytes))
    extracted = reader.pages[0].extract_text()
    assert "Jane Doe" in extracted
    assert "Ran Google Ads campaigns." in extracted
    # Section titles render uppercase for visual hierarchy.
    assert "SKILLS" in extracted


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

    for header in ("SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION"):
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


def test_render_cv_pdf_registers_regular_and_bold_fonts() -> None:
    """Both DejaVuSans and DejaVuSans-Bold must appear in the PDF font table.

    Visual hierarchy (bold name, bold section titles, bold job entries)
    relies on the bold font being registered alongside the regular one.
    If font registration ever regresses, fpdf2 silently falls back to
    the last-set font and the reflow loses its bold signals.
    """
    pdf_bytes = render_cv_pdf(CV)
    reader = PdfReader(BytesIO(pdf_bytes))
    fonts = reader.pages[0]["/Resources"]["/Font"]
    base_fonts = {f["/BaseFont"] for f in fonts.values()}
    assert any("DejaVuSans" in bf and "Bold" not in bf for bf in base_fonts), base_fonts
    assert any("DejaVuSans" in bf and "Bold" in bf for bf in base_fonts), base_fonts


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
