"""Fixture replay: feed each canned scored.json through the parser and assert
the produced ScoreResult satisfies the case's expected.json ranges, keywords
and gap requirements.

This proves the parser + weight injection + overall_score arithmetic
match the fixtures dataset shipped in #2. Real network calls happen only
when OPENROUTER_LIVE=1 is set — see test_fixture_replay_live below.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.scoring import (
    ScoreResult,
    ScoringError,
    _parse_model_response,
    score,
    weighted_overall,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"
INDEX = json.loads((FIXTURES / "index.json").read_text())


def _case_paths(case: dict) -> tuple[Path, Path, Path, Path]:
    base = FIXTURES / case["path"]
    return (
        base / "cv.md",
        base / "jd.md",
        base / "expected.json",
        base / "scored.json",
    )


CATEGORY_ID_TO_NAME = {
    "hard_skills_match": "Hard Skills Match",
    "experience_match": "Experience Match",
    "ats_keywords": "ATS Keywords",
    "quantified_achievements": "Quantified Achievements",
    "formatting_and_length": "Formatting & Length",
}

# Map required_gap ids to a substring that must appear in the corresponding
# actual gap's evidence or suggestion (case-insensitive). This is the
# fixture-agnostic acceptance test — no NLP heuristics needed.
GAP_TOPIC: dict[str, str] = {
    "no_hubspot": "hubspot",
    "no_ab_testing": "a/b test",
    "no_linkedin_ads": "linkedin",
    "no_python": "python",
    "no_production_ml": "production",
    "underqualified_years": "4+ years",
    "no_warehouse_sql": "warehouse",
    "no_statistical_modelling": "statistical modelling",
}


def _assert_meets_expected(result: ScoreResult, expected: dict) -> None:
    ov = expected["expected_overall"]
    assert ov["min"] <= result.overall_score <= ov["max"], (
        f"overall {result.overall_score} outside [{ov['min']}, {ov['max']}]"
    )
    breakdown_by_name = {c.category: c.score for c in result.breakdown}
    for cat_id, band in expected["expected_breakdown"].items():
        got = breakdown_by_name[CATEGORY_ID_TO_NAME[cat_id]]
        assert band["min"] <= got <= band["max"], (
            f"{cat_id}: {got} outside [{band['min']}, {band['max']}]"
        )
    for kw in expected["required_matched_keywords"]:
        assert kw in result.matched_keywords, f"missing matched keyword {kw!r}"
    for kw in expected["required_missing_keywords"]:
        assert kw in result.missing_keywords, f"missing gap keyword {kw!r}"
    for req in expected["required_gaps"]:
        topic = GAP_TOPIC[req["id"]]
        matched = [
            g
            for g in result.gaps
            if g.severity == req["severity"]
            and (topic in g.evidence.lower() or topic in g.suggestion.lower())
        ]
        assert matched, (
            f"no gap covers required id={req['id']!r} severity={req['severity']!r}"
        )


@pytest.mark.parametrize("case", INDEX["cases"], ids=[c["id"] for c in INDEX["cases"]])
def test_replay_scored_json_meets_expected(case: dict) -> None:
    _, _, expected_path, scored_path = _case_paths(case)
    scored = json.loads(scored_path.read_text())
    expected = json.loads(expected_path.read_text())
    result = _parse_model_response(scored)
    _assert_meets_expected(result, expected)


@pytest.mark.parametrize("case", INDEX["cases"], ids=[c["id"] for c in INDEX["cases"]])
def test_score_end_to_end_with_replayed_call(case: dict, tmp_path) -> None:
    """The ``score()`` entry point plus an injected ``call`` that returns
    scored.json should produce the same ScoreResult as parsing scored.json."""
    cv_path, jd_path, _, scored_path = _case_paths(case)
    cv_text = cv_path.read_text()
    jd_text = jd_path.read_text()
    scored = json.loads(scored_path.read_text())

    # A real db_connect against a fresh sqlite so cache reads don't collide
    from app.db import connect, init_db
    from functools import partial

    db_path = tmp_path / f"replay-{case['id']}.sqlite3"
    init_db(db_path)
    db_connect = partial(connect, db_path)

    calls: list[int] = []

    def replay(cv_text: str, jd_text: str, *, api_key: str, model: str) -> dict:
        calls.append(1)
        return scored

    result = score(
        cv_text,
        jd_text,
        api_key="test",
        model="test-model",
        db_connect=db_connect,
        call=replay,
    )
    assert len(calls) == 1
    parsed = _parse_model_response(scored)
    assert result.overall_score == parsed.overall_score
    assert [c.model_dump() for c in result.breakdown] == [
        c.model_dump() for c in parsed.breakdown
    ]


@pytest.mark.skipif(
    os.environ.get("OPENROUTER_LIVE") != "1",
    reason="Set OPENROUTER_LIVE=1 to hit OpenRouter for real fixture regression.",
)
@pytest.mark.parametrize("case", INDEX["cases"], ids=[c["id"] for c in INDEX["cases"]])
def test_fixture_replay_live(case: dict, tmp_path) -> None:
    """Live regression test. Requires OPENROUTER_API_KEY in the environment.
    Reads cv/jd, calls OpenRouter, asserts the result satisfies expected.json.
    Also writes the raw response to scored.json when the file does not exist,
    so the offline replay tests can be regenerated by running this test once.
    """
    from app.config import DEFAULT_MODEL
    from app.db import connect, init_db
    from functools import partial

    cv_path, jd_path, expected_path, scored_path = _case_paths(case)
    cv_text = cv_path.read_text()
    jd_text = jd_path.read_text()
    expected = json.loads(expected_path.read_text())

    db_path = tmp_path / f"live-{case['id']}.sqlite3"
    init_db(db_path)
    db_connect = partial(connect, db_path)

    api_key = os.environ["OPENROUTER_API_KEY"]
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)

    try:
        result = score(
            cv_text,
            jd_text,
            api_key=api_key,
            model=model,
            db_connect=db_connect,
        )
    except ScoringError as exc:
        pytest.fail(f"Live scoring failed: {exc}")

    _assert_meets_expected(result, expected)

    if not scored_path.exists():
        # Reconstruct the raw shape (without weight/overall_score) so future
        # offline runs replay a valid model response.
        raw = {
            "breakdown": [
                {"category": c.category, "score": c.score, "evidence": c.evidence}
                for c in result.breakdown
            ],
            "gaps": [g.model_dump() for g in result.gaps],
            "matched_keywords": result.matched_keywords,
            "missing_keywords": result.missing_keywords,
        }
        scored_path.write_text(json.dumps(raw, indent=2) + "\n")
