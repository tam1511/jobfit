"""Endpoint tests for the Optimise chat.

Uses a live-DB TestClient with an injectable ``optimise_fn`` so we can
drive the state machine deterministically without hitting OpenRouter.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.optimise import (
    MAX_ASKS_PER_GAP,
    FabricationError,
    OptimiseError,
    OptimiseOutcome,
)
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
            reason="Candidate confirmed no HubSpot experience.",
        )

    with _client_with_gaps(settings, [HIGH_A, MEDIUM], optimise_fn=skip_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        # "No, I have not used it." matches the denial detector so the
        # router short-circuits before the model runs. The final skip
        # reason is the router's own, not skip_fn's — the model wasn't
        # asked. This test now verifies the message-level skip
        # behaviour, not the model-level one; a separate test drives
        # the model to return kind='skip' without a denial in the
        # user's message.
        body = client.post(
            f"/api/optimise/{session_id}/message",
            json={"content": "Yes but only tangentially — not sure it counts."},
        ).json()
        assert body["current_gap_index"] == 1
        assert body["rewrites"][0]["action"] == "skip"
        assert "HubSpot" in body["rewrites"][0]["reason"]


def test_fabrication_error_records_unavailable_not_user_skip(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    """FabricationError is a system failure, not the user telling us
    they have no experience. It must not be presented as a "skip" in
    the UI (which reads as the user's decision); it advances the gap
    but with a distinct action so the frontend can label it correctly.
    """
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
        rw = body["rewrites"][0]
        assert rw["action"] == "unavailable"
        # The user's "no experience" language must not appear on a
        # system-caused failure — that would blame the user.
        assert "no relevant experience" not in (rw["reason"] or "").lower()
        assert "unsupported claim" in rw["reason"].lower()


def test_mixed_answer_with_affirmative_claim_is_not_treated_as_denial(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    """RED reproduction (bug reported after PR #16): a candidate reply that
    AFFIRMS one skill while admitting they lack another was mislabelled as
    a full denial. The router's short-circuit fired on "have not yet worked
    on large-scale enterprise AI deployments" and skipped the entire gap
    with reason "Candidate indicated no relevant experience", throwing
    away the affirmative half of the answer — the SPSS experience they
    just said they had.

    The router's denial short-circuit is for PURE denials only. A message
    that mixes "I have X" with "I have not Y" must reach the model so it
    can either rewrite around the affirmative claim, ask for one more
    concrete detail, or (if the current gap really is about the denied
    thing) legitimately skip via ``kind="skip"``.
    """
    mixed_answer = (
        "I have hands-on experience with SPSS, having used it for statistical "
        "analysis in my previous role. For AI deployment, I have practical "
        "experience deploying models to production, although I have not yet "
        "worked on large-scale enterprise AI deployments."
    )

    calls: list[dict] = []

    def spy_fn(**kw):
        calls.append(kw)
        return OptimiseOutcome(
            kind="ask",
            question="Which SPSS analyses did you run in that role?",
            action=None,
            original_bullet=None,
            rewritten_bullet=None,
            reason=None,
        )

    with _client_with_gaps(settings, [HIGH_A, MEDIUM], optimise_fn=spy_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post(
            "/api/optimise/start", json={"upload_id": upload_id}
        ).json()["session_id"]

        body = client.post(
            f"/api/optimise/{session_id}/message",
            json={"content": mixed_answer},
        ).json()

    assert len(calls) == 1, (
        "model must be called for mixed answers that contain an "
        "affirmative first-person claim — a partial answer is not a denial"
    )
    assert body["current_gap_index"] == 0, "an ask outcome must not advance the gap"
    assert body["rewrites"] == [], (
        "no skip must be recorded — the user just gave us information "
        "we can use"
    )
    # Sanity: the transcript preserves the user's whole answer, and the
    # assistant's reply is the model's question, not the denial short-circuit
    # boilerplate.
    assert body["transcript"][0]["content"] == mixed_answer
    assert "no relevant experience" not in body["transcript"][-1]["content"].lower()


def test_denial_forces_skip_without_calling_model(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    """RED reproduction: today an "I don't have that experience" answer
    still calls the model, which then loops asking clarifying questions
    ("tell me more") or fabricates against the denial. That is exactly
    the behaviour the product exists to not do.

    The redesign detects a denial in the user's message before the
    model is called and records a skip immediately. The model must
    not run at all; the gap must advance; the persisted row must be
    ``action="skip"`` (the user's decision), not ``unavailable``.
    """
    calls: list[int] = []

    def any_fn(**_):
        calls.append(1)
        return OptimiseOutcome(
            kind="ask",
            question="Could you tell me more about that?",
            action=None,
            original_bullet=None,
            rewritten_bullet=None,
            reason=None,
        )

    with _client_with_gaps(settings, [HIGH_A, MEDIUM], optimise_fn=any_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        body = client.post(
            f"/api/optimise/{session_id}/message",
            json={"content": "I don't have that experience."},
        ).json()

        assert calls == [], "model must not be called when the user has denied experience"
        assert body["current_gap_index"] == 1, "denial must advance the gap"
        assert body["rewrites"][-1]["action"] == "skip"


def test_user_skip_advances_without_calling_model(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    calls: list[int] = []

    def counting_fn(**_):
        calls.append(1)
        return OptimiseOutcome(kind="ask", question="q", action=None, original_bullet=None,
                               rewritten_bullet=None, reason=None)

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
                               rewritten_bullet=None, reason="none")

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


def test_ask_count_is_threaded_through_to_optimise_fn(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    """The router must pass the running ``ask_count`` for the current gap
    into ``optimise_fn`` so the prompt (and the hard cap) can see how
    many questions have already been asked.
    """
    seen: list[int] = []

    def ask_fn(*, ask_count: int, **_):
        seen.append(ask_count)
        return OptimiseOutcome(
            kind="ask", question="another?", action=None, original_bullet=None,
            rewritten_bullet=None, reason=None,
        )

    with _client_with_gaps(settings, [HIGH_A], optimise_fn=ask_fn) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        for i in range(3):
            client.post(f"/api/optimise/{session_id}/message", json={"content": f"answer {i}"})
    assert seen == [0, 1, 2]


def test_model_ask_after_question_budget_exhausted_records_unavailable(
    settings: Settings, marketing_pdf_bytes: bytes
) -> None:
    """When the model keeps returning ``ask`` past ``MAX_ASKS_PER_GAP``,
    the router overrides it and advances with an ``unavailable`` outcome
    rather than persisting the extra question. This is the belt-and-
    braces cap on the confirmation-loop bug.
    """
    def always_ask(**_):
        return OptimiseOutcome(
            kind="ask", question="please confirm phrasing?", action=None,
            original_bullet=None, rewritten_bullet=None, reason=None,
        )

    with _client_with_gaps(settings, [HIGH_A], optimise_fn=always_ask) as client:
        register(client)
        upload_id = _upload(client, marketing_pdf_bytes)
        session_id = client.post("/api/optimise/start", json={"upload_id": upload_id}).json()["session_id"]

        # Feed the model MAX_ASKS_PER_GAP replies; each ask leaves the
        # gap open and the assistant message accumulates.
        body: dict = {}
        for i in range(MAX_ASKS_PER_GAP):
            body = client.post(
                f"/api/optimise/{session_id}/message", json={"content": f"reply {i}"}
            ).json()
        assert body["current_gap_index"] == 0
        assert body["rewrites"] == []

        # One more reply — model still asks, but the router refuses to
        # persist another question and instead records unavailable.
        body = client.post(
            f"/api/optimise/{session_id}/message", json={"content": "final reply"}
        ).json()
        assert body["status"] == "done"
        assert body["rewrites"][0]["action"] == "unavailable"
        assert "question limit" in body["rewrites"][0]["reason"].lower()
        # No new question was appended for the final turn — the last
        # assistant message is the "moving on" system message.
        assert "please confirm phrasing" not in body["transcript"][-1]["content"]


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
