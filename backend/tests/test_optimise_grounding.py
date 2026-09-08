"""verify_grounding: the anti-fabrication guard.

Every hard fact in a rewritten bullet must be traceable to either the
original CV, the original bullet (for preserved metrics), or the user's
messages in the chat.
"""

from __future__ import annotations

import pytest

from app.optimise import FabricationError, RewriteSource, verify_grounding


CV_TEXT = """Mai Nguyen
Digital Marketing Manager

- Grew organic sessions from 8k to 26k in 12 months.
- Ran Google Ads spending 60k EUR per quarter with 4.2 ROAS.
"""


def test_grounded_rewrite_from_cv_source_passes() -> None:
    verify_grounding(
        rewritten="Grew organic sessions from 8k to 26k in 12 months via editorial planning.",
        sources=[
            RewriteSource(text="Grew organic sessions from 8k to 26k in 12 months.", origin="cv"),
        ],
        cv_text=CV_TEXT,
        original_bullet=None,
        user_messages=[],
    )


def test_grounded_rewrite_from_user_source_passes() -> None:
    verify_grounding(
        rewritten="Ran 3 A/B tests on landing pages, lifting signup conversion by 18%.",
        sources=[
            RewriteSource(
                text="I ran 3 A/B tests on landing pages, lifting signup conversion by 18%",
                origin="user",
            ),
        ],
        cv_text=CV_TEXT,
        original_bullet=None,
        user_messages=["I ran 3 A/B tests on landing pages, lifting signup conversion by 18% last year"],
    )


def test_preserved_original_metric_needs_no_source() -> None:
    """A rewrite that keeps an existing bullet's metric should not need a source for it."""
    verify_grounding(
        rewritten="Managed 60k EUR quarterly Google Ads budget hitting 4.2 ROAS.",
        sources=[],
        cv_text=CV_TEXT,
        original_bullet="Ran Google Ads spending 60k EUR per quarter with 4.2 ROAS.",
        user_messages=[],
    )


def test_invented_number_is_rejected() -> None:
    with pytest.raises(FabricationError, match="45%"):
        verify_grounding(
            rewritten="Grew organic sessions by 45%.",
            sources=[
                RewriteSource(text="Grew organic sessions from 8k to 26k in 12 months.", origin="cv"),
            ],
            cv_text=CV_TEXT,
            original_bullet=None,
            user_messages=[],
        )


def test_invented_tool_name_is_rejected() -> None:
    with pytest.raises(FabricationError, match="HubSpot"):
        verify_grounding(
            rewritten="Ran HubSpot lead-scoring workflows to drive pipeline.",
            sources=[],
            cv_text=CV_TEXT,
            original_bullet=None,
            user_messages=["I've used Google Ads but not HubSpot"],
        )


def test_source_not_actually_in_cv_is_rejected() -> None:
    with pytest.raises(FabricationError, match="not found in cv"):
        verify_grounding(
            rewritten="Managed a team of 12 marketers.",
            sources=[
                RewriteSource(text="Managed a team of 12 marketers.", origin="cv"),
            ],
            cv_text=CV_TEXT,
            original_bullet=None,
            user_messages=[],
        )


def test_source_not_actually_in_user_message_is_rejected() -> None:
    with pytest.raises(FabricationError, match="not found in user"):
        verify_grounding(
            rewritten="Ran email campaigns for 50k subscribers.",
            sources=[
                RewriteSource(text="Ran email campaigns for 50k subscribers.", origin="user"),
            ],
            cv_text=CV_TEXT,
            original_bullet=None,
            user_messages=["I have not run email campaigns"],
        )


def test_common_action_verbs_are_not_flagged() -> None:
    """Ordinary verbs like 'Led', 'Grew' should not require a source."""
    verify_grounding(
        rewritten="Led the SEO strategy that grew organic sessions from 8k to 26k.",
        sources=[
            RewriteSource(text="Grew organic sessions from 8k to 26k", origin="cv"),
            RewriteSource(text="SEO", origin="cv"),
        ],
        cv_text=CV_TEXT + "\n- SEO across 60 articles.\n",
        original_bullet=None,
        user_messages=[],
    )
