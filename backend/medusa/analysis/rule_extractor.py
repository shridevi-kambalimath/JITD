"""Rule-based claim extraction (deterministic). Always runs; the LLM layer is optional and additive.

Every emitted Claim is anchored to a passage span and an entity span. Nothing is emitted
without a source. Mentions the rules cannot interpret safely are skipped and reported in
ExtractionResult.notes rather than guessed.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date

from . import lexicon as lx
from .assertion import classify
from .dates import DateContext, extract_date, undated
from ..schemas.domain import (AllergyAttrs, Claim, DateValue, DiagnosisAttrs, Document, EventAttrs, LabAttrs,
                              MedicationAttrs, Passage, ReferenceAttrs, SourceRef)

RULE_VERSION = "v1"

_ACTIONS: list[tuple[str, str]] = [
    ("restarted", r"restarted|re-started|resumed|recommenced"),
    ("discontinued", r"discontinued|stopped|ceased|inactive"),
    ("held", r"held|withheld|withhold|on hold"),
    ("changed", r"changed|switched|increased|decreased|reduced|titrated"),
    ("started", r"started|initiated|commenced"),
]
_DOSE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mg|mcg|g|units|iu|ml)\b", re.IGNORECASE)
_LAB_LINE = re.compile(
    r"^(?P<analyte>[A-Za-z][A-Za-z ]*?):\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z%][A-Za-z/%0-9^]*)?"
    r"\s*(?:\((?P<flag>HH|LL|H|L)\))?\s*(?:\[reference\s+(?P<ref>[^\]]+)\])?\s*$")
_PERFORMED = re.compile(r"\b(performed|given|received|underwent|done|completed|administered)\b", re.IGNORECASE)
_NKDA = re.compile(r"\b(NKDA|no known drug allergies|no known allergies)\b", re.IGNORECASE)
_REF = re.compile(r"\b([A-Za-z]+)\s+report\b", re.IGNORECASE)
_REF_TRIGGER = re.compile(
    r"\b(see|awaiting|pending|to follow|refer to|as per|per|attached|not available|outstanding)\b", re.IGNORECASE)
_EVENT_HEADERS = ("COLLECTION DATE", "STUDY DATE", "PROCEDURE DATE")


@dataclass
class BundleContext:
    admission_date: date | None
    document_types: set[str]
    notes: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    claims: list[Claim]
    notes: list[str]


def build_context(documents: list[Document]) -> BundleContext:
    values = {d.metadata["ADMISSION DATE"] for d in documents if d.metadata.get("ADMISSION DATE")}
    notes: list[str] = []
    admission = None
    if len(values) == 1:
        try:
            admission = date.fromisoformat(values.pop())
        except ValueError:
            notes.append("ADMISSION DATE header is not ISO formatted; relative dates left unresolved")
    elif len(values) > 1:
        notes.append(f"Documents disagree on admission date {sorted(values)}; relative dates left unresolved")
    return BundleContext(admission, {d.document_type.lower() for d in documents}, notes)


def claim_id(doc_id: str, start: int, end: int, claim_type: str, entity: str, method: str = "rule") -> str:
    """Deterministic: the same text extracted the same way gets the same id in every run."""
    h = hashlib.sha1(f"{doc_id}|{start}|{end}|{claim_type}|{entity}|{method}".encode()).hexdigest()[:12].upper()
    return f"CLM-{h}"


def _detect_action(sentence: str) -> str | None:
    for action, pattern in _ACTIONS:
        if re.search(rf"\b({pattern})\b", sentence, re.IGNORECASE):
            return action
    return None


def _list_context(doc: Document, section: str) -> str:
    s, t = section.upper(), doc.document_type.lower()
    if "MEDIC" in s and "DISCHARGE" in s:
        return "discharge"
    if "MEDIC" in s and ("HOME" in s or "ADMISSION" in s or "admission" in t):
        return "admission"
    if "medication list" in t or "imported" in t:
        return "imported"
    if "progress" in t or s in {"PLAN", "INPATIENT MEDICATIONS"}:
        return "inpatient"
    return "other"


def _header_event_date(doc: Document) -> DateValue | None:
    for key in _EVENT_HEADERS:
        raw = doc.metadata.get(key)
        if raw:
            try:
                v = date.fromisoformat(raw)
            except ValueError:
                return DateValue(raw_text=raw, basis="document_header", note=f"{key} not ISO formatted; not resolved")
            note = f"{key.lower()} from document header"
            if doc.document_date and doc.document_date != v:
                note += f"; document dated {doc.document_date.isoformat()}"
            return DateValue(value=v, precision="day", raw_text=f"{key}: {raw}", basis="document_header", note=note)
    return None


def extract_claims(doc: Document, passages: list[Passage], bundle: BundleContext) -> ExtractionResult:
    ctx = DateContext(document_date=doc.document_date, admission_date=bundle.admission_date)
    header_date = _header_event_date(doc)
    claims: list[Claim] = []
    notes: list[str] = []

    def emit(claim_type, entity, surface, attrs, p: Passage, rel_start, rel_end, event_date, rule):
        claims.append(Claim(
            claim_id=claim_id(doc.document_id, p.char_start + rel_start, p.char_start + rel_end, claim_type, entity),
            patient_id=doc.patient_id,
            claim_type=claim_type,
            entity=entity,
            surface=surface,
            attributes=attrs,
            source=SourceRef(document_id=doc.document_id, passage_id=p.passage_id, section=p.section,
                             char_start=p.char_start, char_end=p.char_end, evidence_text=p.text,
                             entity_char_start=p.char_start + rel_start, entity_char_end=p.char_start + rel_end),
            document_date=doc.document_date,
            document_type=doc.document_type,
            event_date=event_date,
            extraction_method=f"rule:{rule}-{RULE_VERSION}",
        ))

    for p in passages:
        text, section = p.text, p.section

        # ---------------------------------------------------------------- header: encounter dates
        if section == "HEADER":
            for key, entity in (("ADMISSION DATE", "admission"), ("DISCHARGE DATE", "discharge")):
                if text.startswith(key + ":"):
                    dv = extract_date(text, ctx)
                    if dv is None or dv.value is None:
                        notes.append(f"{p.passage_id}: {key} not parseable; encounter not extracted")
                        continue
                    dv = dv.model_copy(update={"basis": "document_header"})
                    emit("encounter", entity, key, EventAttrs(detail=f"{entity} date"), p, 0, len(key), dv,
                         "ENC-HEADER")
            continue

        stated = extract_date(text, ctx)
        event_date = stated or header_date or undated()

        # ---------------------------------------------------------------- allergies
        if "ALLERG" in section.upper():
            if m := _NKDA.search(text):
                emit("allergy", "no known drug allergies", m.group(1),
                     AllergyAttrs(no_known_allergies=True), p, m.start(1), m.end(1), event_date, "ALG-NKDA")
            for m in lx.find_allergens(text):
                reaction = re.search(r"\(([^)]+)\)", text[m.end:])
                emit("allergy", m.canonical, m.surface,
                     AllergyAttrs(substance=m.canonical, reaction=reaction.group(1) if reaction else None),
                     p, m.start, m.end, event_date, "ALG-SUBSTANCE")
            continue

        # ---------------------------------------------------------------- labs
        if (lm := _LAB_LINE.match(text)) and (analyte := lx.lab_canonical(lm.group("analyte"))):
            emit("lab_result", analyte, lm.group("analyte"),
                 LabAttrs(analyte=analyte, value=float(lm.group("value")), unit=lm.group("unit"),
                          flag=lm.group("flag"), reference_range=lm.group("ref")),
                 p, lm.start("analyte"), lm.end("analyte"), event_date, "LAB-LINE")
            continue

        # ---------------------------------------------------------------- medications
        list_ctx = _list_context(doc, section)
        for m in lx.find_drugs(text):
            stop = len(text)
            for ch in "(;":
                i = text.find(ch, m.end)
                if i != -1:
                    stop = min(stop, i)
            tail = text[m.end:stop]
            action = _detect_action(text)
            if action is None:
                if list_ctx in {"admission", "discharge", "imported"}:
                    action = "listed_active"
                else:
                    notes.append(f"{p.passage_id}: '{m.surface}' mentioned without list context or action; skipped")
                    continue
            dose = _DOSE.match(tail)
            freq_text, per_day = lx.parse_frequency(tail)
            emit("medication", m.canonical, m.surface,
                 MedicationAttrs(drug=m.canonical, drug_class=lx.drug_class(m.canonical), surface_name=m.surface,
                                 dose_value=float(dose.group(1)) if dose else None,
                                 dose_unit=dose.group(2).lower() if dose else None,
                                 route=lx.parse_route(tail), frequency_text=freq_text, frequency_per_day=per_day,
                                 action=action, list_context=list_ctx),
                 p, m.start, m.end, event_date, "MED")

        # ---------------------------------------------------------------- diagnoses
        for m in lx.find_diagnoses(text):
            assertion, trigger = classify(text, m.start, m.end, section)
            emit("diagnosis", m.canonical, m.surface, DiagnosisAttrs(assertion=assertion, assertion_trigger=trigger),
                 p, m.start, m.end, event_date, "DX")

        # ---------------------------------------------------------------- symptoms (present only)
        for m in lx.find_symptoms(text):
            assertion, _ = classify(text, m.start, m.end, section)
            if assertion != "present":
                notes.append(f"{p.passage_id}: symptom '{m.surface}' asserted {assertion}; not added to timeline")
                continue
            emit("symptom", m.canonical, m.surface, EventAttrs(detail="symptom onset or report"),
                 p, m.start, m.end, event_date, "SYM")

        # ---------------------------------------------------------------- procedures (performed only)
        if _PERFORMED.search(text):
            seen: set[str] = set()
            for m in lx.find_procedures(text):
                if re.match(r"\s+report\b", text[m.end:], re.IGNORECASE) or m.canonical in seen:
                    continue
                seen.add(m.canonical)
                emit("procedure", m.canonical, m.surface, EventAttrs(detail="documented as performed"),
                     p, m.start, m.end, event_date, "PROC")

        # ---------------------------------------------------------------- referenced records
        if _REF_TRIGGER.search(text):
            for m in _REF.finditer(text):
                kw = m.group(1).lower()
                if kw not in lx.REPORT_TYPES:
                    continue
                ref_type = f"{kw} report"
                available = any(kw in t for t in bundle.document_types)
                emit("record_reference", ref_type, m.group(0),
                     ReferenceAttrs(referenced_type=ref_type, available_in_bundle=available),
                     p, m.start(), m.end(), event_date, "REF")

    return ExtractionResult(claims, notes)
