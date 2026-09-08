"""Deterministic CV scoring against a JD.

One public entry point, ``score()``. It reads the ``scores`` table for a
cache hit (keyed on the content of the CV, the JD, the model id and the
rubric version), and only calls OpenRouter when the cache misses.

Design notes:

- The model returns per-category scores, gaps, and keyword lists. The
  overall score is computed in Python from the rubric weights so we do
  not depend on the model doing arithmetic correctly.
- Determinism comes from ``temperature=0`` plus, more importantly, the
  cache: identical inputs never reach the model twice.
- Structured Outputs are enforced via a JSON Schema built from
  ``rubric.json`` at import time, so a rubric edit propagates
  automatically.
- Failures (network, malformed JSON, wrong shape) surface as
  ``ScoringError``. The router turns that into HTTP 502. The caller may
  choose to retry once; ``score()`` itself retries the HTTP call once
  before giving up.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable

import httpx
from pydantic import BaseModel, Field, ValidationError


logger = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parents[2]
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
HTTP_TIMEOUT = 60.0

DbConnect = Callable[[], sqlite3.Connection]


class ScoringError(RuntimeError):
    """Raised when a score cannot be produced (network, retries exhausted, bad response)."""


# ---------------------------------------------------------------------------
# Rubric (loaded once at import time)
# ---------------------------------------------------------------------------

_RUBRIC = json.loads((REPO_ROOT / "rubric.json").read_text())
RUBRIC_VERSION: int = _RUBRIC["version"]
CATEGORY_NAMES: list[str] = [c["name"] for c in _RUBRIC["categories"]]
CATEGORY_WEIGHTS: dict[str, int] = {c["name"]: c["weight"] for c in _RUBRIC["categories"]}
assert sum(CATEGORY_WEIGHTS.values()) == 100, (
    f"Rubric weights must sum to 100, got {sum(CATEGORY_WEIGHTS.values())}"
)


# ---------------------------------------------------------------------------
# Response models (shape returned to the frontend, matches SKILL.md)
# ---------------------------------------------------------------------------

class ScoreCategory(BaseModel):
    category: str
    score: int = Field(ge=0, le=100)
    weight: int
    evidence: str


class ScoreGap(BaseModel):
    severity: str
    evidence: str
    suggestion: str


class ScoreResult(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    breakdown: list[ScoreCategory]
    gaps: list[ScoreGap]
    matched_keywords: list[str]
    missing_keywords: list[str]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def cache_key(cv_text: str, jd_text: str, model: str) -> str:
    """Content-addressed cache key. Includes rubric version so rubric edits invalidate."""
    payload = f"{cv_text}\x00{jd_text}\x00{model}\x00v{RUBRIC_VERSION}".encode()
    return hashlib.sha256(payload).hexdigest()


def weighted_overall(breakdown: list[ScoreCategory]) -> int:
    """Compute overall_score from per-category scores using rubric weights."""
    total = sum(c.score * c.weight for c in breakdown)
    return round(total / 100)


def build_response_schema() -> dict:
    """JSON Schema handed to OpenRouter as ``response_format``.

    The category enum locks the five names; the model cannot invent a
    sixth. ``overall_score`` is intentionally omitted — we compute it.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["breakdown", "gaps", "matched_keywords", "missing_keywords"],
        "properties": {
            "breakdown": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["category", "score", "evidence"],
                    "properties": {
                        "category": {"type": "string", "enum": CATEGORY_NAMES},
                        "score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "evidence": {"type": "string"},
                    },
                },
            },
            "gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["severity", "evidence", "suggestion"],
                    "properties": {
                        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                        "evidence": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                },
            },
            "matched_keywords": {"type": "array", "items": {"type": "string"}},
            "missing_keywords": {"type": "array", "items": {"type": "string"}},
        },
    }


def build_system_prompt() -> str:
    lines = [
        "You are a CV scoring engine. Score the candidate's CV against the job description using the rubric below.",
        "",
        "Rubric — five weighted categories, all scored 0-100:",
    ]
    for c in _RUBRIC["categories"]:
        lines.append(
            f"- {c['name']} (weight {c['weight']}): {c['measurement']} "
            f"Scoring rule: {c['scoring_rule']}"
        )
    lines += [
        "",
        "Rules:",
        "- Base every score on explicit evidence from the CV and JD.",
        "- When evidence is unavailable, record a gap. Do not assume the requirement is satisfied.",
        "- matched_keywords: JD-important terms that appear in the CV.",
        "- missing_keywords: JD-important terms absent from the CV.",
        "- Each gap has severity (high, medium, or low), evidence (what the JD asks that the CV lacks), and suggestion (a concrete way to close the gap without fabricating experience).",
        "- Return JSON matching the schema exactly. No prose outside the JSON.",
    ]
    return "\n".join(lines)


SYSTEM_PROMPT = build_system_prompt()
RESPONSE_SCHEMA = build_response_schema()


def _parse_model_response(raw: dict) -> ScoreResult:
    """Turn the raw model JSON into a validated ScoreResult.

    Injects the rubric weight per category (we do not trust the model to
    echo it) and computes overall_score in Python.
    """
    breakdown_raw = raw.get("breakdown", [])
    if len(breakdown_raw) != len(CATEGORY_NAMES):
        raise ScoringError(f"Expected {len(CATEGORY_NAMES)} categories, got {len(breakdown_raw)}.")
    names_seen: set[str] = set()
    breakdown: list[ScoreCategory] = []
    for item in breakdown_raw:
        name = item.get("category")
        if name not in CATEGORY_WEIGHTS:
            raise ScoringError(f"Unknown category '{name}'.")
        if name in names_seen:
            raise ScoringError(f"Duplicate category '{name}'.")
        names_seen.add(name)
        breakdown.append(
            ScoreCategory(
                category=name,
                score=int(item.get("score", 0)),
                weight=CATEGORY_WEIGHTS[name],
                evidence=str(item.get("evidence", "")),
            )
        )
    breakdown.sort(key=lambda c: CATEGORY_NAMES.index(c.category))
    try:
        return ScoreResult(
            overall_score=weighted_overall(breakdown),
            breakdown=breakdown,
            gaps=[ScoreGap(**g) for g in raw.get("gaps", [])],
            matched_keywords=[str(k) for k in raw.get("matched_keywords", [])],
            missing_keywords=[str(k) for k in raw.get("missing_keywords", [])],
        )
    except ValidationError as exc:
        raise ScoringError(f"Model response failed validation: {exc}") from exc


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def read_cache(key: str, db_connect: DbConnect) -> ScoreResult | None:
    """Return a previously-computed score for this content key, or None."""
    with closing(db_connect()) as conn:
        row = conn.execute(
            "SELECT result_json FROM scores WHERE cache_key = ? LIMIT 1",
            (key,),
        ).fetchone()
    if row is None:
        return None
    return ScoreResult.model_validate_json(row["result_json"])


def read_score_for_upload(upload_id: int, db_connect: DbConnect) -> ScoreResult | None:
    """Return the score row tied to a specific upload, or None if missing."""
    with closing(db_connect()) as conn:
        row = conn.execute(
            "SELECT result_json FROM scores WHERE upload_id = ?",
            (upload_id,),
        ).fetchone()
    if row is None:
        return None
    return ScoreResult.model_validate_json(row["result_json"])


# ---------------------------------------------------------------------------
# OpenRouter call
# ---------------------------------------------------------------------------

def _call_openrouter(
    cv_text: str,
    jd_text: str,
    *,
    api_key: str,
    model: str,
) -> dict:
    """Single HTTP call to OpenRouter. Returns the parsed message content dict.

    Raises ``ScoringError`` on any failure (HTTP, JSON, wrong shape).
    Callers handle retry.
    """
    if not api_key:
        raise ScoringError("OPENROUTER_API_KEY is not configured.")

    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"CV:\n{cv_text}\n\nJD:\n{jd_text}"},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "cv_score",
                "strict": True,
                "schema": RESPONSE_SCHEMA,
            },
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(OPENROUTER_URL, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise ScoringError(f"OpenRouter request failed: {exc}") from exc

    if response.status_code >= 400:
        raise ScoringError(
            f"OpenRouter returned {response.status_code}: {response.text[:200]}"
        )

    try:
        envelope = response.json()
        content = envelope["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ScoringError(f"OpenRouter response was not valid: {exc}") from exc


def _call_with_retry(
    cv_text: str,
    jd_text: str,
    *,
    api_key: str,
    model: str,
    call: Callable[..., dict] = _call_openrouter,
) -> dict:
    """One retry on any ScoringError. Two attempts total.

    The first error is logged before the retry so operators can see
    transient failures. Configuration errors (missing api_key) are
    checked before entering the retry loop, so they fail fast without
    a wasted second attempt.
    """
    if not api_key:
        raise ScoringError("OPENROUTER_API_KEY is not configured.")
    try:
        return call(cv_text, jd_text, api_key=api_key, model=model)
    except ScoringError as first:
        logger.warning("Scoring call failed, retrying once: %s", first)
        return call(cv_text, jd_text, api_key=api_key, model=model)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def score(
    cv_text: str,
    jd_text: str,
    *,
    api_key: str,
    model: str,
    db_connect: DbConnect,
    call: Callable[..., dict] | None = None,
) -> ScoreResult:
    """Return a ScoreResult for the given CV and JD.

    Consults the ``scores`` cache first. On a miss, calls OpenRouter with
    one retry. The caller is responsible for persisting the returned
    result against a specific ``upload_id``.
    """
    key = cache_key(cv_text, jd_text, model)
    cached = read_cache(key, db_connect)
    if cached is not None:
        return cached
    raw = _call_with_retry(
        cv_text,
        jd_text,
        api_key=api_key,
        model=model,
        call=call or _call_openrouter,
    )
    return _parse_model_response(raw)


def persist_score(
    conn: sqlite3.Connection,
    upload_id: int,
    result: ScoreResult,
    *,
    key: str,
    model: str,
) -> None:
    """Insert a scores row for the upload. Caller commits the transaction."""
    conn.execute(
        "INSERT INTO scores(upload_id, cache_key, model_id, result_json) "
        "VALUES (?, ?, ?, ?)",
        (upload_id, key, model, result.model_dump_json()),
    )
