"""Upload a CV PDF plus a pasted JD, extract text, score, store the pair.

Also lists a user's uploads (grouped in the frontend by company/role for the
history view) and reads or deletes a single upload. All routes require an
authenticated session; ownership is enforced on every per-upload read.
"""

from __future__ import annotations

from contextlib import closing
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from app.auth import CurrentUser, current_user
from app.cv_pdf import apply_rewrites, content_disposition, render_cv_pdf, sanitize_filename
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
    company: str
    role_title: str
    extracted_text: str
    jd_text: str
    jd_url: str | None
    score: ScoreResult


class UploadSummary(BaseModel):
    upload_id: int
    filename: str
    company: str
    role_title: str
    created_at: str
    overall_score: int


class UploadDetail(BaseModel):
    upload_id: int
    filename: str
    company: str
    role_title: str
    extracted_text: str
    jd_text: str
    jd_url: str | None
    created_at: str
    score: ScoreResult


MAX_PDF_BYTES = 10 * 1024 * 1024


def _require_field(value: str, label: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise HTTPException(status_code=422, detail=f"{label} cannot be blank.")
    return stripped


@router.post("", response_model=UploadResponse)
async def create_upload(
    request: Request,
    jd_text: str = Form(...),
    company: str = Form(...),
    role_title: str = Form(...),
    cv: UploadFile = ...,
    user: CurrentUser = Depends(current_user),
    jd_url: str | None = Form(None),
) -> UploadResponse:
    if cv.content_type not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(status_code=415, detail="CV must be a PDF file.")

    jd_text = _require_field(jd_text, "Job description")
    company = _require_field(company, "Company")
    role_title = _require_field(role_title, "Role title")
    jd_url_clean = jd_url.strip() if jd_url else None
    if jd_url_clean == "":
        jd_url_clean = None

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
            "INSERT INTO uploads(user_id, company, role_title, filename, "
            "file_bytes, extracted_text, jd_text, jd_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user.id, company, role_title, filename, pdf_bytes, text, jd_text, jd_url_clean),
        )
        upload_id = int(cursor.lastrowid)
        persist_score(conn, upload_id, result, key=key, model=settings.openrouter_model)

    return UploadResponse(
        upload_id=upload_id,
        filename=filename,
        company=company,
        role_title=role_title,
        extracted_text=text,
        jd_text=jd_text,
        jd_url=jd_url_clean,
        score=result,
    )


@router.get("", response_model=list[UploadSummary])
def list_uploads(
    request: Request,
    user: CurrentUser = Depends(current_user),
    company: str | None = None,
    role_title: str | None = None,
) -> list[UploadSummary]:
    """List current user's uploads, newest first. Optional company/role filter."""
    sql = [
        "SELECT u.id, u.filename, u.company, u.role_title, u.created_at, s.result_json",
        "FROM uploads u LEFT JOIN scores s ON s.upload_id = u.id",
        "WHERE u.user_id = ?",
    ]
    params: list[Any] = [user.id]
    if company is not None:
        sql.append("AND u.company = ?")
        params.append(company)
    if role_title is not None:
        sql.append("AND u.role_title = ?")
        params.append(role_title)
    sql.append("ORDER BY u.created_at DESC, u.id DESC")

    with closing(request.app.state.db_connect()) as conn:
        rows = conn.execute(" ".join(sql), params).fetchall()

    summaries: list[UploadSummary] = []
    for row in rows:
        overall = 0
        if row["result_json"] is not None:
            overall = ScoreResult.model_validate_json(row["result_json"]).overall_score
        summaries.append(
            UploadSummary(
                upload_id=row["id"],
                filename=row["filename"],
                company=row["company"],
                role_title=row["role_title"],
                created_at=row["created_at"],
                overall_score=overall,
            )
        )
    return summaries


def _fetch_owned_upload(request: Request, upload_id: int, user_id: int) -> Any:
    with closing(request.app.state.db_connect()) as conn:
        row = conn.execute(
            "SELECT id, user_id, filename, company, role_title, extracted_text, "
            "jd_text, jd_url, created_at FROM uploads WHERE id = ?",
            (upload_id,),
        ).fetchone()
    if row is None or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Unknown upload.")
    return row


@router.get("/{upload_id}", response_model=UploadDetail)
def get_upload(
    upload_id: int,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> UploadDetail:
    row = _fetch_owned_upload(request, upload_id, user.id)
    score = read_score_for_upload(upload_id, request.app.state.db_connect)
    if score is None:
        raise HTTPException(status_code=404, detail="No score for this upload.")
    return UploadDetail(
        upload_id=row["id"],
        filename=row["filename"],
        company=row["company"],
        role_title=row["role_title"],
        extracted_text=row["extracted_text"],
        jd_text=row["jd_text"],
        jd_url=row["jd_url"],
        created_at=row["created_at"],
        score=score,
    )


@router.get("/{upload_id}/score", response_model=ScoreResult)
def get_upload_score(
    upload_id: int,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> ScoreResult:
    _fetch_owned_upload(request, upload_id, user.id)
    result = read_score_for_upload(upload_id, request.app.state.db_connect)
    if result is None:
        raise HTTPException(status_code=404, detail="No score for this upload.")
    return result


@router.get("/{upload_id}/rewritten.pdf")
def download_rewritten_pdf(
    upload_id: int,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> Response:
    """Render the CV with Optimise rewrites applied and return a PDF.

    Requires an existing optimise session for the upload and at least
    one persisted ``action='rewrite'`` row; the frontend only surfaces
    the download when rewrites exist, so failing hard here catches
    stale clients and prevents "downloaded my own CV unchanged".
    """
    row = _fetch_owned_upload(request, upload_id, user.id)
    with closing(request.app.state.db_connect()) as conn:
        session = conn.execute(
            "SELECT id FROM optimise_sessions WHERE upload_id = ?",
            (upload_id,),
        ).fetchone()
        if session is None:
            raise HTTPException(status_code=404, detail="No optimise session for this upload.")
        rewrites = conn.execute(
            "SELECT action, original_bullet, rewritten_bullet FROM optimise_rewrites "
            "WHERE session_id = ? AND action = 'rewrite' "
            "AND original_bullet IS NOT NULL AND rewritten_bullet IS NOT NULL "
            "ORDER BY id ASC",
            (session["id"],),
        ).fetchall()
    if not rewrites:
        raise HTTPException(status_code=409, detail="No rewritten bullets yet.")

    text = apply_rewrites(row["extracted_text"], [dict(r) for r in rewrites])
    pdf_bytes = render_cv_pdf(text)
    filename = sanitize_filename(user.name, row["company"], row["role_title"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(filename),
            "Cache-Control": "no-store",
        },
    )


@router.delete("/{upload_id}")
def delete_upload(
    upload_id: int,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> dict[str, str]:
    _fetch_owned_upload(request, upload_id, user.id)
    with closing(request.app.state.db_connect()) as conn, conn:
        conn.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
    return {"status": "ok"}
