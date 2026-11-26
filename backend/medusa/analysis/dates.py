"""Date extraction that preserves uncertainty.

Rules:
* A date is only resolved when the text states it or states an anchor-relative expression
  whose anchor is itself documented (admission date, document date).
* If the anchor is missing, the expression is kept (raw_text) with value=None. Nothing is guessed.
* Year and month precision are kept as precision, not silently expanded to a day.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from ..schemas.domain import DateValue

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], start=1)}
_MONTH_RE = "|".join(MONTHS)

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_RE})\s+(\d{{4}})\b", re.IGNORECASE)
_MDY = re.compile(rf"\b({_MONTH_RE})\s+(\d{{1,2}}),\s*(\d{{4}})\b", re.IGNORECASE)
_MY = re.compile(rf"\b({_MONTH_RE})\s+(\d{{4}})\b", re.IGNORECASE)
_HOSP_DAY = re.compile(r"\bhospital day\s+(\d{1,3})\b", re.IGNORECASE)
_PRIOR_ADM = re.compile(
    r"\b(?:(approximately|about|around|roughly|~)\s*)?(\d{1,3})\s+(day|week)s?\s+(?:prior to|before)\s+admission\b",
    re.IGNORECASE)
_LAST_NIGHT = re.compile(r"\b(since last night|last night|yesterday)\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:in|since|during)\s+((?:19|20)\d{2})\b", re.IGNORECASE)
# relative expressions with no fixed anchor: kept as written, never resolved to a calendar date
_VAGUE = re.compile(r"\b(since last week|last week|a few days ago|a few weeks ago|recently|earlier this month|some time ago)\b",
                    re.IGNORECASE)


@dataclass(frozen=True)
class DateContext:
    document_date: date | None
    admission_date: date | None = None


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def extract_date(text: str, ctx: DateContext) -> DateValue | None:
    """Return the first date expression in text, or None if the text states no date."""
    if m := _ISO.search(text):
        v = _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if v:
            return DateValue(value=v, precision="day", raw_text=m.group(0), basis="explicit")
    if m := _DMY.search(text):
        v = _safe(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        if v:
            return DateValue(value=v, precision="day", raw_text=m.group(0), basis="explicit")
    if m := _MDY.search(text):
        v = _safe(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        if v:
            return DateValue(value=v, precision="day", raw_text=m.group(0), basis="explicit")
    if m := _MY.search(text):
        return DateValue(value=date(int(m.group(2)), MONTHS[m.group(1).lower()], 1), precision="month",
                         raw_text=m.group(0), basis="explicit")
    if m := _HOSP_DAY.search(text):
        n = int(m.group(1))
        if ctx.admission_date and n >= 1:
            return DateValue(value=ctx.admission_date + timedelta(days=n - 1), precision="day",
                             raw_text=m.group(0), basis="relative",
                             note=f"hospital day {n} counted from admission date {ctx.admission_date.isoformat()} (day 1)")
        return DateValue(raw_text=m.group(0), basis="relative", note="admission date not documented; not resolved")
    if m := _PRIOR_ADM.search(text):
        n = int(m.group(2)) * (7 if m.group(3).lower() == "week" else 1)
        approx = m.group(1) is not None
        if ctx.admission_date:
            return DateValue(value=ctx.admission_date - timedelta(days=n), precision="day", approximate=approx,
                             raw_text=m.group(0).strip(), basis="relative",
                             note=f"{n} days before admission date {ctx.admission_date.isoformat()}")
        return DateValue(raw_text=m.group(0).strip(), approximate=approx, basis="relative",
                         note="admission date not documented; not resolved")
    if m := _LAST_NIGHT.search(text):
        if ctx.document_date:
            return DateValue(value=ctx.document_date - timedelta(days=1), precision="day",
                             approximate=m.group(1).lower() != "yesterday", raw_text=m.group(0), basis="relative",
                             note=f"relative to document date {ctx.document_date.isoformat()}")
        return DateValue(raw_text=m.group(0), approximate=True, basis="relative",
                         note="document date unknown; not resolved")
    if m := _YEAR.search(text):
        return DateValue(value=date(int(m.group(1)), 1, 1), precision="year", raw_text=m.group(0),
                         basis="explicit", note="year only")
    if m := _VAGUE.search(text):
        return DateValue(raw_text=m.group(0), approximate=True, basis="relative",
                         note="vague relative expression with no fixed anchor; not resolved to a date")
    return None


def undated(note: str = "no date stated in the passage; document date is kept separately") -> DateValue:
    return DateValue(basis="none", note=note)
