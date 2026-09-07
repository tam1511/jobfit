"""Fake login. Creates a user row from a name and returns the id.

No password, no verification. Enough to pin the shape of a session so
later tickets can slot real auth in without redoing the frontend.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/session", tags=["session"])


class LoginRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class LoginResponse(BaseModel):
    user_id: int
    name: str


@router.post("", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request) -> LoginResponse:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name cannot be blank.")
    with request.app.state.db_connect() as conn:
        cursor = conn.execute("INSERT INTO users(name) VALUES (?)", (name,))
        conn.commit()
        user_id = int(cursor.lastrowid)
    return LoginResponse(user_id=user_id, name=name)
