"""Optimise chat — walks the user through high/medium gaps.

Endpoints:

- ``POST /api/optimise/start``          create-or-get session for an upload
- ``POST /api/optimise/{sid}/message``  user message; may produce a rewrite
- ``POST /api/optimise/{sid}/skip``     user-initiated skip of current gap
- ``GET  /api/optimise/{sid}``          full state (for page reload)

Ownership is enforced at each entry point via the upload's ``user_id``.
Low-severity gaps are dropped up front so the state machine only ever
sees the ones we care about closing.
"""

from __future__ import annotations

from contextlib import closing
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import CurrentUser, current_user
from app.optimise import (
    MAX_ASKS_PER_GAP,
    FabricationError,
    OptimiseError,
    OptimiseOutcome,
    TranscriptMessage,
    is_denial,
)
from app.scoring import ScoreGap, read_score_for_upload


router = APIRouter(prefix="/api/optimise", tags=["optimise"])


# Only high and medium gaps are walked; low ones are dropped up front.
# Keeps the state machine and the DB free of gaps we would never touch.
_SEVERITY_ORDER = {"high": 0, "medium": 1}


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: str
    content: str


class Rewrite(BaseModel):
    gap_index: int
    # "rewrite" | "add" | "skip" | "unavailable". "skip" means the user
    # (or the model, on the user's behalf) said they have no relevant
    # experience. "unavailable" means the system could not produce a
    # valid rewrite (fabrication guard tripped, etc.). The frontend
    # renders these two very differently — "skip" belongs to the user,
    # "unavailable" belongs to us.
    action: str
    original_bullet: str | None
    rewritten_bullet: str | None
    reason: str | None


class SessionState(BaseModel):
    session_id: int
    upload_id: int
    status: str
    current_gap_index: int
    gaps: list[ScoreGap]
    transcript: list[Message]
    rewrites: list[Rewrite]


class StartRequest(BaseModel):
    upload_id: int


class MessageRequest(BaseModel):
    content: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _walked_gaps(gaps: list[ScoreGap]) -> list[ScoreGap]:
    """Keep only the gaps we walk (high before medium). Stable ordering."""
    walked = [(i, g) for i, g in enumerate(gaps) if g.severity in _SEVERITY_ORDER]
    walked.sort(key=lambda pair: (_SEVERITY_ORDER[pair[1].severity], pair[0]))
    return [g for _, g in walked]


def _fetch_owned_upload(request: Request, upload_id: int, user_id: int) -> Any:
    with closing(request.app.state.db_connect()) as conn:
        row = conn.execute(
            "SELECT id, user_id, extracted_text FROM uploads WHERE id = ?",
            (upload_id,),
        ).fetchone()
    if row is None or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Unknown upload.")
    return row


def _fetch_session(request: Request, session_id: int, user_id: int) -> Any:
    with closing(request.app.state.db_connect()) as conn:
        row = conn.execute(
            "SELECT id, upload_id, user_id, current_gap_index, status "
            "FROM optimise_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    if row is None or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Unknown optimise session.")
    return row


def _load_transcript(request: Request, session_id: int) -> list[Message]:
    with closing(request.app.state.db_connect()) as conn:
        rows = conn.execute(
            "SELECT role, content FROM optimise_messages "
            "WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [Message(role=r["role"], content=r["content"]) for r in rows]


def _count_asks_for_gap(request: Request, session_id: int, gap_index: int) -> int:
    """How many clarifying questions the model has already asked for this
    gap. Only ``ask`` outcomes leave the gap pointer in place, so any
    assistant message tagged with ``gap_index`` is an ``ask`` from a
    prior turn on this same gap.
    """
    with closing(request.app.state.db_connect()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM optimise_messages "
            "WHERE session_id = ? AND gap_index = ? AND role = 'assistant'",
            (session_id, gap_index),
        ).fetchone()
    return int(row["n"]) if row is not None else 0


def _load_rewrites(request: Request, session_id: int) -> list[Rewrite]:
    with closing(request.app.state.db_connect()) as conn:
        rows = conn.execute(
            "SELECT gap_index, action, original_bullet, rewritten_bullet, reason "
            "FROM optimise_rewrites WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [
        Rewrite(
            gap_index=r["gap_index"],
            action=r["action"],
            original_bullet=r["original_bullet"],
            rewritten_bullet=r["rewritten_bullet"],
            reason=r["reason"],
        )
        for r in rows
    ]


def _load_gaps(request: Request, upload_id: int) -> list[ScoreGap]:
    score = read_score_for_upload(upload_id, request.app.state.db_connect)
    if score is None:
        raise HTTPException(
            status_code=409,
            detail="Cannot optimise: this upload has not been scored.",
        )
    walked = _walked_gaps(score.gaps)
    if not walked:
        raise HTTPException(
            status_code=409,
            detail="Nothing to optimise: this CV has no high or medium gaps.",
        )
    return walked


def _state_from_row(
    request: Request, session_row: Any, gaps: list[ScoreGap]
) -> SessionState:
    return SessionState(
        session_id=session_row["id"],
        upload_id=session_row["upload_id"],
        status=session_row["status"],
        current_gap_index=session_row["current_gap_index"],
        gaps=gaps,
        transcript=_load_transcript(request, session_row["id"]),
        rewrites=_load_rewrites(request, session_row["id"]),
    )


def _persist_message(
    request: Request, session_id: int, gap_index: int, role: str, content: str
) -> None:
    with closing(request.app.state.db_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO optimise_messages(session_id, gap_index, role, content) "
            "VALUES (?, ?, ?, ?)",
            (session_id, gap_index, role, content),
        )


def _persist_rewrite(
    request: Request,
    session_id: int,
    gap_index: int,
    *,
    action: str,
    original_bullet: str | None,
    rewritten_bullet: str | None,
    reason: str | None,
) -> None:
    with closing(request.app.state.db_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO optimise_rewrites(session_id, gap_index, action, "
            "original_bullet, rewritten_bullet, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session_id,
                gap_index,
                action,
                original_bullet,
                rewritten_bullet,
                reason,
            ),
        )


def _advance(request: Request, session_id: int, current_index: int, total: int) -> None:
    """Bump the gap index; mark done when past the last gap.

    The UPDATE is conditional on the current index matching, so two
    concurrent requests reading the same index cannot both advance and
    silently skip a gap. If the guard misses, the caller's outcome has
    already been persisted; the next request will read the fresh index.
    """
    new_index = current_index + 1
    status = "done" if new_index >= total else "active"
    with closing(request.app.state.db_connect()) as conn, conn:
        conn.execute(
            "UPDATE optimise_sessions SET current_gap_index = ?, status = ? "
            "WHERE id = ? AND current_gap_index = ?",
            (new_index, status, session_id, current_index),
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/start", response_model=SessionState)
def start(
    payload: StartRequest,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> SessionState:
    upload = _fetch_owned_upload(request, payload.upload_id, user.id)
    gaps = _load_gaps(request, upload["id"])

    # Idempotent: same upload returns the existing session.
    with closing(request.app.state.db_connect()) as conn, conn:
        existing = conn.execute(
            "SELECT id FROM optimise_sessions WHERE upload_id = ?",
            (upload["id"],),
        ).fetchone()
        if existing is None:
            cursor = conn.execute(
                "INSERT INTO optimise_sessions(upload_id, user_id) VALUES (?, ?)",
                (upload["id"], user.id),
            )
            session_id = int(cursor.lastrowid)
        else:
            session_id = int(existing["id"])

    session_row = _fetch_session(request, session_id, user.id)
    return _state_from_row(request, session_row, gaps)


@router.get("/{session_id}", response_model=SessionState)
def get_session(
    session_id: int,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> SessionState:
    session_row = _fetch_session(request, session_id, user.id)
    gaps = _load_gaps(request, session_row["upload_id"])
    return _state_from_row(request, session_row, gaps)


@router.post("/{session_id}/message", response_model=SessionState)
def send_message(
    session_id: int,
    payload: MessageRequest,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> SessionState:
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message cannot be blank.")

    session_row = _fetch_session(request, session_id, user.id)
    if session_row["status"] == "done":
        raise HTTPException(status_code=409, detail="This optimise session is complete.")

    upload = _fetch_owned_upload(request, session_row["upload_id"], user.id)
    gaps = _load_gaps(request, upload["id"])
    current_index = session_row["current_gap_index"]
    if current_index >= len(gaps):
        raise HTTPException(status_code=409, detail="This optimise session is complete.")

    _persist_message(request, session_id, current_index, "user", content)

    # Short-circuit: if the candidate has said they have no experience
    # for this gap, we skip immediately without calling the model. This
    # is the whole product boundary — we don't invent, and we don't
    # push the user for more detail after they've said no.
    if is_denial(content):
        _record_skip(
            request,
            session_id,
            current_index,
            len(gaps),
            reason="Candidate indicated no relevant experience for this gap.",
            assistant_message="Understood. Skipping this gap and moving on.",
        )
        session_row = _fetch_session(request, session_id, user.id)
        return _state_from_row(request, session_row, gaps)

    transcript = _load_transcript(request, session_id)
    transcript_models = [TranscriptMessage(role=m.role, content=m.content) for m in transcript]
    ask_count = _count_asks_for_gap(request, session_id, current_index)

    try:
        outcome = request.app.state.optimise_fn(
            cv_text=upload["extracted_text"],
            gap=gaps[current_index],
            gap_index=current_index,
            total_gaps=len(gaps),
            transcript=transcript_models,
            ask_count=ask_count,
        )
    except FabricationError as exc:
        _record_unavailable(
            request,
            session_id,
            current_index,
            len(gaps),
            reason=f"The AI response contained an unsupported claim: {exc}",
            assistant_message=(
                "I could not produce a valid rewrite for this gap. "
                "Try answering with more specific detail, or skip to the next gap."
            ),
        )
    except OptimiseError as exc:
        raise HTTPException(status_code=502, detail=f"Optimise call failed: {exc}") from exc
    else:
        _apply_outcome(
            request, session_id, current_index, len(gaps), outcome, ask_count=ask_count
        )

    session_row = _fetch_session(request, session_id, user.id)
    return _state_from_row(request, session_row, gaps)


@router.post("/{session_id}/skip", response_model=SessionState)
def skip_gap(
    session_id: int,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> SessionState:
    session_row = _fetch_session(request, session_id, user.id)
    if session_row["status"] == "done":
        raise HTTPException(status_code=409, detail="This optimise session is complete.")

    gaps = _load_gaps(request, session_row["upload_id"])
    current_index = session_row["current_gap_index"]
    if current_index >= len(gaps):
        raise HTTPException(status_code=409, detail="This optimise session is complete.")

    _record_skip(
        request,
        session_id,
        current_index,
        len(gaps),
        reason="Skipped by user.",
        assistant_message="Skipped. Moving on to the next gap.",
    )

    session_row = _fetch_session(request, session_id, user.id)
    return _state_from_row(request, session_row, gaps)


# ---------------------------------------------------------------------------
# Outcome handling
# ---------------------------------------------------------------------------

def _record_skip(
    request: Request,
    session_id: int,
    gap_index: int,
    total_gaps: int,
    *,
    reason: str,
    assistant_message: str,
) -> None:
    """Persist a user/model 'no experience' skip and advance the pointer."""
    _persist_rewrite(
        request,
        session_id,
        gap_index,
        action="skip",
        original_bullet=None,
        rewritten_bullet=None,
        reason=reason,
    )
    _persist_message(request, session_id, gap_index, "assistant", assistant_message)
    _advance(request, session_id, gap_index, total_gaps)


def _record_unavailable(
    request: Request,
    session_id: int,
    gap_index: int,
    total_gaps: int,
    *,
    reason: str,
    assistant_message: str,
) -> None:
    """Persist a system-side 'could not produce a rewrite' outcome.

    Advances the pointer just like a skip so the conversation isn't
    stuck on a gap the model keeps failing to rewrite, but uses a
    distinct action so the frontend does not present this as the user's
    "I have no experience" decision.
    """
    _persist_rewrite(
        request,
        session_id,
        gap_index,
        action="unavailable",
        original_bullet=None,
        rewritten_bullet=None,
        reason=reason,
    )
    _persist_message(request, session_id, gap_index, "assistant", assistant_message)
    _advance(request, session_id, gap_index, total_gaps)


def _apply_outcome(
    request: Request,
    session_id: int,
    gap_index: int,
    total_gaps: int,
    outcome: OptimiseOutcome,
    *,
    ask_count: int,
) -> None:
    """Persist the outcome and advance the gap pointer when appropriate.

    ``ask_count`` is the number of questions the model had already asked
    before this turn. If the model tries to ask another once the budget
    is exhausted (``>= MAX_ASKS_PER_GAP``) we override that decision and
    record an ``unavailable`` outcome — this is the hard cap that stops
    the chat looping forever on confirmation questions.
    """
    if outcome.kind == "ask":
        if ask_count >= MAX_ASKS_PER_GAP:
            _record_unavailable(
                request,
                session_id,
                gap_index,
                total_gaps,
                reason=(
                    "Reached the question limit for this gap without a rewrite. "
                    "You can revisit the gap with a fresh chat later."
                ),
                assistant_message=(
                    "I've asked as many questions as I can for this gap without "
                    "committing to a rewrite. Moving on to the next gap."
                ),
            )
            return
        question = outcome.question or "Could you tell me more about this?"
        _persist_message(request, session_id, gap_index, "assistant", question)
        return

    if outcome.kind == "skip":
        reason = outcome.reason or "No relevant experience for this gap."
        _record_skip(
            request,
            session_id,
            gap_index,
            total_gaps,
            reason=reason,
            assistant_message=f"Skipping this gap. {reason}",
        )
        return

    # kind == "rewrite"
    _persist_rewrite(
        request,
        session_id,
        gap_index,
        action=outcome.action or "rewrite",
        original_bullet=outcome.original_bullet,
        rewritten_bullet=outcome.rewritten_bullet,
        reason=None,
    )
    verb = "Added a new bullet" if outcome.action == "add" else "Rewrote the bullet"
    _persist_message(
        request, session_id, gap_index, "assistant", f"{verb}. See the preview below."
    )
    _advance(request, session_id, gap_index, total_gaps)
