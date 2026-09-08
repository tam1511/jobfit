"""SQLite access.

Schema is created once and preserved across restarts so user accounts and
application history survive container reboots. ``user_version`` tracks the
current schema so we know when a pre-accounts (ticket #3) database is
present and needs to be reset — pre-accounts data had no real users, so a
drop-and-recreate is the honest migration.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);

CREATE TABLE IF NOT EXISTS uploads (
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

CREATE INDEX IF NOT EXISTS idx_uploads_user_company_role
    ON uploads(user_id, company, role_title);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id INTEGER NOT NULL UNIQUE REFERENCES uploads(id) ON DELETE CASCADE,
    cache_key TEXT NOT NULL,
    model_id TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scores_cache_key ON scores(cache_key);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    """Create the schema if missing; reset if a pre-accounts DB is present.

    We stamp ``PRAGMA user_version`` with the current schema. If we find a
    ``user_version = 0`` DB that already has a ``users`` table, it was
    written by ticket #3 with the old name-only schema. Those rows carry
    no credential information and no expectation of durability, so the
    cleanest migration is to remove the file and start fresh.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        with closing(connect(db_path)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            has_users = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
        if version < SCHEMA_VERSION and has_users:
            db_path.unlink()
    with closing(connect(db_path)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
