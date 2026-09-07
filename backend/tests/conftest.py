"""Shared fixtures for the backend tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "test.sqlite3",
        frontend_dir=tmp_path / "no-frontend",
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture()
def marketing_pdf_bytes() -> bytes:
    return (FIXTURES / "case-02-marketing-partial" / "cv.pdf").read_bytes()
