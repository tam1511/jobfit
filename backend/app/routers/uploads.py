"""Upload a CV PDF plus a pasted JD, extract text, store the pair."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.pdf_extract import PdfExtractionError, extract_text


router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class UploadResponse(BaseModel):
    upload_id: int
    filename: str
    extracted_text: str
    jd_text: str


MAX_PDF_BYTES = 10 * 1024 * 1024


@router.post("", response_model=UploadResponse)
async def create_upload(
    request: Request,
    user_id: int = Form(...),
    jd_text: str = Form(...),
    cv: UploadFile = ...,
) -> UploadResponse:
    if cv.content_type not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(status_code=415, detail="CV must be a PDF file.")

    jd_text = jd_text.strip()
    if not jd_text:
        raise HTTPException(status_code=422, detail="Paste the job description.")

    pdf_bytes = await cv.read()
    if not pdf_bytes:
        raise HTTPException(status_code=422, detail="The uploaded PDF is empty.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds the 10 MB limit.")

    try:
        text = extract_text(pdf_bytes)
    except PdfExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = cv.filename or "cv.pdf"

    with request.app.state.db_connect() as conn:
        user_row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is None:
            raise HTTPException(status_code=404, detail="Unknown user.")
        cursor = conn.execute(
            "INSERT INTO uploads(user_id, filename, file_bytes, extracted_text, jd_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, filename, pdf_bytes, text, jd_text),
        )
        conn.commit()
        upload_id = int(cursor.lastrowid)

    return UploadResponse(
        upload_id=upload_id,
        filename=filename,
        extracted_text=text,
        jd_text=jd_text,
    )
