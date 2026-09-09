"""SQLite access.

Schema is created once and preserved across restarts so user accounts and
application history survive container reboots. ``user_version`` tracks the
current schema. Version 0 is the pre-accounts (#3) shape; version 1 is
the multi-user shape (#5); version 2 adds ``uploads.jd_url`` (#10); version
3 adds the ``optimise_*`` tables (#11); version 4 drops
``optimise_rewrites.sources_json`` (the anti-fabrication redesign — the
model no longer returns sources).

Migration policy:

- Version 0 databases carry no real credentials and are reset on boot.
- Versions >= 1 receive additive migrations only, so real user data
  survives.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


SCHEMA_VERSION = 4

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
    jd_url TEXT,
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

CREATE TABLE IF NOT EXISTS optimise_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id INTEGER NOT NULL UNIQUE REFERENCES uploads(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    current_gap_index INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS optimise_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES optimise_sessions(id) ON DELETE CASCADE,
    gap_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_optimise_messages_session
    ON optimise_messages(session_id, id);

CREATE TABLE IF NOT EXISTS optimise_rewrites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES optimise_sessions(id) ON DELETE CASCADE,
    gap_index INTEGER NOT NULL,
    action TEXT NOT NULL,
    original_bullet TEXT,
    rewritten_bullet TEXT,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_optimise_rewrites_session
    ON optimise_rewrites(session_id, gap_index);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _pre_accounts_shape(conn: sqlite3.Connection) -> bool:
    """A #3 database has a ``users`` table without an ``email`` column."""
    has_users = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if not has_users:
        return False
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    return "email" not in cols


def _apply_migrations(conn: sqlite3.Connection, from_version: int) -> None:
    """Additive migrations from ``from_version`` up to ``SCHEMA_VERSION``."""
    if from_version < 2:
        conn.execute("ALTER TABLE uploads ADD COLUMN jd_url TEXT")
    # v3 additions (optimise_* tables) are created by the executescript() call
    # in init_db() via CREATE TABLE IF NOT EXISTS, so no ALTER is needed here.
    if from_version < 4:
        # v3 -> v4: drop optimise_rewrites.sources_json. The redesign
        # removed the sources round-trip through the LLM entirely.
        # SQLite has supported DROP COLUMN since 3.35 (2021).
        has_sources_col = any(
            row[1] == "sources_json"
            for row in conn.execute("PRAGMA table_info(optimise_rewrites)").fetchall()
        )
        if has_sources_col:
            conn.execute("ALTER TABLE optimise_rewrites DROP COLUMN sources_json")


def init_db(db_path: Path) -> None:
    """Create the schema if missing, migrate forward if it exists.

    Version 0 databases (ticket #3) are reset on boot because they held
    no real credentials. Version 1+ databases get real migrations so
    accounts and history survive.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        with closing(connect(db_path)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            pre_accounts = _pre_accounts_shape(conn)
        if version == 0 and pre_accounts:
            db_path.unlink()
        elif 0 < version < SCHEMA_VERSION:
            with closing(connect(db_path)) as conn, conn:
                _apply_migrations(conn, version)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    with closing(connect(db_path)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
