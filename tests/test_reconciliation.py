"""Reconciliation rules against the synthetic ground truth, review status and the API."""
import hashlib
import json

import pytest

from medusa.analysis.reconciliation import reconcile
from medusa.analysis.retrieval import EvidenceIndex
from medusa.analysis.review import priority
from medusa.analysis.rule_extractor import build_context, extract_claims
from medusa.analysis.segmentation import segment
from medusa.core.config import PROJECT_ROOT
from medusa.ingestion.metadata import parse_header
from medusa.ingestion.text_extraction import normalize_text
from medusa.schemas.domain import Document, Finding, Issue, LlmAttrs

P = "SYN-0001"
EXPECTED = json.loads((PROJECT_ROOT / "data" / "demo" / "expected.json").read_text())["findings"]
CONFLICTS = {"medication_status_conflict", "medication_dose_discrepancy", "diagnosis_status_conflict", "allergy_conflict"}
JUDGEMENT_WORDS = ("incorrect", "wrong", "error", "mistake", "false")


def _doc(text: str, name: str) -> Document:
    text = normalize_text(text)
    h = parse_header(text, P)
    return Document(document_id="DOC-" + hashlib.sha256(text.encode()).hexdigest()[:16].upper(), patient_id=P,
                    document_type=h.document_type, document_date=h.document_date, metadata=h.fields, text=text,
                    filename=name, sha256="x")


def run(docs: list[Document], verified_ids=None) -> dict[str, Finding]:
    ctx = build_context(docs)
    passages = {d.document_id: segment(d.document_id, d.text) for d in docs}
    claims = [c for d in docs for c in extract_claims(d, passages[d.document_id], ctx).claims]
    idx = EvidenceIndex([p for ps in passages.values() for p in ps])
    return {f.finding_id: f for f in reconcile(claims, idx, verified_ids)}


def extra_note(body: str) -> Document:
    return _doc(f"DOCUMENT TYPE: Progress Note\nDOCUMENT ID: DOC-X\nPATIENT ID: {P}\nDOCUMENT DATE: 2026-03-13\n---\n"
                f"PLAN:\n{body}\n", "extra.txt")


@pytest.fixture(scope="module")
def findings(demo_documents):
    return run(demo_documents)


# ------------------------------------------------------------------ ground truth
@pytest.mark.parametrize("finding_id", sorted(EXPECTED))
def test_matches_ground_truth(findings, finding_id):
    assert sorted({i.issue_type for i in findings[finding_id].issues}) == sorted(EXPECTED[finding_id]["issues"])


def test_no_unexpected_findings(findings):
    assert set(findings) == set(EXPECTED)


def test_exit_criterion_planted_issues_detected(findings):
    assert "medication_status_conflict" in {i.issue_type for i in findings["FND-MED-warfarin"].issues}
    assert findings["FND-MED-metformin"].issues[0].issue_type == "medication_dose_discrepancy"
    assert findings["FND-ALG-drug-allergies"].issues[0].issue_type == "allergy_conflict"
    assert findings["FND-DX-chronic-kidney-disease"].issues[0].issue_type == "diagnosis_status_conflict"
    missing = [f for f in findings.values() if any(i.issue_type == "missing_referenced_record" for i in f.issues)]
    assert sorted(f.subject for f in missing) == ["endoscopy report", "histopathology report"]


def test_decoys_raise_no_conflicts(findings):
    decoys = [fid for fid, spec in EXPECTED.items() if "decoy" in spec]
    assert len(decoys) == 7
    for fid in decoys:
        assert not [i for i in findings[fid].issues if i.issue_type in CONFLICTS], fid


def test_non_flagged_patterns_are_explained(findings):
    assert findings["FND-DX-pneumonia"].observations[0].rule_id == "DX-EVOL-01"
    assert findings["FND-MED-pantoprazole"].observations[0].rule_id == "MED-CHANGE-01"
    assert findings["FND-FH-breast-cancer"].observations[0].rule_id == "DX-FAMILY-01"


def test_conflicts_cite_both_sides(findings):
    w = next(i for i in findings["FND-MED-warfarin"].issues if i.issue_type == "medication_status_conflict")
    assert len(w.claim_ids) == 2
    m = findings["FND-MED-metformin"].issues[0]
    assert len(m.claim_ids) == 3 and "Imported Medication List" in m.description


def test_wording_never_judges_a_record(findings):
    for f in findings.values():
        for text in [i.description for i in f.issues] + [o.text for o in f.observations]:
            assert not any(w in text.lower() for w in JUDGEMENT_WORDS), text


def test_high_risk_configuration(findings):
    assert findings["FND-MED-warfarin"].high_risk and "anticoagulant" in findings["FND-MED-warfarin"].risk_reason
    assert findings["FND-ALG-drug-allergies"].high_risk
    assert not findings["FND-MED-metformin"].high_risk


def test_investigation_runs_for_medication_issues(findings):
    steps = findings["FND-MED-warfarin"].investigation
    assert steps and {s.rule_id for s in steps} == {"INV-01"} and all(s.scope == "section" for s in steps)
    assert all("No uncaptured" in s.outcome for s in steps)


# ------------------------------------------------------------------ rules respond to the records
def test_documented_restart_resolves_status_conflict(demo_documents):
    f = run(list(demo_documents) + [extra_note("Warfarin restarted on 2026-03-13.")])["FND-MED-warfarin"]
    assert "medication_status_conflict" not in {i.issue_type for i in f.issues}


def test_anaphoric_restart_is_escalated_not_used_to_resolve(demo_documents):
    f = run(list(demo_documents) + [extra_note("Anticoagulation plan reviewed for warfarin. It was resumed today.")])[
        "FND-MED-warfarin"]
    types = {i.issue_type for i in f.issues}
    assert {"possible_unextracted_evidence", "medication_status_conflict"} <= types
    assert priority(f) == 1


def test_documented_dose_change_is_observation_not_discrepancy(demo_documents):
    f = run(list(demo_documents) + [extra_note("Metformin dose increased to 1000 mg twice daily.")])["FND-MED-metformin"]
    assert not f.issues and any(o.rule_id == "MED-CHANGE-01" for o in f.observations)


def test_unverified_claims_are_excluded_and_reported(demo_documents, demo_claims):
    target = next(c for c in demo_claims if c.entity == "atorvastatin")
    f = run(demo_documents, {c.claim_id for c in demo_claims} - {target.claim_id})["FND-MED-atorvastatin"]
    assert [i.issue_type for i in f.issues] == ["unverified_claim"] and f.issues[0].claim_ids == [target.claim_id]


def test_llm_claims_are_not_reconciled(demo_documents, demo_claims):
    base = {k: v.issues for k, v in run(demo_documents).items()}
    med = next(c for c in demo_claims if c.claim_type == "medication")
    fake = med.model_copy(update={"claim_id": "CLM-LLMLLMLLMLLM", "attributes": LlmAttrs(statement="x"),
                                  "extraction_method": "llm:fake/m"})
    out = reconcile(demo_claims + [fake], None)
    assert {f.finding_id: f.issues for f in out}.keys() == base.keys()
    assert all(fake.claim_id not in f.claim_ids for f in out)


@pytest.mark.parametrize("issues, high_risk, expected", [
    ([], False, None),
    ([("missing_referenced_record", "gap")], False, 3),
    ([("diagnosis_status_conflict", "conflict")], False, 2),
    ([("missing_referenced_record", "gap")], True, 1),
    ([("possible_unextracted_evidence", "integrity")], False, 1),
])
def test_priority_without_state(issues, high_risk, expected):
    f = Finding(finding_id="FND-X-y", patient_id=P, category="medication", subject="y", claim_ids=[], high_risk=high_risk,
                issues=[Issue(issue_type=t, kind=k, rule_id="R", description="d") for t, k in issues])
    assert priority(f) == expected


# ------------------------------------------------------------------ API
URL = f"/api/patients/{P}/reconciliation"


@pytest.fixture()
def analysed(client):
    client.post(f"/api/patients/{P}/demo/load")
    client.post(f"/api/patients/{P}/analysis")
    return client


def test_empty_before_analysis(client):
    r = client.get(URL).json()
    assert r["results_run_id"] is None and r["findings"] == [] and r["counts"]["findings"] == 0


def test_reconciliation_list(analysed):
    r = analysed.get(URL).json()
    assert r["is_current"] and r["counts"] == {"findings": 17, "with_issues": 7, "conflict": 4, "gap": 4,
                                               "integrity": 0, "pending_review": 7, "EVIDENCE_SUPPORTED": 10,
                                               "CONFLICTING_EVIDENCE": 2, "INSUFFICIENT_EVIDENCE": 3,
                                               "REVIEW_REQUIRED": 2}
    prios = [f["priority"] for f in r["findings"]]
    assert prios[:7] == [1, 1, 2, 2, 3, 3, 3] and prios[7:] == [None] * 10
    assert r["findings"][0]["finding_id"] == "FND-MED-warfarin"
    only = analysed.get(URL, params={"only_issues": True}).json()["findings"]
    assert len(only) == 7
    dx = analysed.get(URL, params={"category": "diagnosis"}).json()["findings"]
    assert dx and {f["category"] for f in dx} == {"diagnosis"}
    assert analysed.get(URL, params={"category": "lab_result"}).status_code == 422
    assert [f["finding_id"] for f in analysed.get(f"/api/patients/{P}/review-queue").json()["findings"]] == \
        [f["finding_id"] for f in only]


def test_finding_detail_has_both_sides_with_passages(analysed):
    d = analysed.get(f"{URL}/FND-MED-warfarin").json()
    assert [c["document_type"] for c in d["claims"]] == ["Admission Note", "Progress Note", "Imported Medication List",
                                                         "Clinic Follow-up Note"]  # the later restart is shown too
    status = next(i for i in d["issues"] if i["rule_id"] == "MED-STATUS-01")
    by_id = {c["claim_id"]: c for c in d["claims"]}
    sides = [by_id[cid]["source"]["evidence_text"] for cid in status["claim_ids"]]
    assert sides == ["Warfarin held due to upper gastrointestinal bleed.", "Warfarin 5 mg orally once daily - Active."]
    assert d["investigation"] and d["missing_claim_ids"] == [] and d["is_current"]
    assert analysed.get(f"{URL}/FND-MED-nothing").status_code == 404
    assert analysed.get(f"{URL}/not-a-finding").status_code == 422


def test_review_status_is_recorded_kept_across_reruns_and_never_changes_the_finding(analysed):
    before = analysed.get(f"{URL}/FND-MED-warfarin").json()
    r = analysed.put(f"/api/patients/{P}/reviews/FND-MED-warfarin", json={"status": "reviewed", "note": "  seen  "})
    assert r.status_code == 200 and r.json()["status"] == "reviewed" and r.json()["note"] == "seen"
    analysed.post(f"/api/patients/{P}/analysis")
    after = analysed.get(f"{URL}/FND-MED-warfarin").json()
    assert after["review"]["status"] == "reviewed" and after["review"]["changed_since_review"] is False
    assert after["issues"] == before["issues"] and after["priority"] == before["priority"]
    assert analysed.get(URL).json()["counts"]["pending_review"] == 6


def test_review_is_marked_changed_when_the_finding_changes(analysed):
    analysed.put(f"/api/patients/{P}/reviews/FND-MED-warfarin", json={"status": "flagged"})
    note = (f"DOCUMENT TYPE: Progress Note\nDOCUMENT ID: DOC-X\nPATIENT ID: {P}\nDOCUMENT DATE: 2026-03-13\n---\n"
            "PLAN:\nWarfarin restarted on 2026-03-13.\n").encode()
    analysed.post(f"/api/patients/{P}/documents", files={"file": ("restart.txt", note)})
    analysed.post(f"/api/patients/{P}/analysis")
    w = analysed.get(f"{URL}/FND-MED-warfarin").json()
    assert "medication_status_conflict" not in w["issue_types"]
    assert w["review"]["status"] == "flagged" and w["review"]["changed_since_review"] is True
    assert analysed.get(URL).json()["counts"]["pending_review"] == 7  # changed items need another look


def test_uploading_the_referenced_report_resolves_the_missing_record(analysed):
    pdf = (PROJECT_ROOT / "data" / "samples" / "endoscopy_report.pdf").read_bytes()
    analysed.post(f"/api/patients/{P}/documents", files={"file": ("endoscopy_report.pdf", pdf)})
    assert analysed.get(URL).json()["is_current"] is False
    analysed.post(f"/api/patients/{P}/analysis")
    ref = analysed.get(f"{URL}/FND-REF-endoscopy-report").json()
    assert ref["issue_types"] == [] and ref["observation_rules"] == ["REF-01"]


@pytest.mark.parametrize("body, status", [({"status": "approved"}, 422), ({"status": "reviewed", "note": "x" * 2001}, 422),
                                          ({}, 422)])
def test_review_validation(analysed, body, status):
    assert analysed.put(f"/api/patients/{P}/reviews/FND-MED-warfarin", json=body).status_code == status


def test_review_unknown_finding_is_404(analysed):
    assert analysed.put(f"/api/patients/{P}/reviews/FND-MED-nothing", json={"status": "reviewed"}).status_code == 404


def test_demo_reset_clears_findings_and_reviews(analysed, settings):
    import sqlite3
    analysed.put(f"/api/patients/{P}/reviews/FND-MED-warfarin", json={"status": "reviewed"})
    analysed.post(f"/api/patients/{P}/demo/reset")
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 0
    assert analysed.get(URL).json()["findings"] == []


def test_priority_follows_the_gate_state():
    from medusa.schemas.domain import EvidenceState
    # GATE-01 on a high-risk subject: no verified claims and no issues, still Review required
    f = Finding(finding_id="FND-X-y", patient_id=P, category="medication", subject="y", claim_ids=["CLM-1"], high_risk=True,
                state=EvidenceState.REVIEW, gate_rule="GATE-01")
    assert priority(f) == 1
    assert priority(f.model_copy(update={"state": EvidenceState.SUPPORTED})) is None
    assert priority(f.model_copy(update={"state": EvidenceState.INSUFFICIENT})) == 3
