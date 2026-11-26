"""Document ingestion models (API responses and repository records)."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

FileFormat = Literal["pdf", "txt"]
ExtractionMethod = Literal["utf8_text", "pdf_text_layer"]


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


# The only legal status changes. Enforced by the repository.
ALLOWED_TRANSITIONS: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.UPLOADED: frozenset({DocumentStatus.PROCESSING, DocumentStatus.FAILED}),
    DocumentStatus.PROCESSING: frozenset({DocumentStatus.PROCESSED, DocumentStatus.FAILED}),
    DocumentStatus.PROCESSED: frozenset(),
    DocumentStatus.FAILED: frozenset(),
}


class DocumentEvent(BaseModel):
    status: DocumentStatus
    detail: str | None = None
    at: datetime


class DocumentSummary(BaseModel):
    """Listing view. Excludes the extracted text, which can be large."""

    document_id: str
    patient_id: str
    filename: str
    file_format: FileFormat
    size_bytes: int
    sha256: str
    status: DocumentStatus
    document_type: str | None = None
    document_date: date | None = None
    source_document_id: str | None = None
    extraction_method: ExtractionMethod | None = None
    page_count: int | None = None
    char_count: int | None = None
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    uploaded_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    metadata: dict[str, str] = Field(default_factory=dict)
    extracted_text: str | None = None
    page_spans: list[tuple[int, int]] = Field(default_factory=list)
    events: list[DocumentEvent] = Field(default_factory=list)


class DemoLoadResult(BaseModel):
    patient_id: str
    loaded: list[DocumentSummary]
    skipped_existing: list[str]
    rejected: list[dict[str, str]]
    removed: int = 0  # documents deleted first (reset only)
