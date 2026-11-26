"""Evidence search across passages, claims, timeline entries and reconciliation items.

One BM25 ranking over the patient's stored passages (built in memory per request, demo scale) drives all scopes:
* passages:        the ranked passages themselves, with the matched words marked
* claims:          claims in a matching passage whose entity or quoted words contain a query term
* timeline:        those claims that passed verification, as timeline entries
* reconciliation:  findings whose subject matches a term, or that rely on a matching claim
A claim, entry or finding inherits the score of the passage it comes from, so all lists rank consistently.
Search finds where the records mention something. It does not answer clinical questions.
"""
from __future__ import annotations

from ..core.config import Settings
from ..db import analysis as repo
from ..db import documents as doc_repo
from ..db.connection import transaction
from ..schemas.search import ClaimHit, ClaimRef, FindingHit, FindingRef, PassageHit, SearchResponse, TimelineHit
from .pipeline import AnalysisService
from .retrieval import EvidenceIndex, expand_query, match_spans, tokenize
from .timeline import to_entry

MAX_PASSAGES = 25
SCOPES = ("passages", "claims", "timeline", "reconciliation")


class SearchService:
    def __init__(self, settings: Settings, analysis: AnalysisService):
        self.db = settings.db_path
        self.analysis = analysis

    def search(self, patient_id: str, query: str, scope: str = "all") -> SearchResponse:
        status = self.analysis.status(patient_id)
        terms = expand_query(query)
        typed = tokenize(query)
        base = dict(patient_id=patient_id, query=query, terms=terms, expanded=[t for t in terms if t not in typed],
                    scope=scope, results_run_id=status.results_run.run_id if status.results_run else None,
                    is_current=status.is_current)
        empty = dict(passages=[], claims=[], timeline=[], reconciliation=[], counts={s: 0 for s in SCOPES})
        if not terms:
            return SearchResponse(**base, **empty, note="The query has no searchable words (only very common words).")
        if status.results_run is None:
            return SearchResponse(**base, **empty, note="Nothing to search yet. Run the analysis first.")

        with transaction(self.db) as conn:
            passages = repo.list_passages(conn, patient_id)
            findings = [f for f, _ in repo.list_findings(conn, patient_id)]
        claims = self.analysis.claims(patient_id)
        doc_meta = self._doc_meta(patient_id)
        hits = EvidenceIndex(passages).search(query, k=MAX_PASSAGES)
        score_of = {h.passage_id: h.score for h in hits}

        finding_of_claim: dict[str, FindingRef] = {}
        for f in findings:
            for cid in f.claim_ids:
                finding_of_claim.setdefault(cid, FindingRef(finding_id=f.finding_id, subject=f.subject, state=f.state))

        def ref(c) -> dict:
            return dict(claim_id=c.claim_id, category=c.claim_type, entity=c.entity, surface=c.surface,
                        extraction_method=c.extraction_method, verified=c.verified, finding=finding_of_claim.get(c.claim_id))

        by_passage: dict[str, list] = {}
        for c in claims:
            by_passage.setdefault(c.source.passage_id, []).append(c)

        wanted = set(terms)
        passage_hits = []
        for h in hits:
            dtype, ddate = doc_meta.get(h.document_id, ("Unknown", None))
            passage_hits.append(PassageHit(
                passage_id=h.passage_id, document_id=h.document_id, document_type=dtype, document_date=ddate,
                section=h.section, text=h.text, score=h.score, matches=match_spans(h.text, terms),
                section_matched=bool(wanted & set(tokenize(h.section))),
                claims=[ClaimRef(**ref(c)) for c in by_passage.get(h.passage_id, [])]))

        section_hit = {p.passage_id for p in passage_hits if p.section_matched}
        # a claim matches when its own words match, or when the query named its section ("allergies")
        matched_claims = [c for c in claims if c.source.passage_id in score_of
                          and (wanted & set(tokenize(f"{c.entity} {c.surface}")) or c.source.passage_id in section_hit)]
        matched_claims.sort(key=lambda c: (-score_of[c.source.passage_id], c.claim_id))
        claim_hits = [ClaimHit(**ref(c), document_id=c.source.document_id, document_type=c.document_type,
                               document_date=c.document_date,
                               event_when=c.event_date.display() if c.event_date.value else None,
                               passage_text=c.source.evidence_text, score=score_of[c.source.passage_id])
                      for c in matched_claims]
        timeline_hits = [TimelineHit(**to_entry(c).model_dump(), score=score_of[c.source.passage_id])
                         for c in matched_claims if c.verified is not False]

        claim_score = {c.claim_id: score_of[c.source.passage_id] for c in matched_claims}
        best = max(score_of.values(), default=0.0)
        finding_hits = []
        for f in findings:
            s = max((claim_score[cid] for cid in f.claim_ids if cid in claim_score), default=0.0)
            if not s and wanted & set(tokenize(f.subject)):
                s = best or 1.0  # subject named directly, e.g. "histopathology"
            if s:
                finding_hits.append(FindingHit(finding_id=f.finding_id, subject=f.subject, state=f.state,
                                               category=f.category, gate_rule=f.gate_rule,
                                               issue_types=list(dict.fromkeys(i.issue_type for i in f.issues)),
                                               score=round(s, 4)))
        finding_hits.sort(key=lambda h: (-h.score, h.finding_id))

        lists = {"passages": passage_hits, "claims": claim_hits, "timeline": timeline_hits,
                 "reconciliation": finding_hits}
        counts = {k: len(v) for k, v in lists.items()}
        shown = {k: (v if scope in ("all", k) else []) for k, v in lists.items()}
        note = None if any(counts.values()) else "No passage in these records mentions the search terms."
        return SearchResponse(**base, counts=counts, note=note, **shown)

    def _doc_meta(self, patient_id: str) -> dict:
        with transaction(self.db) as conn:
            return {d.document_id: (d.document_type or "Unknown", d.document_date)
                    for d in doc_repo.list_documents(conn, patient_id, None)}
