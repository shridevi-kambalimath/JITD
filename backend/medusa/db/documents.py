"""Document repository: all SQL for the documents and document_events tables.

Functions take an open connection so the caller (the ingestion service) decides transaction
boundaries. Every status change goes through `_transition`, which enforces
schemas.documents.ALLOWED_TRANSITIONS and appends an event row in the same transaction.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone

from ..core.errors import ConflictError, NotFoundError
from ..schemas.documents import (ALLOWED_TRANSITIONS, DocumentDetail, DocumentEvent, DocumentStatus,
                                 DocumentSummary)

S = DocumentStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


_SUMMARY_COLUMNS = """document_id, patient_id, filename, file_format, size_bytes, sha256, status, document_type,
    document_date, source_document_id, extraction_method, page_count, length(extracted_text) AS char_count,
    warnings, error_code, error_message, uploaded_at, updated_at"""


def _summary_fields(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["warnings"] = json.loads(d["warnings"])
    return d


def insert_uploaded(conn: sqlite3.Connection, *, document_id: str, patient_id: str, filename: str,
                    file_format: str, size_bytes: int, sha256: str, storage_path: str) -> None:
    now = _now()
    conn.execute(
        """INSERT INTO documents (document_id, patient_id, filename, file_format, size_bytes, sha256, storage_path,
                                  status, uploaded_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded', ?, ?)""",
        (document_id, patient_id, filename, file_format, size_bytes, sha256, storage_path, now, now))
    _add_event(conn, document_id, S.UPLOADED, f"{file_format} file, {size_bytes} bytes", now)


def _add_event(conn: sqlite3.Connection, document_id: str, status: DocumentStatus, detail: str | None,
               at: str) -> None:
    conn.execute("INSERT INTO document_events (document_id, status, detail, at) VALUES (?, ?, ?, ?)",
                 (document_id, status.value, detail, at))


def _transition(conn: sqlite3.Connection, document_id: str, target: DocumentStatus, detail: str | None,
                updates: dict[str, object]) -> None:
    row = conn.execute("SELECT status FROM documents WHERE document_id = ?", (document_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Document {document_id} not found")
    current = S(row["status"])
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ConflictError(f"Document {document_id} cannot move from '{current.value}' to '{target.value}'",
                            details={"document_id": document_id, "status": current.value})
    now = _now()
    fields = {"status": target.value, "updated_at": now, **updates}
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE documents SET {assignments} WHERE document_id = ?", (*fields.values(), document_id))
    _add_event(conn, document_id, target, detail, now)


def mark_processing(conn: sqlite3.Connection, document_id: str) -> None:
    _transition(conn, document_id, S.PROCESSING, None, {})


def mark_processed(conn: sqlite3.Connection, document_id: str, *, text: str, extraction_method: str,
                   page_count: int | None, page_spans: list[tuple[int, int]], warnings: list[str],
                   document_type: str, document_date: date, source_document_id: str | None,
                   metadata: dict[str, str]) -> None:
    detail = f"{len(text)} characters extracted" + (f"; {len(warnings)} warning(s)" if warnings else "")
    _transition(conn, document_id, S.PROCESSED, detail, {
        "extracted_text": text, "extraction_method": extraction_method, "page_count": page_count,
        "page_spans": json.dumps(page_spans), "warnings": json.dumps(warnings),
        "document_type": document_type, "document_date": document_date.isoformat(),
        "source_document_id": source_document_id, "metadata": json.dumps(metadata),
        "error_code": None, "error_message": None,
    })


def mark_failed(conn: sqlite3.Connection, document_id: str, *, code: str, message: str, text: str | None = None,
                extraction_method: str | None = None, page_count: int | None = None,
                page_spans: list[tuple[int, int]] | None = None, warnings: list[str] | None = None) -> None:
    """Text extracted before the failure is kept so a reviewer can see why the document failed."""
    _transition(conn, document_id, S.FAILED, f"{code}: {message}", {
        "error_code": code, "error_message": message, "extracted_text": text,
        "extraction_method": extraction_method, "page_count": page_count,
        "page_spans": json.dumps(page_spans or []), "warnings": json.dumps(warnings or []),
    })


def fail_interrupted(conn: sqlite3.Connection) -> list[str]:
    """Documents left in uploaded/processing by a crash or restart can never finish; mark them failed."""
    ids = [r["document_id"] for r in conn.execute(
        "SELECT document_id FROM documents WHERE status IN ('uploaded', 'processing')")]
    for document_id in ids:
        mark_failed(conn, document_id, code="interrupted",
                    message="Processing was interrupted before it finished (server stopped). "
                            "Delete the document and upload it again.")
    return ids


def get_summary(conn: sqlite3.Connection, document_id: str) -> DocumentSummary | None:
    row = conn.execute(f"SELECT {_SUMMARY_COLUMNS} FROM documents WHERE document_id = ?", (document_id,)).fetchone()
    return DocumentSummary(**_summary_fields(row)) if row else None


def get_detail(conn: sqlite3.Connection, document_id: str) -> DocumentDetail | None:
    row = conn.execute(f"SELECT {_SUMMARY_COLUMNS}, metadata, extracted_text, page_spans FROM documents "
                       f"WHERE document_id = ?", (document_id,)).fetchone()
    if row is None:
        return None
    d = _summary_fields(row)
    d["metadata"] = json.loads(d["metadata"])
    d["page_spans"] = [tuple(x) for x in json.loads(d["page_spans"])]
    d["events"] = [DocumentEvent(status=r["status"], detail=r["detail"], at=r["at"]) for r in conn.execute(
        "SELECT status, detail, at FROM document_events WHERE document_id = ? ORDER BY event_id", (document_id,))]
    return DocumentDetail(**d)


def get_storage_path(conn: sqlite3.Connection, document_id: str) -> tuple[str, str] | None:
    row = conn.execute("SELECT storage_path, file_format FROM documents WHERE document_id = ?",
                       (document_id,)).fetchone()
    return (row["storage_path"], row["file_format"]) if row else None


def list_documents(conn: sqlite3.Connection, patient_id: str,
                   status: DocumentStatus | None = None) -> list[DocumentSummary]:
    sql, args = f"SELECT {_SUMMARY_COLUMNS} FROM documents WHERE patient_id = ?", [patient_id]
    if status is not None:
        sql += " AND status = ?"
        args.append(status.value)
    rows = conn.execute(sql + " ORDER BY document_date IS NULL, document_date, uploaded_at, document_id", args)
    return [DocumentSummary(**_summary_fields(r)) for r in rows]


def delete(conn: sqlite3.Connection, document_id: str) -> bool:
    """Deletes the document; events, passages and claims cascade via foreign keys."""
    return conn.execute("DELETE FROM documents WHERE document_id = ?", (document_id,)).rowcount > 0


def storage_paths_for_patient(conn: sqlite3.Connection, patient_id: str) -> list[str]:
    return [r["storage_path"] for r in conn.execute(
        "SELECT storage_path FROM documents WHERE patient_id = ?", (patient_id,))]


def delete_for_patient(conn: sqlite3.Connection, patient_id: str) -> int:
    """Deletes every document of one patient; events and derived rows cascade."""
    return conn.execute("DELETE FROM documents WHERE patient_id = ?", (patient_id,)).rowcount
