"""Evidence search: retrieval with expansion, highlighting, and the four result scopes."""
import pytest

from medusa.analysis.retrieval import EvidenceIndex, expand_query, match_spans
from medusa.analysis.segmentation import segment

P = "SYN-0001"
URL = f"/api/patients/{P}/search"


@pytest.mark.parametrize("q, expected", [
    ("metformin", ["metformin", "glycomet", "glucophage"]),
    ("Glycomet", ["glycomet", "metformin", "glucophage"]),
    ("hb", ["hb", "hemoglobin", "haemoglobin"]),
    ("the and of", []),
])
def test_query_expansion(q, expected):
    assert expand_query(q) == expected


def test_match_spans_are_whole_tokens():
    text = "Glycomet 500 mg; metformin-like? Not metformins."
    assert [text[a:b] for a, b in match_spans(text, ["glycomet", "metformin"])] == ["Glycomet", "metformin"]


def test_index_ranks_brand_name_for_generic_query(demo_documents):
    passages = [p for d in demo_documents for p in segment(d.document_id, d.text)]
    index = EvidenceIndex(passages)
    assert any("Glycomet" in h.text for h in index.search("metformin"))
    assert all("Glycomet" not in h.text for h in index.search("metformin", expand=False))  # expansion is what finds it


def test_empty_before_analysis(client):
    r = client.get(URL, params={"q": "metformin"}).json()
    assert r["results_run_id"] is None and r["counts"] == {"passages": 0, "claims": 0, "timeline": 0, "reconciliation": 0}
    assert "Run the analysis" in r["note"]


@pytest.fixture()
def analysed(client):
    client.post(f"/api/patients/{P}/demo/load")
    client.post(f"/api/patients/{P}/analysis")
    return client


def test_exit_criterion_metformin_finds_the_glycomet_line(analysed):
    r = analysed.get(URL, params={"q": "metformin"}).json()
    assert r["expanded"] == ["glycomet", "glucophage"]
    top = r["passages"][0]
    assert top["document_type"] == "Admission Note" and top["text"] == "Glycomet 500 mg orally twice daily."
    assert [top["text"][a:b] for a, b in top["matches"]] == ["Glycomet"]
    assert [c["entity"] for c in top["claims"]] == ["metformin"]
    assert top["claims"][0]["finding"] == {"finding_id": "FND-MED-metformin", "subject": "metformin",
                                           "state": "CONFLICTING_EVIDENCE"}
    assert r["counts"] == {"passages": 3, "claims": 3, "timeline": 3, "reconciliation": 1}
    assert {c["surface"] for c in r["claims"]} == {"Glycomet", "Metformin"}
    assert [f["finding_id"] for f in r["reconciliation"]] == ["FND-MED-metformin"]


def test_lists_rank_consistently_and_point_at_stored_evidence(analysed):
    r = analysed.get(URL, params={"q": "warfarin"}).json()
    scores = [p["score"] for p in r["passages"]]
    assert scores == sorted(scores, reverse=True)
    claims = {c["claim_id"]: c for c in analysed.get(f"/api/patients/{P}/claims").json()}
    for hit in r["claims"]:
        assert claims[hit["claim_id"]]["source"]["evidence_text"] == hit["passage_text"]
    assert {t["claim_id"] for t in r["timeline"]} <= {c["claim_id"] for c in r["claims"]}
    assert r["reconciliation"][0]["state"] == "REVIEW_REQUIRED" and r["reconciliation"][0]["gate_rule"] == "GATE-03"


def test_section_names_are_searchable(analysed):
    r = analysed.get(URL, params={"q": "allergies"}).json()
    assert {p["text"] for p in r["passages"]} == {"NKDA.", "Penicillin (rash)."}
    assert all(p["section_matched"] for p in r["passages"])
    assert sorted(c["category"] for c in r["claims"]) == ["allergy", "allergy"]
    assert [f["finding_id"] for f in r["reconciliation"]] == ["FND-ALG-drug-allergies"]


def test_lab_abbreviation(analysed):
    r = analysed.get(URL, params={"q": "Hb"}).json()
    assert r["passages"][0]["document_type"] == "Laboratory Report" and r["claims"][0]["entity"] == "hemoglobin"
    assert r["timeline"][0]["when"] == "2026-03-11"


@pytest.mark.parametrize("scope", ["passages", "claims", "timeline", "reconciliation"])
def test_scope_filters_lists_but_keeps_counts(analysed, scope):
    r = analysed.get(URL, params={"q": "metformin", "scope": scope}).json()
    assert r["scope"] == scope and r["counts"]["passages"] == 3
    for other in ("passages", "claims", "timeline", "reconciliation"):
        assert (len(r[other]) > 0) == (other == scope)


def test_no_match_and_stopwords(analysed):
    assert "No passage" in analysed.get(URL, params={"q": "zebra"}).json()["note"]
    assert "no searchable words" in analysed.get(URL, params={"q": "the of"}).json()["note"]


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "x" * 201}, {"q": "warfarin", "scope": "documents"}])
def test_bad_queries(analysed, params):
    assert analysed.get(URL, params=params).status_code == 422


def test_unverified_claims_stay_out_of_timeline_hits(analysed, monkeypatch):
    from medusa.analysis import pipeline
    real = pipeline.verify_all

    def tamper(claims, docs, passages, index):
        claims = [c.model_copy(update={"source": c.source.model_copy(update={"evidence_text": "edited"})})
                  if c.entity == "metformin" and c.surface == "Glycomet" else c for c in claims]
        return real(claims, docs, passages, index)

    monkeypatch.setattr(pipeline, "verify_all", tamper)
    analysed.post(f"/api/patients/{P}/analysis")
    r = analysed.get(URL, params={"q": "glycomet"}).json()
    bad = [c for c in r["claims"] if c["surface"] == "Glycomet"]
    assert bad and bad[0]["verified"] is False
    assert all(t["claim_id"] != bad[0]["claim_id"] for t in r["timeline"])
