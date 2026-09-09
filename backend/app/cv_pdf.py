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


FONT_PATH: Path = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"
if not FONT_PATH.is_file():
    raise FileNotFoundError(
        f"DejaVuSans font missing at {FONT_PATH}. The CV PDF renderer needs it "
        "to render diacritics."
    )

_FILENAME_UNSAFE = re.compile(r"[^\w\-.]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


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

    Uses the same units, margins, font size, line height, and
    blank-line handling as ``build_pdf.py``; only the font family
    changes so Latin-Extended characters render.
    """
    pdf = FPDF(unit="pt", format="A4")
    pdf.set_margins(left=54, top=54, right=54)
    pdf.set_auto_page_break(auto=True, margin=54)
    pdf.add_font("DejaVuSans", fname=str(font_path))
    pdf.set_font("DejaVuSans", size=11)
    pdf.add_page()

    for line in text.split("\n"):
        if line.strip() == "":
            pdf.ln(11)
            continue
        pdf.multi_cell(w=pdf.epw, h=14, text=line)

    return bytes(pdf.output())


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
