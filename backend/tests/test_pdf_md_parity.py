"""Guard the pypdf-to-scorer seam for the marketing demo fixture.

The scorer is deterministic on its input string (see CLAUDE.md). So
"the PDF and the .md must produce the same score" reduces to "the
canonical text extracted from the PDF must match the canonical text
of the .md". This test asserts exactly that, without needing the
scorer itself to exist yet.

Only case-02 has a PDF companion. The other fixtures do not need this
guarantee at this stage; when they do, add them to CASES below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pypdf import PdfReader


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

CASES = [
    "case-02-marketing-partial",
]


def _strip_markdown(md: str) -> str:
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


def _canonicalize(text: str) -> str:
    return " ".join(text.split())


def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.mark.parametrize("case_id", CASES)
def test_pdf_extract_matches_md(case_id: str) -> None:
    case_dir = FIXTURES / case_id
    md_text = _strip_markdown((case_dir / "cv.md").read_text(encoding="utf-8"))
    pdf_text = _read_pdf(case_dir / "cv.pdf")

    assert _canonicalize(pdf_text) == _canonicalize(md_text), (
        "pypdf extraction of cv.pdf diverged from cv.md. Regenerate the PDF "
        f"with: python fixtures/{case_id}/build_pdf.py"
    )
