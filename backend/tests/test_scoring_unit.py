"""Unit tests for pure helpers in app.scoring."""

from __future__ import annotations

import pytest

from app import scoring
from app.scoring import (
    CATEGORY_NAMES,
    CATEGORY_WEIGHTS,
    RUBRIC_VERSION,
    ScoreCategory,
    ScoringError,
    build_response_schema,
    build_system_prompt,
    cache_key,
    weighted_overall,
    _parse_model_response,
)


def test_cache_key_is_stable() -> None:
    a = cache_key("cv", "jd", "model")
    b = cache_key("cv", "jd", "model")
    assert a == b


def test_cache_key_changes_with_cv() -> None:
    assert cache_key("cv", "jd", "model") != cache_key("cv2", "jd", "model")


def test_cache_key_changes_with_jd() -> None:
    assert cache_key("cv", "jd", "model") != cache_key("cv", "jd2", "model")


def test_cache_key_changes_with_model() -> None:
    assert cache_key("cv", "jd", "model") != cache_key("cv", "jd", "model2")


def test_cache_key_includes_rubric_version() -> None:
    key_before = cache_key("cv", "jd", "model")
    original = scoring.RUBRIC_VERSION
    scoring.RUBRIC_VERSION = original + 1
    try:
        key_after = cache_key("cv", "jd", "model")
    finally:
        scoring.RUBRIC_VERSION = original
    assert key_before != key_after


def test_weighted_overall_matches_rubric_arithmetic() -> None:
    breakdown = [
        ScoreCategory(category="Hard Skills Match", score=80, weight=30, evidence=""),
        ScoreCategory(category="Experience Match", score=70, weight=25, evidence=""),
        ScoreCategory(category="ATS Keywords", score=60, weight=20, evidence=""),
        ScoreCategory(category="Quantified Achievements", score=50, weight=15, evidence=""),
        ScoreCategory(category="Formatting & Length", score=90, weight=10, evidence=""),
    ]
    # 80*30 + 70*25 + 60*20 + 50*15 + 90*10 = 2400 + 1750 + 1200 + 750 + 900 = 7000 / 100 = 70
    assert weighted_overall(breakdown) == 70


def test_schema_has_five_categories_locked_by_enum() -> None:
    schema = build_response_schema()
    enum = schema["properties"]["breakdown"]["items"]["properties"]["category"]["enum"]
    assert enum == CATEGORY_NAMES
    assert schema["properties"]["breakdown"]["minItems"] == 5
    assert schema["properties"]["breakdown"]["maxItems"] == 5


def test_schema_gap_severity_enum() -> None:
    schema = build_response_schema()
    gap_props = schema["properties"]["gaps"]["items"]["properties"]
    assert gap_props["severity"]["enum"] == ["high", "medium", "low"]


def test_system_prompt_lists_every_rubric_category() -> None:
    prompt = build_system_prompt()
    for name in CATEGORY_NAMES:
        assert name in prompt


def test_parse_response_injects_rubric_weights_over_model_output() -> None:
    raw = {
        "breakdown": [
            {"category": name, "score": 50, "evidence": "ok"}
            for name in CATEGORY_NAMES
        ],
        "gaps": [],
        "matched_keywords": ["python"],
        "missing_keywords": ["go"],
    }
    result = _parse_model_response(raw)
    for cat in result.breakdown:
        assert cat.weight == CATEGORY_WEIGHTS[cat.category]


def test_parse_response_computes_overall_score() -> None:
    raw = {
        "breakdown": [
            {"category": "Hard Skills Match", "score": 100, "evidence": ""},
            {"category": "Experience Match", "score": 100, "evidence": ""},
            {"category": "ATS Keywords", "score": 100, "evidence": ""},
            {"category": "Quantified Achievements", "score": 100, "evidence": ""},
            {"category": "Formatting & Length", "score": 100, "evidence": ""},
        ],
        "gaps": [],
        "matched_keywords": [],
        "missing_keywords": [],
    }
    result = _parse_model_response(raw)
    assert result.overall_score == 100


def test_parse_response_orders_breakdown_by_rubric() -> None:
    raw = {
        "breakdown": [
            {"category": "Formatting & Length", "score": 10, "evidence": ""},
            {"category": "Hard Skills Match", "score": 90, "evidence": ""},
            {"category": "ATS Keywords", "score": 50, "evidence": ""},
            {"category": "Quantified Achievements", "score": 40, "evidence": ""},
            {"category": "Experience Match", "score": 70, "evidence": ""},
        ],
        "gaps": [],
        "matched_keywords": [],
        "missing_keywords": [],
    }
    result = _parse_model_response(raw)
    assert [c.category for c in result.breakdown] == CATEGORY_NAMES


def test_parse_response_rejects_wrong_category_count() -> None:
    raw = {"breakdown": [], "gaps": [], "matched_keywords": [], "missing_keywords": []}
    with pytest.raises(ScoringError):
        _parse_model_response(raw)


def test_parse_response_rejects_unknown_category() -> None:
    raw = {
        "breakdown": [
            {"category": "Bogus", "score": 50, "evidence": ""},
            *[{"category": name, "score": 50, "evidence": ""} for name in CATEGORY_NAMES[:4]],
        ],
        "gaps": [],
        "matched_keywords": [],
        "missing_keywords": [],
    }
    with pytest.raises(ScoringError):
        _parse_model_response(raw)


def test_parse_response_rejects_duplicate_category() -> None:
    raw = {
        "breakdown": [{"category": CATEGORY_NAMES[0], "score": 50, "evidence": ""}] * 5,
        "gaps": [],
        "matched_keywords": [],
        "missing_keywords": [],
    }
    with pytest.raises(ScoringError):
        _parse_model_response(raw)


def test_rubric_version_is_loaded() -> None:
    assert isinstance(RUBRIC_VERSION, int)
    assert RUBRIC_VERSION >= 1
