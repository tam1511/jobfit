"""Unit tests for the rewrite() entry point and prompt builder."""

from __future__ import annotations

import pytest

from app.optimise import (
    OptimiseError,
    OptimiseOutcome,
    RewriteSource,
    TranscriptMessage,
    build_user_message,
    rewrite,
)
from app.scoring import ScoreGap


GAP = ScoreGap(
    severity="high",
    evidence="HubSpot experience is a stated requirement and the CV shows none.",
    suggestion="Ask about campaign tooling from prior roles.",
)


def _ok_ask() -> dict:
    return {
        "kind": "ask",
        "question": "Have you used any marketing automation tools?",
        "action": None,
        "original_bullet": None,
        "rewritten_bullet": None,
        "sources": [],
        "reason": None,
    }


def _ok_rewrite() -> dict:
    return {
        "kind": "rewrite",
        "question": None,
        "action": "rewrite",
        "original_bullet": "Ran Google Ads campaigns.",
        "rewritten_bullet": "Ran Google Ads campaigns spending 60k EUR quarterly.",
        "sources": [
            {"text": "60k EUR", "origin": "user"},
        ],
        "reason": None,
    }


def test_build_user_message_contains_gap_and_cv_and_transcript() -> None:
    msg = build_user_message(
        cv_text="- Sample bullet.",
        gap=GAP,
        gap_index=0,
        total_gaps=2,
        transcript=[TranscriptMessage(role="user", content="I have used Mailchimp.")],
    )
    assert "CURRENT GAP (1 of 2, severity: high)" in msg
    assert GAP.evidence in msg
    assert "- Sample bullet." in msg
    assert "user: I have used Mailchimp." in msg


def test_build_user_message_flags_empty_transcript() -> None:
    msg = build_user_message(
        cv_text="cv",
        gap=GAP,
        gap_index=0,
        total_gaps=1,
        transcript=[],
    )
    assert "no messages yet" in msg


def test_rewrite_ask_outcome_returned_verbatim() -> None:
    def stub(_system: str, _user: str, *, api_key: str, model: str) -> dict:
        return _ok_ask()

    out = rewrite(
        cv_text="cv",
        gap=GAP,
        gap_index=0,
        total_gaps=1,
        transcript=[],
        api_key="k",
        model="m",
        call=stub,
    )
    assert isinstance(out, OptimiseOutcome)
    assert out.kind == "ask"
    assert out.question == "Have you used any marketing automation tools?"


def test_rewrite_grounded_rewrite_passes_grounding_check() -> None:
    def stub(_system: str, _user: str, *, api_key: str, model: str) -> dict:
        return _ok_rewrite()

    out = rewrite(
        cv_text="Ran Google Ads campaigns.",
        gap=GAP,
        gap_index=0,
        total_gaps=1,
        transcript=[TranscriptMessage(role="user", content="Spent 60k EUR quarterly on Google Ads")],
        api_key="k",
        model="m",
        call=stub,
    )
    assert out.kind == "rewrite"
    assert out.rewritten_bullet is not None
    assert out.sources == [RewriteSource(text="60k EUR", origin="user")]


def test_rewrite_fabricated_metric_raises_fabrication_error() -> None:
    def stub(_system: str, _user: str, *, api_key: str, model: str) -> dict:
        return {
            "kind": "rewrite",
            "question": None,
            "action": "rewrite",
            "original_bullet": "Ran Google Ads campaigns.",
            "rewritten_bullet": "Ran Google Ads campaigns hitting 5.5 ROAS.",
            "sources": [],
            "reason": None,
        }

    from app.optimise import FabricationError

    with pytest.raises(FabricationError):
        rewrite(
            cv_text="Ran Google Ads campaigns.",
            gap=GAP,
            gap_index=0,
            total_gaps=1,
            transcript=[],
            api_key="k",
            model="m",
            call=stub,
        )


def test_rewrite_missing_api_key_fails_fast() -> None:
    calls: list[int] = []

    def stub(_system: str, _user: str, *, api_key: str, model: str) -> dict:
        calls.append(1)
        return _ok_ask()

    with pytest.raises(OptimiseError):
        rewrite(
            cv_text="cv",
            gap=GAP,
            gap_index=0,
            total_gaps=1,
            transcript=[],
            api_key="",
            model="m",
            call=stub,
        )
    assert calls == []


def test_rewrite_retries_once_on_transient_error() -> None:
    attempts: list[int] = []

    def flaky(_system: str, _user: str, *, api_key: str, model: str) -> dict:
        attempts.append(1)
        if len(attempts) == 1:
            raise OptimiseError("transient")
        return _ok_ask()

    out = rewrite(
        cv_text="cv",
        gap=GAP,
        gap_index=0,
        total_gaps=1,
        transcript=[],
        api_key="k",
        model="m",
        call=flaky,
    )
    assert out.kind == "ask"
    assert len(attempts) == 2


def test_rewrite_gives_up_after_second_failure() -> None:
    attempts: list[int] = []

    def always_fail(_system: str, _user: str, *, api_key: str, model: str) -> dict:
        attempts.append(1)
        raise OptimiseError("nope")

    with pytest.raises(OptimiseError):
        rewrite(
            cv_text="cv",
            gap=GAP,
            gap_index=0,
            total_gaps=1,
            transcript=[],
            api_key="k",
            model="m",
            call=always_fail,
        )
    assert len(attempts) == 2


def test_rewrite_response_missing_required_field_raises() -> None:
    def stub(_system: str, _user: str, *, api_key: str, model: str) -> dict:
        return {
            "kind": "rewrite",
            "question": None,
            "action": None,  # required for kind=rewrite
            "original_bullet": None,
            "rewritten_bullet": None,
            "sources": [],
            "reason": None,
        }

    with pytest.raises(OptimiseError):
        rewrite(
            cv_text="cv",
            gap=GAP,
            gap_index=0,
            total_gaps=1,
            transcript=[],
            api_key="k",
            model="m",
            call=stub,
        )
