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

from app.config import Settings, load_settings
from app.db import connect, init_db
from app.routers import session as session_router
from app.routers import uploads as uploads_router
from app.scoring import ScoreResult, score


ScoreFn = Callable[[str, str], ScoreResult]


def _mount_frontend(app: FastAPI, frontend_dir: Path) -> None:
    """Serve the Next.js static export.

    In development the app may run before the frontend is built. The
    backend still starts; the root path just returns a helpful message
    instead of 404.
    """
    index = frontend_dir / "index.html"
    if not index.is_file():
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
        app.mount("/_next", StaticFiles(directory=next_static), name="next-static")

    app_index = frontend_dir / "app" / "index.html"

    @app.get("/")
    def _root() -> FileResponse:
        return FileResponse(index)

    @app.get("/app")
    @app.get("/app/")
    def _app_page() -> FileResponse:
        return FileResponse(app_index if app_index.is_file() else index)


def create_app(
    settings: Settings | None = None,
    score_fn: ScoreFn | None = None,
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

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(session_router.router)
    app.include_router(uploads_router.router)

    _mount_frontend(app, settings.frontend_dir)
    return app


app = create_app()
