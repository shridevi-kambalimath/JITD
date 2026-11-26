"""Timeline endpoint (mounted under /api).

GET /patients/{patient_id}/timeline?category=&q=&document_id=
    Stored claims in chronological order. Each entry states whether it is placed by the event date the
    passage gives or by its document's date. Counts are before filtering; entries are after.
    Empty (results_run_id null) until an analysis has run.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from ..analysis.pipeline import AnalysisService
from ..ingestion.service import PATIENT_ID_PATTERN
from ..schemas.common import ErrorResponse
from ..schemas.timeline import TimelineResponse
from .analysis import Category, get_analysis
from .documents import DOCUMENT_ID_PATTERN

router = APIRouter(tags=["timeline"])


@router.get("/patients/{patient_id}/timeline", response_model=TimelineResponse, responses={422: {"model": ErrorResponse}})
def timeline(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN), category: Category | None = None,
             q: str | None = Query(None, max_length=200),
             document_id: str | None = Query(None, pattern=DOCUMENT_ID_PATTERN),
             service: AnalysisService = Depends(get_analysis)) -> TimelineResponse:
    return service.timeline(patient_id, category, (q or "").strip() or None, document_id)
