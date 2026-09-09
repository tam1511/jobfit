"""Bullet extractor + end-to-end proof that the false positive is fixed.

Two layers:

- ``extract_bullets`` splits pypdf-extracted CV text into a numbered list.
  It has to survive the messy shapes pypdf actually produces (unmarked
  lines, 2-space continuation indents, mixed marker glyphs) because that
  is what the model is asked to index into.
- ``rewrite()`` on the case-02 fixture, driven by a stub that mimics
  the "concatenate three bullets" behaviour that used to trip the
  guard. Post-refactor the model returns ``bullet_index`` so this shape
  can't arise at all; the test locks that in.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from app.optimise import (
    OptimiseOutcome,
    TranscriptMessage,
    extract_bullets,
    rewrite,
)
from app.scoring import ScoreGap


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _case_02_text() -> str:
    return PdfReader(str(FIXTURES / "case-02-marketing-partial" / "cv.pdf")).pages[0].extract_text()


def test_extract_bullets_from_case_02_produces_expected_items() -> None:
    bullets = extract_bullets(_case_02_text())
    displays = [b.display for b in bullets]
    # The five Verano Studio bullets and the three Halo Retail bullets
    # must all be recovered from the extractor. Exact ordering is
    # preserved from the CV.
    assert "Grew organic sessions from 8k to 26k per month over 18 months" in displays
    assert any("60 published articles" in d for d in displays)
    assert any("USD 4k" in d for d in displays)
    assert any("40 long-form articles" in d for d in displays)


def test_extract_bullets_folds_continuation_lines_into_one_display() -> None:
    """pypdf preserves the two-space continuation indent for wrapped
    bullet bodies; the extractor must fold them so the model sees one
    clean bullet per index."""
    bullets = extract_bullets(_case_02_text())
    match = next(b for b in bullets if b.display.startswith("Owned the SEO roadmap"))
    assert "60 published articles" in match.display
    # The raw slice keeps the newline+indent so str.replace matches
    # against the actual CV text later.
    assert "\n  research and on-page optimisation" in match.raw


def test_extract_bullets_gives_contiguous_indices() -> None:
    bullets = extract_bullets(_case_02_text())
    assert [b.index for b in bullets] == list(range(len(bullets)))


def test_extract_bullets_recognises_marker_glyphs() -> None:
    cv = "\n".join([
        "- Marker dash bullet.",
        "* Marker star bullet.",
        "\u2022 Marker bullet dot.",
        "\u25cf Marker filled circle.",
        "Unmarked line as bullet too.",
    ])
    displays = [b.display for b in extract_bullets(cv)]
    assert displays == [
        "Marker dash bullet.",
        "Marker star bullet.",
        "Marker bullet dot.",
        "Marker filled circle.",
        "Unmarked line as bullet too.",
    ]


def test_paraphrased_source_from_llm_does_not_reject_grounded_rewrite() -> None:
    """RED reproduction of the production bug the user re-reported.

    The current design asks the model for verbatim substrings in
    ``sources``. Real LLMs paraphrase — even at temperature=0 the
    OpenRouter models routinely soften wording, tweak numbers'
    formatting, and drop bullet markers. So a rewrite grounded in
    facts the CV actually contains (organic sessions grew 8k -> 26k
    over 18 months, 60 published articles) but whose ``sources`` are
    the model's paraphrase of those facts ("sessions grew from 8k to
    26k over eighteen months", "sixty published articles") is
    rejected today with ``FabricationError("Source not found in cv")``.

    The user cannot fix this from their side; the model does not
    reliably reproduce the CV's exact wording. The redesign moves
    grounding away from "verbatim source strings" entirely — entities
    in the rewrite are checked directly against the CV (and against
    the user's own messages), so a paraphrased source is no longer
    load-bearing. This test locks that in: given a rewrite whose
    every hard fact appears in the CV, the call succeeds regardless
    of whatever the model wrote in ``sources``.
    """
    cv = _case_02_text()

    def stub(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
        target_idx = next(
            b.index for b in extract_bullets(cv)
            if b.display.startswith("Grew organic sessions from 8k to 26k")
        )
        return {
            "kind": "rewrite",
            "question": None,
            "action": "rewrite",
            "bullet_index": target_idx,
            # Every hard fact ("8k", "26k", "18 months", "60") is a
            # verbatim substring of the CV — this rewrite is grounded.
            "rewritten_bullet": (
                "Grew organic sessions from 8k to 26k per month over 18 months by "
                "owning the SEO roadmap across 60 published articles."
            ),
            # The model's sources are paraphrases — they capture the
            # same facts but are not substrings of the CV. This is
            # the shape that trips the current guard.
            "sources": [
                {"text": "organic sessions grew from 8k to 26k over eighteen months", "origin": "cv"},
                {"text": "sixty published articles on the company blog", "origin": "cv"},
            ],
            "reason": None,
        }

    gap = ScoreGap(
        severity="high",
        evidence="Content scale not clear from CV.",
        suggestion="Rewrite the SEO bullet to make the scale explicit.",
    )

    outcome = rewrite(
        cv_text=cv,
        gap=gap,
        gap_index=0,
        total_gaps=1,
        transcript=[TranscriptMessage(role="user", content="please go ahead")],
        api_key="k",
        model="m",
        call=stub,
    )
    assert outcome.kind == "rewrite"
    assert outcome.rewritten_bullet is not None
    assert "8k to 26k" in outcome.rewritten_bullet


def test_rewrite_end_to_end_no_longer_rejects_multi_bullet_synthesis() -> None:
    """Full stack proof of the false-positive fix. Given the real case-02
    CV, a model can pick one bullet by index and reference facts from
    others via ``sources``; there is no legal way for the model to
    submit a "concatenated bullets" string, so the guard cannot false-
    positive on this shape at all.
    """
    cv = _case_02_text()

    def stub(_system: str, _user: str, *, api_key: str, model: str, schema: dict) -> dict:
        # The bullet at index 1 in case-02 is the "Grew organic sessions"
        # bullet after the role heading. Rather than hard-coding an
        # index that depends on extractor detail, resolve it here.
        target_idx = next(
            b.index for b in extract_bullets(cv)
            if b.display.startswith("Grew organic sessions from 8k to 26k")
        )
        return {
            "kind": "rewrite",
            "question": None,
            "action": "rewrite",
            "bullet_index": target_idx,
            "rewritten_bullet": (
                "Grew organic sessions from 8k to 26k per month over 18 months while "
                "running Google Ads at USD 4k monthly across 60 published articles."
            ),
            "sources": [
                {"text": "Ran paid campaigns on Google Ads, managing a monthly budget of USD 4k", "origin": "cv"},
                {"text": "60 published articles", "origin": "cv"},
            ],
            "reason": None,
        }

    gap = ScoreGap(
        severity="high",
        evidence="Paid budget and content scale not clear from CV.",
        suggestion="Combine paid and organic evidence into one strong bullet.",
    )

    outcome = rewrite(
        cv_text=cv,
        gap=gap,
        gap_index=0,
        total_gaps=1,
        transcript=[TranscriptMessage(role="user", content="I ran both together for 18 months.")],
        api_key="k",
        model="m",
        call=stub,
    )
    assert isinstance(outcome, OptimiseOutcome)
    assert outcome.kind == "rewrite"
    assert outcome.original_bullet is not None
    assert outcome.original_bullet in cv  # backend-derived; verbatim by construction
    assert "Grew organic sessions from 8k to 26k" in outcome.original_bullet
