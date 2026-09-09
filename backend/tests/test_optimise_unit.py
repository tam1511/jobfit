"""Unit tests for the rewrite() entry point and prompt builder."""

from __future__ import annotations

import pytest

from app.optimise import (
    MAX_ASKS_PER_GAP,
    OptimiseError,
    OptimiseOutcome,
    TranscriptMessage,
    build_user_message,
    extract_bullets,
    is_denial,
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
        "bullet_index": None,
        "rewritten_bullet": None,
        "reason": None,
    }


def _ok_rewrite() -> dict:
    return {
        "kind": "rewrite",
        "question": None,
        "action": "rewrite",
        "bullet_index": 0,
        "rewritten_bullet": "Ran Google Ads campaigns spending 60k EUR quarterly.",
        "reason": None,
    }


def test_build_user_message_contains_gap_and_cv_and_transcript() -> None:
    cv = "- Sample bullet."
    msg = build_user_message(
        cv_text=cv,
        bullets=extract_bullets(cv),
        gap=GAP,
        gap_index=0,
        total_gaps=2,
        transcript=[TranscriptMessage(role="user", content="I have used Mailchimp.")],
    )
    assert "CURRENT GAP (1 of 2, severity: high)" in msg
    assert GAP.evidence in msg
    assert "- Sample bullet." in msg
    assert "user: I have used Mailchimp." in msg


def test_build_user_message_lists_bullets_by_index() -> None:
    cv = "- Bullet one.\n- Bullet two."
    msg = build_user_message(
        cv_text=cv,
        bullets=extract_bullets(cv),
        gap=GAP,
        gap_index=0,
        total_gaps=1,
        transcript=[],
    )
    assert "[0] Bullet one." in msg
    assert "[1] Bullet two." in msg


def test_build_user_message_flags_empty_transcript() -> None:
    msg = build_user_message(
        cv_text="cv",
        bullets=[],
        gap=GAP,
        gap_index=0,
        total_gaps=1,
        transcript=[],
    )
    assert "no messages yet" in msg


def test_build_user_message_shows_ask_budget_under_cap() -> None:
    msg = build_user_message(
        cv_text="cv",
        bullets=[],
        gap=GAP,
        gap_index=0,
        total_gaps=1,
        transcript=[],
        ask_count=1,
    )
    assert f"QUESTIONS ASKED FOR THIS GAP: 1 of {MAX_ASKS_PER_GAP} max" in msg
    assert "question budget exhausted" not in msg


def test_build_user_message_injects_forced_commit_directive_at_cap() -> None:
    msg = build_user_message(
        cv_text="cv",
        bullets=[],
        gap=GAP,
        gap_index=0,
        total_gaps=1,
        transcript=[],
        ask_count=MAX_ASKS_PER_GAP,
    )
    assert "question budget exhausted" in msg
    assert "MUST NOT ask another question" in msg


def test_rewrite_ask_outcome_returned_verbatim() -> None:
    def stub(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
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
    def stub(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
        return _ok_rewrite()

    out = rewrite(
        cv_text="- Ran Google Ads campaigns.",
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
    assert out.original_bullet == "- Ran Google Ads campaigns."


def test_rewrite_resolves_bullet_index_to_canonical_cv_text() -> None:
    """The model returns bullet_index; the backend fills original_bullet
    from the CV so downstream code always has a verbatim substring."""
    cv = "- Ran Google Ads campaigns.\n- Wrote landing page copy."

    def stub(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
        return {
            "kind": "rewrite",
            "question": None,
            "action": "rewrite",
            "bullet_index": 1,
            "rewritten_bullet": "Wrote landing page copy for four seasonal campaigns.",
            "reason": None,
        }

    out = rewrite(
        cv_text=cv,
        gap=GAP,
        gap_index=0,
        total_gaps=1,
        transcript=[TranscriptMessage(role="user", content="Wrote copy for four seasonal campaigns.")],
        api_key="k",
        model="m",
        call=stub,
    )
    assert out.original_bullet == "- Wrote landing page copy."


def test_rewrite_out_of_range_bullet_index_raises() -> None:
    def stub(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
        return {
            "kind": "rewrite",
            "question": None,
            "action": "rewrite",
            "bullet_index": 99,
            "rewritten_bullet": "x",
            "reason": None,
        }

    with pytest.raises(OptimiseError, match="out of range"):
        rewrite(
            cv_text="- Only one bullet.",
            gap=GAP,
            gap_index=0,
            total_gaps=1,
            transcript=[],
            api_key="k",
            model="m",
            call=stub,
        )


def test_rewrite_add_action_leaves_original_bullet_null() -> None:
    def stub(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
        return {
            "kind": "rewrite",
            "question": None,
            "action": "add",
            "bullet_index": None,
            "rewritten_bullet": "Ran 3 A/B tests lifting signup conversion by 18%.",
            "reason": None,
        }

    out = rewrite(
        cv_text="- Some existing bullet.",
        gap=GAP,
        gap_index=0,
        total_gaps=1,
        transcript=[TranscriptMessage(role="user", content="Ran 3 A/B tests lifting signup conversion by 18%.")],
        api_key="k",
        model="m",
        call=stub,
    )
    assert out.action == "add"
    assert out.original_bullet is None


def test_rewrite_fabricated_metric_raises_fabrication_error() -> None:
    def stub(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
        return {
            "kind": "rewrite",
            "question": None,
            "action": "rewrite",
            "bullet_index": 0,
            "rewritten_bullet": "Ran Google Ads campaigns hitting 5.5 ROAS.",
            "reason": None,
        }

    from app.optimise import FabricationError

    with pytest.raises(FabricationError):
        rewrite(
            cv_text="- Ran Google Ads campaigns.",
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

    def stub(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
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

    def flaky(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
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

    def always_fail(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
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


def test_is_denial_matches_explicit_no_experience_phrasings() -> None:
    """The router uses is_denial() to short-circuit the LLM when the
    candidate has already said they don't have the experience. It must
    fire on the phrasings a real user would type; it must NOT fire on
    ambiguous or affirmative answers.
    """
    for phrase in [
        "I don't have that experience.",
        "I do not have any HubSpot experience.",
        "I have never used Salesforce.",
        "I've never worked with that.",
        "I haven't done that.",
        "I have no experience with automation tools.",
        "no such experience",
        "never used it",
    ]:
        assert is_denial(phrase), f"should be a denial: {phrase!r}"

    for phrase in [
        "Yes, I used it last year.",
        "I ran three A/B tests on landing pages.",
        "not sure, maybe a bit",
        "no",  # too ambiguous alone; the model handles this
        "please go ahead",
        "",
        "   ",
    ]:
        assert not is_denial(phrase), f"should not be a denial: {phrase!r}"


def test_rewrite_response_missing_required_field_raises() -> None:
    def stub(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
        return {
            "kind": "rewrite",
            "question": None,
            "action": None,  # required for kind=rewrite
            "bullet_index": None,
            "rewritten_bullet": None,
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
