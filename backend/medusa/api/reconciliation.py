"""Reconciliation and review endpoints (mounted under /api).

GET /patients/{pid}/reconciliation?category=&only_issues=   findings with issues first (by priority), counts
GET /patients/{pid}/reconciliation/{finding_id}             one finding: issues, observations, investigation,
                                                            every cited claim with its source passage
PUT /patients/{pid}/reviews/{finding_id}                    {status: pending_review|reviewed|flagged, note}

Finding ids are deterministic per subject (FND-MED-warfarin), so they are scoped by patient in the path.
Review status records that a person looked at an item. It never changes the finding and is not medical approval.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Request

from ..analysis.review import ReviewService
from ..ingestion.service import PATIENT_ID_PATTERN
from ..schemas.common import ErrorResponse
from ..schemas.reconciliation import FindingDetail, ReconciliationResponse, Review, ReviewUpdate

router = APIRouter(tags=["reconciliation"])
FINDING_ID_PATTERN = r"^FND-[A-Z]+-[a-z0-9-]{1,120}$"
_ERRORS = {s: {"model": ErrorResponse} for s in (404, 422)}
FindingCategory = Literal["medication", "diagnosis", "allergy", "family_history", "record_reference"]


def get_reviews(request: Request) -> ReviewService:
    return request.app.state.reviews


@router.get("/patients/{patient_id}/reconciliation", response_model=ReconciliationResponse, responses=_ERRORS)
def reconciliation(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN), category: FindingCategory | None = None,
                   only_issues: bool = False, service: ReviewService = Depends(get_reviews)) -> ReconciliationResponse:
    return service.reconciliation(patient_id, category, only_issues)


@router.get("/patients/{patient_id}/reconciliation/{finding_id}", response_model=FindingDetail, responses=_ERRORS)
def finding_detail(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
                   finding_id: str = Path(..., pattern=FINDING_ID_PATTERN),
                   service: ReviewService = Depends(get_reviews)) -> FindingDetail:
    return service.detail(patient_id, finding_id)


@router.put("/patients/{patient_id}/reviews/{finding_id}", response_model=Review, responses=_ERRORS)
def set_review(update: ReviewUpdate, patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN),
               finding_id: str = Path(..., pattern=FINDING_ID_PATTERN),
               service: ReviewService = Depends(get_reviews)) -> Review:
    return service.set_review(patient_id, finding_id, update)
