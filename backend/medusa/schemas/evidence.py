"""Evidence inspector model: one claim, its exact source, every verification check and where it is used."""
from __future__ import annotations

from pydantic import BaseModel

from .analysis import ClaimRecord
from .documents import DocumentSummary
from .domain import EvidenceState, Passage, Verification
from .timeline import TimelineEntry


class RelatedFinding(BaseModel):
    finding_id: str
    subject: str
    category: str
    state: EvidenceState | None
    gate_rule: str | None
    role: str  # "cited by an issue" or "record for this subject"


class EvidenceView(BaseModel):
    claim: ClaimRecord
    document: DocumentSummary
    passage: Passage
    context_before: str          # stored text just before the passage, cut at a line boundary
    evidence_text: str           # the passage exactly as stored now
    context_after: str
    verification: Verification   # re-run now against the stored text
    verified_at_analysis: bool | None  # what the analysis run recorded
    verification_changed: bool   # the stored text no longer gives the result the analysis recorded
    timeline_entry: TimelineEntry | None  # None when the claim is not on the timeline (failed verification)
    related_findings: list[RelatedFinding]
