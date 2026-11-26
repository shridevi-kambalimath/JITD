"""Analysis pipeline and API, run through the real app with a temporary database.

LLM behaviour is exercised with in-process fake providers injected through AnalysisService's
provider_factory, so these tests never reach the network."""
import json
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from medusa.analysis.llm.provider import LLMError
from medusa.analysis.pipeline import AnalysisService
from medusa.core.config import PROJECT_ROOT
from medusa.db import analysis as repo
from medusa.db.connection import transaction
from medusa.main import create_app

P = "SYN-0001"
RUN = f"/api/patients/{P}/analysis"
LATEST = f"/api/patients/{P}/analysis/latest"
CLAIMS = f"/api/patients/{P}/claims"
SAMPLES = PROJECT_ROOT / "data" / "samples"
PASSAGE_LINE = re.compile(r"^\[(?P<pid>[^\]]+)\] \((?P<section>[^)]*)\) (?P<text>.*)$", re.M)


class FakeProvider:
    """Answers like a model would: finds passages in the prompt and proposes claims for them."""

    name = "fake/model-1"

    def __init__(self, fail_for=(), error_code="unavailable"):
        self.fail_for, self.error_code, self.calls = fail_for, error_code, 0

    def complete_json(self, system, user):
        self.calls += 1
        doc_type = user.splitlines()[0].removeprefix("Document type: ")
        if doc_type in self.fail_for or "*" in self.fail_for:
            raise LLMError(self.error_code, "simulated failure")
        claims = []
        for m in PASSAGE_LINE.finditer(user):
            if "focal consolidation" in m["text"]:
                claims.append({"passage_id": m["pid"], "category": "diagnosis", "entity": "consolidation",
                               "quote": "focal consolidation", "assertion": "present"})
                claims.append({"passage_id": m["pid"], "category": "diagnosis", "entity": "effusion",
                               "quote": "small pleural effusion"})  # not in the text: must be rejected
        return json.dumps({"claims": claims})


def use_provider(app, provider, **settings_update):
    s = app.state.settings.model_copy(update={"llm_provider": "openai_compatible", "llm_model": "model-1",
                                              **settings_update})
    app.state.analysis = AnalysisService(s, provider_factory=lambda _: provider)
    return app.state.analysis


@pytest.fixture()
def loaded(client):
    assert client.post(f"/api/patients/{P}/demo/load").status_code == 200
    return client


def claim_rows(settings):
    with sqlite3.connect(settings.db_path) as conn:
        return conn.execute("SELECT run_id, extraction_method FROM claims").fetchall()


# ------------------------------------------------------------------ rules only
def test_no_processed_documents_is_422(client):
    r = client.post(RUN)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unprocessable"
    assert client.get(LATEST).json() == {"patient_id": P, "latest_run": None, "results_run": None,
                                         "is_current": False, "stale_reason": None}


def test_rules_only_run(loaded, settings):
    r = loaded.post(RUN)
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "completed" and run["extractor"] == "rules" and run["llm_status"] == "disabled"
    assert re.fullmatch(r"RUN-[0-9A-F]{12}", run["run_id"])
    s = run["stats"]
    assert s["documents_analyzed"] == 7 and s["claims_total"] == 51 and s["claims_by_method"] == {"rule": 51, "llm": 0}
    assert s["claims_by_category"]["diagnosis"] == 18 and s["documents_skipped"] == [] and s["llm"] == {}
    claims = loaded.get(CLAIMS).json()
    assert len(claims) == 51 and all(c["extraction_method"].startswith("rule:") for c in claims)
    assert {c["patient_id"] for c in claims} == {P}
    status = loaded.get(LATEST).json()
    assert status["is_current"] and status["results_run"]["run_id"] == run["run_id"] == status["latest_run"]["run_id"]


def test_claim_provenance_points_at_the_stored_text(loaded):
    loaded.post(RUN)
    for c in loaded.get(CLAIMS).json():
        doc = loaded.get(f"/api/documents/{c['source']['document_id']}").json()
        src = c["source"]
        assert doc["extracted_text"][src["char_start"]:src["char_end"]] == src["evidence_text"]
        assert src["char_start"] <= src["entity_char_start"] < src["entity_char_end"] <= src["char_end"]


def test_claim_filters(loaded):
    loaded.post(RUN)
    labs = loaded.get(CLAIMS, params={"category": "lab_result"}).json()
    assert len(labs) == 4 and {c["claim_type"] for c in labs} == {"lab_result"}
    doc_id = labs[0]["source"]["document_id"]
    in_doc = loaded.get(CLAIMS, params={"document_id": doc_id}).json()
    assert in_doc and {c["source"]["document_id"] for c in in_doc} == {doc_id}
    assert loaded.get(CLAIMS, params={"category": "prescription"}).status_code == 422
    assert loaded.get(CLAIMS, params={"document_id": "../etc"}).status_code == 422
    assert loaded.get("/api/patients/OTHER/claims").json() == []


def test_rerun_replaces_results_atomically_and_keeps_history(loaded, settings):
    first = loaded.post(RUN).json()
    second = loaded.post(RUN).json()
    assert first["run_id"] != second["run_id"]
    rows = claim_rows(settings)
    assert len(rows) == 51 and {r[0] for r in rows} == {second["run_id"]}
    ids_1 = {c["claim_id"] for c in loaded.get(CLAIMS).json()}
    loaded.post(RUN)
    assert {c["claim_id"] for c in loaded.get(CLAIMS).json()} == ids_1  # deterministic ids across runs
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0] == 3


def test_failed_documents_are_skipped_and_listed(loaded):
    loaded.post(f"/api/patients/{P}/documents", files={"file": ("no_header_note.txt",
                                                                (SAMPLES / "no_header_note.txt").read_bytes())})
    run = loaded.post(RUN).json()
    assert run["stats"]["documents_analyzed"] == 7
    [skipped] = run["stats"]["documents_skipped"]
    assert skipped["filename"] == "no_header_note.txt" and skipped["status"] == "failed"


def test_results_become_stale_when_documents_change(loaded):
    loaded.post(RUN)
    r = loaded.post(f"/api/patients/{P}/documents", files={"file": ("endoscopy_report.pdf",
                                                                    (SAMPLES / "endoscopy_report.pdf").read_bytes())})
    assert r.json()["status"] == "processed"
    status = loaded.get(LATEST).json()
    assert status["is_current"] is False and "Run it again" in status["stale_reason"]
    run = loaded.post(RUN).json()
    assert run["stats"]["documents_analyzed"] == 8 and loaded.get(LATEST).json()["is_current"] is True


def test_fingerprint_changes_when_the_same_file_is_uploaded_again(loaded, settings):
    """Document ids are content-addressed, so delete + re-upload gives the same id; it must still count as a change."""
    with transaction(settings.db_path) as conn:
        before = repo.processed_fingerprint(conn, P)
    doc_id = loaded.get(f"/api/patients/{P}/documents").json()[0]["document_id"]
    detail = loaded.get(f"/api/documents/{doc_id}").json()
    loaded.delete(f"/api/documents/{doc_id}")
    data = (PROJECT_ROOT / "data" / "demo" / P / detail["filename"]).read_bytes()
    assert loaded.post(f"/api/patients/{P}/documents", files={"file": (detail["filename"], data)}).json()["document_id"] == doc_id
    with transaction(settings.db_path) as conn:
        assert repo.processed_fingerprint(conn, P) != before


def test_deleting_a_document_removes_its_claims_and_marks_results_stale(loaded):
    loaded.post(RUN)
    victim = loaded.get(CLAIMS, params={"category": "lab_result"}).json()[0]["source"]["document_id"]
    assert loaded.delete(f"/api/documents/{victim}").status_code == 204
    remaining = loaded.get(CLAIMS).json()
    assert remaining and victim not in {c["source"]["document_id"] for c in remaining}
    assert loaded.get(LATEST).json()["is_current"] is False


def test_demo_reset_clears_claims(loaded):
    loaded.post(RUN)
    loaded.post(f"/api/patients/{P}/demo/reset")
    assert loaded.get(CLAIMS).json() == []
    assert loaded.get(LATEST).json()["is_current"] is False


def test_concurrent_run_is_rejected(loaded, app):
    lock = app.state.analysis._lock(P)
    lock.acquire()
    try:
        r = loaded.post(RUN)
    finally:
        lock.release()
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    assert loaded.post(RUN).status_code == 200


def test_failed_run_keeps_previous_results(loaded, app, monkeypatch):
    good = loaded.post(RUN).json()

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(repo, "replace_patient_results", boom)
    with pytest.raises(RuntimeError):
        app.state.analysis.run(P)
    status = loaded.get(LATEST).json()
    assert status["latest_run"]["status"] == "failed" and "disk full" in status["latest_run"]["error"]
    assert status["results_run"]["run_id"] == good["run_id"] and status["is_current"]
    assert len(loaded.get(CLAIMS).json()) == 51


def test_interrupted_runs_are_failed_at_startup(settings, client):
    with transaction(settings.db_path) as conn:
        repo.start_run(conn, run_id="RUN-000000000001", patient_id=P, extractor="rules", llm_status="disabled",
                       fingerprint="x")
    with TestClient(create_app(settings)) as c2:
        run = c2.get("/api/analysis/runs/RUN-000000000001").json()
    assert run["status"] == "failed" and "Interrupted" in run["error"]


def test_get_run_not_found_and_bad_id(client):
    assert client.get("/api/analysis/runs/RUN-FFFFFFFFFFFF").status_code == 404
    assert client.get("/api/analysis/runs/nope").status_code == 422


# ------------------------------------------------------------------ with an LLM
def test_llm_adds_only_verified_claims_labelled_as_llm(loaded, app):
    fake = FakeProvider()
    use_provider(app, fake)
    run = loaded.post(RUN).json()
    assert fake.calls == 7
    assert run["extractor"] == "rules+llm:fake/model-1" and run["llm_status"] == "ok" and run["llm_error"] is None
    llm = run["stats"]["llm"]
    assert (llm["accepted"], llm["rejected"], llm["documents_ok"], llm["documents_failed"]) == (1, 1, 7, 0)
    assert llm["rejections"][0]["reason"] == "quote_not_in_passage"
    assert run["stats"]["claims_by_method"] == {"rule": 51, "llm": 1}
    [c] = [c for c in loaded.get(CLAIMS).json() if c["extraction_method"].startswith("llm:")]
    assert c["extraction_method"] == "llm:fake/model-1" and c["surface"] == "focal consolidation"
    assert c["attributes"]["kind"] == "llm" and c["attributes"]["assertion"] == "absent"
    assert c["attributes"]["model_assertion"] == "present"


def test_llm_failure_still_completes_with_rule_claims(loaded, app):
    use_provider(app, FakeProvider(fail_for="*", error_code="auth"))
    run = loaded.post(RUN).json()
    assert run["status"] == "completed" and run["extractor"] == "rules" and run["llm_status"] == "failed"
    assert run["llm_error"].startswith("auth:") and run["stats"]["llm"]["documents_failed"] == 7
    claims = loaded.get(CLAIMS).json()
    assert len(claims) == 51 and not any(c["extraction_method"].startswith("llm:") for c in claims)


def test_llm_partial_failure(loaded, app):
    use_provider(app, FakeProvider(fail_for=("Discharge Summary",), error_code="timeout"))
    run = loaded.post(RUN).json()
    assert run["llm_status"] == "partial" and run["extractor"] == "rules+llm:fake/model-1"
    assert run["stats"]["llm"]["errors"][0]["code"] == "timeout" and run["stats"]["llm"]["documents_ok"] == 6


def test_misconfigured_llm_is_reported_not_crashing(loaded, app):
    s = app.state.settings.model_copy(update={"llm_provider": "anthropic", "llm_model": "m", "llm_api_key": None})
    app.state.analysis = AnalysisService(s)
    run = loaded.post(RUN).json()
    assert run["status"] == "completed" and run["llm_status"] == "misconfigured" and run["extractor"] == "rules"
    cfg = loaded.get("/api/analysis/config").json()
    assert cfg["status"] == "misconfigured" and "MEDUSA_LLM_API_KEY" in cfg["reason"]


def test_config_endpoint_never_returns_the_key(client, app):
    from pydantic import SecretStr
    secret = "sk-live-DO-NOT-LEAK-42"
    s = app.state.settings.model_copy(update={"llm_provider": "anthropic", "llm_model": "claude-x",
                                              "llm_api_key": SecretStr(secret)})
    app.state.analysis = AnalysisService(s)
    r = client.get("/api/analysis/config")
    assert secret not in r.text
    assert r.json() == {"provider": "anthropic", "model": "claude-x", "status": "configured", "reason": None,
                        "api_key_set": True, "custom_base_url": False}
