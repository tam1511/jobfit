"""Cache-Control headers on served static assets and HTML."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.scoring import ScoreResult


def _fake_frontend(root: Path) -> Path:
    frontend = root / "frontend-out"
    (frontend / "app").mkdir(parents=True)
    (frontend / "_next" / "static" / "chunks").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>root</html>")
    (frontend / "app" / "index.html").write_text("<html>app</html>")
    (frontend / "_next" / "static" / "chunks" / "page-abc123.js").write_text("//js")
    return frontend


def _client(tmp_path: Path) -> TestClient:
    frontend = _fake_frontend(tmp_path)
    settings = Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "test.sqlite3",
        frontend_dir=frontend,
        openrouter_api_key="test-key",
        openrouter_model="test-model",
    )

    def stub_score(_cv: str, _jd: str) -> ScoreResult:  # pragma: no cover
        raise AssertionError("scoring should not run in cache-header tests")

    app = create_app(settings, score_fn=stub_score)
    return TestClient(app)


def test_html_routes_send_no_cache(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        for path in ("/", "/app", "/app/"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers["cache-control"] == "no-cache", path


def test_next_static_is_immutable(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/_next/static/chunks/page-abc123.js")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
