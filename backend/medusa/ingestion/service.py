"""Ingestion service: the only entry point that changes documents.

Flow for one upload

    validate (reject: 413/415/422, nothing stored)
      -> duplicate check (409, nothing stored)
      -> store original file -> row 'uploaded'                 (commit)
      -> 'processing'                                         (commit)
      -> extract text -> quality gates -> header metadata
      -> 'processed'  or  'failed' with error code + message  (commit)

Each status change is committed on its own so the status is visible while work is in progress
and survives a crash; startup marks anything stuck in uploaded/processing as failed.

Document ids are derived from the patient id and the file bytes, so ids are reproducible and the
same file cannot be ingested twice for one patient. That matters downstream: a duplicated document
would count as two independent sources and inflate the apparent support for every claim in it.
"""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from pathlib import Path

from ..core.config import Settings
from ..core.errors import ConflictError, NotFoundError
from ..db import analysis as analysis_repo
from ..db import documents as repo
from ..db.connection import transaction
from ..schemas.documents import DemoLoadResult, DocumentDetail, DocumentStatus, DocumentSummary
from . import IngestionError
from .metadata import parse_header
from .storage import FileStore
from .text_extraction import ExtractionError, extract_text
from .validation import UploadRejected, sanitize_filename, validate_upload

logger = logging.getLogger("medusa.ingestion")
PATIENT_ID_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"
_PATIENT_ID = re.compile(PATIENT_ID_PATTERN)


def make_document_id(patient_id: str, data: bytes) -> str:
    return "DOC-" + hashlib.sha256(patient_id.encode() + b"\x00" + data).hexdigest()[:16].upper()


class IngestionService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = settings.db_path
        self.files = FileStore(settings.upload_dir)

    # ------------------------------------------------------------------ commands
    def ingest(self, patient_id: str, raw_filename: str | None, data: bytes) -> DocumentDetail:
        if not _PATIENT_ID.match(patient_id):
            raise UploadRejected(422, "invalid_patient_id", "Patient id may contain letters, digits, '-' and '_'.")
        filename = sanitize_filename(raw_filename)
        file_format = validate_upload(filename, data, self.settings.max_upload_bytes)
        document_id = make_document_id(patient_id, data)

        with transaction(self.db) as conn:
            existing = repo.get_summary(conn, document_id)
        if existing is not None:
            raise self._duplicate(existing)

        storage_name = self.files.save(document_id, file_format, data)
        try:
            with transaction(self.db) as conn:
                repo.insert_uploaded(conn, document_id=document_id, patient_id=patient_id, filename=filename,
                                     file_format=file_format, size_bytes=len(data),
                                     sha256=hashlib.sha256(data).hexdigest(), storage_path=storage_name)
        except sqlite3.IntegrityError:
            # a concurrent upload of the same file won the race; it owns the stored file
            with transaction(self.db) as conn:
                existing = repo.get_summary(conn, document_id)
            if existing is None:
                self.files.delete(storage_name)
                raise
            raise self._duplicate(existing) from None
        except Exception:
            self.files.delete(storage_name)
            raise
        logger.info("Uploaded %s (%s, %d bytes) for patient %s as %s", filename, file_format, len(data),
                    patient_id, document_id)
        return self._process(document_id, patient_id, storage_name, file_format)

    def _process(self, document_id: str, patient_id: str, storage_name: str, file_format: str) -> DocumentDetail:
        with transaction(self.db) as conn:
            repo.mark_processing(conn, document_id)
        extraction = None
        try:
            data = self.files.read(storage_name)
            extraction = extract_text(file_format, data, max_pdf_pages=self.settings.max_pdf_pages,
                                      min_chars=self.settings.min_text_chars)
            header = parse_header(extraction.text, patient_id)
        except IngestionError as exc:
            partial = extraction or (exc.partial if isinstance(exc, ExtractionError) else None)
            self._fail(document_id, exc.code, exc.message, partial)
        except Exception:
            logger.exception("Unexpected error while processing %s", document_id)
            self._fail(document_id, "internal_error",
                       "Unexpected processing error. The server log has details under this request id.", extraction)
        else:
            with transaction(self.db) as conn:
                repo.mark_processed(conn, document_id, text=extraction.text, extraction_method=extraction.method,
                                    page_count=extraction.page_count, page_spans=extraction.page_spans,
                                    warnings=extraction.warnings, document_type=header.document_type,
                                    document_date=header.document_date,
                                    source_document_id=header.source_document_id, metadata=header.fields)
            logger.info("Processed %s: %s dated %s, %d characters, %d warning(s)", document_id,
                        header.document_type, header.document_date, len(extraction.text), len(extraction.warnings))
        return self.get(document_id)

    def _fail(self, document_id: str, code: str, message: str, partial) -> None:
        logger.warning("Document %s failed: %s: %s", document_id, code, message)
        with transaction(self.db) as conn:
            repo.mark_failed(conn, document_id, code=code, message=message,
                             text=partial.text if partial else None,
                             extraction_method=partial.method if partial else None,
                             page_count=partial.page_count if partial else None,
                             page_spans=partial.page_spans if partial else None,
                             warnings=partial.warnings if partial else None)

    @staticmethod
    def _duplicate(existing: DocumentSummary) -> ConflictError:
        return ConflictError(
            f"This file has already been uploaded for patient {existing.patient_id} as {existing.document_id} "
            f"(status: {existing.status.value}). Delete it first to upload it again.",
            details={"document_id": existing.document_id, "status": existing.status.value})

    def delete(self, document_id: str) -> None:
        with transaction(self.db) as conn:
            stored = repo.get_storage_path(conn, document_id)
            if stored is None or not repo.delete(conn, document_id):
                raise NotFoundError(f"Document {document_id} not found")
        try:  # after commit: a leftover file is harmless, a dangling row is not
            self.files.delete(stored[0])
        except OSError:
            logger.warning("Document %s deleted but its stored file could not be removed", document_id)
        logger.info("Deleted document %s", document_id)

    def recover_interrupted(self) -> list[str]:
        with transaction(self.db) as conn:
            ids = repo.fail_interrupted(conn)
        if ids:
            logger.warning("Marked %d interrupted document(s) as failed: %s", len(ids), ", ".join(ids))
        return ids

    def _demo_folder(self, patient_id: str) -> Path:
        if _PATIENT_ID.match(patient_id):
            root = self.settings.demo_dir.resolve()
            folder = (root / patient_id).resolve()
            if folder.parent == root and folder.is_dir():
                return folder
        raise NotFoundError(f"No synthetic demo bundle for {patient_id!r}")

    def delete_patient_documents(self, patient_id: str) -> int:
        with transaction(self.db) as conn:
            paths = repo.storage_paths_for_patient(conn, patient_id)
            removed = repo.delete_for_patient(conn, patient_id)
        for name in paths:  # after commit, as in delete()
            try:
                self.files.delete(name)
            except (OSError, ValueError):
                logger.warning("Stored file %r could not be removed", name)
        logger.info("Deleted %d document(s) for patient %s", removed, patient_id)
        return removed

    def reset_demo(self, patient_id: str) -> DemoLoadResult:
        """Remove every document, finding and review of this patient, then reload the synthetic bundle through the
        real upload path.

        The bundle is located first, so an unknown patient id deletes nothing.
        """
        self._demo_folder(patient_id)
        removed = self.delete_patient_documents(patient_id)
        with transaction(self.db) as conn:  # a reset starts the review from scratch too
            analysis_repo.clear_reviews(conn, patient_id)
            conn.execute("DELETE FROM findings WHERE patient_id = ?", (patient_id,))
        result = self.load_demo(patient_id)
        result.removed = removed
        return result

    def load_demo(self, patient_id: str) -> DemoLoadResult:
        """Ingest the fixed synthetic bundle in demo_dir/<patient_id> through the normal upload path."""
        folder = self._demo_folder(patient_id)
        result = DemoLoadResult(patient_id=patient_id, loaded=[], skipped_existing=[], rejected=[])
        for path in sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".txt", ".pdf"}):
            try:
                result.loaded.append(self.ingest(patient_id, path.name, path.read_bytes()))
            except ConflictError as exc:
                result.skipped_existing.append(exc.details["document_id"])
            except UploadRejected as exc:
                result.rejected.append({"filename": path.name, "code": exc.code, "message": exc.message})
        return result

    # ------------------------------------------------------------------ queries
    def get(self, document_id: str) -> DocumentDetail:
        with transaction(self.db) as conn:
            doc = repo.get_detail(conn, document_id)
        if doc is None:
            raise NotFoundError(f"Document {document_id} not found")
        return doc

    def list(self, patient_id: str, status: DocumentStatus | None = None) -> list[DocumentSummary]:
        with transaction(self.db) as conn:
            return repo.list_documents(conn, patient_id, status)
