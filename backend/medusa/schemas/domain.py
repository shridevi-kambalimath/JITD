"""Domain data contracts (docs/ARCHITECTURE.md section 4).

These models are shared by every pipeline module, the database layer (stored as JSON in the
`data` columns) and the API. Changing a field is a contract change: update the architecture
document and add a database migration if a promoted column is affected.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field



# --------------------------------------------------------------------------- states
class EvidenceState(str, Enum):
    """API codes. Display labels live in the frontend (Evidence-supported, Conflicting evidence, ...).
    No state means the record is medically correct; they describe what the documents establish."""
    SUPPORTED = "EVIDENCE_SUPPORTED"
    CONFLICTING = "CONFLICTING_EVIDENCE"
    INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
    REVIEW = "REVIEW_REQUIRED"


# --------------------------------------------------------------------------- dates
class DateValue(BaseModel):
    """A date as the record states it. Never guessed.

    value is None whenever the record does not let us resolve a calendar date.
    For year or month precision, value holds the first day of the period and
    precision says how much of it is real.
    """

    value: date | None = None
    precision: Literal["day", "month", "year", "unknown"] = "unknown"
    approximate: bool = False
    raw_text: str | None = None
    basis: Literal["explicit", "relative", "document_header", "none"] = "none"
    note: str | None = None

    @property
    def known(self) -> bool:
        return self.value is not None

    def display(self) -> str:
        if self.value is None:
            return "date not stated"
        if self.precision == "year":
            s = f"{self.value.year}"
        elif self.precision == "month":
            s = self.value.strftime("%Y-%m")
        else:
            s = self.value.isoformat()
        return f"~{s}" if self.approximate else s


# --------------------------------------------------------------------------- documents
class Document(BaseModel):
    document_id: str
    patient_id: str
    document_type: str
    document_date: date | None
    metadata: dict[str, str] = Field(default_factory=dict)
    text: str
    filename: str
    sha256: str


class Passage(BaseModel):
    passage_id: str
    document_id: str
    section: str
    char_start: int
    char_end: int
    text: str


class SourceRef(BaseModel):
    document_id: str
    passage_id: str
    section: str
    char_start: int
    char_end: int
    evidence_text: str
    entity_char_start: int  # absolute offsets of the entity mention inside the document
    entity_char_end: int


# --------------------------------------------------------------------------- claim attributes
MedAction = Literal["listed_active", "started", "held", "discontinued", "restarted", "changed"]
ListContext = Literal["admission", "discharge", "imported", "inpatient", "other"]
Assertion = Literal["present", "absent", "possible", "historical", "family"]


class MedicationAttrs(BaseModel):
    kind: Literal["medication"] = "medication"
    drug: str
    drug_class: str
    surface_name: str
    dose_value: float | None = None
    dose_unit: str | None = None
    route: str | None = None
    frequency_text: str | None = None
    frequency_per_day: float | None = None
    action: MedAction
    list_context: ListContext

    @property
    def daily_dose(self) -> float | None:
        if self.dose_value is None or self.frequency_per_day is None:
            return None
        return self.dose_value * self.frequency_per_day

    def regimen(self) -> str:
        parts = []
        if self.dose_value is not None:
            v = int(self.dose_value) if self.dose_value.is_integer() else self.dose_value
            parts.append(f"{v} {self.dose_unit or ''}".strip())
        if self.route:
            parts.append(self.route)
        if self.frequency_text:
            parts.append(self.frequency_text)
        return " ".join(parts) if parts else "regimen not stated"


class DiagnosisAttrs(BaseModel):
    kind: Literal["diagnosis"] = "diagnosis"
    assertion: Assertion
    assertion_trigger: str | None = None


class AllergyAttrs(BaseModel):
    kind: Literal["allergy"] = "allergy"
    substance: str | None = None
    no_known_allergies: bool = False
    reaction: str | None = None


class LabAttrs(BaseModel):
    kind: Literal["lab_result"] = "lab_result"
    analyte: str
    value: float
    unit: str | None = None
    flag: str | None = None  # copied exactly as printed in the report, never computed
    reference_range: str | None = None


class EventAttrs(BaseModel):
    kind: Literal["event"] = "event"
    detail: str | None = None


class ReferenceAttrs(BaseModel):
    kind: Literal["record_reference"] = "record_reference"
    referenced_type: str
    available_in_bundle: bool


class LlmAttrs(BaseModel):
    """A claim proposed by the LLM layer. Only the quote, its passage and the category are trusted (the quote was
    found verbatim by the server); the model's own statement and assertion are kept as reported, unverified."""

    kind: Literal["llm"] = "llm"
    statement: str | None = None
    model_assertion: str | None = None  # what the model said, kept for comparison only
    assertion: Assertion | None = None  # computed by the server from the passage (diagnosis/symptom only)


ClaimAttributes = Annotated[
    Union[MedicationAttrs, DiagnosisAttrs, AllergyAttrs, LabAttrs, EventAttrs, ReferenceAttrs, LlmAttrs],
    Field(discriminator="kind"),
]

ClaimType = Literal[
    "medication", "diagnosis", "allergy", "lab_result", "symptom", "procedure", "encounter",
    "record_reference",
]


class Claim(BaseModel):
    claim_id: str
    patient_id: str
    claim_type: ClaimType
    entity: str
    surface: str
    attributes: ClaimAttributes
    source: SourceRef
    document_date: date | None
    document_type: str
    event_date: DateValue
    extraction_method: str  # "rule:<rule id>" or "llm:<provider>/<model>"

    def effective_date(self) -> date | None:
        """Date used for ordering: event date if the record states one, else document date."""
        return self.event_date.value if self.event_date.value else self.document_date


# --------------------------------------------------------------------------- verification
class CheckResult(BaseModel):
    check_id: str
    passed: bool
    severity: Literal["hard", "advisory"]
    detail: str


class Verification(BaseModel):
    claim_id: str
    verified: bool
    checks: list[CheckResult]
    retrieval_refs: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- reconciliation
IssueType = Literal[
    "medication_status_conflict",
    "medication_dose_discrepancy",
    "diagnosis_status_conflict",
    "allergy_conflict",
    "unexplained_discharge_omission",
    "diagnosis_not_established",
    "missing_referenced_record",
    "unverified_claim",
    "possible_unextracted_evidence",
]

ISSUE_KIND: dict[str, str] = {
    "medication_status_conflict": "conflict",
    "medication_dose_discrepancy": "conflict",
    "diagnosis_status_conflict": "conflict",
    "allergy_conflict": "conflict",
    "unexplained_discharge_omission": "gap",
    "diagnosis_not_established": "gap",
    "missing_referenced_record": "gap",
    "unverified_claim": "integrity",
    "possible_unextracted_evidence": "integrity",
}


class Issue(BaseModel):
    issue_type: IssueType
    kind: Literal["conflict", "gap", "integrity"]
    rule_id: str
    description: str
    claim_ids: list[str] = Field(default_factory=list)


class Observation(BaseModel):
    """Explains a pattern that was examined and deliberately NOT flagged."""

    rule_id: str
    text: str
    claim_ids: list[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    passage_id: str
    document_id: str
    section: str
    score: float
    text: str


class InvestigationStep(BaseModel):
    rule_id: str
    query: str
    scope: Literal["passage", "section"]
    hits: list[SearchHit]
    outcome: str


FindingCategory = Literal["medication", "diagnosis", "allergy", "family_history", "record_reference"]


class Finding(BaseModel):
    finding_id: str
    patient_id: str
    category: FindingCategory
    subject: str
    claim_ids: list[str]
    issues: list[Issue] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    investigation: list[InvestigationStep] = Field(default_factory=list)
    high_risk: bool = False
    risk_reason: str | None = None
    state: EvidenceState | None = None
    gate_rule: str | None = None
    gate_rationale: str | None = None
