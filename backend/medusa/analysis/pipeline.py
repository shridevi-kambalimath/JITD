"""Analysis pipeline for one patient: segment -> rule extraction -> optional LLM extraction -> store.

Guarantees
* Only documents with status 'processed' are analysed. Others are listed in the run stats as skipped.
* Rule extraction always runs. The LLM can add claims but never remove or change rule claims.
* If the LLM is disabled, misconfigured or fails, the run still completes with rule claims, and the run
  record says so (llm_status, llm_error, extractor). LLM output is never presented as rule output, and
  rule output is never presented as LLM output.
* Results are replaced atomically: one transaction deletes the old passages/claims and inserts the new
  ones. A failed run leaves the previous results in place.
* One run per patient at a time (409 otherwise). Runs left 'running' by a crash are failed at startup.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from ..core.config import Settings
from ..core.errors import ConflictError, NotFoundError, UnprocessableError
from ..db import analysis as repo
from ..db import documents as doc_repo
from ..db.connection import transaction
from ..schemas.analysis import AnalysisRun, AnalysisStatus, ClaimRecord, LlmConfig
from ..schemas.documents import DocumentStatus
from ..schemas.domain import Claim, Document, Passage
from ..schemas.timeline import TimelineResponse
from .dates import DateContext
from .llm.extractor import LlmExtraction, extract_with_llm
from .llm.provider import LLMError, LLMProvider, build_provider, llm_configuration
from .gate import apply_gate
from .reconciliation import reconcile
from .retrieval import EvidenceIndex
from .rule_extractor import build_context, extract_claims
from .segmentation import segment
from .timeline import build_timeline, matches, tally
from .verification import verify_all

logger = logging.getLogger("medusa.analysis")
MAX_NOTES = 100
MAX_LLM_WORKERS = 4


def _run_model(row) -> AnalysisRun:
    return AnalysisRun(**{k: row[k] for k in row.keys() if k != "stats"}, stats=json.loads(row["stats"] or "{}"))


class AnalysisService:
    def __init__(self, settings: Settings,
                 provider_factory: Callable[[Settings], LLMProvider | None] = build_provider):
        self.settings = settings
        self.db = settings.db_path
        self._provider_factory = provider_factory
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------ config
    def llm_config(self) -> LlmConfig:
        s = self.settings
        status, reason = llm_configuration(s)
        return LlmConfig(provider=s.llm_provider, model=s.llm_model.strip() or None, status=status, reason=reason,
                         api_key_set=s.llm_api_key is not None, custom_base_url=bool(s.llm_base_url.strip()))

    def recover_interrupted(self) -> int:
        with transaction(self.db) as conn:
            n = repo.fail_interrupted_runs(conn)
        if n:
            logger.warning("Marked %d interrupted analysis run(s) as failed", n)
        return n

    # ------------------------------------------------------------------ run
    def _lock(self, patient_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(patient_id, threading.Lock())

    def run(self, patient_id: str) -> AnalysisRun:
        lock = self._lock(patient_id)
        if not lock.acquire(blocking=False):
            raise ConflictError(f"An analysis run for {patient_id} is already in progress.",
                                {"patient_id": patient_id})
        try:
            return self._run_locked(patient_id)
        finally:
            lock.release()

    def _load_documents(self, patient_id: str) -> tuple[list[Document], list[dict], str]:
        with transaction(self.db) as conn:
            summaries = doc_repo.list_documents(conn, patient_id, None)
            processed = [doc_repo.get_detail(conn, s.document_id) for s in summaries
                         if s.status == DocumentStatus.PROCESSED]
            fingerprint = repo.processed_fingerprint(conn, patient_id)
        skipped = [{"document_id": s.document_id, "filename": s.filename, "status": s.status.value,
                    "reason": s.error_code or s.status.value}
                   for s in summaries if s.status != DocumentStatus.PROCESSED]
        docs = [Document(document_id=d.document_id, patient_id=d.patient_id, document_type=d.document_type or "Unknown",
                         document_date=d.document_date, metadata=d.metadata, text=d.extracted_text or "",
                         filename=d.filename, sha256=d.sha256)
                for d in processed if d is not None and d.extracted_text]
        return docs, skipped, fingerprint

    def _run_locked(self, patient_id: str) -> AnalysisRun:
        docs, skipped, fingerprint = self._load_documents(patient_id)
        if not docs:
            raise UnprocessableError(f"Patient {patient_id} has no processed documents to analyse.",
                                     {"patient_id": patient_id, "skipped": skipped})
        cfg_status, cfg_reason = llm_configuration(self.settings)
        provider = self._provider_factory(self.settings) if cfg_status == "configured" else None
        llm_status = {"disabled": "disabled", "misconfigured": "misconfigured"}.get(cfg_status, "ok")
        run_id = "RUN-" + uuid.uuid4().hex[:12].upper()
        with transaction(self.db) as conn:
            repo.start_run(conn, run_id=run_id, patient_id=patient_id, extractor="rules", llm_status=llm_status,
                           fingerprint=fingerprint)
        logger.info("Analysis %s started for %s: %d document(s), LLM %s", run_id, patient_id, len(docs), cfg_status)
        try:
            return self._execute(run_id, patient_id, docs, skipped, provider, llm_status, cfg_reason)
        except Exception as exc:
            logger.exception("Analysis %s failed", run_id)
            with transaction(self.db) as conn:
                repo.finish_run(conn, run_id, status="failed", extractor="rules", llm_status=llm_status,
                                llm_error=cfg_reason, stats={"documents_skipped": skipped},
                                error=f"{exc.__class__.__name__}: {exc}"[:500])
            raise

    def _execute(self, run_id: str, patient_id: str, docs: list[Document], skipped: list[dict],
                 provider: LLMProvider | None, llm_status: str, llm_error: str | None) -> AnalysisRun:
        bundle = build_context(docs)
        passages: dict[str, list[Passage]] = {d.document_id: segment(d.document_id, d.text) for d in docs}
        rule_claims: dict[str, list[Claim]] = {}
        notes: list[str] = list(bundle.notes)
        for d in docs:
            result = extract_claims(d, passages[d.document_id], bundle)
            rule_claims[d.document_id] = result.claims
            notes.extend(result.notes)

        llm_claims: list[Claim] = []
        llm_stats: dict = {}
        extractor = "rules"
        if provider is not None:
            outcomes = self._run_llm(provider, docs, passages, rule_claims, bundle.admission_date)
            ok = {k: v for k, v in outcomes.items() if isinstance(v, LlmExtraction)}
            errors = [{"document_id": k, "code": v.code, "message": v.message}
                      for k, v in outcomes.items() if isinstance(v, LLMError)]
            for r in ok.values():
                llm_claims.extend(r.accepted)
            llm_status = "ok" if not errors else ("partial" if ok else "failed")
            llm_error = None if not errors else f"{errors[0]['code']}: {errors[0]['message']}"
            if ok:
                extractor = f"rules+llm:{provider.name}"
            llm_stats = {"provider": provider.name, "documents_ok": len(ok), "documents_failed": len(errors),
                         "errors": errors, "accepted": len(llm_claims),
                         "agreed_with_rules": sum(r.agreed_with_rules for r in ok.values()),
                         "rejected": sum(r.rejected_count for r in ok.values()),
                         "rejections": [x for r in ok.values() for x in r.rejected][:50]}

        all_passages = [p for d in docs for p in passages[d.document_id]]
        all_claims = [c for d in docs for c in rule_claims[d.document_id]] + llm_claims
        index = EvidenceIndex(all_passages)
        verifications = verify_all(all_claims, docs, all_passages, index)
        verified_ids = {v.claim_id for v in verifications if v.verified}
        findings = apply_gate(reconcile(all_claims, index, verified_ids), verified_ids)
        kinds = Counter(i.kind for f in findings for i in f.issues)
        failed_checks = Counter(c.check_id for v in verifications for c in v.checks if not c.passed and c.severity == "hard")
        advisory = Counter(c.check_id for v in verifications for c in v.checks if not c.passed and c.severity == "advisory")
        stats = {
            "documents_analyzed": len(docs), "documents_skipped": skipped, "passages": len(all_passages),
            "claims_total": len(all_claims),
            "claims_by_category": dict(Counter(c.claim_type for c in all_claims)),
            "claims_by_method": {"rule": sum(len(v) for v in rule_claims.values()), "llm": len(llm_claims)},
            "notes": notes[:MAX_NOTES], "llm": llm_stats,
            "verification": {"verified": len(verified_ids), "failed": len(all_claims) - len(verified_ids),
                             "failed_checks": dict(failed_checks), "advisory_not_met": dict(advisory)},
            "findings": {"total": len(findings), "with_issues": sum(1 for f in findings if f.issues),
                         "by_state": dict(Counter(f.state.value for f in findings if f.state)),
                         "high_risk_with_issues": sum(1 for f in findings if f.issues and f.high_risk),
                         "issues_by_kind": dict(kinds)},
        }
        with transaction(self.db) as conn:
            repo.replace_patient_results(conn, patient_id, all_passages, all_claims, run_id, findings, verifications)
            repo.finish_run(conn, run_id, status="completed", extractor=extractor, llm_status=llm_status,
                            llm_error=llm_error, stats=stats)
            row = repo.get_run(conn, run_id)
        logger.info("Analysis %s completed: %d claims (%d rule, %d LLM, %d verified), %d findings, LLM %s", run_id,
                    len(all_claims), stats["claims_by_method"]["rule"], len(llm_claims), len(verified_ids),
                    len(findings), llm_status)
        return _run_model(row)

    @staticmethod
    def _run_llm(provider: LLMProvider, docs: list[Document], passages: dict[str, list[Passage]],
                 rule_claims: dict[str, list[Claim]], admission_date) -> dict[str, LlmExtraction | LLMError]:
        def one(d: Document) -> LlmExtraction | LLMError:
            ctx = DateContext(document_date=d.document_date, admission_date=admission_date)
            try:
                return extract_with_llm(provider, d, passages[d.document_id], rule_claims[d.document_id], ctx)
            except LLMError as exc:
                logger.warning("LLM extraction failed for %s: %s", d.document_id, exc.code)
                return exc
        with ThreadPoolExecutor(max_workers=min(MAX_LLM_WORKERS, len(docs))) as pool:
            return dict(zip([d.document_id for d in docs], pool.map(one, docs)))

    # ------------------------------------------------------------------ queries
    def status(self, patient_id: str) -> AnalysisStatus:
        with transaction(self.db) as conn:
            latest = repo.latest_run(conn, patient_id)
            results = repo.latest_run(conn, patient_id, completed_only=True)
            fingerprint = repo.processed_fingerprint(conn, patient_id)
            stored_passages = repo.count_passages(conn, patient_id)
        results_model = _run_model(results) if results else None
        reason = None
        if results_model is not None:
            if results_model.document_fingerprint != fingerprint:
                reason = "Documents were added, removed or re-uploaded after this analysis. Run it again."
            elif stored_passages != results_model.stats.get("passages"):
                reason = "Stored results no longer match this analysis run. Run it again."
        is_current = results_model is not None and reason is None
        return AnalysisStatus(patient_id=patient_id, latest_run=_run_model(latest) if latest else None,
                              results_run=results_model, is_current=is_current,
                              stale_reason=reason)

    def claims(self, patient_id: str, category: str | None = None, document_id: str | None = None) -> list[ClaimRecord]:
        with transaction(self.db) as conn:
            claims = repo.list_claims(conn, patient_id, category=category, document_id=document_id)
            ver = repo.verifications_for(conn, patient_id)
        return [ClaimRecord(**c.model_dump(), verified=ver[c.claim_id].verified if c.claim_id in ver else None,
                            failed_checks=[k.check_id for k in ver[c.claim_id].checks if not k.passed and k.severity == "hard"]
                            if c.claim_id in ver else [])
                for c in claims]

    def timeline(self, patient_id: str, category: str | None = None, q: str | None = None,
                 document_id: str | None = None) -> TimelineResponse:
        status = self.status(patient_id)
        records = self.claims(patient_id)
        # only claims that passed verification; an unverified run (older schema) has no records, so keep all
        usable = [c for c in records if c.verified is not False]
        entries = build_timeline(usable)
        by_basis, by_category = tally(entries)
        shown = [e for e in entries
                 if (category is None or e.category == category)
                 and (document_id is None or e.document_id == document_id)
                 and (not q or matches(e, q))]
        return TimelineResponse(patient_id=patient_id,
                                results_run_id=status.results_run.run_id if status.results_run else None,
                                is_current=status.is_current, stale_reason=status.stale_reason, total=len(entries),
                                excluded_unverified=len(records) - len(usable),
                                by_basis=by_basis, by_category=by_category, entries=shown)

    def get_run(self, run_id: str) -> AnalysisRun:
        with transaction(self.db) as conn:
            row = repo.get_run(conn, run_id)
        if row is None:
            raise NotFoundError(f"Analysis run {run_id} not found")
        return _run_model(row)
