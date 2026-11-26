"""Clinical timeline: ordering, date honesty and filters (unit tests on the demo claims, plus the API)."""
from datetime import date

import pytest

from medusa.analysis.timeline import build_timeline, label, matches
from medusa.schemas.domain import Claim, DateValue, EventAttrs, LlmAttrs, SourceRef

P = "SYN-0001"
URL = f"/api/patients/{P}/timeline"


@pytest.fixture(scope="module")
def timeline(demo_claims):
    return build_timeline(demo_claims)


def _find(timeline, category, entity, doc_type=None):
    hits = [e for e in timeline if e.category == category and e.entity == entity
            and (doc_type is None or e.document_type == doc_type)]
    assert hits, f"no {category} {entity}"
    return hits[0]


def _placed(e):
    return e.event_date.value if e.ordering_basis == "event_date" else e.document_date


def test_every_claim_appears_once(timeline, demo_claims):
    assert sorted(e.claim_id for e in timeline) == sorted(c.claim_id for c in demo_claims)


def test_entries_are_in_chronological_order(timeline):
    placed = [_placed(e) for e in timeline]
    assert None not in placed and placed == sorted(placed)


def test_no_date_is_invented(timeline):
    for e in timeline:
        if e.ordering_basis == "event_date":
            assert e.event_date.value is not None and e.when == e.event_date.display()
        else:
            assert e.ordering_basis == "document_date"
            assert e.event_date.value is None and e.when == e.document_date.isoformat()


def test_exit_criterion_fever_is_approximate(timeline):
    fever = _find(timeline, "symptom", "fever")
    assert (fever.when, fever.when_approximate, fever.ordering_basis) == ("~2026-03-07", True, "event_date")
    assert fever.event_date.basis == "relative"


def test_exit_criterion_haemoglobin_collected_vs_reported(timeline):
    hb = _find(timeline, "lab_result", "hemoglobin")
    assert hb.when == "2026-03-11" and hb.ordering_basis == "event_date"
    assert hb.event_date.basis == "document_header" and "COLLECTION DATE" in hb.event_date.raw_text
    assert hb.document_date == date(2026, 3, 12)
    assert "flagged L in the report" in hb.label


def test_year_only_stays_year_only_and_comes_first(timeline):
    tb = timeline[0]
    assert tb.entity == "tuberculosis" and tb.when == "2015" and tb.when_precision == "year"
    assert tb.label == "Diagnosis documented as historical: tuberculosis"


def test_undated_passage_falls_back_to_document_date_and_says_so(timeline):
    htn = _find(timeline, "diagnosis", "hypertension", "Admission Note")
    assert (htn.ordering_basis, htn.when, htn.event_date.value) == ("document_date", "2026-03-10", None)


def test_stated_event_dates_precede_document_date_fallbacks_on_the_same_day(timeline):
    day = [e for e in timeline if _placed(e) == date(2026, 3, 12)]
    bases = [e.ordering_basis for e in day]
    assert bases == sorted(bases, key=lambda b: b != "event_date")


def test_labels_restate_the_record(timeline):
    assert _find(timeline, "medication", "metformin", "Admission Note").label == \
        "Medication listed active: metformin (written as “Glycomet”), 500 mg oral twice daily [admission list]"
    assert _find(timeline, "medication", "warfarin", "Progress Note").label.startswith("Medication held: warfarin")
    assert _find(timeline, "diagnosis", "chronic kidney disease", "Progress Note").assertion == "absent"
    ref = _find(timeline, "record_reference", "histopathology report")
    assert ref.label == "Referenced record: histopathology report (not in this bundle)"


def _claim(cid, event: DateValue, doc_date, category="encounter", attrs=None):
    return Claim(claim_id=cid, patient_id=P, claim_type=category, entity=cid.lower(), surface=cid.lower(),
                 attributes=attrs or EventAttrs(),
                 source=SourceRef(document_id="DOC-X", passage_id="DOC-X:P001", section="S", char_start=0, char_end=5,
                                  evidence_text="x", entity_char_start=0, entity_char_end=1),
                 document_date=doc_date, document_type="Note", event_date=event, extraction_method="rule:test")


def test_undated_entries_go_last_and_coarse_precision_first():
    day = _claim("DAY", DateValue(value=date(2020, 1, 1), precision="day", basis="explicit"), None)
    year = _claim("YEAR", DateValue(value=date(2020, 1, 1), precision="year", basis="explicit"), None)
    undated = _claim("NONE", DateValue(), None)
    later = _claim("LATER", DateValue(), date(2021, 5, 1))
    out = build_timeline([undated, day, later, year])
    assert [e.claim_id for e in out] == ["YEAR", "DAY", "LATER", "NONE"]
    assert (out[0].when, out[-1].when, out[-1].ordering_basis) == ("2020", "undated", "undated")


def test_llm_claim_label_and_search():
    c = _claim("LLM1", DateValue(), date(2026, 3, 11), "diagnosis",
               LlmAttrs(statement="x", model_assertion="present", assertion="absent"))
    c = c.model_copy(update={"entity": "consolidation", "surface": "No focal consolidation",
                             "extraction_method": "llm:fake/m"})
    [e] = build_timeline([c])
    assert label(c) == "Diagnosis: consolidation (documented as absent)"
    assert e.assertion == "absent" and e.extraction_method == "llm:fake/m"
    assert matches(e, "NO FOCAL")  # only the quote contains these words
    assert matches(e, "Note") and not matches(e, "warfarin")  # document type is searchable too


# ------------------------------------------------------------------ API
def test_empty_before_any_analysis(client):
    t = client.get(URL).json()
    assert t == {"patient_id": P, "results_run_id": None, "is_current": False, "stale_reason": None, "total": 0,
                 "excluded_unverified": 0,
                 "by_basis": {}, "by_category": {}, "entries": []}


@pytest.fixture()
def analysed(client):
    client.post(f"/api/patients/{P}/demo/load")
    client.post(f"/api/patients/{P}/analysis")
    return client


def test_timeline_api(analysed):
    t = analysed.get(URL).json()
    assert t["total"] == len(t["entries"]) == 51 and t["is_current"] and t["results_run_id"].startswith("RUN-")
    assert t["by_basis"] == {"event_date": 19, "document_date": 32}
    assert t["by_category"]["medication"] == 14
    assert t["entries"][0]["when"] == "2015"


def test_timeline_filters_keep_unfiltered_counts(analysed):
    meds = analysed.get(URL, params={"category": "medication"}).json()
    assert len(meds["entries"]) == 14 and meds["total"] == 51
    assert {e["category"] for e in meds["entries"]} == {"medication"}
    brand = analysed.get(URL, params={"q": "glycomet"}).json()["entries"]
    assert [e["entity"] for e in brand] == ["metformin"]
    both = analysed.get(URL, params={"category": "lab_result", "q": "  INR "}).json()["entries"]
    assert [e["entity"] for e in both] == ["inr"]
    doc = brand[0]["document_id"]
    in_doc = analysed.get(URL, params={"document_id": doc}).json()["entries"]
    assert in_doc and {e["document_id"] for e in in_doc} == {doc}
    assert analysed.get(URL, params={"q": "no such thing"}).json()["entries"] == []


@pytest.mark.parametrize("params", [{"category": "prescription"}, {"q": "x" * 201}, {"document_id": "nope"}])
def test_timeline_rejects_bad_filters(analysed, params):
    assert analysed.get(URL, params=params).status_code == 422


def test_timeline_reports_staleness(analysed):
    from medusa.core.config import PROJECT_ROOT
    pdf = (PROJECT_ROOT / "data" / "samples" / "endoscopy_report.pdf").read_bytes()
    analysed.post(f"/api/patients/{P}/documents", files={"file": ("endoscopy_report.pdf", pdf)})
    t = analysed.get(URL).json()
    assert t["is_current"] is False and t["stale_reason"] and t["total"] == 51
