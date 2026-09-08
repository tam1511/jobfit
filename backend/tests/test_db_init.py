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


def _write_v1_db(path: Path) -> None:
    """Ticket #5 schema: uploads had no jd_url column."""
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                company TEXT NOT NULL,
                role_title TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_bytes BLOB NOT NULL,
                extracted_text TEXT NOT NULL,
                jd_text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute(
            "INSERT INTO users(email, password_hash, name) VALUES (?, ?, ?)",
            ("mai@example.com", "hash", "Mai"),
        )
        conn.execute(
            "INSERT INTO uploads(user_id, company, role_title, filename, file_bytes, extracted_text, jd_text) "
            "VALUES (1, 'Acme', 'Manager', 'cv.pdf', ?, 'text', 'jd')",
            (b"pdf-bytes",),
        )
        conn.execute("PRAGMA user_version = 1")


def test_init_db_migrates_v1_to_v2_adds_jd_url(tmp_path: Path) -> None:
    db_path = tmp_path / "v1.sqlite3"
    _write_v1_db(db_path)

    init_db(db_path)

    with closing(connect(db_path)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(uploads)").fetchall()}
        assert "jd_url" in cols
        row = conn.execute("SELECT company, role_title, jd_url FROM uploads WHERE id=1").fetchone()
        assert row["company"] == "Acme"
        assert row["role_title"] == "Manager"
        assert row["jd_url"] is None
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def _write_v2_db(path: Path) -> None:
    """Ticket #10 schema: uploads has jd_url but no optimise_* tables."""
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                company TEXT NOT NULL,
                role_title TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_bytes BLOB NOT NULL,
                extracted_text TEXT NOT NULL,
                jd_text TEXT NOT NULL,
                jd_url TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute(
            "INSERT INTO users(email, password_hash, name) VALUES (?, ?, ?)",
            ("mai@example.com", "hash", "Mai"),
        )
        conn.execute(
            "INSERT INTO uploads(user_id, company, role_title, filename, file_bytes, extracted_text, jd_text) "
            "VALUES (1, 'Acme', 'Manager', 'cv.pdf', ?, 'text', 'jd')",
            (b"pdf-bytes",),
        )
        conn.execute("PRAGMA user_version = 2")


def test_init_db_migrates_v2_to_v3_adds_optimise_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "v2.sqlite3"
    _write_v2_db(db_path)

    init_db(db_path)

    with closing(connect(db_path)) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"optimise_sessions", "optimise_messages", "optimise_rewrites"}.issubset(tables)
        # Existing data survives.
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0] == 1
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
