"""Render a rewritten CV as a PDF and build the download response header.

Optimise (#11) surfaces per-bullet rewrites as ``optimise_rewrites`` rows
whose ``original_bullet`` is a verbatim substring of the stored CV text.
The extracted CV text is a flat pypdf dump — section order and item
order are preserved in the text stream, so applying each rewrite as a
first-occurrence string substitution against that stream yields the
"same CV with rewritten bullets" the user expects.

The renderer classifies every source line into one of a small set of
kinds (name / subheader / section title / job entry / bullet /
paragraph) and styles each kind differently, so the output reads as a
proper CV rather than as a flat text dump. Fonts do not match the
user's original CV — we cannot know what those were — but the visual
hierarchy (bold name at the top, uppercase section titles with a rule,
bold role/date lines, indented bullets) mirrors what a CV reader
expects to see.

Bold styling requires the bundled ``DejaVuSans-Bold.ttf`` alongside the
regular TTF; both paths are checked at import so a broken deploy fails
fast rather than at first download.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fpdf import FPDF
from fpdf.enums import XPos, YPos


FONTS_DIR: Path = Path(__file__).resolve().parent / "fonts"
FONT_PATH: Path = FONTS_DIR / "DejaVuSans.ttf"
BOLD_FONT_PATH: Path = FONTS_DIR / "DejaVuSans-Bold.ttf"
for _path in (FONT_PATH, BOLD_FONT_PATH):
    if not _path.is_file():
        raise FileNotFoundError(
            f"CV PDF renderer needs {_path.name} at {_path}."
        )


# ---------------------------------------------------------------------------
# Rewrite application
# ---------------------------------------------------------------------------

_ADD_SECTION_HEADING = "ADDITIONAL HIGHLIGHTS"


def apply_rewrites(cv_text: str, rewrites: list[dict]) -> str:
    """Apply ``rewrite`` and ``add`` rows from ``optimise_rewrites``.

    Each row carries ``action``, ``original_bullet``, ``rewritten_bullet``.

    - ``rewrite`` rows use ``str.replace`` with ``count=1`` so a phrase
      that happens to appear twice in the CV is only replaced at its
      first occurrence.
    - ``add`` rows are collected and appended under an
      ``ADDITIONAL HIGHLIGHTS`` section at the end of the document.
      The flat text stream doesn't tell us which job header owns them,
      so v1 groups them into a dedicated trailing section rather than
      dropping them silently — the download button appears whenever a
      rewrite OR an add exists, so the two must produce output.
    - ``skip`` rows are ignored.

    Rows missing the fields their action needs (``rewrite`` without an
    ``original_bullet``, either action without a ``rewritten_bullet``)
    are skipped as if absent.
    """
    text = cv_text
    adds: list[str] = []
    for row in rewrites:
        action = row.get("action")
        rewritten = row.get("rewritten_bullet")
        if not rewritten:
            continue
        if action == "rewrite":
            original = row.get("original_bullet")
            if not original:
                continue
            text = text.replace(original, rewritten, 1)
        elif action == "add":
            adds.append(rewritten)
    if adds:
        appendix = "\n\n" + _ADD_SECTION_HEADING + "\n" + "\n".join(
            f"- {bullet}" for bullet in adds
        )
        text = text.rstrip() + appendix
    return text


# ---------------------------------------------------------------------------
# Structure inference
# ---------------------------------------------------------------------------

Kind = Literal[
    "name",
    "subheader",
    "section_title",
    "job_entry",
    "bullet",
    "paragraph",
    "blank",
]


@dataclass(frozen=True)
class CvElement:
    """One reflow unit produced by ``classify_lines``.

    ``text`` carries the content to render, with pypdf's 2-space
    continuation indent already folded into single spaces. Job entries
    additionally split into ``text`` (role, company) and ``dates`` (the
    parenthesised date range) so the renderer can right-align dates on
    the same visual row as the role.
    """

    kind: Kind
    text: str
    dates: str | None = None


# Section titles we recognise regardless of case. Anything unusual gets
# caught by the ALL-CAPS short-line fallback in ``_is_section_title``.
_SECTION_TITLES: frozenset[str] = frozenset(
    s.lower() for s in (
        "Summary", "Objective", "Profile", "About", "Overview",
        "Experience", "Work Experience", "Employment", "Employment History",
        "Professional Experience",
        "Education", "Skills", "Technical Skills", "Core Skills", "Key Skills",
        "Projects", "Certifications", "Awards", "Languages",
        "Interests", "Publications", "Volunteer", "References", "Contact",
    )
)

# "Role, Company (year - year|present)" with dash variants. The dates
# group is required to contain at least one 4-digit year so ordinary
# parenthesised prose ("(see below)") isn't picked up as a job header.
# ``mid`` allows commas so lines like "Role, Company, Location (2020 -
# 2023)" still match, with the location folded into the company cell.
_JOB_ENTRY_RE = re.compile(
    r"^(?P<left>[^,()]+?),\s*(?P<mid>[^()]+?)\s*"
    r"\((?P<dates>[^()]*\d{4}[^()]*?)\)\s*$",
)

# Bullet-marker prefixes we normalise to a single ``\u2022`` when rendering.
_BULLET_RE = re.compile(r"^([\-*\u2022\u2023\u25AA\u25CF\u25E6\u00B7]|\d+[.)])(\s+)")


def _strip_bullet_marker(line: str) -> str:
    stripped = line.lstrip()
    m = _BULLET_RE.match(stripped)
    return stripped[m.end():] if m else stripped


def _is_section_title(line: str) -> bool:
    """True for lines that read as a CV section header.

    Two signals: an exact case-insensitive match against a known list
    of common section titles, and a narrow "short ALL-CAPS line"
    fallback for CVs that use ``PROFESSIONAL EXPERIENCE`` and friends.
    The fallback requires 2-4 words so single-token ALL-CAPS company
    names ("IBM", "NASA") don't get promoted, and excludes lines that
    look like a job entry ("Senior Engineer, IBM (2020 - 2023)") so
    uppercase role/company lines stay in the job-entry path.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.lower() in _SECTION_TITLES:
        return True
    if _JOB_ENTRY_RE.match(stripped):
        return False
    words = stripped.split()
    if 2 <= len(words) <= 4 and stripped.isupper():
        return True
    return False


def classify_lines(text: str) -> list[CvElement]:
    """Turn flat pypdf-extracted CV text into a list of reflow elements.

    The first non-blank line is always the name. Up to two immediately
    following non-blank, non-section-title lines fold into a single
    subheader (contact / role tagline). Section-title lines break the
    flow and govern how subsequent unmarked content is treated: within
    a section, an unmarked line becomes a bullet only after a job-entry
    line has appeared (Experience-style) — before then, it folds into a
    running paragraph (Summary-style). Bullet-marker lines are always
    bullets. Continuation lines (source lines starting with two or more
    spaces) fold into the preceding bullet or paragraph.

    Blank source lines pass through as ``blank`` so the renderer can
    honour them as vertical spacing when pypdf preserved any.
    """
    lines = text.split("\n")
    elements: list[CvElement] = []
    saw_name = False
    in_bullet_zone = False
    i = 0

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        if not stripped:
            elements.append(CvElement(kind="blank", text=""))
            i += 1
            continue

        if not saw_name:
            elements.append(CvElement(kind="name", text=stripped))
            saw_name = True
            i += 1
            subheader_parts: list[str] = []
            while i < len(lines) and len(subheader_parts) < 2:
                candidate = lines[i].strip()
                if not candidate or _is_section_title(candidate):
                    break
                subheader_parts.append(candidate)
                i += 1
            if subheader_parts:
                elements.append(
                    CvElement(kind="subheader", text=" \u00b7 ".join(subheader_parts))
                )
            continue

        if _is_section_title(raw):
            elements.append(CvElement(kind="section_title", text=stripped.upper()))
            in_bullet_zone = False
            i += 1
            continue

        m = _JOB_ENTRY_RE.match(stripped)
        if m:
            left = m.group("left").strip()
            mid = m.group("mid").strip()
            dates = m.group("dates").strip()
            elements.append(
                CvElement(kind="job_entry", text=f"{left}, {mid}", dates=dates)
            )
            in_bullet_zone = True
            i += 1
            continue

        has_marker = bool(_BULLET_RE.match(stripped))
        content_lines = [_strip_bullet_marker(stripped) if has_marker else stripped]
        j = i + 1
        while j < len(lines) and lines[j].startswith("  ") and lines[j].strip():
            content_lines.append(lines[j].strip())
            j += 1
        content = " ".join(content_lines)

        if has_marker or in_bullet_zone:
            elements.append(CvElement(kind="bullet", text=content))
        else:
            if elements and elements[-1].kind == "paragraph":
                prev = elements.pop()
                elements.append(
                    CvElement(kind="paragraph", text=f"{prev.text} {content}")
                )
            else:
                elements.append(CvElement(kind="paragraph", text=content))
        i = j

    return elements


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_LEFT_MARGIN_PT = 54.0
_RIGHT_MARGIN_PT = 54.0
_TOP_MARGIN_PT = 54.0
_BOTTOM_MARGIN_PT = 54.0

_NAME_SIZE_PT = 20.0
_NAME_LINE_HEIGHT_PT = 24.0
_SUBHEADER_SIZE_PT = 10.0
_SUBHEADER_LINE_HEIGHT_PT = 13.0
_SECTION_TITLE_SIZE_PT = 12.5
_SECTION_TITLE_LINE_HEIGHT_PT = 15.0
_JOB_ENTRY_SIZE_PT = 11.5
_JOB_ENTRY_LINE_HEIGHT_PT = 15.0
_BODY_SIZE_PT = 11.0
_BODY_LINE_HEIGHT_PT = 14.0

_SECTION_TOP_GAP_PT = 10.0
_SECTION_RULE_GAP_PT = 4.0
_POST_JOB_ENTRY_GAP_PT = 2.0
_POST_PARAGRAPH_GAP_PT = 3.0

_BULLET_MARKER = "\u2022"
_BULLET_PREFIX = f"{_BULLET_MARKER}   "

_SUBHEADER_GREY = (102, 102, 102)
_RULE_GREY = (170, 170, 170)


def render_cv_pdf(
    text: str,
    font_path: Path = FONT_PATH,
    bold_font_path: Path = BOLD_FONT_PATH,
) -> bytes:
    """Render structured CV text as a styled A4 PDF and return the bytes.

    Classifies each source line via ``classify_lines`` and dispatches to
    a per-kind renderer. Wrapping uses real font metrics so no visible
    text is pushed past the right margin. Page breaks trigger
    automatically when a line would cross the bottom margin.
    """
    pdf = FPDF(unit="pt", format="A4")
    pdf.set_margins(left=_LEFT_MARGIN_PT, top=_TOP_MARGIN_PT, right=_RIGHT_MARGIN_PT)
    pdf.set_auto_page_break(auto=True, margin=_BOTTOM_MARGIN_PT)
    pdf.add_font("DejaVuSans", fname=str(font_path))
    pdf.add_font("DejaVuSans", style="B", fname=str(bold_font_path))
    pdf.add_page()

    epw = pdf.epw
    elements = classify_lines(text)

    for elem in elements:
        if elem.kind == "name":
            _render_name(pdf, elem.text, epw)
        elif elem.kind == "subheader":
            _render_subheader(pdf, elem.text, epw)
        elif elem.kind == "section_title":
            _render_section_title(pdf, elem.text, epw)
        elif elem.kind == "job_entry":
            _render_job_entry(pdf, elem.text, elem.dates or "", epw)
        elif elem.kind == "bullet":
            _render_body_block(pdf, elem.text, epw, prefix=_BULLET_PREFIX)
        elif elem.kind == "paragraph":
            _render_body_block(pdf, elem.text, epw, trailing_gap=_POST_PARAGRAPH_GAP_PT)
        elif elem.kind == "blank":
            _advance_blank(pdf)

    return bytes(pdf.output())


def _render_name(pdf: FPDF, text: str, epw: float) -> None:
    pdf.set_font("DejaVuSans", "B", _NAME_SIZE_PT)
    for piece in _wrap_to_width(pdf, text, epw):
        _draw_visual_line(pdf, piece, 0.0, _NAME_LINE_HEIGHT_PT)


def _render_subheader(pdf: FPDF, text: str, epw: float) -> None:
    pdf.set_font("DejaVuSans", "", _SUBHEADER_SIZE_PT)
    pdf.set_text_color(*_SUBHEADER_GREY)
    for piece in _wrap_to_width(pdf, text, epw):
        _draw_visual_line(pdf, piece, 0.0, _SUBHEADER_LINE_HEIGHT_PT)
    pdf.set_text_color(0, 0, 0)


def _render_section_title(pdf: FPDF, text: str, epw: float) -> None:
    # Reserve room for the title plus one line of following content so a
    # section header never lands as the last visible line on the page.
    needed = (
        _SECTION_TOP_GAP_PT
        + _SECTION_TITLE_LINE_HEIGHT_PT
        + _SECTION_RULE_GAP_PT
        + _JOB_ENTRY_LINE_HEIGHT_PT
    )
    if pdf.get_y() + needed > pdf.h - pdf.b_margin:
        pdf.add_page()
    pdf.ln(_SECTION_TOP_GAP_PT)
    pdf.set_font("DejaVuSans", "B", _SECTION_TITLE_SIZE_PT)
    for piece in _wrap_to_width(pdf, text, epw):
        _draw_visual_line(pdf, piece, 0.0, _SECTION_TITLE_LINE_HEIGHT_PT)
    y = pdf.get_y()
    pdf.set_draw_color(*_RULE_GREY)
    pdf.line(pdf.l_margin, y, pdf.l_margin + epw, y)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(_SECTION_RULE_GAP_PT)


def _render_job_entry(pdf: FPDF, left_text: str, dates: str, epw: float) -> None:
    """Draw the role/company on the left and the date range on the right.

    Both cells are on the same visual row. Only the first wrapped piece
    of ``left_text`` shares the row with the date — subsequent pieces
    (rare, only when the role/company line is very long) fall onto
    plain full-width lines below with no date column.
    """
    pdf.set_font("DejaVuSans", "B", _JOB_ENTRY_SIZE_PT)
    dates_width = pdf.get_string_width(dates) + 4.0 if dates else 0.0
    left_max = epw - dates_width
    left_pieces = _wrap_to_width(pdf, left_text, left_max)

    if pdf.get_y() + _JOB_ENTRY_LINE_HEIGHT_PT > pdf.h - pdf.b_margin:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_xy(pdf.l_margin, y)
    pdf.cell(
        w=left_max,
        h=_JOB_ENTRY_LINE_HEIGHT_PT,
        text=left_pieces[0],
        new_x=XPos.END,
        new_y=YPos.LAST,
    )
    if dates:
        pdf.set_xy(pdf.l_margin + left_max, y)
        pdf.cell(
            w=dates_width,
            h=_JOB_ENTRY_LINE_HEIGHT_PT,
            text=dates,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    else:
        pdf.set_x(pdf.l_margin)
        pdf.ln(_JOB_ENTRY_LINE_HEIGHT_PT)
    for piece in left_pieces[1:]:
        _draw_visual_line(pdf, piece, 0.0, _JOB_ENTRY_LINE_HEIGHT_PT)
    pdf.ln(_POST_JOB_ENTRY_GAP_PT)


def _render_body_block(
    pdf: FPDF,
    text: str,
    epw: float,
    *,
    prefix: str = "",
    trailing_gap: float = 0.0,
) -> None:
    """Render body text with an optional prefix + hanging indent.

    Bullets pass ``prefix=_BULLET_PREFIX`` so continuation lines align
    under the first character of content rather than under the marker.
    Paragraphs pass ``trailing_gap`` so consecutive paragraphs breathe.
    """
    pdf.set_font("DejaVuSans", "", _BODY_SIZE_PT)
    marker_w = pdf.get_string_width(prefix)
    pieces = _wrap_to_width(pdf, text, epw - marker_w)
    _draw_visual_line(pdf, prefix + pieces[0], 0.0, _BODY_LINE_HEIGHT_PT)
    for piece in pieces[1:]:
        _draw_visual_line(pdf, piece, marker_w, _BODY_LINE_HEIGHT_PT)
    if trailing_gap:
        pdf.ln(trailing_gap)


def _draw_visual_line(pdf: FPDF, text: str, x_indent: float, line_height: float) -> None:
    """Draw one visual line flush-left at ``l_margin + x_indent``.

    We reset x explicitly before every line and use ``new_x=LMARGIN``
    so the cursor is anchored at the left margin between calls; that
    prevents the cumulative rightward drift that ``multi_cell`` with
    ``new_x=RIGHT`` produces when several short lines are stacked.
    """
    pdf.set_x(pdf.l_margin + x_indent)
    pdf.cell(
        w=pdf.epw - x_indent,
        h=line_height,
        text=text,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )


def _advance_blank(pdf: FPDF) -> None:
    """Insert a blank line's worth of vertical space, triggering a page break if needed."""
    if pdf.get_y() + _BODY_LINE_HEIGHT_PT > pdf.h - pdf.b_margin:
        pdf.add_page()
    else:
        pdf.ln(_BODY_LINE_HEIGHT_PT)


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


# ---------------------------------------------------------------------------
# Filename / header helpers
# ---------------------------------------------------------------------------

_FILENAME_UNSAFE = re.compile(r"[^\w\-.]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


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
