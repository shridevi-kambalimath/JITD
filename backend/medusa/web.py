"""Single-process demo mode: the backend also serves the built React app (frontend/dist).

Enabled with MEDUSA_SERVE_FRONTEND=true. Everything under /api behaves exactly as in development. Any other GET or HEAD
that matches no API route is answered from the build: a real file if one exists (hashed assets are cached for a
year), otherwise index.html, so deep links such as /workspace/review work on reload.

This hooks the not-found path instead of adding a catch-all route. A catch-all route would also match API paths, so a
wrong method on a real endpoint would stop returning 405 and an unknown /api path could fall through to the UI.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .core.errors import _http_error

ASSET_CACHE = "public, max-age=31536000, immutable"  # Vite puts a content hash in every asset file name


def dist_problem(dist: Path) -> str | None:
    """Explain why the build cannot be served, or None if it can."""
    if (dist / "index.html").is_file():
        return None
    return (f"The frontend build was not found at {dist}.\n"
            f"  Build it first:  cd frontend   then   npm run build\n"
            f"  (the VS Code task \"Demo: single process\" builds and starts in one step)")


def _ui_response(dist: Path, path: str) -> Response | None:
    if path == "/api" or path.startswith("/api/"):
        return None
    root = dist.resolve()
    relative = path.lstrip("/")
    if relative:
        candidate = (root / relative).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            cache = ASSET_CACHE if relative.startswith("assets/") else "no-cache"
            return FileResponse(candidate, headers={"Cache-Control": cache})
        if "." in relative.rsplit("/", 1)[-1]:
            return None  # a missing file such as /favicon.png is a real 404, not the app shell
    index = root / "index.html"
    if not index.is_file():
        return None
    return FileResponse(index, headers={"Cache-Control": "no-cache"})  # always revalidate: it names the current assets


def mount_frontend(app: FastAPI, dist: Path) -> None:
    async def not_found_or_ui(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and request.method in ("GET", "HEAD"):
            response = _ui_response(dist, request.url.path)
            if response is not None:
                return response
        return await _http_error(request, exc)

    app.add_exception_handler(StarletteHTTPException, not_found_or_ui)
