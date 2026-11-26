"""Repository for analysis results: passages, analysis runs and claims.

Claims are stored as typed columns (for filtering and integrity checks) plus the category-specific
attributes as JSON. Reading a claim back goes through the Pydantic domain model, so anything the
database returns has been validated again.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone

from pydantic import TypeAdapter

from ..schemas.domain import (CheckResult, Claim, ClaimAttributes, DateValue, DiagnosisAttrs, Finding, LlmAttrs, Passage,
                              SourceRef, Verification)

_ATTRS = TypeAdapter(ClaimAttributes)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _d(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


# ------------------------------------------------------------------ passages
def finding_fingerprint(f: Finding) -> str:
    """Changes when the issues change (type, rule or cited claims), not when wording does."""
    key = sorted((i.issue_type, i.rule_id, tuple(sorted(i.claim_ids))) for i in f.issues)
    return hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]


def replace_patient_results(conn: sqlite3.Connection, patient_id: str, passages: list[Passage],
                            claims: list[Claim], run_id: str, findings: list[Finding] | None = None,
                            verifications: list[Verification] | None = None) -> None:
    """Swap the patient's passages, claims and findings for a new set. Must run inside one transaction:
    readers see either the old results or the new ones, never a mixture. Reviews are not touched."""
    conn.execute("DELETE FROM passages WHERE patient_id = ?", (patient_id,))  # claims cascade
    conn.execute("DELETE FROM findings WHERE patient_id = ?", (patient_id,))
    conn.executemany(
        "INSERT INTO findings (patient_id, finding_id, run_id, seq, category, subject, high_risk, issue_count,"
        " fingerprint, payload, state, gate_rule) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(patient_id, f.finding_id, run_id, i, f.category, f.subject, int(f.high_risk), len(f.issues),
          finding_fingerprint(f), f.model_dump_json(), f.state.value if f.state else None, f.gate_rule)
         for i, f in enumerate(findings or [])])
    conn.executemany(
        "INSERT INTO passages (passage_id, document_id, patient_id, seq, section, char_start, char_end, text)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(p.passage_id, p.document_id, patient_id, i, p.section, p.char_start, p.char_end, p.text)
         for i, p in enumerate(passages)])
    created = now_iso()
    conn.executemany(
        "INSERT INTO claims (claim_id, run_id, patient_id, document_id, passage_id, seq, category, entity,"
        " surface_text, entity_start, entity_end, assertion, document_date, event_date, event_date_precision,"
        " event_date_approximate, event_date_basis, event_date_raw, event_date_note, extraction_method,"
        " attributes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [_claim_row(c, run_id, i, created) for i, c in enumerate(claims)])
    conn.executemany("INSERT INTO verifications (claim_id, patient_id, verified, checks) VALUES (?, ?, ?, ?)",
                     [(v.claim_id, patient_id, int(v.verified), json.dumps([c.model_dump() for c in v.checks]))
                      for v in verifications or []])


def _assertion(c: Claim) -> str | None:
    a = c.attributes
    if isinstance(a, (DiagnosisAttrs, LlmAttrs)):
        return a.assertion
    return None


def _claim_row(c: Claim, run_id: str, seq: int, created: str) -> tuple:
    ev = c.event_date
    return (c.claim_id, run_id, c.patient_id, c.source.document_id, c.source.passage_id, seq, c.claim_type,
            c.entity, c.surface, c.source.entity_char_start, c.source.entity_char_end, _assertion(c),
            c.document_date.isoformat() if c.document_date else None,
            ev.value.isoformat() if ev.value else None, ev.precision if ev.value else "unknown",
            int(ev.approximate), ev.basis, ev.raw_text, ev.note, c.extraction_method,
            c.attributes.model_dump_json(), created)


_CLAIM_SELECT = """
SELECT c.*, p.section, p.char_start AS p_start, p.char_end AS p_end, p.text AS p_text, d.document_type
FROM claims c JOIN passages p ON p.passage_id = c.passage_id JOIN documents d ON d.document_id = c.document_id
"""


def _claim_from_row(r: sqlite3.Row) -> Claim:
    return Claim(
        claim_id=r["claim_id"], patient_id=r["patient_id"], claim_type=r["category"], entity=r["entity"],
        surface=r["surface_text"], attributes=_ATTRS.validate_python(json.loads(r["attributes"])),
        source=SourceRef(document_id=r["document_id"], passage_id=r["passage_id"], section=r["section"],
                         char_start=r["p_start"], char_end=r["p_end"], evidence_text=r["p_text"],
                         entity_char_start=r["entity_start"], entity_char_end=r["entity_end"]),
        document_date=_d(r["document_date"]), document_type=r["document_type"] or "",
        event_date=DateValue(value=_d(r["event_date"]), precision=r["event_date_precision"],
                             approximate=bool(r["event_date_approximate"]), raw_text=r["event_date_raw"],
                             basis=r["event_date_basis"], note=r["event_date_note"]),
        extraction_method=r["extraction_method"])


def list_claims(conn: sqlite3.Connection, patient_id: str, *, category: str | None = None,
                document_id: str | None = None) -> list[Claim]:
    sql, args = _CLAIM_SELECT + " WHERE c.patient_id = ?", [patient_id]
    if category:
        sql += " AND c.category = ?"
        args.append(category)
    if document_id:
        sql += " AND c.document_id = ?"
        args.append(document_id)
    sql += " ORDER BY d.document_date IS NULL, d.document_date, c.document_id, c.seq"
    return [_claim_from_row(r) for r in conn.execute(sql, args)]


def count_passages(conn: sqlite3.Connection, patient_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM passages WHERE patient_id = ?", (patient_id,)).fetchone()[0]


# ------------------------------------------------------------------ runs
def start_run(conn: sqlite3.Connection, *, run_id: str, patient_id: str, extractor: str, llm_status: str,
              fingerprint: str) -> None:
    conn.execute("INSERT INTO analysis_runs (run_id, patient_id, status, started_at, extractor, llm_status,"
                 " document_fingerprint) VALUES (?, ?, 'running', ?, ?, ?, ?)",
                 (run_id, patient_id, now_iso(), extractor, llm_status, fingerprint))


def finish_run(conn: sqlite3.Connection, run_id: str, *, status: str, extractor: str, llm_status: str,
               llm_error: str | None, stats: dict, error: str | None = None) -> None:
    conn.execute("UPDATE analysis_runs SET status = ?, finished_at = ?, extractor = ?, llm_status = ?, llm_error = ?,"
                 " stats = ?, error = ? WHERE run_id = ?",
                 (status, now_iso(), extractor, llm_status, llm_error, json.dumps(stats), error, run_id))


def fail_interrupted_runs(conn: sqlite3.Connection) -> int:
    return conn.execute("UPDATE analysis_runs SET status = 'failed', finished_at = ?,"
                        " error = 'Interrupted: the server stopped during the run.' WHERE status = 'running'",
                        (now_iso(),)).rowcount


def get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,)).fetchone()


def latest_run(conn: sqlite3.Connection, patient_id: str, *, completed_only: bool = False) -> sqlite3.Row | None:
    sql = "SELECT * FROM analysis_runs WHERE patient_id = ?"
    if completed_only:
        sql += " AND status = 'completed'"
    return conn.execute(sql + " ORDER BY started_at DESC, rowid DESC LIMIT 1", (patient_id,)).fetchone()


def processed_fingerprint(conn: sqlite3.Connection, patient_id: str) -> str:
    """Identity of the processed document set. Any upload, delete or re-upload changes it.

    Document ids are content-addressed, so deleting a file and uploading it again gives the same id;
    updated_at is included so that case still counts as a change."""
    rows = conn.execute("SELECT document_id, updated_at FROM documents WHERE patient_id = ? AND status = 'processed'"
                        " ORDER BY document_id", (patient_id,)).fetchall()
    return hashlib.sha256("|".join(f"{r[0]}@{r[1]}" for r in rows).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ findings and reviews
def list_findings(conn: sqlite3.Connection, patient_id: str) -> list[tuple[Finding, str]]:
    rows = conn.execute("SELECT payload, fingerprint FROM findings WHERE patient_id = ? ORDER BY seq", (patient_id,))
    return [(Finding.model_validate_json(r["payload"]), r["fingerprint"]) for r in rows]


def get_finding(conn: sqlite3.Connection, patient_id: str, finding_id: str) -> tuple[Finding, str] | None:
    r = conn.execute("SELECT payload, fingerprint FROM findings WHERE patient_id = ? AND finding_id = ?",
                     (patient_id, finding_id)).fetchone()
    return (Finding.model_validate_json(r["payload"]), r["fingerprint"]) if r else None


def reviews_for(conn: sqlite3.Connection, patient_id: str) -> dict[str, sqlite3.Row]:
    return {r["finding_id"]: r for r in conn.execute("SELECT * FROM reviews WHERE patient_id = ?", (patient_id,))}


def upsert_review(conn: sqlite3.Connection, patient_id: str, finding_id: str, status: str, note: str | None,
                  fingerprint: str) -> None:
    conn.execute("INSERT INTO reviews (patient_id, finding_id, status, note, finding_fingerprint, updated_at)"
                 " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (patient_id, finding_id) DO UPDATE SET status = excluded.status,"
                 " note = excluded.note, finding_fingerprint = excluded.finding_fingerprint, updated_at = excluded.updated_at",
                 (patient_id, finding_id, status, note, fingerprint, now_iso()))


def clear_reviews(conn: sqlite3.Connection, patient_id: str) -> int:
    return conn.execute("DELETE FROM reviews WHERE patient_id = ?", (patient_id,)).rowcount


# ------------------------------------------------------------------ verification and lookups
def verifications_for(conn: sqlite3.Connection, patient_id: str) -> dict[str, Verification]:
    rows = conn.execute("SELECT * FROM verifications WHERE patient_id = ?", (patient_id,))
    return {r["claim_id"]: Verification(claim_id=r["claim_id"], verified=bool(r["verified"]),
                                        checks=[CheckResult(**c) for c in json.loads(r["checks"])]) for r in rows}


def get_claim(conn: sqlite3.Connection, patient_id: str, claim_id: str) -> Claim | None:
    r = conn.execute(_CLAIM_SELECT + " WHERE c.patient_id = ? AND c.claim_id = ?", (patient_id, claim_id)).fetchone()
    return _claim_from_row(r) if r else None


def list_passages(conn: sqlite3.Connection, patient_id: str) -> list[Passage]:
    return [Passage(passage_id=r["passage_id"], document_id=r["document_id"], section=r["section"],
                    char_start=r["char_start"], char_end=r["char_end"], text=r["text"])
            for r in conn.execute("SELECT * FROM passages WHERE patient_id = ? ORDER BY document_id, seq", (patient_id,))]
