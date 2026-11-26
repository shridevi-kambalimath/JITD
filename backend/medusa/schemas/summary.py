"""Evidence-linked summary models. Every content line cites the verified claims it restates."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .domain import EvidenceState


class Citation(BaseModel):
    claim_id: str
    document_id: str
    document_type: str
    section: str
    passage_id: str
    label: str  # short human reference, e.g. "Admission Note, HOME MEDICATIONS, P005"


class SummaryLine(BaseModel):
    text: str
    state: EvidenceState | None = None  # the reconciliation state behind this line, when there is one
    finding_id: str | None = None
    citations: list[Citation]          # empty only for count lines (kind "count")
    kind: str = "content"              # "content" restates claims; "count" is a structural tally


class SummarySection(BaseModel):
    key: str
    title: str
    description: str
    lines: list[SummaryLine]


class EvidenceSummary(BaseModel):
    patient_id: str
    results_run_id: str | None
    is_current: bool
    stale_reason: str | None = None
    generated_at: datetime
    disclaimer: str
    sections: list[SummarySection]
