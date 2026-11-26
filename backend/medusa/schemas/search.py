"""Evidence search API models. Every hit points at a stored passage, claim, timeline entry or finding."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from .domain import EvidenceState
from .timeline import TimelineEntry

SearchScope = Literal["all", "passages", "claims", "timeline", "reconciliation"]


class FindingRef(BaseModel):
    finding_id: str
    subject: str
    state: EvidenceState | None


class ClaimRef(BaseModel):
    claim_id: str
    category: str
    entity: str
    surface: str
    extraction_method: str
    verified: bool | None
    finding: FindingRef | None = None


class PassageHit(BaseModel):
    passage_id: str
    document_id: str
    document_type: str
    document_date: date | None
    section: str
    text: str
    score: float
    matches: list[tuple[int, int]]      # spans in text that matched the query or its expansions
    section_matched: bool = False       # the section label matched (e.g. "allergies" finds lines under ALLERGIES)
    claims: list[ClaimRef]              # claims extracted from this passage


class ClaimHit(ClaimRef):
    document_id: str
    document_type: str
    document_date: date | None
    event_when: str | None              # event date as displayed (e.g. "~2026-03-07"); None when not stated
    passage_text: str
    score: float


class TimelineHit(TimelineEntry):
    score: float


class FindingHit(FindingRef):
    category: str
    gate_rule: str | None
    issue_types: list[str]
    score: float


class SearchResponse(BaseModel):
    patient_id: str
    query: str
    terms: list[str]                    # tokens searched, including brand/generic and abbreviation expansions
    expanded: list[str]                 # the expansions alone, shown so the user knows what else was matched
    scope: SearchScope
    results_run_id: str | None
    is_current: bool
    note: str | None = None
    counts: dict[str, int]              # per scope, regardless of the scope requested
    passages: list[PassageHit]
    claims: list[ClaimHit]
    timeline: list[TimelineHit]
    reconciliation: list[FindingHit]
