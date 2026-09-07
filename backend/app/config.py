"""Runtime configuration.

Everything the app needs to know about the filesystem it lives in.
Kept flat: environment variables win, sensible defaults for local dev.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    frontend_dir: Path


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("JOBFIT_DATA_DIR", REPO_ROOT / "backend" / ".data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(os.environ.get("JOBFIT_DB_PATH", data_dir / "jobfit.sqlite3"))
    frontend_dir = Path(os.environ.get("JOBFIT_FRONTEND_DIR", REPO_ROOT / "frontend" / "out"))
    return Settings(data_dir=data_dir, db_path=db_path, frontend_dir=frontend_dir)
