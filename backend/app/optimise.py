"""Gap-driven CV rewrite via a chat loop.

After scoring has produced ``gaps``, this module runs the conversation
that closes those gaps one at a time. The model may:

- ``ask`` a targeted question about the current gap,
- ``rewrite`` an existing CV bullet (chosen by ``bullet_index`` into a
  numbered list built here from the CV) or ``add`` a new one, using
  only material the candidate has shown in the CV or supplied in chat,
- ``skip`` the gap when the candidate says they do not have the
  experience.

The model never copies text back at us. It picks an existing bullet by
``bullet_index`` into the numbered CV BULLETS list; it does not return
an ``original_bullet`` string or a ``sources`` array. That closes off
the entire "string round-trip" failure surface: LLMs paraphrase when
they copy, pypdf mangles whitespace, and any protocol built on the
model reproducing an exact CV substring will false-positive against
otherwise-grounded rewrites.

The anti-fabrication guard runs at the entity level, not the string
level. ``verify_grounding`` extracts atomic facts from the rewritten
bullet (numbers with units, currency, CamelCase / ALLCAPS proper-noun
tokens) and checks each fact against a normalised concatenation of the
CV text, the resolved ``original_bullet`` and every user message in
this conversation. A long paragraph is never the unit of matching.

The user's own denial short-circuits the whole loop. When the current
message reads as "I have no such experience", the router records a
skip and advances the gap without calling the model at all — this is
the behaviour the product exists for.

Rewrite calls are **not cached**. Conversation state changes every turn
and any two chats will differ, so a content-hash cache would only ever
miss.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.scoring import ScoreGap


logger = logging.getLogger(__name__)


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
HTTP_TIMEOUT = 60.0


class OptimiseError(RuntimeError):
    """Raised when a rewrite call cannot be produced (network, malformed response)."""


class FabricationError(RuntimeError):
    """Raised when a rewrite contains claims not backed by CV or chat."""


# ---------------------------------------------------------------------------
# Bullet extraction
# ---------------------------------------------------------------------------

# Common bullet glyphs found in pypdf-extracted text. The extractor also
# handles unmarked bullets that rely on 2-space continuation indent, which
# is what pypdf produces for our own fixture CVs.
_BULLET_MARKERS = ("- ", "* ", "• ", "● ", "▪ ", "▸ ", "◦ ", "· ")


@dataclass(frozen=True)
class CvBullet:
    """One CV bullet as seen by the Optimise chat.

    ``raw`` is the exact substring of ``cv_text`` — this is what
    ``apply_rewrites`` needs so ``str.replace(original, rewritten, 1)``
    finds the bullet when we re-render the PDF. ``display`` is the same
    text with whitespace collapsed for prompts and matching.
    """

    index: int
    raw: str
    display: str


def _strip_marker(line: str) -> str:
    stripped = line.lstrip()
    for marker in _BULLET_MARKERS:
        if stripped.startswith(marker):
            return stripped[len(marker):]
    return stripped


def extract_bullets(cv_text: str) -> list[CvBullet]:
    """Split CV text into a numbered list of bullet-like items.

    A bullet starts at a non-empty line and consumes any following lines
    that begin with two or more spaces (continuation). Both marked
    bullets (``-``, ``*``, ``•``, ``●``, ...) and unmarked lines are
    included; the model can decide which to rewrite. Blank lines separate
    bullets.

    The returned ``raw`` values are contiguous non-overlapping slices of
    ``cv_text``, so a downstream ``str.replace(bullet.raw, rewritten)``
    will match exactly once.
    """
    bullets: list[CvBullet] = []
    lines = cv_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        group = [line]
        j = i + 1
        while j < len(lines) and lines[j].startswith("  ") and lines[j].strip():
            group.append(lines[j])
            j += 1
        raw = "\n".join(group)
        display = re.sub(r"\s+", " ", _strip_marker(" ".join(g.strip() for g in group))).strip()
        if display:
            bullets.append(CvBullet(index=len(bullets), raw=raw, display=display))
        i = j
    return bullets


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


class OptimiseOutcome(BaseModel):
    """One resolved turn, ready for the router to persist.

    - ``ask``: model needs more info; ``question`` is populated.
    - ``rewrite``: model produced a bullet; the other fields are populated.
      ``original_bullet`` is backend-derived from the model's
      ``bullet_index`` (see ``_ModelResponse``), so it is always a
      verbatim substring of the CV.
    - ``skip``: model recognised the user has no relevant experience.
    """

    kind: Literal["ask", "rewrite", "skip"]
    question: str | None = None
    action: Literal["rewrite", "add"] | None = None
    original_bullet: str | None = None
    rewritten_bullet: str | None = None
    reason: str | None = None


class _ModelResponse(BaseModel):
    """Raw shape the LLM returns via Structured Outputs.

    The model never copies bullet text back to us — no ``sources``
    array, no ``original_bullet`` string. When it wants to rewrite an
    existing bullet it picks one by ``bullet_index`` from the numbered
    list included in the prompt; the backend resolves the string. The
    fabrication guard then works at the entity level against the CV
    text and the user's own messages, not against a fragile string
    round-trip through the model.
    """

    kind: Literal["ask", "rewrite", "skip"]
    question: str | None = None
    action: Literal["rewrite", "add"] | None = None
    bullet_index: int | None = None
    rewritten_bullet: str | None = None
    reason: str | None = None


class TranscriptMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

# Hard cap on clarifying questions the model may ask per gap. After
# ``MAX_ASKS_PER_GAP`` questions, the user message carries a forced-
# commit directive: the model must produce a rewrite/add or skip. This
# is belt-and-braces on top of the prompt rules — a poorly-behaved
# model can otherwise loop asking "confirm the exact phrasing" forever
# even after the candidate has explicitly said "please proceed".
MAX_ASKS_PER_GAP = 3


SYSTEM_PROMPT = """You are the JobFit rewrite assistant. Your job is to close one CV gap at a time by rewriting the candidate's own words. You never invent experience.

Rules:

1. Focus only on the current gap you are given. Do not ask about other gaps.
2. Ask at most one concrete, specific question per turn, and only when you truly need a missing fact. You have a hard budget of a few questions per gap — spend it on facts you cannot rewrite without.
3. Do not ask the candidate to approve or confirm your phrasing. You choose the wording. Never ask "which phrasing do you prefer" or "should I go ahead" — if the candidate has provided grounded facts, commit to a rewrite immediately.
4. If the candidate explicitly asks you to proceed, add the bullet, finish the gap, or write the bullet themselves — commit on that turn. Do not ask another clarifying question. Choose action="rewrite" or action="add" with the material you have.
5. When you commit, either rewrite an existing bullet from the CV (action="rewrite" plus the bullet_index from the numbered CV BULLETS list) or add a fully new bullet (action="add" with bullet_index=null). Use Action Verb -> Work Performed -> Measurable Result when a metric is available; a bullet without a numeric metric is acceptable if the candidate says none exists — use qualitative outcomes and specific technologies or scope instead. Never make up a metric to complete the pattern.
6. Never copy an existing bullet's text into "rewritten_bullet" as if it were unchanged. If you can't improve it, ask another question or skip.
7. If the candidate says or implies they have no such experience — "I don't have that", "never done", "no experience with that", "haven't used" — choose kind="skip" immediately. Do not ask a follow-up question. Do not invite them to elaborate. The whole point of skipping is to move on.
8. Never fabricate. Every number, percentage, currency figure, date, tool name, company name, certification, or job title in the rewritten bullet must come from either the CV or the candidate's own messages in this chat. You do not need to quote your sources back to us; the backend verifies grounding automatically.
9. Preserve the candidate's tone.

Return only the JSON matching the provided schema. No prose outside the JSON."""


_FORCED_COMMIT_DIRECTIVE = (
    "IMPORTANT DIRECTIVE (question budget exhausted): You have already asked "
    "{ask_count} question(s) for this gap. You MUST NOT ask another question. "
    "Choose one of: (a) kind=\"rewrite\", action=\"rewrite\" with a bullet_index, "
    "or (b) kind=\"rewrite\", action=\"add\" with bullet_index=null — using "
    "only the facts the candidate has already given, and omitting a numeric "
    "metric if none was provided; or (c) kind=\"skip\" only if the candidate "
    "has said they have no relevant experience for this gap."
)


def _build_response_schema(num_bullets: int) -> dict:
    """Build the Structured Outputs schema for one turn.

    ``bullet_index`` is enum-constrained to the exact set of valid bullet
    indices (plus null for ``add`` / ``ask`` / ``skip``), so the model
    cannot pick an out-of-range integer or a stray value.
    """
    bullet_choices: list[int | None] = list(range(num_bullets))
    bullet_choices.append(None)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "question", "action", "bullet_index", "rewritten_bullet", "reason"],
        "properties": {
            "kind": {"type": "string", "enum": ["ask", "rewrite", "skip"]},
            "question": {"type": ["string", "null"]},
            "action": {"type": ["string", "null"], "enum": ["rewrite", "add", None]},
            "bullet_index": {"type": ["integer", "null"], "enum": bullet_choices},
            "rewritten_bullet": {"type": ["string", "null"]},
            "reason": {"type": ["string", "null"]},
        },
    }


def build_user_message(
    cv_text: str,
    bullets: list[CvBullet],
    gap: ScoreGap,
    gap_index: int,
    total_gaps: int,
    transcript: list[TranscriptMessage],
    ask_count: int = 0,
) -> str:
    """Assemble the per-turn user message handed to the model.

    Includes the full CV text (small documents, low cost, avoids losing
    context) and a separate numbered CV BULLETS list. When the model
    picks a bullet to rewrite it returns the index from this list, never
    a copy of the bullet text — that is how the guard against fake
    "originals" is enforced end to end.

    ``ask_count`` is the number of clarifying questions the model has
    already asked for this gap. When it reaches ``MAX_ASKS_PER_GAP`` we
    prepend a forced-commit directive so the model can't loop asking
    for confirmation.
    """
    lines: list[str] = []
    if ask_count >= MAX_ASKS_PER_GAP:
        lines.append(_FORCED_COMMIT_DIRECTIVE.format(ask_count=ask_count))
        lines.append("")
    lines += [
        f"CURRENT GAP ({gap_index + 1} of {total_gaps}, severity: {gap.severity}):",
        f"- Evidence: {gap.evidence}",
        f"- Suggestion: {gap.suggestion}",
        "",
        "ORIGINAL CV:",
        cv_text,
        "",
        "CV BULLETS (choose bullet_index from this list when action=\"rewrite\"):",
    ]
    if bullets:
        for b in bullets:
            lines.append(f"[{b.index}] {b.display}")
    else:
        lines.append("(no bullets detected in this CV — use action=\"add\" or ask a question)")
    lines.append("")
    lines.append(f"QUESTIONS ASKED FOR THIS GAP: {ask_count} of {MAX_ASKS_PER_GAP} max")
    lines.append("")
    lines.append("CHAT SO FAR:")
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
# look like tool / brand names (ALLCAPS 2+ chars, CamelCase, or plain
# Capitalized 2+ chars). These are the fields most likely to be
# invented; the check errs on the side of catching invented material.
#
# Bare single digits ("led 2 hires") are excluded because they will
# trivially substring-match any source containing that digit, which
# defeats the whole point of the check. A single digit with a unit
# ("2%", "$2", "2k") still counts.
_NUMBER_RE = re.compile(r"[$£€¥]\d[\d,\.]*|\d[\d,\.]*[%kKmMbB]|\d[\d,\.]+")

# Three token shapes, matched separately so the plain-Capitalized shape
# can carry an extra sentence-start exemption (see ``_extract_hard_facts``).
_ALLCAPS_RE = re.compile(r"\b[A-Z]{2,}[A-Za-z0-9+.-]*\b")
_CAMELCASE_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][A-Za-z0-9+.-]*)+\b")
_PLAIN_CAP_RE = re.compile(r"\b[A-Z][a-zA-Z]+\b")

# Small stopword list of grammatical words that also happen to be
# plain-Capitalized. Sentence-initial verbs are handled separately by
# the sentence-start check, so this list only needs pronouns / articles
# / verbs that may appear mid-sentence.
_TOKEN_STOPWORDS = {"I", "A", "An", "The"}


def _is_sentence_start(text: str, i: int) -> bool:
    """True if position ``i`` is the first non-space character after a
    sentence terminator (``.``, ``!``, ``?``, ``;``, newline) or the
    start of the string. Used to exempt plain-Capitalized tokens like
    "Deployed" or "Applied" that start a rewritten bullet — those are
    ordinary English verbs, not proper nouns.
    """
    j = i - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    if j < 0:
        return True
    return text[j] in ".!?;\n"


def _extract_hard_facts(text: str) -> list[str]:
    """Numbers and proper-noun-ish tokens worth checking for fabrication.

    CamelCase and ALLCAPS shapes only occur in brand / tool / acronym
    names, so every match is checked. Plain-Capitalized words are more
    ambiguous (proper noun vs sentence-initial verb), so a match is
    checked only when it is *not* the first word of a sentence — that
    is where English verbs and articles show up.
    """
    facts: list[str] = list(_NUMBER_RE.findall(text))
    facts.extend(_ALLCAPS_RE.findall(text))
    facts.extend(_CAMELCASE_RE.findall(text))
    for m in _PLAIN_CAP_RE.finditer(text):
        tok = m.group(0)
        if tok in _TOKEN_STOPWORDS:
            continue
        if _is_sentence_start(text, m.start()):
            continue
        facts.append(tok)
    return [f.strip() for f in facts if f.strip()]


# Bullet markers we strip so a source that quotes a marked bullet still
# matches a haystack that stripped its marker (or vice versa).
_BULLET_MARKER_RE = re.compile(r"^\s*[-*•●▪▸◦·]+\s+", flags=re.MULTILINE)


def _norm(text: str) -> str:
    """Fold text to a canonical form for substring matching.

    - NFC unicode normalisation, so precomposed vs decomposed diacritics
      compare equal.
    - Strip leading bullet markers on every line — pypdf drops them for
      unmarked bullets but keeps them when present, and the model prompt
      shows the marker-stripped ``display`` form of each bullet, so the
      two sides can disagree here even when the content is identical.
    - Collapse every whitespace run (including the newline + 2-space
      continuation indent pypdf injects between wrapped bullet lines) to
      a single space.
    - Lowercase, so casing drift in either side doesn't matter for the
      substring check.

    Raise messages keep the original (un-normalised) strings so the user
    still sees what the model actually returned.
    """
    text = unicodedata.normalize("NFC", text)
    text = _BULLET_MARKER_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def verify_grounding(
    rewritten: str,
    *,
    cv_text: str,
    original_bullet: str | None,
    user_messages: list[str],
) -> None:
    """Raise FabricationError if the rewrite contains unsupported claims.

    Entity-level check. For each hard fact in ``rewritten`` (numbers
    with units, currency, CamelCase / ALLCAPS proper-noun tokens) the
    fact must appear in at least one of:

    - the ``cv_text`` — fully trusted, the candidate typed it into
      their own document,
    - the resolved ``original_bullet`` — a substring of the CV by
      construction (the caller resolved it from ``bullet_index``),
    - any user message in this conversation.

    User messages **can** contain denials ("I have not used HubSpot"),
    so an entity present in a message is trusted the same way the CV
    is trusted: as raw material the model may draw on. The router's
    denial detector is what stops the model from picking up "HubSpot"
    from a denial in the first place — by the time we reach here, if
    an entity is in a user message the candidate typed it themselves.

    There is no ``sources`` argument: the model doesn't have to hand
    back verbatim substrings, and the guard doesn't rely on it doing
    so. That closes off the false-positive class where an LLM
    paraphrase of a real CV fact caused a legitimate rewrite to be
    rejected.
    """
    haystack_norm = _norm(
        "\n".join([cv_text, original_bullet or "", *user_messages])
    )

    for fact in _extract_hard_facts(rewritten):
        fact_norm = _norm(fact)
        if not fact_norm:
            continue
        if fact_norm in haystack_norm:
            continue
        raise FabricationError(
            f"Rewritten bullet contains unsupported claim: {fact!r}"
        )


# ---------------------------------------------------------------------------
# Denial detection
# ---------------------------------------------------------------------------

# Phrases that read as "I have no such experience for this gap". The
# router uses these to short-circuit the LLM: if the user's current
# message matches, we record a skip and move on rather than firing
# another turn that would either loop asking for detail or try to
# rephrase a denial into a claim. The list is deliberately small and
# unambiguous — false negatives are fine (the user can hit Skip), but
# false positives would silently drop a real answer.
_DENIAL_PATTERNS = (
    re.compile(r"\bi\s+(do\s*n[o']?t|don't|do\s+not)\s+have\b", re.I),
    re.compile(r"\bi\s+have\s+(not|never|no)\s", re.I),
    re.compile(r"\bi\s+(haven[o']?t|haven't|have\s+not)\b", re.I),
    re.compile(r"\bi\s+(have\s+)?no\s+(experience|background)\b", re.I),
    re.compile(r"\b(never|not)\s+(used|worked|done|had)\b", re.I),
    re.compile(r"\bno\s+such\s+experience\b", re.I),
    re.compile(r"\b(none|nope|nothing)\s+(there|for\s+that|like\s+that)\b", re.I),
)


# Affirmative first-person claims. When any of these appears in the same
# message as a denial pattern, the message is a MIXED answer, not a pure
# denial: the candidate is saying they have some of what we asked about
# and lack the rest. The short-circuit must not fire on mixed answers,
# or the affirmative half gets thrown away.
#
# The patterns intentionally require an object after the verb ("I have
# experience", "I've deployed models") so grammatical constructions
# inside the denial itself ("I have never used it") never accidentally
# match here — the denial patterns above already own that shape.
_AFFIRMATIVE_PATTERNS = (
    # "I have <positive quantifier> experience/knowledge/skills..."
    re.compile(
        r"\bi\s+(?:have|had|'ve)\s+"
        r"(?:hands[-\s]?on|practical|direct|solid|real|extensive|significant|"
        r"prior|previous|deep|strong|working|good|some|a\s+lot\s+of|plenty\s+of)\s+"
        r"(?:experience|expertise|knowledge|background)\b",
        re.I,
    ),
    # "I have used|worked|built|... X" — first-person past-tense action
    # verb with a noun following. Bare "have" without an object is not
    # enough; that could still be the start of a denial.
    re.compile(
        r"\bi\s+(?:have|had|'ve)\s+"
        r"(?:used|worked|built|shipped|led|managed|run|ran|deployed|designed|"
        r"delivered|owned|created|wrote|written|analysed|analyzed|scaled|"
        r"launched|maintained|integrated|migrated|refactored|architected)\b",
        re.I,
    ),
    # "I used|ran|built|... X" — bare past-tense first person.
    re.compile(
        r"\bi\s+"
        r"(?:used|ran|built|shipped|led|managed|deployed|designed|"
        r"delivered|owned|created|wrote|analysed|analyzed|scaled|"
        r"launched|maintained|integrated|migrated|refactored|architected)\b",
        re.I,
    ),
)


# Contrast markers signal that the sentence carrying a negation is being
# played off against another clause — almost always an affirmative one.
# Any of these in the message alongside a denial pattern is a strong
# hint the message is mixed rather than a pure denial.
_CONTRAST_MARKERS = re.compile(
    r"\b(but|although|though|however|whereas|while|yet)\b", re.I
)


def is_denial(message: str) -> bool:
    """True when the user's message reads as a PURE "I have no experience here".

    The check is deliberately conservative on both sides:

    - It fires on unambiguous first-person negative constructions
      ("I don't have", "I've never used", "no experience with").
    - It stands down on MIXED answers — messages that carry a denial
      alongside either an affirmative first-person claim ("I have
      hands-on experience with X") or a contrast marker ("but",
      "although", "however"). Those messages are for the model to
      handle: they contain real material we can rewrite from, and the
      whole point of the guard is to not throw that away.

    False negatives (a real denial the guard misses) are recoverable —
    the user can hit Skip, or the model itself will emit ``kind="skip"``.
    False positives (a partial answer misread as a denial) silently
    drop the affirmative half of the candidate's message and cannot be
    recovered from within the same turn. So err on the side of not
    firing.
    """
    if not message or not message.strip():
        return False
    if not any(pattern.search(message) for pattern in _DENIAL_PATTERNS):
        return False
    # Denial pattern present. Now check whether the message is actually
    # a PURE denial or a mixed one.
    if _CONTRAST_MARKERS.search(message):
        return False
    if any(pattern.search(message) for pattern in _AFFIRMATIVE_PATTERNS):
        return False
    return True


# ---------------------------------------------------------------------------
# OpenRouter call
# ---------------------------------------------------------------------------

def _call_openrouter(
    system_prompt: str,
    user_message: str,
    *,
    api_key: str,
    model: str,
    schema: dict,
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
                "schema": schema,
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
    schema: dict,
    call: Callable[..., dict],
) -> dict:
    """One retry on any OptimiseError. Two attempts total.

    Misconfiguration is checked up front so a missing api_key fails
    without wasting a call (or a retry) on a request that cannot work.
    """
    if not api_key:
        raise OptimiseError("OPENROUTER_API_KEY is not configured.")
    try:
        return call(system_prompt, user_message, api_key=api_key, model=model, schema=schema)
    except OptimiseError as first:
        logger.warning("Optimise call failed, retrying once: %s", first)
        return call(system_prompt, user_message, api_key=api_key, model=model, schema=schema)


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
    ask_count: int = 0,
    call: Callable[..., dict] | None = None,
) -> OptimiseOutcome:
    """Run one turn of the rewrite chat.

    The model chooses which existing bullet to rewrite by
    ``bullet_index`` into the numbered list built here from ``cv_text``.
    The backend then resolves that index to a real CV substring, which
    downstream code uses both as the anti-fabrication anchor and as the
    ``str.replace`` target when the rewritten PDF is rendered.

    ``ask_count`` is the number of clarifying questions the model has
    already asked for this gap. When it reaches ``MAX_ASKS_PER_GAP`` an
    ``ask`` outcome is converted to a forced skip so the conversation
    cannot loop — belt-and-braces alongside the prompt-side directive
    ``build_user_message`` already includes at that threshold.
    """
    bullets = extract_bullets(cv_text)
    user_message = build_user_message(
        cv_text, bullets, gap, gap_index, total_gaps, transcript, ask_count=ask_count
    )
    schema = _build_response_schema(len(bullets))
    raw = _call_with_retry(
        SYSTEM_PROMPT,
        user_message,
        api_key=api_key,
        model=model,
        schema=schema,
        call=call or _call_openrouter,
    )
    try:
        response = _ModelResponse.model_validate(raw)
    except ValidationError as exc:
        raise OptimiseError(f"Model response failed validation: {exc}") from exc

    original_bullet: str | None = None
    if response.kind == "rewrite":
        if not response.rewritten_bullet or response.action is None:
            raise OptimiseError("Rewrite outcome missing rewritten_bullet or action.")
        if response.action == "rewrite":
            if response.bullet_index is None:
                raise OptimiseError("action='rewrite' requires a bullet_index.")
            if response.bullet_index < 0 or response.bullet_index >= len(bullets):
                raise OptimiseError(
                    f"bullet_index {response.bullet_index} out of range 0..{len(bullets) - 1}."
                )
            original_bullet = bullets[response.bullet_index].raw
        user_texts = [m.content for m in transcript if m.role == "user"]
        verify_grounding(
            response.rewritten_bullet,
            cv_text=cv_text,
            original_bullet=original_bullet,
            user_messages=user_texts,
        )

    return OptimiseOutcome(
        kind=response.kind,
        question=response.question,
        action=response.action,
        original_bullet=original_bullet,
        rewritten_bullet=response.rewritten_bullet,
        reason=response.reason,
    )
