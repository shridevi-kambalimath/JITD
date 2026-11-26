"""Analysis endpoints (mounted under /api).

POST /patients/{patient_id}/analysis           run segmentation + extraction on the processed documents
GET  /patients/{patient_id}/analysis/latest    latest attempt, the run behind the stored claims, staleness
GET  /patients/{patient_id}/claims             stored claims; optional ?category= and ?document_id=
GET  /patients/{patient_id}/claims/{claim_id}/evidence   evidence inspector for one claim
GET  /analysis/runs/{run_id}                   one run record
GET  /analysis/config                          LLM extraction settings as the server sees them (no secrets)

Outcomes of POST
  200  run completed (check llm_status: the LLM may have failed while rule extraction succeeded)
  409  a run for this patient is already in progress
  422  the patient has no processed documents
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.concurrency import run_in_threadpool

from ..analysis.evidence import EvidenceService
from ..analysis.pipeline import AnalysisService
from ..ingestion.service import PATIENT_ID_PATTERN
from ..schemas.analysis import AnalysisRun, AnalysisStatus, ClaimRecord, LlmConfig
from ..schemas.common import ErrorResponse
from ..schemas.evidence import EvidenceView
from .documents import DOCUMENT_ID_PATTERN

router = APIRouter(tags=["analysis"])
_ERRORS = {s: {"model": ErrorResponse} for s in (404, 409, 422)}
Category = Literal["medication", "diagnosis", "allergy", "lab_result", "symptom", "procedure", "encounter",
                   "record_reference"]


def get_analysis(request: Request) -> AnalysisService:
    return request.app.state.analysis


def get_evidence(request: Request) -> EvidenceService:
    return request.app.state.evidence


@router.post("/patients/{patient_id}/analysis", response_model=AnalysisRun, responses=_ERRORS)
async def run_analysis(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
                       service: AnalysisService = Depends(get_analysis)) -> AnalysisRun:
    # extraction is CPU-bound and LLM calls block: keep both off the event loop
    return await run_in_threadpool(service.run, patient_id)


@router.get("/patients/{patient_id}/analysis/latest", response_model=AnalysisStatus, responses=_ERRORS)
def analysis_status(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
                    service: AnalysisService = Depends(get_analysis)) -> AnalysisStatus:
    return service.status(patient_id)


@router.get("/patients/{patient_id}/claims", response_model=list[ClaimRecord], responses=_ERRORS)
def list_claims(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN), category: Category | None = None,
                document_id: str | None = Query(None, pattern=DOCUMENT_ID_PATTERN),
                service: AnalysisService = Depends(get_analysis)) -> list[ClaimRecord]:
    return service.claims(patient_id, category, document_id)


@router.get("/patients/{patient_id}/claims/{claim_id}/evidence", response_model=EvidenceView, responses=_ERRORS)
def claim_evidence(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
                   claim_id: str = Path(..., pattern=r"^CLM-[0-9A-F]{12}$"),
                   service: EvidenceService = Depends(get_evidence)) -> EvidenceView:
    """One claim with its exact source passage, context, every verification check (re-run now against the
    stored text), its timeline entry and the reconciliation items that use it."""
    return service.view(patient_id, claim_id)


@router.get("/analysis/runs/{run_id}", response_model=AnalysisRun, responses=_ERRORS)
def get_run(run_id: str = Path(..., pattern=r"^RUN-[0-9A-F]{12}$"),
            service: AnalysisService = Depends(get_analysis)) -> AnalysisRun:
    return service.get_run(run_id)


@router.get("/analysis/config", response_model=LlmConfig)
def llm_config(service: AnalysisService = Depends(get_analysis)) -> LlmConfig:
    return service.llm_config()
