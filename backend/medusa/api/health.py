"""Health endpoints.

GET /health        liveness: the process is up and serving requests. No dependencies checked.
GET /health/ready  readiness: the database is reachable and at the expected schema version.
                   Returns 503 with the failing check when it is not.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import __version__
from ..db.schema import check_database
from ..schemas.common import DatabaseCheck, HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    s = request.app.state.settings
    return HealthResponse(status="ok", app=s.app_name, version=__version__, environment=s.environment,
                          max_upload_bytes=s.max_upload_bytes)


@router.get("/health/ready", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}})
def ready(request: Request):
    db = DatabaseCheck(**check_database(request.app.state.settings.db_path))
    ok = db.reachable and db.error is None and db.schema_version == db.expected_version
    body = ReadinessResponse(status="ready" if ok else "unavailable", database=db)
    return body if ok else JSONResponse(status_code=503, content=body.model_dump())
