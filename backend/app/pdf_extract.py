"""Thin wrapper over pypdf so callers don't leak the library shape."""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfExtractionError(ValueError):
    """Raised when a PDF cannot be parsed or contains no readable text."""


def extract_text(pdf_bytes: bytes) -> str:
    """Return the concatenated text of all pages in the PDF.

    Raises PdfExtractionError if the file is not a valid PDF or if pypdf
    cannot pull any text out of it (image-only PDFs land here).
    """
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except (PdfReadError, OSError) as exc:
        raise PdfExtractionError("The file is not a readable PDF.") from exc

    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise PdfExtractionError(
            "The PDF has no selectable text. It may be a scanned image."
        )
    return text
