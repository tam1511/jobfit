"""Shared fixtures for the backend tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.jd_fetch import FetchedJd
from app.main import create_app
from app.optimise import OptimiseOutcome
from app.scoring import ScoreCategory, ScoreGap, ScoreResult, weighted_overall


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "test.sqlite3",
        frontend_dir=tmp_path / "no-frontend",
        openrouter_api_key="test-key",
        openrouter_model="test-model",
        jd_fetch_http_timeout=5.0,
        jd_fetch_browser_timeout=10.0,
        jd_fetch_max_bytes=20 * 1024,
    )


def _canned_marketing_score() -> ScoreResult:
    breakdown = [
        ScoreCategory(category="Hard Skills Match", score=55, weight=30, evidence="SEO and GA4 present; HubSpot and LinkedIn Ads absent."),
        ScoreCategory(category="Experience Match", score=70, weight=25, evidence="Three years in digital marketing; JD asks for 3+."),
        ScoreCategory(category="ATS Keywords", score=60, weight=20, evidence="SEO, Google Analytics, content strategy present."),
        ScoreCategory(category="Quantified Achievements", score=65, weight=15, evidence="Organic sessions 8k to 26k and 60 articles listed."),
        ScoreCategory(category="Formatting & Length", score=80, weight=10, evidence="Standard sections; length appropriate."),
    ]
    return ScoreResult(
        overall_score=weighted_overall(breakdown),
        breakdown=breakdown,
        gaps=[
            ScoreGap(severity="high", evidence="HubSpot experience is a stated requirement and the CV shows none.", suggestion="Ask the candidate about any campaign tooling used in prior roles."),
            ScoreGap(severity="high", evidence="The JD asks for A/B testing on landing pages with a clear methodology.", suggestion="Ask whether the candidate has run experiments and how they called winners."),
            ScoreGap(severity="medium", evidence="Paid acquisition on LinkedIn Ads is required alongside Google Ads.", suggestion="Ask if the candidate has run any paid LinkedIn campaigns, even at small budgets."),
        ],
        matched_keywords=["SEO", "Google Analytics", "content strategy", "editorial calendar", "Google Ads"],
        missing_keywords=["HubSpot", "LinkedIn Ads", "A/B testing", "lead scoring"],
    )


@pytest.fixture()
def canned_score() -> ScoreResult:
    """A ScoreResult for the marketing fixture. Deterministic, no network."""
    return _canned_marketing_score()


def _stub_jd_fetch_fn(url: str) -> FetchedJd:
    """Default JD fetcher: pretends it fetched the URL and returns a stub JD."""
    return FetchedJd(
        jd_text="Fake fetched JD text long enough to look plausible in tests.",
        final_url=url,
        used_browser=False,
    )


def _stub_optimise_fn(**_kwargs) -> OptimiseOutcome:
    """Default optimise turn: an 'ask' outcome. Endpoint tests that need
    other kinds inject their own optimise_fn via create_app."""
    return OptimiseOutcome(
        kind="ask",
        question="Tell me more about that experience.",
        action=None,
        original_bullet=None,
        rewritten_bullet=None,
        sources=[],
        reason=None,
    )


@pytest.fixture()
def client(settings: Settings, canned_score: ScoreResult) -> TestClient:
    """Default client uses stub scorer, JD fetcher, and optimise fn; no network."""
    def stub_score_fn(_cv: str, _jd: str) -> ScoreResult:
        return canned_score
    app = create_app(
        settings,
        score_fn=stub_score_fn,
        jd_fetch_fn=_stub_jd_fetch_fn,
        optimise_fn=_stub_optimise_fn,
    )
    with TestClient(app) as tc:
        yield tc


DEFAULT_CREDENTIALS = {"email": "mai@example.com", "password": "correcthorse", "name": "Mai"}


def register(client: TestClient, **overrides: str) -> dict:
    """Register a fresh user and return the AuthResponse body. Cookie is set on the client."""
    payload = {**DEFAULT_CREDENTIALS, **overrides}
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def authed_client(client: TestClient) -> TestClient:
    """A TestClient with a fresh registered session cookie already set."""
    register(client)
    return client


@pytest.fixture()
def marketing_pdf_bytes() -> bytes:
    return (FIXTURES / "case-02-marketing-partial" / "cv.pdf").read_bytes()
