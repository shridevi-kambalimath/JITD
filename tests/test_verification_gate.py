"""Claim verification (V1 to V7), the evidence gate (GATE-01 to GATE-07) and the evidence inspector."""
import json
import sqlite3
from datetime import date

import pytest

from medusa.analysis.gate import RULES, GateInput, evaluate
from medusa.analysis.retrieval import EvidenceIndex
from medusa.analysis.segmentation import segment
from medusa.analysis.verification import verify_all, verify_claim
from medusa.core.config import PROJECT_ROOT
from medusa.schemas.domain import DateValue
from medusa.schemas.domain import EvidenceState as S

P = "SYN-0001"
EXPECTED = json.loads((PROJECT_ROOT / "data" / "demo" / "expected.json").read_text())["findings"]


@pytest.fixture(scope="module")
def world(demo_documents, demo_claims):
    passages = [p for d in demo_documents for p in segment(d.document_id, d.text)]
    return ({d.document_id: d for d in demo_documents}, {p.passage_id: p for p in passages}, EvidenceIndex(passages))


def _failed(v):
    return {c.check_id for c in v.checks if not c.passed}


# ------------------------------------------------------------------ verification
def test_every_demo_claim_verifies(demo_documents, demo_claims, world):
    docs, passages, index = world
    vs = verify_all(demo_claims, demo_documents, list(passages.values()), index)
    assert len(vs) == 51 and all(v.verified for v in vs)
    assert all(len(v.checks) == 7 for v in vs)
    assert not [v.claim_id for v in vs if _failed(v)]  # advisory V7 also met for every demo claim


def _warfarin(demo_claims):
    return next(c for c in demo_claims if c.entity == "warfarin" and c.attributes.action == "held")


def test_exit_criterion_tampered_span_fails(demo_claims, world):
    docs, passages, index = world
    c = _warfarin(demo_claims)
    tampered = c.model_copy(update={"source": c.source.model_copy(update={"evidence_text": "Warfarin continued as before."})})
    v = verify_claim(tampered, docs, passages, index)
    assert not v.verified and "V3_span_exact_match" in _failed(v)


def test_tampered_document_text_fails(demo_claims, world):
    docs, passages, index = world
    c = _warfarin(demo_claims)
    doc = docs[c.source.document_id]
    edited = doc.model_copy(update={"text": doc.text.replace("Warfarin held", "Warfarin given")})
    v = verify_claim(c, {**docs, doc.document_id: edited}, passages, index)
    assert not v.verified and _failed(v) == {"V3_span_exact_match"}  # the drug name itself is untouched


def test_shifted_entity_offsets_fail(demo_claims, world):
    docs, passages, index = world
    c = _warfarin(demo_claims)
    shifted = c.model_copy(update={"source": c.source.model_copy(update={"entity_char_start": c.source.entity_char_start + 1,
                                                                          "entity_char_end": c.source.entity_char_end + 1})})
    assert "V5_entity_grounded" in _failed(verify_claim(shifted, docs, passages, index))


def test_offsets_outside_passage_fail(demo_claims, world):
    docs, passages, index = world
    c = _warfarin(demo_claims)
    out = c.model_copy(update={"source": c.source.model_copy(update={"entity_char_end": c.source.char_end + 5})})
    assert "V4_span_within_passage" in _failed(verify_claim(out, docs, passages, index))


def test_unknown_passage_or_document_or_other_patient_fails(demo_claims, world):
    docs, passages, index = world
    c = _warfarin(demo_claims)
    assert "V2_passage_exists" in _failed(verify_claim(
        c.model_copy(update={"source": c.source.model_copy(update={"passage_id": "DOC-X:P999"})}), docs, passages, index))
    assert "V1_source_document_exists" in _failed(verify_claim(c, {}, passages, index))
    other = c.model_copy(update={"patient_id": "SYN-9999"})
    assert "V1_source_document_exists" in _failed(verify_claim(other, docs, passages, index))


@pytest.mark.parametrize("event, ok", [
    (DateValue(value=date(2026, 3, 13), precision="day", basis="explicit"), False),
    (DateValue(value=date(2026, 3, 12), precision="day", basis="explicit"), True),
    (DateValue(value=date(2026, 3, 1), precision="month", basis="explicit"), True),
    (DateValue(value=date(2027, 1, 1), precision="year", basis="explicit"), False),
    (DateValue(), True),
])
def test_event_date_not_after_document_date(demo_claims, world, event, ok):
    docs, passages, index = world
    c = _warfarin(demo_claims).model_copy(update={"event_date": event})  # document dated 2026-03-12
    assert ("V6_event_not_after_document" not in _failed(verify_claim(c, docs, passages, index))) is ok


def test_retrievability_is_advisory_only(demo_claims, world):
    docs, passages, _ = world
    c = _warfarin(demo_claims)
    empty = EvidenceIndex([])
    v = verify_claim(c, docs, passages, empty)
    assert _failed(v) == {"V7_retrievable"} and v.verified


# ------------------------------------------------------------------ gate
def g(**kw):
    base = dict(verified_claims=2, conflicts=[], gaps=[], integrity=[], unextracted=False, high_risk=False, risk_reason=None)
    return GateInput(**(base | kw))


@pytest.mark.parametrize("inp, state, rule", [
    (g(verified_claims=0), S.INSUFFICIENT, "GATE-01"),
    (g(verified_claims=0, high_risk=True), S.REVIEW, "GATE-01"),
    (g(unextracted=True, integrity=["possible_unextracted_evidence"]), S.REVIEW, "GATE-02"),
    (g(conflicts=["allergy_conflict"], high_risk=True), S.REVIEW, "GATE-03"),
    (g(conflicts=["medication_dose_discrepancy"]), S.CONFLICTING, "GATE-04"),
    (g(conflicts=["diagnosis_status_conflict"], gaps=["missing_referenced_record"]), S.CONFLICTING, "GATE-04"),
    (g(gaps=["unexplained_discharge_omission"], high_risk=True), S.REVIEW, "GATE-05"),
    (g(integrity=["unverified_claim"], high_risk=True), S.REVIEW, "GATE-05"),
    (g(gaps=["missing_referenced_record"]), S.INSUFFICIENT, "GATE-06"),
    (g(integrity=["unverified_claim"]), S.INSUFFICIENT, "GATE-06"),
    (g(), S.SUPPORTED, "GATE-07"),
])
def test_gate_rules(inp, state, rule):
    s, r, rationale = evaluate(inp)
    assert (s, r) == (state, rule) and rationale


def test_gate_rule_ids_are_ordered_and_unique():
    ids = [r.rule_id for r in RULES]
    assert ids == sorted(ids) and len(ids) == len(set(ids)) == 7


def test_gate_never_supports_an_item_with_any_issue():
    for conflicts in ([], ["allergy_conflict"]):
        for gaps in ([], ["missing_referenced_record"]):
            for integrity in ([], ["unverified_claim"]):
                for hr in (False, True):
                    state, _, _ = evaluate(g(conflicts=conflicts, gaps=gaps, integrity=integrity, high_risk=hr))
                    assert (state == S.SUPPORTED) == (not conflicts and not gaps and not integrity)


def test_gate_rationales_never_pick_a_side():
    for inp in (g(conflicts=["allergy_conflict"], high_risk=True), g(conflicts=["medication_dose_discrepancy"])):
        text = evaluate(inp)[2].lower()
        assert "does not choose" in text or "neither is selected" in text


# ------------------------------------------------------------------ pipeline and API
@pytest.fixture()
def analysed(client):
    client.post(f"/api/patients/{P}/demo/load")
    client.post(f"/api/patients/{P}/analysis")
    return client


def test_all_17_findings_get_the_ground_truth_state(analysed):
    got = {f["finding_id"]: (f["state"], f["gate_rule"]) for f in analysed.get(f"/api/patients/{P}/reconciliation").json()["findings"]}
    assert {k: v[0] for k, v in got.items()} == {k: v["state"] for k, v in EXPECTED.items()}
    assert got["FND-MED-warfarin"][1] == "GATE-03" and got["FND-MED-metformin"][1] == "GATE-04"


def test_run_stats_and_claims_carry_verification(analysed):
    run = analysed.get(f"/api/patients/{P}/analysis/latest").json()["results_run"]
    assert run["stats"]["verification"] == {"verified": 51, "failed": 0, "failed_checks": {}, "advisory_not_met": {}}
    assert run["stats"]["findings"]["by_state"] == {"EVIDENCE_SUPPORTED": 10, "CONFLICTING_EVIDENCE": 2,
                                                     "INSUFFICIENT_EVIDENCE": 3, "REVIEW_REQUIRED": 2}
    claims = analysed.get(f"/api/patients/{P}/claims").json()
    assert all(c["verified"] is True and c["failed_checks"] == [] for c in claims)


def _claim(client, entity, action=None):
    return next(c for c in client.get(f"/api/patients/{P}/claims").json()
                if c["entity"] == entity and (action is None or c["attributes"].get("action") == action))


def test_evidence_inspector(analysed):
    c = _claim(analysed, "warfarin", "held")
    e = analysed.get(f"/api/patients/{P}/claims/{c['claim_id']}/evidence").json()
    assert e["evidence_text"] == "Warfarin held due to upper gastrointestinal bleed."
    assert e["context_before"].endswith("PLAN:\n") and e["context_after"].startswith("\nStarted pantoprazole")
    assert e["verification"]["verified"] and len(e["verification"]["checks"]) == 7
    assert e["verified_at_analysis"] is True and e["verification_changed"] is False
    assert e["timeline_entry"]["when"] == "2026-03-12"
    assert e["document"]["document_type"] == "Progress Note"
    assert [(f["finding_id"], f["state"], f["role"]) for f in e["related_findings"]] == \
        [("FND-MED-warfarin", "REVIEW_REQUIRED", "cited by an issue")]


def test_evidence_inspector_detects_tampering_after_analysis(analysed, settings):
    c = _claim(analysed, "warfarin", "held")
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("UPDATE documents SET extracted_text = replace(extracted_text, 'Warfarin held', 'Warfarin given')"
                     " WHERE document_id = ?", (c["source"]["document_id"],))
    e = analysed.get(f"/api/patients/{P}/claims/{c['claim_id']}/evidence").json()
    assert e["verification"]["verified"] is False and e["verified_at_analysis"] is True and e["verification_changed"]
    assert {k["check_id"] for k in e["verification"]["checks"] if not k["passed"]} >= {"V3_span_exact_match"}
    assert e["timeline_entry"] is None


def test_failed_verification_excludes_claim_and_changes_the_state(analysed, settings, monkeypatch):
    """Rerun with one claim's stored text tampered between extraction and verification."""
    from medusa.analysis import pipeline
    real = pipeline.verify_all

    def tamper(claims, docs, passages, index):
        target = next(c for c in claims if c.entity == "atorvastatin")
        claims = [c.model_copy(update={"source": c.source.model_copy(update={"evidence_text": "edited"})})
                  if c.claim_id == target.claim_id else c for c in claims]
        return real(claims, docs, passages, index)

    monkeypatch.setattr(pipeline, "verify_all", tamper)
    run = analysed.post(f"/api/patients/{P}/analysis").json()
    assert run["stats"]["verification"]["failed"] == 1
    assert run["stats"]["verification"]["failed_checks"] == {"V3_span_exact_match": 1}
    f = analysed.get(f"/api/patients/{P}/reconciliation/FND-MED-atorvastatin").json()
    assert f["state"] == "INSUFFICIENT_EVIDENCE" and "unverified_claim" in f["issue_types"]
    bad = [c for c in analysed.get(f"/api/patients/{P}/claims").json() if c["verified"] is False]
    assert len(bad) == 1 and bad[0]["entity"] == "atorvastatin" and bad[0]["failed_checks"] == ["V3_span_exact_match"]
    t = analysed.get(f"/api/patients/{P}/timeline").json()
    assert t["total"] == 50 and t["excluded_unverified"] == 1


def test_evidence_inspector_errors(analysed):
    assert analysed.get(f"/api/patients/{P}/claims/CLM-000000000000/evidence").status_code == 404
    assert analysed.get(f"/api/patients/{P}/claims/nope/evidence").status_code == 422
    c = _claim(analysed, "warfarin", "held")
    assert analysed.get(f"/api/patients/OTHER/claims/{c['claim_id']}/evidence").status_code == 404
