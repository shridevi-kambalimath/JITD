"""Reconciliation and review API models.

Wording rule: findings describe *potential documentation discrepancies*. Nothing here says a record is
wrong, and a review status records that a person looked at an item; it is not medical approval.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .analysis import ClaimRecord
from .domain import EvidenceState, FindingCategory, InvestigationStep, Issue, Observation

ReviewStatus = Literal["pending_review", "reviewed", "flagged"]


class Review(BaseModel):
    status: ReviewStatus
    note: str | None = None
    updated_at: datetime | None = None
    changed_since_review: bool = False  # the finding's issues differ from when this status was set


class FindingSummary(BaseModel):
    finding_id: str
    category: FindingCategory
    subject: str
    high_risk: bool
    risk_reason: str | None = None
    issue_types: list[str]
    issues_by_kind: dict[str, int]       # conflict / gap / integrity
    observation_rules: list[str]         # rules that examined a pattern and explain why it was not flagged
    claim_count: int
    priority: int | None                 # 1 most urgent; None when evidence-supported (not in the review queue)
    review: Review
    state: EvidenceState | None = None   # set by the gate; None only for results stored before Phase 6
    gate_rule: str | None = None         # the gate rule that decided the state (GATE-01 .. GATE-07)
    gate_rationale: str | None = None


class ReconciliationResponse(BaseModel):
    patient_id: str
    results_run_id: str | None
    is_current: bool
    stale_reason: str | None = None
    counts: dict[str, int]               # includes one count per evidence state code
    findings: list[FindingSummary]


class FindingDetail(FindingSummary):
    issues: list[Issue]
    observations: list[Observation]
    investigation: list[InvestigationStep]
    claims: list[ClaimRecord]            # every claim the finding cites, in date order, with verification
    missing_claim_ids: list[str]         # cited claims no longer stored (their document was removed)
    results_run_id: str | None
    is_current: bool


class ReviewUpdate(BaseModel):
    status: ReviewStatus
    note: str | None = Field(default=None, max_length=2000)
