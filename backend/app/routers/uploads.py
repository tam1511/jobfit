"""Upload a CV PDF plus a pasted JD, extract text, score, store the pair."""

from __future__ import annotations

from contextlib import closing

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.pdf_extract import PdfExtractionError, extract_text
from app.scoring import (
    ScoreResult,
    ScoringError,
    cache_key,
    persist_score,
    read_score_for_upload,
)


router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class UploadResponse(BaseModel):
    upload_id: int
    filename: str
    extracted_text: str
    jd_text: str
    score: ScoreResult


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

    settings = request.app.state.settings
    with closing(request.app.state.db_connect()) as conn:
        user_row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is None:
            # 422: the user_id form field references a row that does not
            # exist. Kept distinct from 404 so the frontend can tell a
            # stale session apart from a missing route or resource.
            raise HTTPException(status_code=422, detail="Unknown user.")

    # Score first. If scoring fails we do not persist the upload, so the
    # client can retry cleanly without leaving orphan rows behind.
    try:
        result = request.app.state.score_fn(text, jd_text)
    except ScoringError as exc:
        raise HTTPException(status_code=502, detail=f"Scoring failed: {exc}") from exc

    filename = cv.filename or "cv.pdf"
    key = cache_key(text, jd_text, settings.openrouter_model)

    with closing(request.app.state.db_connect()) as conn, conn:
        cursor = conn.execute(
            "INSERT INTO uploads(user_id, filename, file_bytes, extracted_text, jd_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, filename, pdf_bytes, text, jd_text),
        )
        upload_id = int(cursor.lastrowid)
        persist_score(conn, upload_id, result, key=key, model=settings.openrouter_model)

    return UploadResponse(
        upload_id=upload_id,
        filename=filename,
        extracted_text=text,
        jd_text=jd_text,
        score=result,
    )


@router.get("/{upload_id}/score", response_model=ScoreResult)
def get_upload_score(upload_id: int, request: Request) -> ScoreResult:
    """Return the stored score for a given upload, or 404 if none."""
    with closing(request.app.state.db_connect()) as conn:
        upload = conn.execute(
            "SELECT id FROM uploads WHERE id = ?", (upload_id,)
        ).fetchone()
    if upload is None:
        raise HTTPException(status_code=404, detail="Unknown upload.")
    result = read_score_for_upload(upload_id, request.app.state.db_connect)
    if result is None:
        raise HTTPException(status_code=404, detail="No score for this upload.")
    return result
