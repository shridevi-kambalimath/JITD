"""Overview counts, review queue and the evidence-linked summary."""
import re

import pytest

P = "SYN-0001"


def test_overview_before_anything(client):
    o = client.get(f"/api/patients/{P}/overview").json()
    assert o["documents"] == {"total": 0, "processed": 0, "failed": 0, "in_progress": 0}
    assert o["claims"]["total"] == 0 and o["timeline"]["entries"] == 0 and o["reconciliation"]["subjects"] == 0
    assert o["analysis"]["results_run"] is None and o["llm"]["status"] == "disabled"


@pytest.fixture()
def analysed(client):
    client.post(f"/api/patients/{P}/demo/load")
    client.post(f"/api/patients/{P}/analysis")
    return client


def test_overview_counts_match_the_detailed_endpoints(analysed):
    o = analysed.get(f"/api/patients/{P}/overview").json()
    claims = analysed.get(f"/api/patients/{P}/claims").json()
    timeline = analysed.get(f"/api/patients/{P}/timeline").json()
    recon = analysed.get(f"/api/patients/{P}/reconciliation").json()
    assert o["documents"] == {"total": 7, "processed": 7, "failed": 0, "in_progress": 0}
    assert o["claims"] == {"total": len(claims), "rule": 51, "llm": 0, "verified": 51, "failed_verification": 0}
    assert o["timeline"] == {"entries": timeline["total"], "by_event_date": 19, "by_document_date": 32, "undated": 0,
                             "excluded_unverified": 0}
    assert o["reconciliation"] == {"subjects": 17, "needs_attention": 7, "pending_review": 7,
                                   "EVIDENCE_SUPPORTED": 10, "CONFLICTING_EVIDENCE": 2, "INSUFFICIENT_EVIDENCE": 3,
                                   "REVIEW_REQUIRED": 2}
    assert recon["counts"]["findings"] == o["reconciliation"]["subjects"]
    assert o["analysis"]["is_current"] is True


def test_overview_counts_failed_documents(analysed):
    from medusa.core.config import PROJECT_ROOT
    data = (PROJECT_ROOT / "data" / "samples" / "no_header_note.txt").read_bytes()
    analysed.post(f"/api/patients/{P}/documents", files={"file": ("no_header_note.txt", data)})
    o = analysed.get(f"/api/patients/{P}/overview").json()
    assert o["documents"] == {"total": 8, "processed": 7, "failed": 1, "in_progress": 0}
    assert o["analysis"]["is_current"] is True  # a failed upload is not analysed, so results stay current


def test_review_queue_groups(analysed):
    q = analysed.get(f"/api/patients/{P}/review-queue").json()
    assert q["counts"] == {"review_required": 2, "conflicting": 2, "insufficient": 3, "unverified_claims": 0,
                           "uncertain_dates": 7, "pending_review": 7}
    assert [f["state"] for f in q["findings"]] == ["REVIEW_REQUIRED"] * 2 + ["CONFLICTING_EVIDENCE"] * 2 + \
        ["INSUFFICIENT_EVIDENCE"] * 3
    reasons = {u["entity"]: u["reason"] for u in q["uncertain_dates"]}
    assert reasons["fever"] == "approximate date" and reasons["tuberculosis"] == "year only"
    assert reasons["blood transfusion"] == "resolved from a relative expression"
    analysed.put(f"/api/patients/{P}/reviews/FND-MED-warfarin", json={"status": "reviewed"})
    assert analysed.get(f"/api/patients/{P}/review-queue").json()["counts"]["pending_review"] == 6
    o = analysed.get(f"/api/patients/{P}/overview").json()["reconciliation"]
    assert (o["pending_review"], o["needs_attention"]) == (6, 7)


def test_review_queue_lists_claims_that_failed_verification(analysed, monkeypatch):
    from medusa.analysis import pipeline
    real = pipeline.verify_all

    def tamper(claims, docs, passages, index):
        claims = [c.model_copy(update={"source": c.source.model_copy(update={"evidence_text": "edited"})})
                  if c.entity == "fever" else c for c in claims]
        return real(claims, docs, passages, index)

    monkeypatch.setattr(pipeline, "verify_all", tamper)
    analysed.post(f"/api/patients/{P}/analysis")
    q = analysed.get(f"/api/patients/{P}/review-queue").json()
    assert [c["entity"] for c in q["unverified_claims"]] == ["fever"]
    assert "fever" not in {u["entity"] for u in q["uncertain_dates"]}  # failed claims are not offered as dates


# ------------------------------------------------------------------ summary
def test_summary_before_analysis_is_empty_but_well_formed(client):
    s = client.get(f"/api/patients/{P}/summary").json()
    assert s["results_run_id"] is None and s["disclaimer"]
    assert all(not ln["citations"] for sec in s["sections"] for ln in sec["lines"])


def test_every_summary_line_cites_verified_claims(analysed):
    s = analysed.get(f"/api/patients/{P}/summary").json()
    claims = {c["claim_id"]: c for c in analysed.get(f"/api/patients/{P}/claims").json()}
    content = [ln for sec in s["sections"] for ln in sec["lines"] if ln["kind"] == "content"]
    assert len(content) > 40
    for ln in content:
        assert ln["citations"], ln["text"]
        for cit in ln["citations"]:
            c = claims[cit["claim_id"]]
            assert c["verified"] is True and c["source"]["passage_id"] == cit["passage_id"]
    assert all(ln["kind"] == "count" for sec in s["sections"] for ln in sec["lines"] if not ln["citations"])


def test_summary_sections_and_labels(analysed):
    s = analysed.get(f"/api/patients/{P}/summary").json()
    sec = {x["key"]: x for x in s["sections"]}
    assert list(sec) == ["encounter", "states", "unresolved", "diagnoses", "medications", "allergies", "procedures",
                         "labs", "symptoms", "observations", "timeline"]
    assert len(sec["unresolved"]["lines"]) == 8
    assert [ln["state"] for ln in sec["unresolved"]["lines"]][:3] == ["REVIEW_REQUIRED"] * 3
    metformin = next(ln for ln in sec["medications"]["lines"] if "Metformin" in ln["text"])
    assert metformin["text"].startswith("[Conflicting evidence] Metformin: listed active as “Glycomet”")
    atorva = next(ln for ln in sec["medications"]["lines"] if "Atorvastatin" in ln["text"])
    assert not atorva["text"].startswith("[")
    hb = sec["labs"]["lines"][0]["text"]
    assert hb == "Hemoglobin 7.9 g/dL, flagged L in the report, reference 13.0-17.0 (collected 2026-03-11, report dated 2026-03-12)."
    assert any("family history" in ln["text"].lower() for ln in sec["observations"]["lines"])
    assert "does not decide which record is correct" in sec["unresolved"]["description"]


def test_summary_never_judges_or_recommends(analysed):
    md = analysed.get(f"/api/patients/{P}/summary.md").text.lower()
    for word in ("incorrect", "wrong", "should", "recommend", "diagnose with", "prescribe "):
        assert word not in md.replace("does not diagnose, recommend treatment, prescribe", ""), word


def test_summary_markdown_download(analysed):
    r = analysed.get(f"/api/patients/{P}/summary.md")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert r.headers["content-disposition"] == f'attachment; filename="medusa-x-summary-{P}.md"'
    text = r.text
    assert text.startswith(f"# Evidence-linked reconstruction: {P}") and "> Synthetic demonstration data." in text
    assert "- [Review required] Warfarin documented as held" in text
    assert re.search(r"\[Laboratory Report, RESULTS, P\d{3}\]", text)


def test_summary_excludes_claims_that_failed_verification(analysed, monkeypatch):
    from medusa.analysis import pipeline
    real = pipeline.verify_all

    def tamper(claims, docs, passages, index):
        claims = [c.model_copy(update={"source": c.source.model_copy(update={"evidence_text": "edited"})})
                  if c.entity == "hemoglobin" else c for c in claims]
        return real(claims, docs, passages, index)

    monkeypatch.setattr(pipeline, "verify_all", tamper)
    analysed.post(f"/api/patients/{P}/analysis")
    s = analysed.get(f"/api/patients/{P}/summary").json()
    labs = next(x for x in s["sections"] if x["key"] == "labs")["lines"]
    assert len(labs) == 3 and not any("Hemoglobin" in ln["text"] for ln in labs)


def test_summary_marks_stale_results(analysed):
    from medusa.core.config import PROJECT_ROOT
    pdf = (PROJECT_ROOT / "data" / "samples" / "endoscopy_report.pdf").read_bytes()
    analysed.post(f"/api/patients/{P}/documents", files={"file": ("endoscopy_report.pdf", pdf)})
    s = analysed.get(f"/api/patients/{P}/summary").json()
    assert s["is_current"] is False and s["stale_reason"]
    assert "**Out of date:**" in analysed.get(f"/api/patients/{P}/summary.md").text
