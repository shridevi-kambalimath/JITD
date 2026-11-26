"""End-to-end journey through every API, with cross-checks that the endpoints agree with each other.

reset -> analyse -> timeline -> reconciliation -> verification -> search -> evidence -> review -> summary
"""
import re

P = "SYN-0001"
B = f"/api/patients/{P}"


def test_full_journey(client):
    # reset loads the bundle through the real upload pipeline
    reset = client.post(f"{B}/demo/reset").json()
    assert len(reset["loaded"]) == 7 and all(d["status"] == "processed" for d in reset["loaded"])

    run = client.post(f"{B}/analysis").json()
    assert run["status"] == "completed" and run["stats"]["verification"]["failed"] == 0
    overview = client.get(f"{B}/overview").json()
    claims = {c["claim_id"]: c for c in client.get(f"{B}/claims").json()}
    assert overview["claims"]["total"] == len(claims) == run["stats"]["claims_total"]

    # timeline: only verified claims, every entry backed by a stored claim from the same run
    timeline = client.get(f"{B}/timeline").json()
    assert timeline["results_run_id"] == run["run_id"] and timeline["total"] == overview["timeline"]["entries"]
    assert all(claims[e["claim_id"]]["verified"] for e in timeline["entries"])

    # reconciliation: counts agree with the overview; every cited claim exists and is verified
    recon = client.get(f"{B}/reconciliation").json()
    assert recon["counts"]["findings"] == overview["reconciliation"]["subjects"]
    for f in recon["findings"]:
        d = client.get(f"{B}/reconciliation/{f['finding_id']}").json()
        assert d["missing_claim_ids"] == [] and d["state"] == f["state"]
        for issue in d["issues"]:
            assert set(issue["claim_ids"]) <= {c["claim_id"] for c in d["claims"]}
        assert all(c["verified"] for c in d["claims"])

    # verification: the inspector re-checks every claim and agrees with the analysis
    for cid in claims:
        ev = client.get(f"{B}/claims/{cid}/evidence").json()
        assert ev["verification"]["verified"] and not ev["verification_changed"]
        assert ev["evidence_text"] == claims[cid]["source"]["evidence_text"]

    # search: every hit points at stored evidence
    for q in ("metformin", "warfarin", "allergies", "Hb", "dizziness"):
        s = client.get(f"{B}/search", params={"q": q}).json()
        assert s["counts"]["passages"] > 0, q
        for c in s["claims"]:
            assert claims[c["claim_id"]]["source"]["evidence_text"] == c["passage_text"]
        for f in s["reconciliation"]:
            assert f["finding_id"] in {x["finding_id"] for x in recon["findings"]}

    # review: status persists, never changes the state, and the counts follow
    queue = client.get(f"{B}/review-queue").json()
    first = queue["findings"][0]
    client.put(f"{B}/reviews/{first['finding_id']}", json={"status": "reviewed", "note": "checked in e2e"})
    after = client.get(f"{B}/reconciliation/{first['finding_id']}").json()
    assert after["review"]["status"] == "reviewed" and after["state"] == first["state"]
    assert client.get(f"{B}/overview").json()["reconciliation"]["pending_review"] == queue["counts"]["pending_review"] - 1

    # summary: every citation opens in the inspector; Markdown carries the same lines
    summary = client.get(f"{B}/summary").json()
    cited = {c["claim_id"] for sec in summary["sections"] for ln in sec["lines"] for c in ln["citations"]}
    assert cited and cited <= set(claims)
    md = client.get(f"{B}/summary.md").text
    lines = [ln["text"] for sec in summary["sections"] for ln in sec["lines"]]
    assert all(f"- {t}" in md for t in lines)
    assert len(re.findall(r"^- ", md, re.M)) == len(lines) + sum(1 for sec in summary["sections"] if not sec["lines"])

    # and the state of the world is unchanged by reading it
    assert client.get(f"{B}/analysis/latest").json()["is_current"] is True


def _demo_path(client, sample_pdf):
    """The 3-minute demo path (docs/DEMO.md) through the API: reset, analyse, upload the endoscopy report, re-run."""
    B = "/api/patients/SYN-0001"
    assert client.post(f"{B}/demo/reset").status_code == 200
    first = client.post(f"{B}/analysis").json()
    states = {f["subject"]: (f["state"], f["gate_rule"]) for f in client.get(f"{B}/reconciliation").json()["findings"]}
    with open(sample_pdf, "rb") as fh:
        assert client.post(f"{B}/documents", files={"file": ("endoscopy_report.pdf", fh, "application/pdf")}).status_code == 201
    second = client.post(f"{B}/analysis").json()
    after = {f["subject"]: (f["state"], f["gate_rule"]) for f in client.get(f"{B}/reconciliation").json()["findings"]}
    summary = client.get(f"{B}/summary").json()
    return {
        "first_stats": {k: first["stats"][k] for k in ("claims_total", "claims_by_category")},
        "states": states,
        "second_claims": second["stats"]["claims_total"],
        "after": after,
        "summary": [(sec["title"], [line["text"] for line in sec["lines"]]) for sec in summary["sections"]],
        "overview": {k: v for k, v in client.get(f"{B}/overview").json().items() if k in ("claims", "timeline", "discrepancies")},
    }


def test_demo_path_runs_twice_in_a_row_with_identical_results(client, settings):
    """Phase 11 exit criterion: the demo runs twice in a row without a manual fix. The reset must restore the exact
    starting state, so the second pass gives the same results as the first."""
    pdf = settings.demo_dir.parent / "samples" / "endoscopy_report.pdf"
    one = _demo_path(client, pdf)
    two = _demo_path(client, pdf)
    assert one == two
    assert one["states"]["endoscopy report"] == ("INSUFFICIENT_EVIDENCE", "GATE-06")
    assert one["after"]["endoscopy report"] == ("EVIDENCE_SUPPORTED", "GATE-07")
    assert one["after"]["gastric ulcer"][0] == "EVIDENCE_SUPPORTED" and "gastric ulcer" not in one["states"]
    assert one["states"]["warfarin"] == ("REVIEW_REQUIRED", "GATE-03")
    assert len(client.get("/api/patients/SYN-0001/documents").json()) == 8
