"""FastAPI application factory and entry point.

    cd backend
    python -m medusa            # host, port, reload and logging come from .env

With MEDUSA_SERVE_FRONTEND=true the same process also serves the built UI (single-process demo, see web.py).

create_app() takes an optional Settings so tests can run against a temporary database.
Nothing touches the filesystem at import time; the database is initialised at startup.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from . import __version__
from .analysis.pipeline import AnalysisService
from .analysis.evidence import EvidenceService
from .analysis.review import ReviewService
from .analysis.search import SearchService
from .analysis.workspace import WorkspaceService
from .api import analysis, documents, health, reconciliation, search, timeline, workspace
from .core.config import Settings, get_settings
from .core.errors import RequestContextMiddleware, register_exception_handlers
from .core.logging import configure_logging
from .db.schema import init_db
from .ingestion.service import IngestionService
from .web import dist_problem, mount_frontend

logger = logging.getLogger("medusa")
API_PREFIX = "/api"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings)
        version = init_db(settings.db_path)
        app.state.ingestion.recover_interrupted()
        app.state.analysis.recover_interrupted()
        logger.info("%s %s starting (environment=%s, schema v%d)", settings.app_name, __version__,
                    settings.environment, version)
        yield
        logger.info("%s shutting down", settings.app_name)

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description="Evidence-driven clinical record reconstruction. Synthetic data only.",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.ingestion = IngestionService(settings)
    app.state.analysis = AnalysisService(settings)
    app.state.reviews = ReviewService(settings, app.state.analysis)
    app.state.evidence = EvidenceService(settings, app.state.analysis)
    app.state.search = SearchService(settings, app.state.analysis)
    app.state.workspace = WorkspaceService(settings, app.state.analysis, app.state.reviews)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    # Every endpoint lives under /api so the React app (dev proxy or same-origin build) owns all other paths.
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(documents.router, prefix=API_PREFIX)
    app.include_router(analysis.router, prefix=API_PREFIX)
    app.include_router(timeline.router, prefix=API_PREFIX)
    app.include_router(reconciliation.router, prefix=API_PREFIX)
    app.include_router(search.router, prefix=API_PREFIX)
    app.include_router(workspace.router, prefix=API_PREFIX)
    if settings.serve_frontend:
        mount_frontend(app, settings.frontend_dist)
    return app


app = create_app()


def port_problem(host: str, port: int, timeout: float = 1.5) -> str | None:
    """Explain why host:port cannot be used, or None if it is free.

    Checked before uvicorn starts: otherwise a taken port only shows as a bind error in a busy terminal, and the
    frontend keeps talking to whatever already answers there (often an older MEDUSA-X build).
    """
    import json
    import socket
    import urllib.request

    # "Is something listening?" rather than "can I bind?": a bind test gives false alarms for a few seconds after a
    # restart (sockets in TIME_WAIT on Linux/macOS), and SO_REUSEADDR would hide a real listener on Windows.
    probe = "127.0.0.1" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        if s.connect_ex((probe, port)) != 0:
            return None
    who = "another program"
    try:
        with urllib.request.urlopen(f"http://{probe}:{port}/api/health", timeout=timeout) as r:
            body = json.loads(r.read().decode())
            if body.get("app") == "MEDUSA-X":
                who = f"another MEDUSA-X backend, version {body.get('version')}"
                if body.get("version") == __version__:
                    who += " (this same version: it is probably already running in another terminal)"
    except Exception:  # noqa: BLE001 - any failure just means we cannot identify it
        pass
    return (f"Port {port} on {host} is already in use by {who}.\n"
            f"  Windows: netstat -ano | findstr :{port}   then   taskkill /F /T /PID <number in the last column>\n"
            f"  macOS/Linux: lsof -i :{port}   then   kill <PID>\n"
            f"  Or set MEDUSA_API_PORT to a free port in .env (the frontend reads the same setting).")


def run() -> None:
    settings = get_settings()
    configure_logging(settings)
    problem = port_problem(settings.api_host, settings.api_port)
    if problem:
        logger.error("Backend not started: port %s is in use", settings.api_port)
        print(f"\nMEDUSA-X backend not started.\n{problem}\n", flush=True)
        raise SystemExit(1)
    if settings.serve_frontend:
        problem = dist_problem(settings.frontend_dist)
        if problem:
            logger.error("Backend not started: frontend build missing at %s", settings.frontend_dist)
            print(f"\nMEDUSA-X backend not started (MEDUSA_SERVE_FRONTEND=true).\n{problem}\n", flush=True)
            raise SystemExit(1)
        print(f"\nMEDUSA-X demo: open http://{'127.0.0.1' if settings.api_host in ('0.0.0.0', '') else settings.api_host}"
              f":{settings.api_port}  (UI and API on one port)\n", flush=True)
    uvicorn.run("medusa.main:app", host=settings.api_host, port=settings.api_port, reload=settings.reload,
                log_config=None)
