"""Clinical timeline: stored claims in date order, without inventing dates.

Ordering rules
1. If the passage states an event date, the entry is placed by it (basis 'event_date'). That includes
   dates resolved from the document header for the same event, such as a lab's COLLECTION DATE.
2. Otherwise it is placed by its document's date and labelled 'document_date', so a reader can see that
   the record did not say when the event happened.
3. Only if neither exists is it 'undated' and listed last.
4. Precision is kept: a year-only date sorts at the start of its year and is shown as the year alone;
   an approximate date keeps its '~'. On the same calendar position coarser dates come first, then
   stated event dates before document-date fallbacks, then a fixed category order, then source order.

Labels restate what the record says ("Medication held: warfarin"). They never judge it.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from ..schemas.domain import (AllergyAttrs, Claim, DiagnosisAttrs, LabAttrs, LlmAttrs, MedicationAttrs,
                              ReferenceAttrs)
from ..schemas.timeline import TimelineEntry

CATEGORY_ORDER = {"encounter": 0, "symptom": 1, "procedure": 2, "lab_result": 3, "diagnosis": 4, "medication": 5,
                  "allergy": 6, "record_reference": 7}
CATEGORY_LABEL = {"encounter": "Encounter", "symptom": "Symptom", "procedure": "Procedure", "lab_result": "Lab result",
                  "diagnosis": "Diagnosis", "medication": "Medication", "allergy": "Allergy",
                  "record_reference": "Referenced record"}
_ASSERTION = {"present": "documented as present", "absent": "documented as absent", "possible": "documented as possible",
              "historical": "documented as historical", "family": "documented as family history"}
_PRECISION_RANK = {"year": 0, "month": 1, "day": 2, "unknown": 3}


def label(c: Claim) -> str:
    a = c.attributes
    if isinstance(a, LlmAttrs):
        note = f" ({_ASSERTION[a.assertion]})" if a.assertion and a.assertion != "present" else ""
        return f"{CATEGORY_LABEL[c.claim_type]}: {c.entity}{note}"
    if c.claim_type == "encounter":
        return f"{c.entity.capitalize()} documented"
    if c.claim_type == "symptom":
        return f"Symptom documented: {c.entity} (“{c.surface}”)" if c.surface.lower() != c.entity else \
            f"Symptom documented: {c.entity}"
    if c.claim_type == "procedure":
        return f"Procedure documented as performed: {c.entity}"
    if isinstance(a, LabAttrs):
        unit = f" {a.unit}" if a.unit else ""
        flag = f", flagged {a.flag} in the report" if a.flag else ""
        return f"Lab result: {c.entity} {a.value:g}{unit}{flag}"
    if isinstance(a, DiagnosisAttrs):
        return f"Diagnosis {_ASSERTION[a.assertion]}: {c.entity}"
    if isinstance(a, MedicationAttrs):
        name = c.entity if a.surface_name.lower() == c.entity else f"{c.entity} (written as “{a.surface_name}”)"
        return f"Medication {a.action.replace('_', ' ')}: {name}, {a.regimen()} [{a.list_context} list]"
    if isinstance(a, AllergyAttrs):
        if a.no_known_allergies:
            return "Allergies: no known drug allergies documented"
        return f"Allergy documented: {a.substance}" + (f" ({a.reaction})" if a.reaction else "")
    if isinstance(a, ReferenceAttrs):
        where = "present in this bundle" if a.available_in_bundle else "not in this bundle"
        return f"Referenced record: {c.entity} ({where})"
    return f"{CATEGORY_LABEL.get(c.claim_type, c.claim_type)}: {c.entity}"


def _assertion(c: Claim) -> str | None:
    a = c.attributes
    return a.assertion if isinstance(a, (DiagnosisAttrs, LlmAttrs)) else None


def to_entry(c: Claim) -> TimelineEntry:
    ev = c.event_date
    if ev.value is not None:
        basis, when, precision, approx = "event_date", ev.display(), ev.precision, ev.approximate
    elif c.document_date is not None:
        basis, when, precision, approx = "document_date", c.document_date.isoformat(), "day", False
    else:
        basis, when, precision, approx = "undated", "undated", "unknown", False
    return TimelineEntry(
        claim_id=c.claim_id, category=c.claim_type, label=label(c), entity=c.entity, quote=c.surface,
        assertion=_assertion(c), extraction_method=c.extraction_method, ordering_basis=basis, when=when,
        when_precision=precision, when_approximate=approx, event_date=ev, document_date=c.document_date,
        document_id=c.source.document_id, document_type=c.document_type, section=c.source.section,
        passage_id=c.source.passage_id)


def _sort_key(item: tuple[int, Claim, TimelineEntry]):
    index, c, e = item
    placed = c.event_date.value if e.ordering_basis == "event_date" else c.document_date
    return (placed is None, placed or date.max, _PRECISION_RANK[e.when_precision],
            0 if e.ordering_basis == "event_date" else 1, CATEGORY_ORDER.get(e.category, 9), index)


def build_timeline(claims: list[Claim]) -> list[TimelineEntry]:
    """claims in source order (as the repository returns them); returns entries in chronological order."""
    items = [(i, c, to_entry(c)) for i, c in enumerate(claims)]
    return [e for _, _, e in sorted(items, key=_sort_key)]


def matches(e: TimelineEntry, q: str) -> bool:
    q = q.casefold()
    return any(q in field.casefold() for field in (e.label, e.entity, e.quote, e.document_type, e.section, e.when))


def tally(entries: list[TimelineEntry]) -> tuple[dict[str, int], dict[str, int]]:
    return dict(Counter(e.ordering_basis for e in entries)), dict(Counter(e.category for e in entries))
