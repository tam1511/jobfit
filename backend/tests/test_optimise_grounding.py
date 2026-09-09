"""verify_grounding: the entity-level anti-fabrication guard.

The redesign checks every hard fact in a rewritten bullet against a
combined haystack of the CV text, the resolved original bullet, and
every user message. The model no longer returns a ``sources`` array —
LLMs paraphrase when they copy and pypdf mangles whitespace, so any
protocol built on the model reproducing exact substrings will
false-positive against otherwise-grounded rewrites. The guard defends
against invented facts, not against paraphrased quotes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from app.optimise import FabricationError, verify_grounding


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _case_02_extracted_text() -> str:
    return PdfReader(str(FIXTURES / "case-02-marketing-partial" / "cv.pdf")).pages[0].extract_text()


CV_TEXT = """Mai Nguyen
Digital Marketing Manager

- Grew organic sessions from 8k to 26k in 12 months.
- Ran Google Ads spending 60k EUR per quarter with 4.2 ROAS.
"""


def test_grounded_rewrite_from_cv_passes() -> None:
    verify_grounding(
        rewritten="Grew organic sessions from 8k to 26k in 12 months via editorial planning.",
        cv_text=CV_TEXT,
        original_bullet=None,
        user_messages=[],
    )


def test_grounded_rewrite_from_user_message_passes() -> None:
    verify_grounding(
        rewritten="Ran 3 A/B tests on landing pages, lifting signup conversion by 18%.",
        cv_text=CV_TEXT,
        original_bullet=None,
        user_messages=["I ran 3 A/B tests on landing pages, lifting signup conversion by 18% last year"],
    )


def test_preserved_original_metric_needs_no_source() -> None:
    """A rewrite that keeps an existing bullet's metric passes because the
    fact is in the resolved original_bullet, which itself is a CV substring.
    """
    verify_grounding(
        rewritten="Managed 60k EUR quarterly Google Ads budget hitting 4.2 ROAS.",
        cv_text=CV_TEXT,
        original_bullet="Ran Google Ads spending 60k EUR per quarter with 4.2 ROAS.",
        user_messages=[],
    )


def test_invented_number_is_rejected() -> None:
    with pytest.raises(FabricationError, match="45%"):
        verify_grounding(
            rewritten="Grew organic sessions by 45%.",
            cv_text=CV_TEXT,
            original_bullet=None,
            user_messages=[],
        )


def test_invented_tool_name_is_rejected_when_absent_from_haystack() -> None:
    """A tool name that appears nowhere in CV / original / user messages
    must be flagged, even if the user's message denies it."""
    with pytest.raises(FabricationError, match="Salesforce"):
        verify_grounding(
            rewritten="Ran Salesforce lead-scoring workflows to drive pipeline.",
            cv_text=CV_TEXT,
            original_bullet=None,
            user_messages=["I've used Google Ads"],
        )


def test_paraphrased_lookup_does_not_reject_grounded_rewrite() -> None:
    """The whole point of the redesign: no more string round-trips. A
    rewrite whose every hard fact is present in the CV must pass without
    the model having to produce verbatim substrings anywhere.
    """
    cv_text = _case_02_extracted_text()
    verify_grounding(
        rewritten=(
            "Grew organic sessions from 8k to 26k per month over 18 months by "
            "owning SEO across 60 published articles."
        ),
        cv_text=cv_text,
        original_bullet=None,
        user_messages=[],
    )


def test_common_action_verbs_are_not_flagged() -> None:
    """Ordinary verbs like 'Led', 'Grew', 'Deployed' at the start of a
    sentence must not require grounding."""
    verify_grounding(
        rewritten="Led the SEO strategy that grew organic sessions from 8k to 26k.",
        cv_text=CV_TEXT + "\n- SEO across 60 articles.\n",
        original_bullet=None,
        user_messages=[],
    )


def test_source_wrapped_by_pypdf_across_two_lines_is_accepted() -> None:
    """pypdf wraps continued bullet lines with a newline plus indent. The
    normaliser collapses whitespace before matching so a rewrite whose
    entities span the pypdf line-break in the CV still passes.
    """
    cv_text = _case_02_extracted_text()
    assert "monthly keyword\n  research and on-page optimisation" in cv_text

    verify_grounding(
        rewritten=(
            "Owned the SEO roadmap for the company blog, driving 60 published articles "
            "through monthly keyword research."
        ),
        cv_text=cv_text,
        original_bullet=None,
        user_messages=[],
    )


def test_sentence_initial_verb_deployed_is_not_flagged() -> None:
    """Plain-Capitalized sentence-initial words are English verbs, not
    proper nouns. They must not require grounding.
    """
    verify_grounding(
        rewritten="Deployed end-to-end AI pipelines from prototype to production.",
        cv_text="- Built AI pipelines at university.\n",
        original_bullet=None,
        user_messages=["I've built end-to-end AI pipelines from prototype to production."],
    )


def test_midsentence_proper_noun_still_flagged() -> None:
    """Mid-sentence CamelCase / ALLCAPS / Capitalized tokens are still
    checked. The sentence-start exemption is position-specific."""
    with pytest.raises(FabricationError, match="FakeToolCorp"):
        verify_grounding(
            rewritten="Deployed pipelines using FakeToolCorp for orchestration.",
            cv_text="- Built pipelines at university.\n",
            original_bullet=None,
            user_messages=["I've built pipelines using orchestration but not with any brand tools."],
        )


def test_sentence_initial_verb_after_period_is_not_flagged() -> None:
    """A verb that follows a period mid-bullet is still sentence-initial."""
    verify_grounding(
        rewritten="Owned the SEO roadmap. Deployed weekly editorial planning across the team.",
        cv_text="- Owned the SEO roadmap for the blog.\n",
        original_bullet=None,
        user_messages=["I deployed weekly editorial planning across the team."],
    )


def test_generic_acronym_in_cv_grounds_the_rewrite() -> None:
    """Common domain acronyms (AI, ML, NLP, API) trip the ALLCAPS branch
    of the token regex. When the acronym is in the CV, the fact is
    grounded — the candidate typed it into their own document.
    """
    cv_text = (
        "Data Scientist with three years of experience.\n"
        "- Built ML models for solar agriculture (TIPS R&D).\n"
        "- Applied AI/ML techniques for customer segmentation.\n"
    )
    verify_grounding(
        rewritten=(
            "Designed and delivered enterprise AI pipelines end-to-end for "
            "solar agriculture forecasting and customer segmentation."
        ),
        cv_text=cv_text,
        original_bullet=None,
        user_messages=["I've built end-to-end AI/ML pipelines for solar and payment apps."],
    )


def test_fact_absent_from_every_haystack_is_rejected() -> None:
    """Sanity check for the union: an entity absent from CV, original
    bullet, and every user message must be flagged.
    """
    with pytest.raises(FabricationError, match="HubSpot"):
        verify_grounding(
            rewritten="Ran HubSpot lead-scoring workflows to drive pipeline.",
            cv_text=CV_TEXT,
            original_bullet=None,
            user_messages=["I've used Google Ads"],
        )
