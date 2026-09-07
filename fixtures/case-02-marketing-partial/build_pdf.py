"""Regenerate cv.pdf from cv.md for the marketing demo fixture.

This script exists so cv.pdf can be reproduced whenever cv.md changes.
The generated PDF is intentionally a plain single-column rendering, so
pypdf extraction returns the same text the .md carries. That property
is checked by backend/tests/test_pdf_md_parity.py.

Usage:
    pip install fpdf2
    python fixtures/case-02-marketing-partial/build_pdf.py

fpdf2 is not part of backend/requirements.txt because generation is a
one-off maintenance task, not a runtime dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF


HERE = Path(__file__).resolve().parent
MD_PATH = HERE / "cv.md"
PDF_PATH = HERE / "cv.pdf"


def strip_markdown(md: str) -> str:
    """Turn the fixture markdown into the plain text a reader would see."""
    lines = []
    for raw in md.splitlines():
        line = raw.rstrip()
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s*[-*]\s+", "", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        lines.append(line)
    return "\n".join(lines)


def build() -> None:
    md = MD_PATH.read_text(encoding="utf-8")
    text = strip_markdown(md)

    pdf = FPDF(unit="pt", format="A4")
    pdf.set_margins(left=54, top=54, right=54)
    pdf.set_auto_page_break(auto=True, margin=54)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)

    for line in text.split("\n"):
        if line.strip() == "":
            pdf.ln(11)
            continue
        pdf.multi_cell(w=pdf.epw, h=14, text=line)

    pdf.output(str(PDF_PATH))


if __name__ == "__main__":
    build()
    print(f"wrote {PDF_PATH.relative_to(HERE.parent.parent)}")
