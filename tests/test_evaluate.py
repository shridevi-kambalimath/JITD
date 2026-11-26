"""Ground-truth evaluation (python -m medusa.evaluate) and the Phase 9 demo scenarios."""
import json
from datetime import date

import pytest

from medusa import evaluate
from medusa.analysis.dates import DateContext, extract_date
from medusa.core.config import PROJECT_ROOT

EXPECTED = PROJECT_ROOT / "data" / "demo" / "expected.json"


@pytest.fixture()
def isolated(monkeypatch, settings):
    monkeypatch.setattr(evaluate, "get_settings", lambda: settings)
    return settings


def test_exit_criterion_fresh_run_matches_the_ground_truth(isolated, capsys):
    assert evaluate.main([]) == 0
    out = capsys.readouterr().out
    assert "All expected states matched, every planted issue found, 0 false conflicts." in out
    assert "FAIL" not in out


def test_json_report_covers_every_finding_date_check_and_scenario(isolated, capsys):
    assert evaluate.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    expected = json.loads(EXPECTED.read_text())
    groups = {g: [c for c in report["checks"] if c["group"] == g] for g in ("findings", "dates", "scenarios")}
    assert report["passed"] is True
    assert len(groups["findings"]) == len(expected["findings"]) + 2  # plus "no unexpected" and "0 false conflicts"
    assert len(groups["dates"]) == len(expected["date_checks"])
    assert [c["name"] for c in groups["scenarios"]] == [s["title"] for s in expected["scenarios"]]
    assert len(expected["scenarios"]) == 9


def _break(data, how):
    if how == "state":
        data["findings"]["FND-MED-metformin"]["state"] = "EVIDENCE_SUPPORTED"
        return "[FAIL] FND-MED-metformin"
    if how == "issues":
        data["findings"]["FND-MED-warfarin"]["issues"] = ["medication_status_conflict"]
        return "[FAIL] FND-MED-warfarin"
    if how == "missing":
        del data["findings"]["FND-DX-stroke"]
        return "[FAIL] no unexpected findings"
    if how == "date":
        data["date_checks"][0]["event_date"] = "2026-03-08"
        return "[FAIL] fever"
    if how == "documents":
        data["documents"] = 6
        return "[FAIL] documents processed"
    raise AssertionError(how)


@pytest.mark.parametrize("how", ["state", "issues", "missing", "date", "documents"])
def test_a_wrong_expectation_fails(isolated, tmp_path, capsys, how):
    data = json.loads(EXPECTED.read_text())
    marker = _break(data, how)
    bad = tmp_path / "expected.json"
    bad.write_text(json.dumps(data))
    assert evaluate.main(["--expected", str(bad)]) == 1
    out = capsys.readouterr().out
    assert marker in out and "1 FAILED." in out


def test_current_mode_needs_an_analysis(isolated, client, capsys):
    assert evaluate.main(["--current"]) == 1
    assert "run the analysis first" in capsys.readouterr().out


def test_current_mode_scores_the_live_database(isolated, client, capsys):
    client.post("/api/patients/SYN-0001/demo/load")
    client.post("/api/patients/SYN-0001/analysis")
    assert evaluate.main(["--current"]) == 0
    assert "current database" in capsys.readouterr().out


# ------------------------------------------------------------------ scenario details
@pytest.mark.parametrize("text", ["Dizziness since last week.", "Pain started recently.", "Seen a few days ago."])
def test_vague_relative_dates_are_kept_but_never_resolved(text):
    d = extract_date(text, DateContext(document_date=date(2026, 3, 29), admission_date=date(2026, 3, 10)))
    assert d.value is None and d.raw_text and d.basis == "relative" and "not resolved" in d.note


def test_uploading_the_endoscopy_report_adds_its_findings(client):
    client.post("/api/patients/SYN-0001/demo/load")
    pdf = (PROJECT_ROOT / "data" / "samples" / "endoscopy_report.pdf").read_bytes()
    assert client.post("/api/patients/SYN-0001/documents", files={"file": ("endoscopy_report.pdf", pdf)}).json()["status"] == "processed"
    client.post("/api/patients/SYN-0001/analysis")
    ulcer = client.get("/api/patients/SYN-0001/reconciliation/FND-DX-gastric-ulcer").json()
    assert ulcer["state"] == "EVIDENCE_SUPPORTED" and ulcer["claim_count"] == 2
    ref = client.get("/api/patients/SYN-0001/reconciliation/FND-REF-endoscopy-report").json()
    assert ref["state"] == "EVIDENCE_SUPPORTED" and ref["issue_types"] == []
