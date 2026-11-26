"""Evidence search endpoint (mounted under /api).

GET /patients/{patient_id}/search?q=&scope=all|passages|claims|timeline|reconciliation
    Keyword search (BM25) over the stored passages, with brand/generic drug names and lab abbreviations
    expanded ("metformin" also matches "Glycomet"). Returns ranked passages with the matched words, and the claims,
    timeline entries and reconciliation items they lead to. counts covers every scope; lists outside the
    requested scope are empty.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request

from ..analysis.search import SearchService
from ..ingestion.service import PATIENT_ID_PATTERN
from ..schemas.common import ErrorResponse
from ..schemas.search import SearchResponse

router = APIRouter(tags=["search"])


def get_search(request: Request) -> SearchService:
    return request.app.state.search


@router.get("/patients/{patient_id}/search", response_model=SearchResponse, responses={422: {"model": ErrorResponse}})
def search(patient_id: str = Path(..., pattern=PATIENT_ID_PATTERN), q: str = Query(..., min_length=1, max_length=200),
           scope: Literal["all", "passages", "claims", "timeline", "reconciliation"] = "all",
           service: SearchService = Depends(get_search)) -> SearchResponse:
    return service.search(patient_id, q.strip(), scope)
