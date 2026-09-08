"""Runtime configuration.

Everything the app needs to know about the filesystem it lives in and the
model provider it talks to. Kept flat: environment variables win, sensible
defaults for local dev.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]

# Read .env at import time. Missing file is a no-op. In production the same
# variables are injected directly by the container runtime.
load_dotenv(REPO_ROOT / ".env")


DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    frontend_dir: Path
    openrouter_api_key: str
    openrouter_model: str


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("JOBFIT_DATA_DIR", REPO_ROOT / "backend" / ".data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(os.environ.get("JOBFIT_DB_PATH", data_dir / "jobfit.sqlite3"))
    frontend_dir = Path(os.environ.get("JOBFIT_FRONTEND_DIR", REPO_ROOT / "frontend" / "out"))
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    return Settings(
        data_dir=data_dir,
        db_path=db_path,
        frontend_dir=frontend_dir,
        openrouter_api_key=api_key,
        openrouter_model=model,
    )
