"""FastAPI entrypoint.

Serves the API under /api and the statically-exported Next.js frontend
under /. Both live in the same process so the whole app fits into a
single Docker image, per CLAUDE.md.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from app.config import Settings, load_settings
from app.db import connect, init_db
from app.jd_fetch import FetchedJd, fetch_jd
from app.optimise import OptimiseOutcome, TranscriptMessage, rewrite
from app.routers import auth as auth_router
from app.routers import jd as jd_router
from app.routers import optimise as optimise_router
from app.routers import uploads as uploads_router
from app.scoring import ScoreGap, ScoreResult, score


ScoreFn = Callable[[str, str], ScoreResult]
JdFetchFn = Callable[[str], FetchedJd]
OptimiseFn = Callable[..., OptimiseOutcome]

HTML_CACHE = "no-cache"
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


class ImmutableStaticFiles(StaticFiles):
    """Serve content-hashed build artefacts with a long immutable cache."""

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = IMMUTABLE_CACHE
        return response


def _mount_frontend(app: FastAPI, frontend_dir: Path) -> None:
    """Serve the Next.js static export.

    In development the app may run before the frontend is built. The
    backend still starts; the root path just returns a helpful message
    instead of 404.
    """
    root_index = frontend_dir / "index.html"
    if not root_index.is_file():
        @app.get("/")
        def _no_frontend() -> JSONResponse:
            return JSONResponse(
                {
                    "message": "Backend is running. Build the frontend to serve the UI.",
                    "hint": "cd frontend && npm install && npm run build",
                }
            )
        return

    next_static = frontend_dir / "_next"
    if next_static.is_dir():
        app.mount("/_next", ImmutableStaticFiles(directory=next_static), name="next-static")

    def _serve(subpath: str) -> FileResponse:
        # Next.js static export with trailingSlash writes each route as
        # <route>/index.html. Fall back to the root index if a route was
        # not built (dev safety net) so the SPA can still hydrate.
        candidate = frontend_dir / subpath / "index.html" if subpath else root_index
        target = candidate if candidate.is_file() else root_index
        return FileResponse(target, headers={"Cache-Control": HTML_CACHE})

    @app.get("/")
    def _root() -> FileResponse:
        return _serve("")

    for path in ("/login", "/register", "/app", "/app/new", "/app/applications"):
        for suffix in ("", "/"):
            sub = path.strip("/")
            app.add_api_route(
                f"{path}{suffix}",
                lambda sub=sub: _serve(sub),
                methods=["GET"],
                include_in_schema=False,
            )


def create_app(
    settings: Settings | None = None,
    score_fn: ScoreFn | None = None,
    jd_fetch_fn: JdFetchFn | None = None,
    optimise_fn: OptimiseFn | None = None,
) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db(settings.db_path)
        yield

    app = FastAPI(title="JobFit", lifespan=lifespan)
    app.state.settings = settings
    app.state.db_connect = partial(connect, settings.db_path)

    if score_fn is None:
        def _real_score_fn(cv_text: str, jd_text: str) -> ScoreResult:
            return score(
                cv_text,
                jd_text,
                api_key=settings.openrouter_api_key,
                model=settings.openrouter_model,
                db_connect=app.state.db_connect,
            )
        score_fn = _real_score_fn
    app.state.score_fn = score_fn

    if jd_fetch_fn is None:
        def _real_jd_fetch_fn(url: str) -> FetchedJd:
            return fetch_jd(
                url,
                http_timeout=settings.jd_fetch_http_timeout,
                browser_timeout=settings.jd_fetch_browser_timeout,
                max_bytes=settings.jd_fetch_max_bytes,
            )
        jd_fetch_fn = _real_jd_fetch_fn
    app.state.jd_fetch_fn = jd_fetch_fn

    if optimise_fn is None:
        def _real_optimise_fn(
            *,
            cv_text: str,
            gap: ScoreGap,
            gap_index: int,
            total_gaps: int,
            transcript: list[TranscriptMessage],
            ask_count: int = 0,
        ) -> OptimiseOutcome:
            return rewrite(
                cv_text=cv_text,
                gap=gap,
                gap_index=gap_index,
                total_gaps=total_gaps,
                transcript=transcript,
                api_key=settings.openrouter_api_key,
                model=settings.openrouter_model,
                ask_count=ask_count,
            )
        optimise_fn = _real_optimise_fn
    app.state.optimise_fn = optimise_fn

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router.router)
    app.include_router(uploads_router.router)
    app.include_router(jd_router.router)
    app.include_router(optimise_router.router)

    _mount_frontend(app, settings.frontend_dir)
    return app


app = create_app()
