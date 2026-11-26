"""Error handling.

Every error response uses one envelope:

    {"error": {"code": "not_found", "message": "...", "details": ..., "request_id": "..."}}

* AppError subclasses are raised by application code for expected failures.
* Validation and HTTP errors from FastAPI/Starlette are converted to the same envelope.
* Unexpected exceptions are caught in RequestContextMiddleware: logged with a stack trace,
  returned as a 500 without internal details, and tagged with the request id so the log
  line can be found.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from .logging import request_id_var

logger = logging.getLogger("medusa.http")
REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
MULTIPART_OVERHEAD_BYTES = 64 * 1024  # form boundaries and part headers around an uploaded file


class AppError(Exception):
    status_code = 500
    code = "app_error"

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code, code = 404, "not_found"


class ConflictError(AppError):
    status_code, code = 409, "conflict"


class UnprocessableError(AppError):
    status_code, code = 422, "unprocessable"


class ServiceUnavailableError(AppError):
    status_code, code = 503, "service_unavailable"


def error_response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    rid = request_id_var.get()
    body = {"error": {"code": code, "message": message, "details": details, "request_id": rid}}
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body),
                        headers={REQUEST_ID_HEADER: rid})


_HTTP_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
               405: "method_not_allowed", 409: "conflict", 413: "payload_too_large", 429: "too_many_requests"}


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    log = logger.error if exc.status_code >= 500 else logger.info
    log("%s: %s", exc.code, exc.message)
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return error_response(exc.status_code, _HTTP_CODES.get(exc.status_code, "http_error"), str(exc.detail))


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # drop echoed input values and documentation urls: they can be large and add nothing
    details = [{k: v for k, v in e.items() if k in ("loc", "msg", "type")} for e in exc.errors()]
    return error_response(422, "validation_error", "Request validation failed", details)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)


_recreate_lock = threading.Lock()


def _recreate_database(path) -> JSONResponse:
    """The database file was deleted or replaced while the server ran. Recreate an empty schema so the app keeps
    working, and say plainly that earlier data is gone (synthetic data only, so nothing irreplaceable)."""
    from ..db.schema import init_db  # local import: core must not depend on db at import time
    with _recreate_lock:
        logger.warning("Database at %s has no tables (file deleted or replaced); recreating an empty schema", path)
        init_db(path)
    return error_response(503, "database_recreated",
                          "The database file was missing or replaced, so an empty one was created. Earlier documents "
                          "and results are no longer stored: load the demo bundle again (or re-upload), then run the "
                          "analysis.")


# Bodies up to this size are read and discarded before the 413 is sent. Answering without reading the body makes the
# server close the socket mid-upload, and a proxy in front (Vite in development) then reports a connection reset
# instead of forwarding the 413, so the user sees "backend unreachable" rather than "file too large".
DRAIN_LIMIT_BYTES = 64_000_000


async def _reject_oversized(request: Request, length: int, limit: int) -> JSONResponse:
    response = error_response(413, "payload_too_large", f"Request body exceeds the {limit:,} byte limit.")
    if length > DRAIN_LIMIT_BYTES:
        response.headers["Connection"] = "close"  # too large to drain; the client may see a reset
        return response
    async for _ in request.stream():
        pass
    return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, rejects oversized bodies early, logs one line per request, and converts
    unhandled exceptions to 500s.

    The size check uses Content-Length, before FastAPI parses the multipart body. The upload endpoint
    checks the actual file size again, which also covers clients that send no Content-Length.
    """

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        rid = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            try:
                settings = getattr(request.app.state, "settings", None)
                length = request.headers.get("content-length", "")
                if settings and length.isdigit() and \
                        int(length) > settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES:
                    response = await _reject_oversized(request, int(length), settings.max_upload_bytes)
                else:
                    response = await call_next(request)
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc) or settings is None:
                    logger.exception("Database error on %s %s", request.method, request.url.path)
                    response = error_response(500, "internal_error",
                                              "Internal server error. Quote the request id when reporting it.")
                else:
                    response = _recreate_database(settings.db_path)
            except Exception:
                logger.exception("Unhandled error on %s %s", request.method, request.url.path)
                response = error_response(500, "internal_error",
                                          "Internal server error. Quote the request id when reporting it.")
            response.headers[REQUEST_ID_HEADER] = rid
            duration = round((time.perf_counter() - start) * 1000, 2)
            logger.info("%s %s -> %s (%.2f ms)", request.method, request.url.path, response.status_code, duration,
                        extra={"method": request.method, "path": request.url.path,
                               "status_code": response.status_code, "duration_ms": duration})
            return response
        finally:
            request_id_var.reset(token)
