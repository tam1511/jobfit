"""Endpoint tests for the Optimise chat.

Uses a live-DB TestClient with an injectable ``optimise_fn`` so we can
drive the state machine deterministically without hitting OpenRouter.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.optimise import FabricationError, OptimiseError, OptimiseOutcome, RewriteSource
from app.scoring import ScoreCategory, ScoreGap, ScoreResult, weighted_overall
from tests.conftest import DEFAULT_CREDENTIALS, register


def _register(client: TestClient, email: str = DEFAULT_CREDENTIALS["email"]) -> None:
    client.post("/api/auth/register", json={**DEFAULT_CREDENTIALS, "email": email})


def _upload(client: TestClient, pdf: bytes) -> int:
    resp = client.post(
        "/api/uploads",
        data={"company": "Acme", "role_title": "Manager", "jd_text": "role"},
        files={"cv": ("cv.pdf", pdf, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["upload_id"])


def _score_with_gaps(gaps: list[ScoreGap]) -> ScoreResult:
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
        gaps=gaps,
        matched_keywords=[],
        missing_keywords=[],
    )


HIGH_A = ScoreGap(severity="high", evidence="Needs HubSpot.", suggestion="Ask.")
HIGH_B = ScoreGap(severity="high", evidence="Needs A/B testing.", suggestion="Ask.")
MEDIUM = ScoreGap(severity="medium", evidence="Needs LinkedIn Ads.", suggestion="Ask.")
LOW = ScoreGap(severity="low", evidence="Trivial gap.", suggestion="Ignore.")


def _client_with_gaps(
    settings: Settings,
    gaps: list[ScoreGap],
    optimise_fn=None,
) -> TestClient:
    scored = _score_with_gaps(gaps)
    app = create_app(
        settings,
        score_fn=lambda _cv, _jd: scored,
        optimise_fn=optimise_fn,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# Auth + ownership
# ---------------------------------------------------------------------------

def test_start_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/optimise/start", json={"upload_id": 1})
    assert response.status_code == 401


def test_start_404_for_upload_owned_by_someone_else(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client_with_gaps(settings, [HIGH_A]) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)

        client.cookies.clear()
        register(client, email="other@example.com", name="Other")

        response = client.post("/api/optimise/start", json={"upload_id": upload_id})
        assert response.status_code == 404


def test_get_session_404_for_wrong_user(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client_with_gaps(settings, [HIGH_A]) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        client.cookies.clear()
        register(client, email="other@example.com", name="Other")

        response = client.get(f"/api/optimise/{session_id}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Gap filtering + preconditions
# ---------------------------------------------------------------------------

def test_start_filters_out_low_severity_gaps(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client_with_gaps(settings, [HIGH_A, MEDIUM, LOW]) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        body = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()
        assert [g["severity"] for g in body["gaps"]] == ["high", "medium"]


def test_start_orders_high_before_medium(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client_with_gaps(settings, [MEDIUM, HIGH_A, HIGH_B]) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        body = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()
        assert [g["evidence"] for g in body["gaps"]] == [
            HIGH_A.evidence,
            HIGH_B.evidence,
            MEDIUM.evidence,
        ]


def test_start_409_when_no_walkable_gaps(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client_with_gaps(settings, [LOW]) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        response = client.post("/api/optimise/start", json={"upload_id": upload_id})
        assert response.status_code == 409


def test_start_is_idempotent_for_same_upload(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client_with_gaps(settings, [HIGH_A]) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        first = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()
        second = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()
        assert first["session_id"] == second["session_id"]


# ---------------------------------------------------------------------------
# Message flow
# ---------------------------------------------------------------------------

def test_ask_outcome_appends_assistant_message_without_advancing(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    def ask_fn(**_):
        return OptimiseOutcome(
            kind="ask",
            question="Which channels did you run?",
            action=None,
            original_bullet=None,
            rewritten_bullet=None,
            sources=[],
            reason=None,
        )

    with _client_with_gaps(settings, [HIGH_A, MEDIUM], optimise_fn=ask_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        body = client.post(
            f"/api/optimise/{session_id}/message", json={"content": "I ran email and Google Ads."}
        ).json()
        assert body["current_gap_index"] == 0
        assert body["status"] == "active"
        assert body["transcript"][0]["content"] == "I ran email and Google Ads."
        assert body["transcript"][1]["role"] == "assistant"
        assert "Which channels" in body["transcript"][1]["content"]
        assert body["rewrites"] == []


def test_rewrite_outcome_persists_and_advances(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    def rewrite_fn(*, cv_text, transcript, **_):
        return OptimiseOutcome(
            kind="rewrite",
            question=None,
            action="rewrite",
            original_bullet="Ran Google Ads campaigns.",
            rewritten_bullet="Ran Google Ads campaigns spending 60k EUR quarterly.",
            sources=[RewriteSource(text="60k EUR quarterly", origin="user")],
            reason=None,
        )

    with _client_with_gaps(settings, [HIGH_A, MEDIUM], optimise_fn=rewrite_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        body = client.post(
            f"/api/optimise/{session_id}/message",
            json={"content": "I spent 60k EUR quarterly on Google Ads campaigns."},
        ).json()

        assert body["current_gap_index"] == 1
        assert body["status"] == "active"
        assert len(body["rewrites"]) == 1
        rw = body["rewrites"][0]
        assert rw["action"] == "rewrite"
        assert rw["rewritten_bullet"] == "Ran Google Ads campaigns spending 60k EUR quarterly."
        assert rw["sources"][0]["text"] == "60k EUR quarterly"


def test_model_skip_advances_and_records_reason(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    def skip_fn(**_):
        return OptimiseOutcome(
            kind="skip",
            question=None,
            action=None,
            original_bullet=None,
            rewritten_bullet=None,
            sources=[],
            reason="Candidate confirmed no HubSpot experience.",
        )

    with _client_with_gaps(settings, [HIGH_A, MEDIUM], optimise_fn=skip_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        body = client.post(
            f"/api/optimise/{session_id}/message", json={"content": "No, I have not used it."}
        ).json()
        assert body["current_gap_index"] == 1
        assert body["rewrites"][0]["action"] == "skip"
        assert "HubSpot" in body["rewrites"][0]["reason"]


def test_fabrication_error_is_treated_as_unfillable_skip(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    def liar_fn(**_):
        raise FabricationError("Rewritten bullet contains unsupported claim: '45%'")

    with _client_with_gaps(settings, [HIGH_A], optimise_fn=liar_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        body = client.post(
            f"/api/optimise/{session_id}/message", json={"content": "I did some things."}
        ).json()
        assert body["status"] == "done"
        assert body["rewrites"][0]["action"] == "skip"
        assert "invent" in body["rewrites"][0]["reason"].lower()


def test_user_skip_advances_without_calling_model(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    calls: list[int] = []

    def counting_fn(**_):
        calls.append(1)
        return OptimiseOutcome(kind="ask", question="q", action=None, original_bullet=None,
                               rewritten_bullet=None, sources=[], reason=None)

    with _client_with_gaps(settings, [HIGH_A, MEDIUM], optimise_fn=counting_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        body = client.post(f"/api/optimise/{session_id}/skip").json()
        assert body["current_gap_index"] == 1
        assert body["rewrites"][0]["action"] == "skip"
        assert calls == []


def test_completing_last_gap_marks_session_done(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    def skip_fn(**_):
        return OptimiseOutcome(kind="skip", question=None, action=None, original_bullet=None,
                               rewritten_bullet=None, sources=[], reason="none")

    with _client_with_gaps(settings, [HIGH_A], optimise_fn=skip_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        body = client.post(
            f"/api/optimise/{session_id}/message", json={"content": "no"}
        ).json()
        assert body["status"] == "done"

        follow_up = client.post(f"/api/optimise/{session_id}/message", json={"content": "hi"})
        assert follow_up.status_code == 409


def test_blank_message_is_rejected(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    with _client_with_gaps(settings, [HIGH_A]) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        response = client.post(
            f"/api/optimise/{session_id}/message", json={"content": "   "}
        )
        assert response.status_code == 422


def test_openrouter_error_returns_502(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    def crash(**_):
        raise OptimiseError("upstream down")

    with _client_with_gaps(settings, [HIGH_A], optimise_fn=crash) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        response = client.post(
            f"/api/optimise/{session_id}/message", json={"content": "hello"}
        )
        assert response.status_code == 502
