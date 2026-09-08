"""Register, login, logout, and identity lookup.

The cookie the client receives is HttpOnly and SameSite=Lax. In
production (``JOBFIT_COOKIE_SECURE=1``) it is also flagged Secure so it
only travels over HTTPS.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from app.auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    CurrentUser,
    current_user,
    hash_password,
    issue_session,
    revoke_session,
    verify_password_or_dummy,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class AuthResponse(BaseModel):
    user_id: int
    email: EmailStr
    name: str


def _cookie_secure() -> bool:
    return os.environ.get("JOBFIT_COOKIE_SECURE", "0") == "1"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        path="/",
    )


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, request: Request, response: Response) -> AuthResponse:
    name = payload.name.strip()
    email = payload.email.lower().strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name cannot be blank.")
    with closing(request.app.state.db_connect()) as conn, conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users(email, password_hash, name) VALUES (?, ?, ?)",
                (email, hash_password(payload.password), name),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="An account with that email already exists.")
        user_id = int(cursor.lastrowid)
        token, _ = issue_session(conn, user_id)
    _set_session_cookie(response, token)
    return AuthResponse(user_id=user_id, email=email, name=name)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> AuthResponse:
    email = payload.email.lower().strip()
    with closing(request.app.state.db_connect()) as conn, conn:
        row = conn.execute(
            "SELECT id, email, name, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        password_hash = row["password_hash"] if row is not None else None
        if not verify_password_or_dummy(payload.password, password_hash) or row is None:
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        token, _ = issue_session(conn, row["id"])
    _set_session_cookie(response, token)
    return AuthResponse(user_id=row["id"], email=row["email"], name=row["name"])


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with closing(request.app.state.db_connect()) as conn, conn:
            revoke_session(conn, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "ok"}


@router.get("/me", response_model=AuthResponse)
def me(user: CurrentUser = Depends(current_user)) -> AuthResponse:
    return AuthResponse(user_id=user.id, email=user.email, name=user.name)
