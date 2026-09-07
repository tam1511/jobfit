"""Structural tests for rubric.json and the fixtures dataset.

These do not exercise the scorer (it does not exist yet). They lock
down the shape of the ticket-2 deliverables so later work cannot
silently drift: rubric weights must sum to 100, fixtures/index.json
must point at real files, and every expected.json must talk about
the same category ids that rubric.json defines.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUBRIC_PATH = ROOT / "rubric.json"
FIXTURES = ROOT / "fixtures"
INDEX_PATH = FIXTURES / "index.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rubric() -> dict:
    return _load_json(RUBRIC_PATH)


@pytest.fixture(scope="module")
def index() -> dict:
    return _load_json(INDEX_PATH)


def test_rubric_has_five_categories(rubric: dict) -> None:
    assert len(rubric["categories"]) == 5


def test_rubric_weights_sum_to_100(rubric: dict) -> None:
    assert sum(c["weight"] for c in rubric["categories"]) == 100


def test_rubric_category_ids_are_unique(rubric: dict) -> None:
    ids = [c["id"] for c in rubric["categories"]]
    assert len(set(ids)) == len(ids)


def test_index_lists_three_cases(index: dict) -> None:
    assert len(index["cases"]) == 3


def test_index_covers_all_three_bands(index: dict) -> None:
    bands = {c["band"] for c in index["cases"]}
    assert bands == {"strong", "partial", "weak"}


@pytest.mark.parametrize(
    "case",
    _load_json(INDEX_PATH)["cases"],
    ids=lambda c: c["id"],
)
def test_case_files_exist(case: dict) -> None:
    for key in ("cv", "jd", "expected"):
        assert (FIXTURES / case[key]).is_file(), f"missing {key} for {case['id']}"
    if "cv_pdf" in case:
        assert (FIXTURES / case["cv_pdf"]).is_file()


@pytest.mark.parametrize(
    "case",
    _load_json(INDEX_PATH)["cases"],
    ids=lambda c: c["id"],
)
def test_expected_overall_range_is_valid(case: dict) -> None:
    expected = _load_json(FIXTURES / case["expected"])
    lo = expected["expected_overall"]["min"]
    hi = expected["expected_overall"]["max"]
    assert 0 <= lo <= hi <= 100


@pytest.mark.parametrize(
    "case",
    _load_json(INDEX_PATH)["cases"],
    ids=lambda c: c["id"],
)
def test_expected_band_matches_index(case: dict) -> None:
    expected = _load_json(FIXTURES / case["expected"])
    lo = expected["expected_overall"]["min"]
    hi = expected["expected_overall"]["max"]
    midpoint = (lo + hi) / 2
    band = case["band"]
    if band == "strong":
        assert midpoint >= 75
    elif band == "partial":
        assert 50 <= midpoint < 75
    elif band == "weak":
        assert midpoint < 50
    else:
        pytest.fail(f"unknown band {band}")


@pytest.mark.parametrize(
    "case",
    _load_json(INDEX_PATH)["cases"],
    ids=lambda c: c["id"],
)
def test_expected_breakdown_uses_rubric_ids(case: dict) -> None:
    rubric_ids = {c["id"] for c in _load_json(RUBRIC_PATH)["categories"]}
    expected = _load_json(FIXTURES / case["expected"])
    assert set(expected["expected_breakdown"].keys()) == rubric_ids
