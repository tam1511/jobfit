"""Router-level tests for POST /api/jd/fetch.

The real fetcher is replaced by an injected stub, so no network or
Playwright is touched.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from fastapi.testclient import TestClient

from app.config import Settings
from app.jd_fetch import FetchedJd, JdFetchError
from app.main import create_app
from app.scoring import ScoreResult

from tests.conftest import register


@contextmanager
def _authed_client_with_fetcher(
    settings: Settings, canned_score: ScoreResult, jd_fetch_fn
) -> Iterator[TestClient]:
    def stub_score_fn(_cv: str, _jd: str) -> ScoreResult:
        return canned_score
    app = create_app(settings, score_fn=stub_score_fn, jd_fetch_fn=jd_fetch_fn)
    with TestClient(app) as tc:
        register(tc)
        yield tc


def test_fetch_requires_auth(client: TestClient) -> None:
    response = client.post("/api/jd/fetch", json={"url": "https://example.com/jobs/1"})
    assert response.status_code == 401


def test_fetch_returns_extracted_jd(authed_client: TestClient) -> None:
    response = authed_client.post(
        "/api/jd/fetch",
        json={"url": "https://example.com/jobs/1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["jd_text"].startswith("Fake fetched JD text")
    assert body["final_url"] == "https://example.com/jobs/1"
    assert body["used_browser"] is False


def test_fetch_maps_user_error_to_400(settings: Settings, canned_score: ScoreResult) -> None:
    def broken(_url: str) -> FetchedJd:
        raise JdFetchError("Bad URL from the user.", status_code=400)

    with _authed_client_with_fetcher(settings, canned_score, broken) as client:
        response = client.post("/api/jd/fetch", json={"url": "https://example.com/x"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Bad URL from the user."


def test_fetch_maps_browser_error_to_502(settings: Settings, canned_score: ScoreResult) -> None:
    def crashy(_url: str) -> FetchedJd:
        raise JdFetchError("Headless browser crashed.", status_code=502)

    with _authed_client_with_fetcher(settings, canned_score, crashy) as client:
        response = client.post("/api/jd/fetch", json={"url": "https://example.com/x"})
    assert response.status_code == 502
    assert "browser" in response.json()["detail"].lower()
