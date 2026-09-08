"""Fetch a job description from a URL.

Thin router. All logic (URL validation, HTTP + browser passes, content
extraction) lives in ``app.jd_fetch``. This module maps ``JdFetchError``
to HTTP.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import CurrentUser, current_user
from app.jd_fetch import FetchedJd, JdFetchError


router = APIRouter(prefix="/api/jd", tags=["jd"])


class FetchRequest(BaseModel):
    url: str


@router.post("/fetch", response_model=FetchedJd)
def fetch(
    payload: FetchRequest,
    request: Request,
    _user: CurrentUser = Depends(current_user),
) -> FetchedJd:
    try:
        return request.app.state.jd_fetch_fn(payload.url)
    except JdFetchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
