"""Workspace endpoints (mounted under /api).

GET /patients/{pid}/overview      every count the Overview shows, computed now from stored data
GET /patients/{pid}/review-queue  items needing a person: findings not evidence-supported, claims that failed
                                  verification, and dates that are approximate, partial, relative or unresolvable
GET /patients/{pid}/summary       evidence-linked summary as JSON (every content line cites verified claims)
GET /patients/{pid}/summary.md    the same summary as a Markdown download
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import Response

from ..analysis.summary import to_markdown
from ..analysis.workspace import WorkspaceService
from ..ingestion.service import PATIENT_ID_PATTERN
from ..schemas.common import ErrorResponse
from ..schemas.summary import EvidenceSummary
from ..schemas.workspace import OverviewResponse, ReviewQueue

router = APIRouter(tags=["workspace"])
_ERRORS = {422: {"model": ErrorResponse}}


def get_workspace(request: Request) -> WorkspaceService:
    return request.app.state.workspace


@router.get("/patients/{patient_id}/overview", response_model=OverviewResponse, responses=_ERRORS)
def overview(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
             service: WorkspaceService = Depends(get_workspace)) -> OverviewResponse:
    return service.overview(patient_id)


@router.get("/patients/{patient_id}/review-queue", response_model=ReviewQueue, responses=_ERRORS)
def review_queue(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
                 service: WorkspaceService = Depends(get_workspace)) -> ReviewQueue:
    return service.review_queue(patient_id)


@router.get("/patients/{patient_id}/summary", response_model=EvidenceSummary, responses=_ERRORS)
def summary(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
            service: WorkspaceService = Depends(get_workspace)) -> EvidenceSummary:
    return service.summary(patient_id)


@router.get("/patients/{patient_id}/summary.md", response_class=Response, responses=_ERRORS)
def summary_markdown(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
                     service: WorkspaceService = Depends(get_workspace)) -> Response:
    return Response(to_markdown(service.summary(patient_id)), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="medusa-x-summary-{patient_id}.md"'})
