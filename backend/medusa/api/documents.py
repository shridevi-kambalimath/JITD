"""Document ingestion endpoints (mounted under /api).

POST   /patients/{patient_id}/documents    upload one .pdf/.txt file (multipart field 'file')
GET    /patients/{patient_id}/documents    list documents, optional ?status=
POST   /patients/{patient_id}/demo/load    ingest the fixed synthetic bundle for this patient (idempotent)
POST   /patients/{patient_id}/demo/reset   delete all of this patient's documents, then reload the bundle
GET    /documents/{document_id}            detail: metadata, extracted text, warnings, status history
DELETE /documents/{document_id}            delete the document, its stored file and derived data

Upload outcomes
  201 + status 'processed'   text and metadata extracted
  201 + status 'failed'      file stored but unusable; error_code/error_message say why
                             (corrupted_pdf, no_text_layer, empty_text, missing_header, ...)
  409 duplicate              the same file already exists for this patient
  413 / 415 / 422            rejected before storage (too large, unsupported or mismatched type,
                             empty file, bad encoding)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Path, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..ingestion.service import PATIENT_ID_PATTERN, IngestionService
from ..schemas.common import ErrorResponse
from ..schemas.documents import DemoLoadResult, DocumentDetail, DocumentStatus, DocumentSummary

router = APIRouter(tags=["documents"])
DOCUMENT_ID_PATTERN = r"^DOC-[0-9A-F]{16}$"
_ERRORS = {s: {"model": ErrorResponse} for s in (404, 409, 413, 415, 422)}


def get_service(request: Request) -> IngestionService:
    return request.app.state.ingestion


@router.post("/patients/{patient_id}/documents", status_code=201, response_model=DocumentDetail, responses=_ERRORS)
async def upload_document(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
                          file: UploadFile = File(..., description="A synthetic .pdf or .txt clinical document"),
                          service: IngestionService = Depends(get_service)) -> DocumentDetail:
    # read at most limit+1 bytes: enough to detect an oversized file without loading all of it
    data = await file.read(service.settings.max_upload_bytes + 1)
    # PDF parsing is CPU-bound and the database calls are blocking: keep them off the event loop
    return await run_in_threadpool(service.ingest, patient_id, file.filename, data)


@router.get("/patients/{patient_id}/documents", response_model=list[DocumentSummary], responses=_ERRORS)
def list_documents(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN), status: DocumentStatus | None = None,
                   service: IngestionService = Depends(get_service)) -> list[DocumentSummary]:
    return service.list(patient_id, status)


@router.post("/patients/{patient_id}/demo/load", response_model=DemoLoadResult, responses=_ERRORS)
def load_demo(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
              service: IngestionService = Depends(get_service)) -> DemoLoadResult:
    return service.load_demo(patient_id)


@router.post("/patients/{patient_id}/demo/reset", response_model=DemoLoadResult, responses=_ERRORS)
def reset_demo(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
               service: IngestionService = Depends(get_service)) -> DemoLoadResult:
    return service.reset_demo(patient_id)


@router.get("/documents/{document_id}", response_model=DocumentDetail, responses=_ERRORS)
def get_document(document_id: str = Path(..., pattern=DOCUMENT_ID_PATTERN),
                 service: IngestionService = Depends(get_service)) -> DocumentDetail:
    return service.get(document_id)


@router.delete("/documents/{document_id}", status_code=204, responses=_ERRORS)
def delete_document(document_id: str = Path(..., pattern=DOCUMENT_ID_PATTERN),
                    service: IngestionService = Depends(get_service)) -> Response:
    service.delete(document_id)
    return Response(status_code=204)
