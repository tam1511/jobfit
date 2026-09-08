"""Password hashing, session tokens, and the current-user dependency.

Sessions are opaque random tokens stored in the ``sessions`` table and
delivered to the browser as an HTTP-only cookie. The cookie is the only
thing the server trusts — no client-supplied ``user_id`` is honoured.
"""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, Request


SESSION_COOKIE = "jobfit_session"
SESSION_TTL = timedelta(days=30)


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    name: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# Precomputed once at import so the login timing path always pays the bcrypt
# cost when no user row is found. Prevents "email exists?" enumeration.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-parity")


def verify_password_or_dummy(password: str, password_hash: str | None) -> bool:
    """Verify against the given hash, or against a dummy hash if None.

    Returns False in both the wrong-password and unknown-user cases while
    performing bcrypt work either way.
    """
    if password_hash is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return False
    return verify_password(password, password_hash)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def issue_session(conn: sqlite3.Connection, user_id: int) -> tuple[str, datetime]:
    """Insert a fresh session row and return (token, expires_at)."""
    token = secrets.token_urlsafe(32)
    expires_at = _now() + SESSION_TTL
    conn.execute(
        "INSERT INTO sessions(token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at.isoformat()),
    )
    return token, expires_at


def revoke_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def _lookup_session(conn: sqlite3.Connection, token: str) -> CurrentUser | None:
    row = conn.execute(
        """
        SELECT users.id, users.email, users.name, sessions.expires_at
        FROM sessions JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ?
        """,
        (token,),
    ).fetchone()
    if row is None:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at <= _now():
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    return CurrentUser(id=row["id"], email=row["email"], name=row["name"])


def current_user(request: Request) -> CurrentUser:
    """FastAPI dependency: resolve the session cookie into a CurrentUser or 401."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    with closing(request.app.state.db_connect()) as conn, conn:
        user = _lookup_session(conn, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user


def optional_current_user(request: Request) -> CurrentUser | None:
    """Same as current_user but returns None instead of raising."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with closing(request.app.state.db_connect()) as conn, conn:
        return _lookup_session(conn, token)
