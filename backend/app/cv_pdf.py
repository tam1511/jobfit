"""Render a rewritten CV as a PDF and build the download response header.

Optimise (#11) surfaces per-bullet rewrites as ``optimise_rewrites`` rows
whose ``original_bullet`` is a verbatim substring of the stored CV text.
The extracted CV text is a flat pypdf dump — section order and item
order are preserved in the text stream, so applying each rewrite as a
first-occurrence string substitution against that stream yields the
"same CV with rewritten bullets" the user expects.

The renderer is deliberately plain single-column, matching the fixture
tooling at ``fixtures/case-02-marketing-partial/build_pdf.py``. A
bundled DejaVuSans TTF replaces Helvetica so Vietnamese diacritics
render.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

from fpdf import FPDF
from fpdf.enums import XPos, YPos


FONT_PATH: Path = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"
if not FONT_PATH.is_file():
    raise FileNotFoundError(
        f"DejaVuSans font missing at {FONT_PATH}. The CV PDF renderer needs it "
        "to render diacritics."
    )

_FILENAME_UNSAFE = re.compile(r"[^\w\-.]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_BULLET_RE = re.compile(r"^([\-*\u2022\u2023\u25AA\u25CF\u25E6\u00B7]|\d+[.)])(\s+)")

FONT_SIZE_PT = 11.0
LINE_HEIGHT_PT = 14.0
LEFT_MARGIN_PT = 54.0
RIGHT_MARGIN_PT = 54.0
TOP_MARGIN_PT = 54.0
BOTTOM_MARGIN_PT = 54.0


def apply_rewrites(cv_text: str, rewrites: list[dict]) -> str:
    """Apply ``action='rewrite'`` rows to ``cv_text`` in order.

    Each rewrite dict carries the shape stored in ``optimise_rewrites``:
    ``action``, ``original_bullet``, ``rewritten_bullet``. Only rows whose
    action is ``rewrite`` and whose ``original_bullet`` and
    ``rewritten_bullet`` are both non-empty are applied. The substitution
    uses ``str.replace`` with ``count=1`` so a phrase that happens to
    appear twice in the CV is only replaced at its first occurrence,
    which matches the intent of a targeted bullet rewrite.

    ``add`` and ``skip`` rows are ignored in this pass; ``add`` needs a
    placement decision the flat text can't answer, so v1 does not
    surface it in the exported PDF.
    """
    text = cv_text
    for row in rewrites:
        if row.get("action") != "rewrite":
            continue
        original = row.get("original_bullet")
        rewritten = row.get("rewritten_bullet")
        if not original or not rewritten:
            continue
        text = text.replace(original, rewritten, 1)
    return text


def render_cv_pdf(text: str, font_path: Path = FONT_PATH) -> bytes:
    """Render plain text as a single-column PDF and return the bytes.

    Wraps every source line to the printable width using real font
    metrics, so no visible text is ever pushed past the right margin.
    Bullet lines (``-``, ``*``, ``\u2022``, ``\u25CF``, numbered) keep the marker
    on the first visual line and hang subsequent visual lines under
    the content column. Page breaks trigger automatically when a line
    would cross the bottom margin.

    Character-level word breaking only kicks in when a single word is
    wider than the available line, so ordinary content never gets
    truncated mid-word.
    """
    pdf = FPDF(unit="pt", format="A4")
    pdf.set_margins(left=LEFT_MARGIN_PT, top=TOP_MARGIN_PT, right=RIGHT_MARGIN_PT)
    pdf.set_auto_page_break(auto=True, margin=BOTTOM_MARGIN_PT)
    pdf.add_font("DejaVuSans", fname=str(font_path))
    pdf.set_font("DejaVuSans", size=FONT_SIZE_PT)
    pdf.add_page()

    epw = pdf.epw

    for source_line in text.split("\n"):
        if source_line.strip() == "":
            _advance_blank(pdf)
            continue
        _render_source_line(pdf, source_line, epw)

    return bytes(pdf.output())


def _render_source_line(pdf: FPDF, source_line: str, epw: float) -> None:
    """Wrap and draw a single non-empty source line."""
    stripped = source_line.strip()
    match = _BULLET_RE.match(stripped)
    if match:
        prefix = match.group(0)
        content = stripped[match.end():]
        indent = pdf.get_string_width(prefix)
        pieces = _wrap_to_width(pdf, content, epw - indent)
        _draw_visual_line(pdf, prefix + pieces[0], 0.0)
        for piece in pieces[1:]:
            _draw_visual_line(pdf, piece, indent)
    else:
        for piece in _wrap_to_width(pdf, stripped, epw):
            _draw_visual_line(pdf, piece, 0.0)


def _draw_visual_line(pdf: FPDF, text: str, x_indent: float) -> None:
    """Draw one visual line flush-left at ``l_margin + x_indent``.

    We reset x explicitly before every line and use ``new_x=LMARGIN``
    so the cursor is anchored at the left margin between calls; that
    prevents the cumulative rightward drift that ``multi_cell`` with
    ``new_x=RIGHT`` produces when several short lines are stacked.
    """
    pdf.set_x(pdf.l_margin + x_indent)
    pdf.cell(
        w=pdf.epw - x_indent,
        h=LINE_HEIGHT_PT,
        text=text,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )


def _advance_blank(pdf: FPDF) -> None:
    """Insert a blank line's worth of vertical space, triggering a page break if needed."""
    if pdf.get_y() + LINE_HEIGHT_PT > pdf.h - pdf.b_margin:
        pdf.add_page()
    else:
        pdf.ln(LINE_HEIGHT_PT)


def _wrap_to_width(pdf: FPDF, text: str, max_width: float) -> list[str]:
    """Wrap ``text`` into visual lines, each fitting within ``max_width``.

    Words are broken at whitespace by default. A word only ever gets
    split mid-character when the word itself is wider than ``max_width``
    (a URL, a long token) — in that case the word is sliced into pieces
    that each fit. All whitespace (including tabs and NBSP) collapses
    to single spaces, mirroring how the source PDF's visual line breaks
    are treated as reflow-friendly.
    """
    words = text.split()
    if not words:
        return [""]
    space_w = pdf.get_string_width(" ")
    lines: list[str] = []
    current = ""
    current_w = 0.0
    for word in words:
        word_w = pdf.get_string_width(word)
        if word_w > max_width:
            if current:
                lines.append(current)
                current = ""
                current_w = 0.0
            fragments = _break_word_by_char(pdf, word, max_width)
            lines.extend(fragments[:-1])
            current = fragments[-1]
            current_w = pdf.get_string_width(current)
            continue
        addition = word_w if not current else space_w + word_w
        if current_w + addition <= max_width:
            current = f"{current} {word}" if current else word
            current_w += addition
        else:
            lines.append(current)
            current = word
            current_w = word_w
    if current:
        lines.append(current)
    return lines or [""]


def _break_word_by_char(pdf: FPDF, word: str, max_width: float) -> list[str]:
    """Slice a single word into pieces that each fit within ``max_width``.

    Only reached when the word cannot fit on a line whole. If even one
    character is wider than the line (a degenerate case) it still lands
    on its own piece — we prefer overflow-by-one-glyph to an infinite
    loop.
    """
    pieces: list[str] = []
    current = ""
    for ch in word:
        candidate = current + ch
        if pdf.get_string_width(candidate) <= max_width or not current:
            current = candidate
        else:
            pieces.append(current)
            current = ch
    if current:
        pieces.append(current)
    return pieces


def sanitize_filename(name: str, company: str, role_title: str) -> str:
    """Return ``<name>-<company>-<role>.pdf`` with unsafe chars stripped.

    Whitespace collapses to ``_``; anything outside Unicode word
    characters, ``-``, or ``.`` is dropped. Diacritics survive because
    ``\\w`` in Python regex matches Unicode letters. The empty case
    falls back to ``cv.pdf`` so the browser always has a name to use.
    """
    parts = [_slug_segment(s) for s in (name, company, role_title)]
    joined = "-".join(p for p in parts if p)
    if not joined:
        return "cv.pdf"
    return f"{joined}.pdf"


def _slug_segment(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value or "")
    collapsed = _WHITESPACE.sub("_", normalized.strip())
    return _FILENAME_UNSAFE.sub("", collapsed)


def content_disposition(filename: str) -> str:
    """Build a Content-Disposition header value that handles non-ASCII names.

    Per RFC 6266, the ``filename`` parameter must be ASCII. When the
    slug contains characters outside that range (Vietnamese diacritics,
    for example), we send both an ASCII fallback and an RFC 5987
    ``filename*=UTF-8''<pct-encoded>`` value so modern browsers get the
    accented name and older clients still get a sensible download.
    """
    ascii_fallback = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    if not ascii_fallback:
        ascii_fallback = "cv.pdf"
    if ascii_fallback == filename:
        return f'attachment; filename="{ascii_fallback}"'
    encoded = quote(filename, safe="")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'
