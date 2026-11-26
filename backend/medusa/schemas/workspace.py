"""Overview and review-queue models: every count the workspace shows, computed from stored data."""
from __future__ import annotations

from pydantic import BaseModel

from .analysis import AnalysisStatus, ClaimRecord, LlmConfig
from .domain import DateValue
from .reconciliation import FindingSummary


class OverviewResponse(BaseModel):
    patient_id: str
    documents: dict[str, int]         # total, processed, failed, in_progress
    analysis: AnalysisStatus
    claims: dict[str, int]            # total, rule, llm, verified, failed_verification
    timeline: dict[str, int]          # entries, by_event_date, by_document_date, undated, excluded_unverified
    reconciliation: dict[str, int]    # subjects, needs_attention, pending_review + one count per evidence state
    llm: LlmConfig


class UncertainDate(BaseModel):
    claim_id: str
    category: str
    entity: str
    surface: str
    document_id: str
    document_type: str
    document_date: str | None
    event_date: DateValue
    reason: str


class ReviewQueue(BaseModel):
    patient_id: str
    results_run_id: str | None
    is_current: bool
    stale_reason: str | None = None
    counts: dict[str, int]
    findings: list[FindingSummary]        # not evidence-supported, most urgent first
    unverified_claims: list[ClaimRecord]  # failed a hard verification check
    uncertain_dates: list[UncertainDate]  # approximate, partial, relative or unresolvable dates
