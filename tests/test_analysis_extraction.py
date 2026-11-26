"""Segmentation and rule extraction on the synthetic demo bundle, as stored by ingestion."""
from datetime import date

from medusa.analysis.rule_extractor import build_context, extract_claims
from medusa.analysis.segmentation import segment
from medusa.schemas.domain import Document


def _find(claims, category, entity, **attrs):
    return [c for c in claims if c.claim_type == category and c.entity == entity
            and all(getattr(c.attributes, k) == v for k, v in attrs.items())]


def _doc(text, doc_id="DOC-0000000000000001", **kw):
    base = dict(document_id=doc_id, patient_id="P", document_type="Progress Note", document_date=date(2026, 3, 12),
                metadata={}, text=text, filename="x.txt", sha256="x")
    return Document(**(base | kw))


# ---------------------------------------------------------------- segmentation
def test_segment_offsets_and_sections(demo_documents):
    for doc in demo_documents:
        passages = segment(doc.document_id, doc.text)
        assert passages and len({p.passage_id for p in passages}) == len(passages)
        for p in passages:
            assert doc.text[p.char_start:p.char_end] == p.text
    adm = demo_documents[0]
    ps = segment(adm.document_id, adm.text)
    assert {p.section for p in ps} >= {"HEADER", "HOME MEDICATIONS", "ALLERGIES", "FAMILY HISTORY"}
    assert next(p for p in ps if p.text.startswith("Glycomet")).section == "HOME MEDICATIONS"


def test_segment_splits_sentences_but_not_decimals():
    text = "DOCUMENT TYPE: X\n---\nPLAN:\nWarfarin held. Started pantoprazole 40 mg IV twice daily.\nRESULTS:\nHemoglobin: 7.9 g/dL (L)\n"
    texts = [p.text for p in segment("DOC-0000000000000001", text) if p.section != "HEADER"]
    assert texts == ["Warfarin held.", "Started pantoprazole 40 mg IV twice daily.", "Hemoglobin: 7.9 g/dL (L)"]


def test_segment_pdf_page_separators():
    text = "DOCUMENT TYPE: X\n---\nPLAN:\nPage one line.\n\n\n\nSecond page line."
    assert [p.text for p in segment("DOC-0000000000000001", text) if p.section != "HEADER"] == ["Page one line.", "Second page line."]


# ---------------------------------------------------------------- extraction
def test_golden_claim_counts(demo_claims):
    from collections import Counter
    assert Counter(c.claim_type for c in demo_claims) == {"diagnosis": 18, "medication": 14, "lab_result": 4,
        "procedure": 4, "encounter": 3, "symptom": 4, "allergy": 2, "record_reference": 2}
    assert all(c.extraction_method.startswith("rule:") for c in demo_claims)


def test_every_claim_is_anchored_to_canonical_text(demo_documents, demo_claims):
    texts = {d.document_id: d.text for d in demo_documents}
    for c in demo_claims:
        s = c.source
        assert texts[s.document_id][s.char_start:s.char_end] == s.evidence_text
        assert texts[s.document_id][s.entity_char_start:s.entity_char_end] == c.surface


def test_claim_ids_are_deterministic_and_unique(demo_documents, demo_claims):
    ctx = build_context(demo_documents)
    again = [c.claim_id for d in demo_documents for c in extract_claims(d, segment(d.document_id, d.text), ctx).claims]
    assert again == [c.claim_id for c in demo_claims] and len(set(again)) == len(again)


def test_brand_names_normalised(demo_claims):
    met = _find(demo_claims, "medication", "metformin", list_context="admission")[0]
    assert met.surface == "Glycomet" and met.attributes.daily_dose == 1000.0
    assert _find(demo_claims, "medication", "atorvastatin", list_context="admission")[0].surface == "Atorva"


def test_context_assertions(demo_claims):
    assert _find(demo_claims, "diagnosis", "stroke", assertion="absent")
    assert _find(demo_claims, "diagnosis", "breast cancer", assertion="family")
    assert not _find(demo_claims, "diagnosis", "breast cancer", assertion="present")
    assert _find(demo_claims, "diagnosis", "tuberculosis", assertion="historical")
    assert _find(demo_claims, "diagnosis", "pneumonia", assertion="possible")
    assert _find(demo_claims, "medication", "warfarin", action="held")


def test_event_date_kept_apart_from_document_date(demo_claims):
    hb = _find(demo_claims, "lab_result", "hemoglobin")[0]
    assert (hb.event_date.value, hb.document_date, hb.event_date.basis) == (date(2026, 3, 11), date(2026, 3, 12), "document_header")
    fever = _find(demo_claims, "symptom", "fever")[0]
    assert fever.event_date.value == date(2026, 3, 7) and fever.event_date.approximate
    tb = _find(demo_claims, "diagnosis", "tuberculosis")[0]
    assert tb.event_date.precision == "year"
    undated = _find(demo_claims, "diagnosis", "hypertension")[0]
    assert undated.event_date.value is None and undated.event_date.precision == "unknown"


def test_lab_flag_copied_not_computed(demo_claims):
    assert _find(demo_claims, "lab_result", "potassium")[0].attributes.flag is None
    assert _find(demo_claims, "lab_result", "inr")[0].attributes.flag == "H"


def test_missing_references_detected(demo_claims):
    refs = {c.entity: c.attributes.available_in_bundle for c in demo_claims if c.claim_type == "record_reference"}
    assert refs == {"endoscopy report": False, "histopathology report": False}


def test_narrative_mention_without_context_is_skipped_and_noted():
    doc = _doc("DOCUMENT TYPE: Clinic Letter\n---\nHISTORY:\nPatient asked about warfarin.\n", document_type="Clinic Letter")
    r = extract_claims(doc, segment(doc.document_id, doc.text), build_context([doc]))
    assert not [c for c in r.claims if c.claim_type == "medication"] and any("skipped" in n for n in r.notes)


def test_conflicting_admission_dates_leave_relative_dates_unresolved():
    a = _doc("x", metadata={"ADMISSION DATE": "2026-01-01"})
    b = _doc("x", doc_id="DOC-0000000000000002", metadata={"ADMISSION DATE": "2026-01-02"})
    ctx = build_context([a, b])
    assert ctx.admission_date is None and ctx.notes
