"""init_db must survive a pre-accounts (ticket #3) database on disk."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.db import SCHEMA_VERSION, connect, init_db


def _write_pre_accounts_db(path: Path) -> None:
    """Ticket #3 schema: users had no email or password_hash."""
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );
            CREATE TABLE uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL
            );
            """
        )
        conn.execute("INSERT INTO users(name) VALUES ('Mai')")


def test_init_db_resets_pre_accounts_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "old.sqlite3"
    _write_pre_accounts_db(db_path)

    init_db(db_path)

    with closing(connect(db_path)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        assert {"email", "password_hash"}.issubset(cols)
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_init_db_is_idempotent_on_current_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "current.sqlite3"
    init_db(db_path)

    with closing(connect(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO users(email, password_hash, name) VALUES (?, ?, ?)",
            ("a@b.com", "hash", "Alice"),
        )

    init_db(db_path)

    with closing(connect(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_init_db_creates_fresh_when_no_file(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.sqlite3"
    init_db(db_path)
    with closing(connect(db_path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"users", "sessions", "uploads", "scores"}.issubset(tables)
