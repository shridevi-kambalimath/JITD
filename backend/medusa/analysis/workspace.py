"""Workspace-level views: the Overview counts, the review queue and the evidence summary.

Everything is computed from stored documents, claims, verifications and findings on each request, so the
screens never show a number the backend did not just derive.
"""
from __future__ import annotations

from collections import Counter

from ..core.config import Settings
from ..db import analysis as repo
from ..db import documents as doc_repo
from ..db.connection import transaction
from ..schemas.analysis import ClaimRecord
from ..schemas.domain import EvidenceState
from ..schemas.summary import EvidenceSummary
from ..schemas.workspace import OverviewResponse, ReviewQueue, UncertainDate
from .pipeline import AnalysisService
from .review import ReviewService
from .summary import build_summary


def date_uncertainty(c: ClaimRecord) -> str | None:
    ev = c.event_date
    if ev.value is None:
        return "a date is written but could not be resolved to a calendar date" if ev.raw_text else None
    if ev.approximate:
        return "approximate date"
    if ev.precision in ("year", "month"):
        return f"{ev.precision} only"
    if ev.basis == "relative":
        return "resolved from a relative expression"
    return None


class WorkspaceService:
    def __init__(self, settings: Settings, analysis: AnalysisService, reviews: ReviewService):
        self.db = settings.db_path
        self.analysis = analysis
        self.reviews = reviews

    def overview(self, patient_id: str) -> OverviewResponse:
        with transaction(self.db) as conn:
            docs = doc_repo.list_documents(conn, patient_id, None)
        status = Counter(d.status.value for d in docs)
        claims = self.analysis.claims(patient_id) if self.analysis.status(patient_id).results_run else []
        timeline = self.analysis.timeline(patient_id)
        recon = self.reviews.reconciliation(patient_id)
        return OverviewResponse(
            patient_id=patient_id,
            documents={"total": len(docs), "processed": status["processed"], "failed": status["failed"],
                       "in_progress": status["uploaded"] + status["processing"]},
            analysis=self.analysis.status(patient_id),
            claims={"total": len(claims), "rule": sum(c.extraction_method.startswith("rule:") for c in claims),
                    "llm": sum(c.extraction_method.startswith("llm:") for c in claims),
                    "verified": sum(c.verified is True for c in claims),
                    "failed_verification": sum(c.verified is False for c in claims)},
            timeline={"entries": timeline.total, "by_event_date": timeline.by_basis.get("event_date", 0),
                      "by_document_date": timeline.by_basis.get("document_date", 0),
                      "undated": timeline.by_basis.get("undated", 0),
                      "excluded_unverified": timeline.excluded_unverified},
            reconciliation={"subjects": recon.counts["findings"], "needs_attention": recon.counts["with_issues"],
                            "pending_review": recon.counts["pending_review"],
                            **{s.value: recon.counts.get(s.value, 0) for s in EvidenceState}},
            llm=self.analysis.llm_config())

    def review_queue(self, patient_id: str) -> ReviewQueue:
        recon = self.reviews.reconciliation(patient_id, only_issues=True)
        claims = self.analysis.claims(patient_id)
        unverified = [c for c in claims if c.verified is False]
        uncertain = []
        for c in claims:
            if c.verified is False or (reason := date_uncertainty(c)) is None:
                continue
            uncertain.append(UncertainDate(claim_id=c.claim_id, category=c.claim_type, entity=c.entity, surface=c.surface,
                                           document_id=c.source.document_id, document_type=c.document_type,
                                           document_date=c.document_date.isoformat() if c.document_date else None,
                                           event_date=c.event_date, reason=reason))
        by_state = Counter(f.state for f in recon.findings)
        return ReviewQueue(
            patient_id=patient_id, results_run_id=recon.results_run_id, is_current=recon.is_current,
            stale_reason=recon.stale_reason,
            counts={"review_required": by_state[EvidenceState.REVIEW], "conflicting": by_state[EvidenceState.CONFLICTING],
                    "insufficient": by_state[EvidenceState.INSUFFICIENT], "unverified_claims": len(unverified),
                    "uncertain_dates": len(uncertain), "pending_review": recon.counts["pending_review"]},
            findings=recon.findings, unverified_claims=unverified, uncertain_dates=uncertain)

    def summary(self, patient_id: str) -> EvidenceSummary:
        status = self.analysis.status(patient_id)
        with transaction(self.db) as conn:
            findings = [f for f, _ in repo.list_findings(conn, patient_id)]
        return build_summary(status, self.analysis.claims(patient_id), findings)
