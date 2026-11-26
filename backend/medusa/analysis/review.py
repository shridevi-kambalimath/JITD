"""Reconciliation views and review status.

Priority follows the evidence state set by the gate:
  1  REVIEW_REQUIRED        2  CONFLICTING_EVIDENCE        3  INSUFFICIENT_EVIDENCE
EVIDENCE_SUPPORTED findings have no priority and are not in the review queue, but stay visible with the
observations that explain why nothing was flagged. Findings stored before the gate existed (state None)
fall back to an issue-based order until the analysis is re-run.

Review status never changes a finding. If a later analysis changes a finding's issues, the stored status
is kept but marked changed_since_review, so a reviewer knows to look again.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from ..core.config import Settings
from ..core.errors import NotFoundError
from ..db import analysis as repo
from ..db.connection import transaction
from ..schemas.domain import EvidenceState, Finding
from ..schemas.reconciliation import FindingDetail, FindingSummary, ReconciliationResponse, Review, ReviewUpdate
from .pipeline import AnalysisService


STATE_PRIORITY = {EvidenceState.REVIEW: 1, EvidenceState.CONFLICTING: 2, EvidenceState.INSUFFICIENT: 3,
                  EvidenceState.SUPPORTED: None}


def priority(f: Finding) -> int | None:
    if f.state is not None:
        return STATE_PRIORITY[f.state]
    if not f.issues:
        return None
    if f.high_risk or any(i.issue_type == "possible_unextracted_evidence" for i in f.issues):
        return 1
    if any(i.kind == "conflict" for i in f.issues):
        return 2
    return 3


def _review(row, fingerprint: str) -> Review:
    if row is None:
        return Review(status="pending_review")
    return Review(status=row["status"], note=row["note"], updated_at=row["updated_at"],
                  changed_since_review=row["finding_fingerprint"] != fingerprint)


def _summary(f: Finding, fingerprint: str, review_row) -> dict:
    return dict(finding_id=f.finding_id, category=f.category, subject=f.subject, high_risk=f.high_risk,
                risk_reason=f.risk_reason, issue_types=list(dict.fromkeys(i.issue_type for i in f.issues)),
                issues_by_kind=dict(Counter(i.kind for i in f.issues)),
                observation_rules=list(dict.fromkeys(o.rule_id for o in f.observations)),
                claim_count=len(f.claim_ids), priority=priority(f), review=_review(review_row, fingerprint),
                state=f.state, gate_rule=f.gate_rule, gate_rationale=f.gate_rationale)


class ReviewService:
    def __init__(self, settings: Settings, analysis: AnalysisService):
        self.db = settings.db_path
        self.analysis = analysis

    def reconciliation(self, patient_id: str, category: str | None = None, only_issues: bool = False
                       ) -> ReconciliationResponse:
        status = self.analysis.status(patient_id)
        with transaction(self.db) as conn:
            findings = repo.list_findings(conn, patient_id)
            reviews = repo.reviews_for(conn, patient_id)
        summaries = [FindingSummary(**_summary(f, fp, reviews.get(f.finding_id))) for f, fp in findings]
        with_issues = [s for s in summaries if s.priority is not None]
        counts = {
            "findings": len(summaries), "with_issues": len(with_issues),
            "conflict": sum(s.issues_by_kind.get("conflict", 0) > 0 for s in summaries),
            "gap": sum(s.issues_by_kind.get("gap", 0) > 0 for s in summaries),
            "integrity": sum(s.issues_by_kind.get("integrity", 0) > 0 for s in summaries),
            "pending_review": sum(s.review.status == "pending_review" or s.review.changed_since_review
                                  for s in with_issues),
            **{state.value: sum(s.state == state for s in summaries) for state in EvidenceState},
        }
        shown = [s for s in summaries if (category is None or s.category == category)
                 and (not only_issues or s.priority is not None)]
        # findings with issues first by priority; the rest keep the reconciliation order
        shown.sort(key=lambda s: (s.priority is None, s.priority or 0))
        return ReconciliationResponse(patient_id=patient_id,
                                      results_run_id=status.results_run.run_id if status.results_run else None,
                                      is_current=status.is_current, stale_reason=status.stale_reason, counts=counts,
                                      findings=shown)

    def detail(self, patient_id: str, finding_id: str) -> FindingDetail:
        status = self.analysis.status(patient_id)
        with transaction(self.db) as conn:
            hit = repo.get_finding(conn, patient_id, finding_id)
            if hit is None:
                raise NotFoundError(f"Finding {finding_id} not found for {patient_id}")
            review_row = repo.reviews_for(conn, patient_id).get(finding_id)
        claims = {c.claim_id: c for c in self.analysis.claims(patient_id)}
        f, fp = hit
        cited = [claims[cid] for cid in f.claim_ids if cid in claims]
        cited.sort(key=lambda c: (c.effective_date() or date.max, c.source.document_id, c.source.char_start))
        return FindingDetail(**_summary(f, fp, review_row), issues=f.issues, observations=f.observations,
                             investigation=f.investigation, claims=cited,
                             missing_claim_ids=[cid for cid in f.claim_ids if cid not in claims],
                             results_run_id=status.results_run.run_id if status.results_run else None,
                             is_current=status.is_current)

    def set_review(self, patient_id: str, finding_id: str, update: ReviewUpdate) -> Review:
        note = (update.note or "").strip() or None
        with transaction(self.db) as conn:
            hit = repo.get_finding(conn, patient_id, finding_id)
            if hit is None:
                raise NotFoundError(f"Finding {finding_id} not found for {patient_id}")
            repo.upsert_review(conn, patient_id, finding_id, update.status, note, hit[1])
            row = repo.reviews_for(conn, patient_id)[finding_id]
        return _review(row, hit[1])
