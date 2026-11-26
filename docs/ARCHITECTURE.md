# MEDUSA-X Architecture

> **Status note (Phase 1 of the master build).** Stack, folder layout, API paths (now under `/api`),
> status names and sequence are superseded by `IMPLEMENTATION_PLAN.md`. The rule tables in this document
> (reconciliation rules, verification checks V1 to V7, gate rules GATE-01 to GATE-07) remain the design
> for Phases 5 and 6.

Evidence-driven clinical record reconstruction. Hackathon prototype. Synthetic data only.

MEDUSA-X does not diagnose, recommend treatment, prescribe, or decide which of two conflicting
records is clinically correct. It reports what the records say, where they disagree, what is
missing, and what a qualified human must review.

---

## 1. Design principles

| Principle | How it is enforced |
|---|---|
| Every claim is traceable | `Claim.source` holds document id, passage id, character offsets and the exact evidence text. Verification re-reads the stored document and checks the span byte-for-byte. |
| No fabrication | Extraction only emits claims anchored to a span. The summary is assembled from templates over verified claims. No free-text generation. |
| No silent resolution | Reconciliation never votes, never ranks sources to pick a winner. Incompatible records produce an `Issue`; the gate maps issues to an evidence state. |
| Stopping is rule-based | The evidence gate is an ordered list of rules (`GATE-01` ... `GATE-07`). Each finding stores the rule id that fired and its rationale. No model confidence is used anywhere. |
| Event date is not document date | Each claim stores `document_date` and a separate `event_date: DateValue` with precision, approximation flag, raw text and resolution note. |
| Deterministic and reproducible | Same input bundle produces identical claim ids, findings and states. Tested with a golden ground-truth file. |

### Why rule-based extraction for the prototype

The stack is unchanged (FastAPI, SQLite, Pydantic, Streamlit). One deliberate choice: module 2 uses a
deterministic lexicon + NegEx-style assertion extractor instead of an LLM.

* The demo must work offline, on judging day, with zero API dependency and identical output every run.
* The evaluation claims ("0 ungrounded claims", "all planted conflicts detected, 0 decoys flagged")
  are only meaningful if the extractor is reproducible.
* The `Extractor` boundary is a single function returning `list[Claim]`. An LLM extractor can be added
  later behind the same interface, and its output would still pass through the same deterministic
  verifier (module 8), so the safety property does not depend on the extractor.

Known cost: recall is limited to the lexicon. This is mitigated by module 5 (section-scoped retrieval
investigation, see `possible_unextracted_evidence`) and stated openly in the limitations.

---

## 2. Orchestrated workflow

```
            +-------------------- pipeline.run(patient_id) --------------------+
            |                                                                  |
 documents  |  [1] parse + segment  ->  [2] extract claims  ->  [3] store        |
 (.txt/.pdf)|          |                       |                    |          |
            |          v                       v                    v          |
            |  passages w/ offsets      claims w/ SourceRef     SQLite         |
            |                                                                  |
            |  [5] build BM25 index over passages                              |
            |  [8] verify every claim (hard checks V1-V6, advisory V7)         |
            |  [4] reconstruct timeline (verified claims only)                 |
            |  [6] reconcile -> findings + issues                              |
            |        \-- for each candidate conflict: retrieval investigation  |
            |  [9] evidence gate -> state + rule id per finding                |
            |  [10] review queue (non-supported findings, prioritised)        |
            |  [11] evidence-linked summary (templated, cited)                 |
            |  run trace persisted (stage, counts, duration)                   |
            +------------------------------------------------------------------+
                         |                                  |
                    FastAPI (api.py)  <-- HTTP --  Streamlit (ui/app.py)
                         |
                  [7] evidence inspection endpoint
```

Single entry point: `medusa.pipeline.run_pipeline(store, patient_id)`. Stages run in a fixed order and
each writes a `StageTrace` (name, started, duration_ms, counts, notes) to the run record.

---

## 3. File structure

```
medusa-x/
  .env.example  requirements.txt  requirements-dev.txt  pyproject.toml  README.md
  docs/ARCHITECTURE.md
  data/                                  runtime database (git-ignored); demo bundle added in stage 2
  backend/medusa/
    __main__.py  main.py                 entry point, app factory, lifespan
    core/        config.py logging.py errors.py
    db/          connection.py schema.py                       (stage 1)
                 documents.py                                  (stage 2) document repository
                 repository.py                                 [3] storage of claims, findings, runs
    ingestion/   validation.py text_extraction.py metadata.py storage.py service.py   (stage 2)
    api/         health.py (stage 1)  documents.py (stage 2)
                 runs.py findings.py claims.py review.py summary.py
    schemas/     common.py domain.py
    pipeline/    parsing.py [1]  extraction.py lexicon.py assertion.py dates.py [2]
                 timeline.py [4]  retrieval.py [5]  reconciliation.py [6]  inspection.py [7]
                 verification.py [8]  gate.py [9]  review.py [10]  summary.py [11]
                 orchestrator.py  evaluate.py
  frontend/      app.py api_client.py
  tests/
```

Files not marked stage 1 are added in later stages, one module at a time.

## 4. Data schemas (Pydantic v2, `medusa/schemas.py`)

```python
class EvidenceState(str, Enum):
    SUPPORTED    = "Evidence-supported"
    CONFLICTING  = "Conflicting evidence"
    INSUFFICIENT = "Insufficient evidence"
    REVIEW       = "Review required"

class DateValue(BaseModel):
    value: date | None            # resolved calendar date, None if unknown
    precision: Literal["day", "month", "year", "unknown"]
    approximate: bool             # "approximately", "about", "since last night"
    raw_text: str | None          # exact text the date came from
    basis: Literal["explicit", "relative", "document_header", "none"]
    note: str | None              # e.g. "hospital day 3 resolved from admission date 2026-03-10"

class Document(BaseModel):
    document_id: str; patient_id: str; document_type: str
    document_date: date | None
    metadata: dict[str, str]      # all header fields (admission date, collection date, ...)
    text: str                     # full raw text; offsets index into this
    filename: str; sha256: str

class Passage(BaseModel):
    passage_id: str               # "<document_id>:P<nnn>"
    document_id: str; section: str
    char_start: int; char_end: int; text: str

class SourceRef(BaseModel):
    document_id: str; passage_id: str; section: str
    char_start: int; char_end: int   # span of evidence_text inside Document.text
    evidence_text: str

ClaimType = Literal["medication", "diagnosis", "allergy", "lab_result", "symptom",
                    "procedure", "encounter", "record_reference"]

class MedicationAttrs:  kind="medication"; drug; drug_class; surface_name; dose_value; dose_unit;
                        route; frequency_text; frequency_per_day; action ("listed_active" | "started" |
                        "held" | "discontinued" | "restarted" | "changed"); list_context
class DiagnosisAttrs:   kind="diagnosis"; assertion ("present"|"absent"|"possible"|"historical"|"family");
                        assertion_trigger
class AllergyAttrs:     kind="allergy"; substance | None; no_known_allergies: bool; reaction
class LabAttrs:         kind="lab_result"; analyte; value; unit; flag ("H"|"L"|None, as printed); reference_range
class EventAttrs:       kind="event"; detail  (symptom, procedure, encounter)
class ReferenceAttrs:   kind="record_reference"; referenced_type; available_in_bundle: bool

class Claim(BaseModel):
    claim_id: str                 # deterministic hash of (doc, offsets, type, entity)
    patient_id: str; claim_type: ClaimType
    entity: str                   # normalised, e.g. "metformin"
    surface: str                  # as written, e.g. "Glycomet"
    attributes: <discriminated union on kind>
    source: SourceRef
    document_date: date | None
    event_date: DateValue
    extraction_rule: str          # e.g. "MED-LIST-v1"

class CheckResult(BaseModel):  check_id; passed; severity ("hard"|"advisory"); detail
class Verification(BaseModel): claim_id; verified (all hard checks pass); checks; retrieval_refs

class Issue(BaseModel):
    issue_type: Literal["medication_status_conflict", "medication_dose_discrepancy",
                        "diagnosis_status_conflict", "allergy_conflict",
                        "unexplained_discharge_omission", "diagnosis_not_established",
                        "missing_referenced_record", "unverified_claim",
                        "possible_unextracted_evidence"]
    kind: Literal["conflict", "gap", "integrity"]
    rule_id: str; description: str; claim_ids: list[str]

class Observation(BaseModel):  rule_id; text; claim_ids   # explains why something was NOT flagged
class InvestigationStep(BaseModel): query; scope; hits: list[(passage_id, score)]; outcome

class Finding(BaseModel):
    finding_id: str               # e.g. "FND-MED-warfarin"
    patient_id: str
    category: Literal["medication", "diagnosis", "allergy", "family_history", "record_reference"]
    subject: str
    claim_ids: list[str]
    issues: list[Issue]
    observations: list[Observation]
    investigation: list[InvestigationStep]
    high_risk: bool; risk_reason: str | None
    state: EvidenceState; gate_rule: str; gate_rationale: str

class ReviewItem(BaseModel):
    review_id; finding_id; priority (1 = Review required, 2 = Conflicting, 3 = Insufficient)
    state; reason; status ("open"|"acknowledged"|"escalated"); reviewer_note; updated_at

class TimelineEntry(BaseModel):
    claim_id; claim_type; label; sort_date; ordering_basis ("event_date"|"document_date");
    event_date: DateValue; document_date; document_id; passage_id

class SummaryLine(BaseModel): text; claim_ids; state | None
class SummarySection(BaseModel): title; lines
class EvidenceSummary(BaseModel): patient_id; generated_from_run; disclaimer; sections; markdown
```

SQLite tables (`backend/medusa/db/schema.py`, migration v1): `documents`, `passages`, `claims` (attributes, source, event_date as
JSON), `verifications`, `findings` (JSON), `review_items`, `runs`. Derived tables are rebuilt on every
run; `review_items.status` and `reviewer_note` are preserved across reruns for findings that still exist.

---

## 5. Module contracts and rules

### [1] Parsing and segmentation
* Header block of `KEY: value` lines, terminated by `---`. Required: `DOCUMENT TYPE`, `DOCUMENT DATE`,
  `PATIENT ID`. `DOCUMENT ID` optional (derived from filename hash otherwise).
* Sections: a line that is an uppercase label ending in `:`.
* Passages: one per sentence or list line inside a section. Offsets are absolute into `Document.text`.
* Invariant (tested): `doc.text[p.char_start:p.char_end] == p.text` for every passage.

### [2] Extraction
* Medications: lexicon (generic + brand) -> dose, unit, route, frequency -> `frequency_per_day`;
  action from sentence keywords (`held`, `discontinued`, `started`, `restarted`, `changed`/`switched`);
  `listed_active` inside medication-list sections.
* Diagnoses: lexicon + assertion classifier (pre/post negation triggers, hedges, history, family
  subjects, section context, scope terminators).
* Allergies: `ALLERGIES` section; `NKDA` / `no known drug allergies` -> `no_known_allergies=True`.
* Labs: `Analyte: value unit (H|L) [reference ...]`. Flag copied as printed, never computed.
* Record references: `see/awaiting/pending ... <type> report` -> `available_in_bundle` checked against
  document types present.
* Dates: explicit (`2026-03-12`, `12 March 2026`, `March 2026`, `2015`), relative
  (`3 days prior to admission`, `hospital day 3`, `since last night`), header (`COLLECTION DATE`).
  Unresolvable -> `value=None, precision="unknown"`. Never guessed.

### [4] Timeline
* Verified claims only. Sort key = `event_date.value` if known, else `document_date` with
  `ordering_basis="document_date"` shown explicitly in the UI. Approximate dates are labelled.

### [5] Retrieval
* BM25 (k1=1.5, b=0.75) over passages, with lexicon synonym expansion (brand <-> generic).
* Two scopes: `passage` (search API, verification V7) and `section` (investigation window).

### [6] Reconciliation rules

| Rule | Condition | Output |
|---|---|---|
| MED-STATUS-01 | A `listed_active` claim dated after a `held`/`discontinued` claim for the same drug, with no `restarted` claim in between | `medication_status_conflict` |
| MED-DOSE-01 | Two `listed_active` claims with different daily dose (dose x frequency) and no `changed`/`started` claim between their dates | `medication_dose_discrepancy` |
| MED-OMIT-01 | Drug listed active on admission, absent from discharge medication list, no `discontinued` claim | `unexplained_discharge_omission` |
| MED-CHANGE-01 | Difference explained by a documented `changed`/`started` action | Observation only (not an issue) |
| DX-STATUS-01 | Definite `present` and definite `absent` for the same diagnosis in different documents | `diagnosis_status_conflict` |
| DX-EVOL-01 | `possible` followed later by definite `present` or `absent` | Observation only |
| DX-NOTEST-01 | Only `possible` assertions, never confirmed or refuted | `diagnosis_not_established` |
| DX-FAMILY-01 | Family-history assertions are routed to `family_history`, never reconciled against the patient | Observation |
| ALG-01 | A specific allergy and a `no known allergies` statement both documented | `allergy_conflict` |
| REF-01 | Referenced record type not present in bundle | `missing_referenced_record` |
| INV-01 | For every medication conflict: section-scoped retrieval for drug + resolving terms (`restarted`, `resumed`, `recommenced`). If a hit contains a resolving term not captured as a claim | `possible_unextracted_evidence` |

The system never decides which side of a conflict is correct. It never uses majority, recency or
source authority to drop a record.

### [8] Verification (per claim)

| Check | Severity | Rule |
|---|---|---|
| V1 source_document_exists | hard | document id exists for this patient |
| V2 passage_exists | hard | passage id exists and belongs to that document |
| V3 span_exact_match | hard | `doc.text[start:end] == evidence_text` |
| V4 span_within_passage | hard | span lies inside the passage offsets |
| V5 entity_grounded | hard | surface form occurs (case-insensitive) inside the span |
| V6 event_not_after_document | hard | `event_date <= document_date` when both known |
| V7 retrievable | advisory | BM25 search for the entity returns this passage in top 10 |

### [9] Evidence gate (ordered, first match wins)

| Rule | Condition | State |
|---|---|---|
| GATE-01 | No verified claims remain | Review required if high risk, else Insufficient evidence |
| GATE-02 | Any `possible_unextracted_evidence` | Review required |
| GATE-03 | Any conflict issue and high risk | Review required |
| GATE-04 | Any conflict issue | Conflicting evidence |
| GATE-05 | Any gap or integrity issue and high risk | Review required |
| GATE-06 | Any gap or integrity issue | Insufficient evidence |
| GATE-07 | Otherwise | Evidence-supported |

High risk (prototype configuration in `config.py`, not a clinical standard): drug classes
`anticoagulant`, `insulin`, `opioid`; every allergy finding.

### [10] Review queue
All findings not in `Evidence-supported`. Priority 1/2/3 by state. Reviewer may set
`acknowledged` or `escalated` with a note. Reviewer actions never change the evidence state.

### [11] Summary
Template-generated sections: encounter, diagnoses, medications, allergies, laboratory results,
discrepancies, missing context, review flags. Every line carries claim ids; a test asserts each id
refers to a verified claim. Fixed disclaimer on top.

---

## 6. API contracts (`medusa/api.py`)

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/health` | | `{"status":"ok"}` |
| POST | `/patients/{pid}/load-demo` | | `{"documents_loaded": int}` |
| POST | `/patients/{pid}/documents` | multipart `file` (.txt or .pdf) | `DocumentDetail` (201; `status` processed or failed) |
| DELETE | `/documents/{doc_id}` | | 204 |
| GET | `/patients/{pid}/documents?status=` | | `list[DocumentSummary]` |
| GET | `/documents/{doc_id}` | | `DocumentDetail` (metadata, extracted text, page spans, warnings, events) |
| POST | `/patients/{pid}/run` | | `RunRecord` (run id, stage traces, state counts) |
| GET | `/patients/{pid}/claims?claim_type=` | | `list[Claim]` + verification flag |
| GET | `/patients/{pid}/timeline` | | `list[TimelineEntry]` |
| GET | `/patients/{pid}/findings?state=` | | `list[Finding]` |
| GET | `/claims/{claim_id}/evidence` | | `EvidenceView` (claim, document meta, passage, context window, highlighted offsets, verification checks, retrieval refs, related findings) |
| GET | `/patients/{pid}/search?q=&k=` | | `list[SearchHit]` |
| GET | `/patients/{pid}/review-queue` | | `list[ReviewItem]` sorted by priority |
| POST | `/review-items/{review_id}` | `{"status": "acknowledged"|"escalated", "note": str}` | `ReviewItem` |
| GET | `/patients/{pid}/summary` | | `EvidenceSummary` |
| GET | `/runs/{run_id}` | | `RunRecord` |
| GET | `/patients/{pid}/runs/latest` | | `RunRecord` (409 if none) |

Errors: 404 for unknown ids, 409 when an endpoint needs a completed run, 422 for invalid uploads.

---

## 7. Milestones

- [x] S1 Foundation: settings, .env, logging, error envelope, SQLite + migrations, health checks, status UI
- [x] S2 Document ingestion: upload, validation, PDF/TXT extraction, header metadata, status tracking, synthetic bundle
- [ ] S2b Ground truth file; [1] segmentation into passages
- [ ] S3 [2] extraction (dates, assertion, lexicon)
- [ ] S4 [3] repository, [4] timeline, [5] retrieval
- [ ] S5 [8] verification
- [ ] S6 [6] reconciliation with retrieval investigation
- [ ] S7 [9] gate, [10] review queue, [11] summary, [7] evidence inspection
- [ ] S8 Orchestrator, full API, full UI, evaluation script, demo script

## 8. Explicit non-goals for the prototype

OCR, real patient data, terminology servers (RxNorm/SNOMED), FHIR export, authentication,
multi-user concurrency, LLM extraction. Each is listed as future work in the README.
