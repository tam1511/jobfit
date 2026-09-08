"""Endpoint-level tests for scoring: POST /api/uploads and GET /{id}/score.

Uses a live-DB TestClient with a controllable in-process scorer so we can
assert cache behaviour, error surfacing, and retry policy without HTTP.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.scoring import ScoreCategory, ScoreGap, ScoreResult, ScoringError, score, weighted_overall
from tests.conftest import DEFAULT_CREDENTIALS


def _register(client: TestClient, email: str = DEFAULT_CREDENTIALS["email"]) -> None:
    payload = {**DEFAULT_CREDENTIALS, "email": email}
    client.post("/api/auth/register", json=payload)


def _upload(client: TestClient, pdf: bytes, jd: str = "Digital Marketing Manager"):
    return client.post(
        "/api/uploads",
        data={"company": "Acme", "role_title": "Manager", "jd_text": jd},
        files={"cv": ("cv.pdf", pdf, "application/pdf")},
    )


def _canned() -> ScoreResult:
    breakdown = [
        ScoreCategory(category="Hard Skills Match", score=60, weight=30, evidence="ok"),
        ScoreCategory(category="Experience Match", score=70, weight=25, evidence="ok"),
        ScoreCategory(category="ATS Keywords", score=55, weight=20, evidence="ok"),
        ScoreCategory(category="Quantified Achievements", score=65, weight=15, evidence="ok"),
        ScoreCategory(category="Formatting & Length", score=80, weight=10, evidence="ok"),
    ]
    return ScoreResult(
        overall_score=weighted_overall(breakdown),
        breakdown=breakdown,
        gaps=[ScoreGap(severity="high", evidence="e", suggestion="s")],
        matched_keywords=["python"],
        missing_keywords=["go"],
    )


def _make_client(settings: Settings, score_fn) -> TestClient:
    app = create_app(settings, score_fn=score_fn)
    return TestClient(app)


def test_post_uploads_persists_score_row(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _make_client(settings, lambda _cv, _jd: _canned()) as client:
        _register(client)
        response = _upload(client, marketing_pdf_bytes)
        upload_id = response.json()["upload_id"]
        follow_up = client.get(f"/api/uploads/{upload_id}/score")
        assert follow_up.status_code == 200
        assert follow_up.json()["overall_score"] == _canned().overall_score


def test_scoring_failure_returns_502_and_no_upload_row(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    def fail(_cv: str, _jd: str) -> ScoreResult:
        raise ScoringError("boom")

    with _make_client(settings, fail) as client:
        _register(client)
        response = _upload(client, marketing_pdf_bytes)
        assert response.status_code == 502
        assert client.get("/api/uploads/1/score").status_code == 404


def test_get_score_404_for_unknown_upload(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _make_client(settings, lambda _cv, _jd: _canned()) as client:
        _register(client)
        response = client.get("/api/uploads/9999/score")
        assert response.status_code == 404


def test_repeat_upload_hits_scores_cache(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    """A second identical CV+JD uses the real ``score()`` and should return the
    same JSON without a second HTTP call."""
    calls: list[int] = []

    def fake_http(cv_text: str, jd_text: str, *, api_key: str, model: str) -> dict:
        calls.append(1)
        return {
            "breakdown": [
                {"category": "Hard Skills Match", "score": 60, "evidence": "ok"},
                {"category": "Experience Match", "score": 70, "evidence": "ok"},
                {"category": "ATS Keywords", "score": 55, "evidence": "ok"},
                {"category": "Quantified Achievements", "score": 65, "evidence": "ok"},
                {"category": "Formatting & Length", "score": 80, "evidence": "ok"},
            ],
            "gaps": [],
            "matched_keywords": ["python"],
            "missing_keywords": ["go"],
        }

    app = None

    def real_score_fn(cv_text: str, jd_text: str) -> ScoreResult:
        return score(
            cv_text,
            jd_text,
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            db_connect=app.state.db_connect,
            call=fake_http,
        )

    app = create_app(settings, score_fn=real_score_fn)
    with TestClient(app) as client:
        _register(client)
        first = _upload(client, marketing_pdf_bytes)
        second = _upload(client, marketing_pdf_bytes)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["score"] == second.json()["score"]
        assert len(calls) == 1


def test_retry_once_then_success(settings: Settings, marketing_pdf_bytes: bytes) -> None:
    attempts: list[int] = []

    def flaky(cv_text: str, jd_text: str, *, api_key: str, model: str) -> dict:
        attempts.append(1)
        if len(attempts) == 1:
            raise ScoringError("transient")
        return {
            "breakdown": [
                {"category": "Hard Skills Match", "score": 50, "evidence": ""},
                {"category": "Experience Match", "score": 50, "evidence": ""},
                {"category": "ATS Keywords", "score": 50, "evidence": ""},
                {"category": "Quantified Achievements", "score": 50, "evidence": ""},
                {"category": "Formatting & Length", "score": 50, "evidence": ""},
            ],
            "gaps": [],
            "matched_keywords": [],
            "missing_keywords": [],
        }

    app = None

    def real_score_fn(cv_text: str, jd_text: str) -> ScoreResult:
        return score(
            cv_text,
            jd_text,
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            db_connect=app.state.db_connect,
            call=flaky,
        )

    app = create_app(settings, score_fn=real_score_fn)
    with TestClient(app) as client:
        _register(client)
        response = _upload(client, marketing_pdf_bytes)
        assert response.status_code == 200
        assert len(attempts) == 2


def test_retry_gives_up_after_second_failure(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    attempts: list[int] = []

    def always_fail(cv_text: str, jd_text: str, *, api_key: str, model: str) -> dict:
        attempts.append(1)
        raise ScoringError("nope")

    app = None

    def real_score_fn(cv_text: str, jd_text: str) -> ScoreResult:
        return score(
            cv_text,
            jd_text,
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            db_connect=app.state.db_connect,
            call=always_fail,
        )

    app = create_app(settings, score_fn=real_score_fn)
    with TestClient(app) as client:
        _register(client)
        response = _upload(client, marketing_pdf_bytes)
        assert response.status_code == 502
        assert len(attempts) == 2
