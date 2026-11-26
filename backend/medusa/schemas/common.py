"""API-level response models that are not part of the clinical domain."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str
    version: str
    environment: str
    max_upload_bytes: int  # lets the UI reject an oversized file before sending it; the server still enforces it


class DatabaseCheck(BaseModel):
    path: str
    reachable: bool
    schema_version: int
    expected_version: int
    error: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    database: DatabaseCheck
