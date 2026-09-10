"""Endpoint tests for the download-rewritten-PDF route.

Drives the state machine end-to-end via the real optimise router so the
test exercises the same paths that write ``optimise_rewrites`` rows in
production. PDF text is round-tripped back through pypdf to prove the
substitution actually landed in the rendered file.
"""

from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.config import Settings
from app.main import create_app
from app.optimise import OptimiseOutcome
from app.scoring import ScoreCategory, ScoreGap, ScoreResult, weighted_overall
from tests.conftest import DEFAULT_CREDENTIALS, register


HIGH = ScoreGap(severity="high", evidence="Needs Google Ads spend detail.", suggestion="Ask.")

ORIGINAL_BULLET = "Ran paid campaigns on Google Ads, managing a monthly budget of USD 4k"
REWRITTEN_BULLET = (
    "Ran paid campaigns on Google Ads and LinkedIn Ads, managing a monthly budget of USD 4k"
)


def _score() -> ScoreResult:
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
        gaps=[HIGH],
        matched_keywords=[],
        missing_keywords=[],
    )


def _rewrite_outcome_fn(**_):
    return OptimiseOutcome(
        kind="rewrite",
        question=None,
        action="rewrite",
        original_bullet=ORIGINAL_BULLET,
        rewritten_bullet=REWRITTEN_BULLET,
        reason=None,
    )


def _client(settings: Settings, optimise_fn=None) -> TestClient:
    scored = _score()
    app = create_app(
        settings,
        score_fn=lambda _cv, _jd: scored,
        optimise_fn=optimise_fn,
    )
    return TestClient(app)


def _upload(client: TestClient, pdf: bytes) -> int:
    resp = client.post(
        "/api/uploads",
        data={"company": "Acme", "role_title": "Manager", "jd_text": "role"},
        files={"cv": ("cv.pdf", pdf, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["upload_id"])


def _start(client: TestClient, upload_id: int) -> int:
    body = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()
    return int(body["session_id"])


def _send(client: TestClient, session_id: int, content: str) -> None:
    resp = client.post(f"/api/optimise/{session_id}/message", json={"content": content})
    assert resp.status_code == 200, resp.text


def test_requires_authentication(settings: Settings) -> None:
    with _client(settings) as client:
        response = client.get("/api/uploads/1/rewritten.pdf")
        assert response.status_code == 401


def test_404_when_upload_belongs_to_another_user(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client(settings, optimise_fn=_rewrite_outcome_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)

        client.cookies.clear()
        register(client, email="other@example.com", name="Other")

        response = client.get(f"/api/uploads/{upload_id}/rewritten.pdf")
        assert response.status_code == 404


def test_404_when_upload_has_no_optimise_session(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client(settings) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)

        response = client.get(f"/api/uploads/{upload_id}/rewritten.pdf")
        assert response.status_code == 404


def test_409_when_session_has_no_rewrite_rows(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client(settings) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        _start(client, upload_id)  # session exists but no messages sent -> no rewrites

        response = client.get(f"/api/uploads/{upload_id}/rewritten.pdf")
        assert response.status_code == 409


def test_409_when_only_skip_rows_present(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    def skip_fn(**_):
        return OptimiseOutcome(
            kind="skip", question=None, action=None,
            original_bullet=None, rewritten_bullet=None, reason="no exp",
        )

    with _client(settings, optimise_fn=skip_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = _start(client, upload_id)
        _send(client, session_id, "I have no experience with that.")

        response = client.get(f"/api/uploads/{upload_id}/rewritten.pdf")
        assert response.status_code == 409


def test_add_only_session_still_produces_downloadable_pdf(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    """A session whose only content-producing outcome is an ``add`` must
    still return a PDF. Previously the WHERE clause required
    ``action = 'rewrite'`` and 409'd on add-only sessions, which meant
    the frontend surfaced a Download button that always failed.
    """
    ADDED_BULLET = "Delivered 3 A/B tests lifting signup conversion by 18%."

    def add_fn(**_):
        return OptimiseOutcome(
            kind="rewrite",
            question=None,
            action="add",
            original_bullet=None,
            rewritten_bullet=ADDED_BULLET,
            reason=None,
        )

    with _client(settings, optimise_fn=add_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = _start(client, upload_id)
        _send(
            client, session_id,
            "I ran 3 A/B tests lifting signup conversion by 18%.",
        )

        response = client.get(f"/api/uploads/{upload_id}/rewritten.pdf")
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"%PDF-")
        reader = PdfReader(BytesIO(response.content))
        text = "\n".join(page.extract_text() for page in reader.pages)
        # The added bullet must show up under the highlights section.
        assert "ADDITIONAL HIGHLIGHTS" in text
        assert "A/B tests" in text
        assert "18%" in text


def test_returns_pdf_with_correct_headers_and_content(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client(settings, optimise_fn=_rewrite_outcome_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = _start(client, upload_id)
        _send(client, session_id, "We also ran LinkedIn Ads alongside Google Ads.")

        response = client.get(f"/api/uploads/{upload_id}/rewritten.pdf")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment; filename=")
        assert "Mai-Acme-Manager.pdf" in disposition

        assert response.content.startswith(b"%PDF-")
        reader = PdfReader(BytesIO(response.content))
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "LinkedIn Ads" in text
