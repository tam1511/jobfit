"""Gap-driven CV rewrite via a chat loop.

After scoring has produced ``gaps``, this module runs the conversation
that closes those gaps one at a time. The model may:

- ``ask`` a targeted question about the current gap,
- ``rewrite`` an existing CV bullet (or ``add`` a new one) using only
  material the candidate has either shown in the original CV or supplied
  in this chat, or
- ``skip`` the gap when the candidate says they do not have the
  experience.

The single hard rule: **never fabricate**. The model returns a
``sources`` array of verbatim substrings drawn from the CV or the user's
messages; ``verify_grounding()`` then checks (1) each source really is a
substring of one of those two texts and (2) every "hard fact" appearing
in the rewritten bullet (numbers, percentages, currency, dates, and
CamelCase/ALLCAPS tokens as a proxy for tool and brand names) is
supported by a source or preserved verbatim from the original bullet.
Failures raise ``FabricationError``; the router turns them into a
``skip`` outcome with the reason surfaced back to the user.

Rewrite calls are **not cached**. Conversation state changes every turn
and any two chats will differ, so a content-hash cache would only ever
miss.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.scoring import ScoreGap


logger = logging.getLogger(__name__)


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
HTTP_TIMEOUT = 60.0


class OptimiseError(RuntimeError):
    """Raised when a rewrite call cannot be produced (network, malformed response)."""


class FabricationError(RuntimeError):
    """Raised when a rewrite contains claims not backed by CV or chat."""


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

Origin = Literal["cv", "user"]


class RewriteSource(BaseModel):
    text: str
    origin: Origin


class OptimiseOutcome(BaseModel):
    """One turn's decision. Discriminated on ``kind``.

    - ``ask``: model needs more info from the user; ``question`` is populated.
    - ``rewrite``: model produced a bullet; the other fields are populated.
    - ``skip``: model recognised the user has no relevant experience.
    """

    kind: Literal["ask", "rewrite", "skip"]
    question: str | None = None
    action: Literal["rewrite", "add"] | None = None
    original_bullet: str | None = None
    rewritten_bullet: str | None = None
    sources: list[RewriteSource] = Field(default_factory=list)
    reason: str | None = None


class TranscriptMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the JobFit rewrite assistant. Your job is to close one CV gap at a time by rewriting the candidate's own words. You never invent experience.

Rules:

1. Focus only on the current gap you are given. Do not ask about other gaps.
2. Ask exactly one question per turn when you need more information. Keep it concrete and specific to the gap.
3. When the candidate has given you enough grounded material, rewrite an existing bullet from the CV, or add one new bullet, using the Action Verb -> Work Performed -> Measurable Result structure.
4. If the candidate says they have no such experience, choose "skip". Do not try to salvage the gap with rephrasing.
5. Never fabricate. Every number, percentage, currency figure, date, tool name, company name, certification, or job title in a rewritten bullet must come from either the CV or the candidate's own messages in this chat.
6. Populate "sources" with verbatim substrings from the CV or the user's messages that back every non-preserved claim in the rewritten bullet. Do not paraphrase in the sources.
7. Preserve the candidate's tone.

Return only the JSON matching the provided schema. No prose outside the JSON."""


RESPONSE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "question", "action", "original_bullet", "rewritten_bullet", "sources", "reason"],
    "properties": {
        "kind": {"type": "string", "enum": ["ask", "rewrite", "skip"]},
        "question": {"type": ["string", "null"]},
        "action": {"type": ["string", "null"]},
        "original_bullet": {"type": ["string", "null"]},
        "rewritten_bullet": {"type": ["string", "null"]},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "origin"],
                "properties": {
                    "text": {"type": "string"},
                    "origin": {"type": "string", "enum": ["cv", "user"]},
                },
            },
        },
        "reason": {"type": ["string", "null"]},
    },
}


def build_user_message(
    cv_text: str,
    gap: ScoreGap,
    gap_index: int,
    total_gaps: int,
    transcript: list[TranscriptMessage],
) -> str:
    """Assemble the per-turn user message handed to the model.

    The full CV comes with every turn (small documents, low cost, avoids
    losing context) plus the current gap and the transcript so far.
    """
    lines = [
        f"CURRENT GAP ({gap_index + 1} of {total_gaps}, severity: {gap.severity}):",
        f"- Evidence: {gap.evidence}",
        f"- Suggestion: {gap.suggestion}",
        "",
        "ORIGINAL CV:",
        cv_text,
        "",
        "CHAT SO FAR:",
    ]
    if not transcript:
        lines.append("(no messages yet - start by asking one specific question about this gap)")
    else:
        for msg in transcript:
            lines.append(f"{msg.role}: {msg.content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Anti-fabrication guard
# ---------------------------------------------------------------------------

# Hard facts: numbers with a unit or two-plus digits, and tokens that
# look like tool / brand names (Capitalized words 2+ chars, ALLCAPS 2+
# chars, or CamelCase). These are the fields most likely to be invented;
# the check errs on the side of catching invented material.
#
# Bare single digits ("led 2 hires") are excluded because they will
# trivially substring-match any source containing that digit, which
# defeats the whole point of the check. A single digit with a unit
# ("2%", "$2", "2k") still counts.
_NUMBER_RE = re.compile(r"[$£€¥]\d[\d,\.]*|\d[\d,\.]*[%kKmMbB]|\d[\d,\.]+")
_TOKEN_RE = re.compile(r"\b(?:[A-Z]{2,}[A-Za-z0-9+.-]*|[A-Z][a-z]+(?:[A-Z][A-Za-z0-9+.-]*)+|[A-Z][a-zA-Z]+)\b")

# Tokens that are grammatical rather than proper nouns and should not
# trigger a fabrication check on their own. Kept small; the goal is to
# avoid noise, not to whitelist product names.
_TOKEN_STOPWORDS = {
    "I",
    "A",
    "An",
    "The",
    "Led",
    "Managed",
    "Built",
    "Drove",
    "Launched",
    "Shipped",
    "Owned",
    "Delivered",
    "Improved",
    "Increased",
    "Reduced",
    "Grew",
    "Ran",
    "Rolled",
    "Wrote",
    "Designed",
    "Developed",
    "Implemented",
    "Created",
    "Achieved",
    "Analyzed",
    "Analysed",
}


def _extract_hard_facts(text: str) -> list[str]:
    """Numbers and proper-noun-ish tokens worth checking for fabrication."""
    facts = _NUMBER_RE.findall(text)
    for tok in _TOKEN_RE.findall(text):
        if tok in _TOKEN_STOPWORDS:
            continue
        facts.append(tok)
    return [f.strip() for f in facts if f.strip()]


def verify_grounding(
    rewritten: str,
    sources: list[RewriteSource],
    *,
    cv_text: str,
    original_bullet: str | None,
    user_messages: list[str],
) -> None:
    """Raise FabricationError if the rewrite contains unsupported claims.

    A source is valid only when its verbatim text appears in ``cv_text``
    (for ``origin="cv"``) or in one of the ``user_messages`` (for
    ``origin="user"``). Each hard fact in ``rewritten`` must appear in
    one of the valid sources or verbatim in ``original_bullet`` — the
    latter clause lets a rewrite preserve an existing "30% conversion"
    without re-listing it as a source.

    ``original_bullet`` is model-supplied, so before we trust it as a
    grounding anchor we require that it itself appears verbatim in the
    CV. Otherwise the model could invent a plausible ``original_bullet``
    containing a fake metric and pass the check by "preserving" it.
    """
    original = original_bullet or ""
    if original and original not in cv_text:
        raise FabricationError(
            f"original_bullet not found verbatim in CV: {original!r}"
        )

    joined_user = "\n".join(user_messages)
    valid_sources: list[str] = []
    for src in sources:
        haystack = cv_text if src.origin == "cv" else joined_user
        if src.text and src.text in haystack:
            valid_sources.append(src.text)
        else:
            raise FabricationError(
                f"Source not found in {src.origin} text: {src.text!r}"
            )

    for fact in _extract_hard_facts(rewritten):
        if fact in original:
            continue
        if any(fact in s for s in valid_sources):
            continue
        raise FabricationError(
            f"Rewritten bullet contains unsupported claim: {fact!r}"
        )


# ---------------------------------------------------------------------------
# OpenRouter call
# ---------------------------------------------------------------------------

def _call_openrouter(
    system_prompt: str,
    user_message: str,
    *,
    api_key: str,
    model: str,
) -> dict:
    """One HTTP call. Returns the parsed message content dict."""
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "optimise_turn",
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
        raise OptimiseError(f"OpenRouter request failed: {exc}") from exc

    if response.status_code >= 400:
        raise OptimiseError(
            f"OpenRouter returned {response.status_code}: {response.text[:200]}"
        )

    try:
        envelope = response.json()
        content = envelope["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise OptimiseError(f"OpenRouter response was not valid: {exc}") from exc


def _call_with_retry(
    system_prompt: str,
    user_message: str,
    *,
    api_key: str,
    model: str,
    call: Callable[..., dict],
) -> dict:
    """One retry on any OptimiseError. Two attempts total.

    Misconfiguration is checked up front so a missing api_key fails
    without wasting a call (or a retry) on a request that cannot work.
    """
    if not api_key:
        raise OptimiseError("OPENROUTER_API_KEY is not configured.")
    try:
        return call(system_prompt, user_message, api_key=api_key, model=model)
    except OptimiseError as first:
        logger.warning("Optimise call failed, retrying once: %s", first)
        return call(system_prompt, user_message, api_key=api_key, model=model)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def rewrite(
    *,
    cv_text: str,
    gap: ScoreGap,
    gap_index: int,
    total_gaps: int,
    transcript: list[TranscriptMessage],
    api_key: str,
    model: str,
    call: Callable[..., dict] | None = None,
) -> OptimiseOutcome:
    """Run one turn of the rewrite chat.

    Returns an OptimiseOutcome; the router persists it and advances (or
    stays on) the current gap accordingly. Grounding is checked here so
    a fabricated response is caught before it reaches the DB.
    """
    user_message = build_user_message(cv_text, gap, gap_index, total_gaps, transcript)
    raw = _call_with_retry(
        SYSTEM_PROMPT,
        user_message,
        api_key=api_key,
        model=model,
        call=call or _call_openrouter,
    )
    try:
        outcome = OptimiseOutcome.model_validate(raw)
    except ValidationError as exc:
        raise OptimiseError(f"Model response failed validation: {exc}") from exc

    if outcome.kind == "rewrite":
        if not outcome.rewritten_bullet or outcome.action is None:
            raise OptimiseError("Rewrite outcome missing rewritten_bullet or action.")
        user_texts = [m.content for m in transcript if m.role == "user"]
        verify_grounding(
            outcome.rewritten_bullet,
            outcome.sources,
            cv_text=cv_text,
            original_bullet=outcome.original_bullet,
            user_messages=user_texts,
        )
    return outcome
