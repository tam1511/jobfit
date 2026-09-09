"""Unit tests for the pure PDF-building module.

These functions are deliberately dependency-free so they can be tested
without spinning up FastAPI or the DB. The round-trip via pypdf proves
the substitutions land in the rendered document.
"""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from app.cv_pdf import apply_rewrites, content_disposition, render_cv_pdf, sanitize_filename


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
