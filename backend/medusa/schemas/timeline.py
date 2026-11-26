"""Timeline API models. The timeline is a query over stored claims, never a separate table."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from .domain import ClaimType, DateValue

OrderingBasis = Literal["event_date", "document_date", "undated"]


class TimelineEntry(BaseModel):
    claim_id: str
    category: ClaimType
    label: str                      # deterministic wording of what the record states; no inference
    entity: str
    quote: str                      # the words as written in the source
    assertion: str | None = None
    extraction_method: str
    ordering_basis: OrderingBasis   # which date placed this entry: the stated event date, or the document date
    when: str                       # how the ordering date is shown: "2026-03-11", "~2026-03-07", "2019"
    when_precision: Literal["day", "month", "year", "unknown"]
    when_approximate: bool
    event_date: DateValue           # exactly as extracted; value is None when the passage states no date
    document_date: date | None
    document_id: str
    document_type: str
    section: str
    passage_id: str


class TimelineResponse(BaseModel):
    patient_id: str
    results_run_id: str | None      # analysis run whose claims this timeline shows
    is_current: bool
    stale_reason: str | None = None
    total: int                      # entries before filters
    excluded_unverified: int = 0    # stored claims left off because they failed verification
    by_basis: dict[str, int]        # before filters
    by_category: dict[str, int]     # before filters
    entries: list[TimelineEntry]    # after filters, in chronological order
