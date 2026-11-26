"""Evidence inspector: everything needed to judge one claim against its source.

Verification is re-run on every request against the text as stored now, so a span that no longer matches
(edited database, swapped file, bad offsets) fails here immediately, even if the analysis recorded a pass.
Read-only.
"""
from __future__ import annotations

from ..core.config import Settings
from ..core.errors import NotFoundError
from ..db import analysis as repo
from ..db import documents as doc_repo
from ..db.connection import transaction
from ..schemas.domain import Document
from ..schemas.evidence import EvidenceView, RelatedFinding
from .pipeline import AnalysisService
from .retrieval import EvidenceIndex
from .timeline import to_entry
from .verification import verify_claim

CONTEXT_CHARS = 280


def context_window(text: str, start: int, end: int, chars: int = CONTEXT_CHARS) -> tuple[str, str]:
    lo = max(0, start - chars)
    if lo > 0 and "\n" in text[lo:start]:
        lo = text.index("\n", lo, start) + 1  # start on a line boundary
    hi = min(len(text), end + chars)
    if hi < len(text) and "\n" in text[end:hi]:
        hi = text.rindex("\n", end, hi)
    return text[lo:start], text[end:hi]


class EvidenceService:
    def __init__(self, settings: Settings, analysis: AnalysisService):
        self.db = settings.db_path
        self.analysis = analysis

    def view(self, patient_id: str, claim_id: str) -> EvidenceView:
        with transaction(self.db) as conn:
            claim = repo.get_claim(conn, patient_id, claim_id)
            if claim is None:
                raise NotFoundError(f"Claim {claim_id} not found for {patient_id}")
            detail = doc_repo.get_detail(conn, claim.source.document_id)
            passages = repo.list_passages(conn, patient_id)
            stored = repo.verifications_for(conn, patient_id).get(claim_id)
            findings = repo.list_findings(conn, patient_id)
        if detail is None:  # unreachable while the foreign key holds; kept for a clear error
            raise NotFoundError(f"Document {claim.source.document_id} not found")
        text = detail.extracted_text or ""
        doc = Document(document_id=detail.document_id, patient_id=detail.patient_id,
                       document_type=detail.document_type or "Unknown", document_date=detail.document_date,
                       metadata=detail.metadata, text=text, filename=detail.filename, sha256=detail.sha256)
        passage = next(p for p in passages if p.passage_id == claim.source.passage_id)
        live = verify_claim(claim, {doc.document_id: doc}, {p.passage_id: p for p in passages}, EvidenceIndex(passages))
        record = next(c for c in self.analysis.claims(patient_id, document_id=claim.source.document_id)
                      if c.claim_id == claim_id)
        before, after = context_window(text, passage.char_start, passage.char_end)
        related = []
        for f, _ in findings:
            if claim_id not in f.claim_ids:
                continue
            cited = any(claim_id in i.claim_ids for i in f.issues)
            related.append(RelatedFinding(finding_id=f.finding_id, subject=f.subject, category=f.category, state=f.state,
                                          gate_rule=f.gate_rule,
                                          role="cited by an issue" if cited else "record for this subject"))
        return EvidenceView(
            claim=record, document=detail, passage=passage, context_before=before,
            evidence_text=text[passage.char_start:passage.char_end], context_after=after, verification=live,
            verified_at_analysis=stored.verified if stored else None,
            verification_changed=stored is not None and stored.verified != live.verified,
            timeline_entry=to_entry(claim) if live.verified else None, related_findings=related)
