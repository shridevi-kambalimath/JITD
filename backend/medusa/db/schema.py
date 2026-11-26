"""Database schema and migrations.

The schema version lives in SQLite's built-in PRAGMA user_version. Each migration runs inside
one transaction together with its version bump, so a failed migration leaves the database at
the previous version. Migrations are append-only: never edit one that has shipped.

Tables mirror the architecture (docs/ARCHITECTURE.md section 4). Domain objects are stored as
validated Pydantic JSON in a `data` column, with the fields we filter or join on promoted to
real columns. With seven tables and no ad-hoc relational queries, an ORM would add a layer
without adding safety; Pydantic validation on read and write is the model layer.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from .connection import DatabaseError, connect

logger = logging.getLogger("medusa.db")

_V1 = """
CREATE TABLE documents (
    document_id   TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL,
    document_type TEXT NOT NULL,
    document_date TEXT,
    filename      TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    data          TEXT NOT NULL,              -- Document JSON (includes full text and metadata)
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX ix_documents_patient ON documents(patient_id);

CREATE TABLE passages (
    passage_id  TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    patient_id  TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    data        TEXT NOT NULL                 -- Passage JSON
);
CREATE INDEX ix_passages_document ON passages(document_id, seq);
CREATE INDEX ix_passages_patient ON passages(patient_id);

CREATE TABLE runs (
    run_id     TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    data       TEXT NOT NULL                  -- RunRecord JSON
);
CREATE INDEX ix_runs_patient ON runs(patient_id, started_at);

CREATE TABLE claims (
    claim_id    TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    claim_type  TEXT NOT NULL,
    entity      TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    data        TEXT NOT NULL                 -- Claim JSON
);
CREATE INDEX ix_claims_patient ON claims(patient_id, claim_type);

CREATE TABLE verifications (
    claim_id   TEXT PRIMARY KEY REFERENCES claims(claim_id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL,
    verified   INTEGER NOT NULL CHECK (verified IN (0, 1)),
    data       TEXT NOT NULL                  -- Verification JSON
);

CREATE TABLE findings (
    finding_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    state      TEXT CHECK (state IN ('Evidence-supported', 'Conflicting evidence',
                                     'Insufficient evidence', 'Review required')),
    seq        INTEGER NOT NULL,
    data       TEXT NOT NULL                  -- Finding JSON
);
CREATE INDEX ix_findings_patient ON findings(patient_id, state);

CREATE TABLE review_items (
    review_id  TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    priority   INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 3),
    status     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'escalated')),
    data       TEXT NOT NULL                  -- ReviewItem JSON
);
CREATE INDEX ix_review_patient ON review_items(patient_id, priority);
"""

# v2: document ingestion. Rebuilds `documents` with explicit columns for status tracking, extraction
# results and errors (SQLite cannot add CHECK constraints to an existing table), and adds an
# append-only status event log. Any v1 rows are carried over as processed.
_V2 = """
CREATE TABLE documents_v2 (
    document_id        TEXT PRIMARY KEY,           -- DOC-<16 hex>, derived from patient id + file bytes
    patient_id         TEXT NOT NULL,
    filename           TEXT NOT NULL,              -- sanitised original name, display only
    file_format        TEXT NOT NULL CHECK (file_format IN ('pdf', 'txt')),
    size_bytes         INTEGER NOT NULL CHECK (size_bytes > 0),
    sha256             TEXT NOT NULL,
    storage_path       TEXT NOT NULL,              -- name inside the upload directory, never user-controlled
    status             TEXT NOT NULL CHECK (status IN ('uploaded', 'processing', 'processed', 'failed')),
    document_type      TEXT,                       -- clinical type from the document header
    document_date      TEXT,
    source_document_id TEXT,                       -- DOCUMENT ID written in the header, if any
    metadata           TEXT NOT NULL DEFAULT '{}', -- all header fields (JSON object)
    extracted_text     TEXT,                       -- canonical text; all later offsets index into this
    extraction_method  TEXT CHECK (extraction_method IN ('utf8_text', 'pdf_text_layer')),
    page_count         INTEGER,
    page_spans         TEXT NOT NULL DEFAULT '[]', -- JSON [[start, end], ...] per PDF page
    warnings           TEXT NOT NULL DEFAULT '[]', -- JSON list of strings
    error_code         TEXT,
    error_message      TEXT,
    uploaded_at        TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    CHECK ((status = 'failed') = (error_code IS NOT NULL)),
    CHECK (status <> 'processed' OR (extracted_text IS NOT NULL AND length(trim(extracted_text)) > 0
                                     AND document_type IS NOT NULL AND document_date IS NOT NULL))
);

INSERT INTO documents_v2 (document_id, patient_id, filename, file_format, size_bytes, sha256, storage_path,
                          status, document_type, document_date, metadata, extracted_text, extraction_method,
                          uploaded_at, updated_at)
SELECT document_id, patient_id, filename,
       CASE WHEN lower(filename) LIKE '%.pdf' THEN 'pdf' ELSE 'txt' END,
       max(length(CAST(json_extract(data, '$.text') AS BLOB)), 1), sha256, '',
       'processed', document_type, document_date,
       coalesce(json_extract(data, '$.metadata'), '{}'), json_extract(data, '$.text'), 'utf8_text',
       created_at, created_at
FROM documents;

DROP TABLE documents;
ALTER TABLE documents_v2 RENAME TO documents;
CREATE INDEX ix_documents_patient ON documents(patient_id, uploaded_at);
CREATE INDEX ix_documents_status ON documents(status);

CREATE TABLE document_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    status      TEXT NOT NULL CHECK (status IN ('uploaded', 'processing', 'processed', 'failed')),
    detail      TEXT,
    at          TEXT NOT NULL
);
CREATE INDEX ix_document_events_document ON document_events(document_id, event_id);
"""

# v3: structured extraction. The v1 placeholder tables (JSON blobs, never written by any build) are replaced:
# passages, analysis_runs and claims get real columns and constraints. verifications, findings and reviews
# return with their own migrations in Phases 5 and 6.
_V3 = """
DROP TABLE IF EXISTS review_items;
DROP TABLE IF EXISTS findings;
DROP TABLE IF EXISTS verifications;
DROP TABLE IF EXISTS claims;
DROP TABLE IF EXISTS passages;
DROP TABLE IF EXISTS runs;

CREATE TABLE passages (
    passage_id  TEXT PRIMARY KEY,               -- <document_id>:P<nnn>
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    patient_id  TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    section     TEXT NOT NULL,
    char_start  INTEGER NOT NULL,               -- offsets into documents.extracted_text
    char_end    INTEGER NOT NULL,
    text        TEXT NOT NULL,
    CHECK (char_start >= 0 AND char_end > char_start)
);
CREATE INDEX ix_passages_document ON passages(document_id, seq);
CREATE INDEX ix_passages_patient ON passages(patient_id);

CREATE TABLE analysis_runs (
    run_id               TEXT PRIMARY KEY,
    patient_id           TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    extractor            TEXT NOT NULL,      -- 'rules' or 'rules+llm:<provider>/<model>': what actually produced claims
    llm_status           TEXT NOT NULL CHECK (llm_status IN ('disabled', 'misconfigured', 'ok', 'partial', 'failed')),
    llm_error            TEXT,
    document_fingerprint TEXT NOT NULL,      -- processed documents at run time; differs later = results are stale
    stats                TEXT NOT NULL DEFAULT '{}',
    error                TEXT
);
CREATE INDEX ix_runs_patient ON analysis_runs(patient_id, started_at);

CREATE TABLE claims (
    claim_id               TEXT PRIMARY KEY,
    run_id                 TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    patient_id             TEXT NOT NULL,
    document_id            TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    passage_id             TEXT NOT NULL REFERENCES passages(passage_id) ON DELETE CASCADE,
    seq                    INTEGER NOT NULL,
    category               TEXT NOT NULL CHECK (category IN ('medication', 'diagnosis', 'allergy', 'lab_result',
                                                'symptom', 'procedure', 'encounter', 'record_reference')),
    entity                 TEXT NOT NULL,
    surface_text           TEXT NOT NULL,   -- the words as written in the document
    entity_start           INTEGER NOT NULL,
    entity_end             INTEGER NOT NULL,
    assertion              TEXT CHECK (assertion IN ('present', 'absent', 'possible', 'historical', 'family')),
    document_date          TEXT,
    event_date             TEXT,
    event_date_precision   TEXT NOT NULL CHECK (event_date_precision IN ('day', 'month', 'year', 'unknown')),
    event_date_approximate INTEGER NOT NULL CHECK (event_date_approximate IN (0, 1)),
    event_date_basis       TEXT NOT NULL CHECK (event_date_basis IN ('explicit', 'relative', 'document_header', 'none')),
    event_date_raw         TEXT,
    event_date_note        TEXT,
    extraction_method      TEXT NOT NULL CHECK (extraction_method LIKE 'rule:%' OR extraction_method LIKE 'llm:%'),
    attributes             TEXT NOT NULL,   -- category-specific fields (JSON), validated by Pydantic on read and write
    created_at             TEXT NOT NULL,
    CHECK (entity_end > entity_start),
    CHECK ((event_date IS NULL) = (event_date_precision = 'unknown'))
);
CREATE INDEX ix_claims_patient ON claims(patient_id, category);
CREATE INDEX ix_claims_document ON claims(document_id);
"""

_V4 = """
CREATE TABLE findings (
    patient_id   TEXT NOT NULL,
    finding_id   TEXT NOT NULL,                  -- deterministic per subject, e.g. FND-MED-warfarin
    run_id       TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    category     TEXT NOT NULL CHECK (category IN ('medication', 'diagnosis', 'allergy', 'family_history',
                                                   'record_reference')),
    subject      TEXT NOT NULL,
    high_risk    INTEGER NOT NULL CHECK (high_risk IN (0, 1)),
    issue_count  INTEGER NOT NULL CHECK (issue_count >= 0),
    fingerprint  TEXT NOT NULL,                  -- identity of the issues; a review applies only while it matches
    payload      TEXT NOT NULL,                  -- the Finding as JSON (issues, observations, investigation, claim ids)
    PRIMARY KEY (patient_id, finding_id)
);
CREATE INDEX ix_findings_run ON findings(run_id);

-- Kept across analysis runs on purpose (no foreign key to findings): a rerun must not erase a person's review.
CREATE TABLE reviews (
    patient_id          TEXT NOT NULL,
    finding_id          TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('pending_review', 'reviewed', 'flagged')),
    note                TEXT CHECK (note IS NULL OR length(note) <= 2000),
    finding_fingerprint TEXT NOT NULL,           -- the finding as it was when reviewed
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (patient_id, finding_id)
);
"""

_V5 = """
CREATE TABLE verifications (
    claim_id   TEXT PRIMARY KEY REFERENCES claims(claim_id) ON DELETE CASCADE,
    patient_id TEXT NOT NULL,
    verified   INTEGER NOT NULL CHECK (verified IN (0, 1)),  -- 1 only if every hard check passed
    checks     TEXT NOT NULL                                 -- list of CheckResult as JSON
);
CREATE INDEX ix_verifications_patient ON verifications(patient_id);
ALTER TABLE findings ADD COLUMN state TEXT CHECK (state IS NULL OR state IN
    ('EVIDENCE_SUPPORTED', 'CONFLICTING_EVIDENCE', 'INSUFFICIENT_EVIDENCE', 'REVIEW_REQUIRED'));
ALTER TABLE findings ADD COLUMN gate_rule TEXT;
"""

# (version, description, sql). Append new migrations; never edit shipped ones.
MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial schema", _V1),
    (2, "document ingestion: status tracking, extraction results, event log", _V2),
    (3, "structured extraction: passages, analysis runs, claims", _V3),
    (4, "reconciliation: findings and reviews", _V4),
    (5, "verification and evidence states", _V5),
]
SCHEMA_VERSION = MIGRATIONS[-1][0]
EXPECTED_TABLES = frozenset({"documents", "document_events", "passages", "analysis_runs", "claims", "findings",
                             "reviews", "verifications"})


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations.

    Follows SQLite's documented procedure for table rebuilds: foreign keys are switched off
    (this cannot be done inside a transaction), each migration runs in its own transaction,
    PRAGMA foreign_key_check must return nothing before commit, then foreign keys are re-enabled.
    """
    version = current_version(conn)
    if version > SCHEMA_VERSION:
        raise DatabaseError(
            f"Database schema version {version} is newer than this application supports ({SCHEMA_VERSION}).")
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for target, description, sql in MIGRATIONS:
            if target <= version:
                continue
            logger.info("Applying migration %d: %s", target, description)
            try:
                conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {target};")
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise DatabaseError(f"foreign key violations: {[tuple(v) for v in violations[:5]]}")
                conn.commit()
            except (sqlite3.Error, DatabaseError) as exc:
                conn.rollback()
                raise DatabaseError(f"Migration {target} ({description}) failed: {exc}") from exc
            version = target
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return version


def init_db(path: Path) -> int:
    """Create the database file if needed, enable WAL, apply pending migrations. Returns schema version."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = migrate(conn)
    finally:
        conn.close()
    logger.info("Database ready at %s (schema v%d)", path, version)
    return version


def check_database(path: Path) -> dict[str, str | int | bool]:
    """Readiness probe. Never raises; reports what it found."""
    result: dict[str, str | int | bool] = {"path": str(path), "reachable": False,
                                           "schema_version": -1, "expected_version": SCHEMA_VERSION}
    if not path.exists():
        result["error"] = "database file does not exist"
        return result
    try:
        conn = connect(path)
        try:
            conn.execute("SELECT 1").fetchone()
            result["reachable"] = True
            result["schema_version"] = current_version(conn)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            missing = sorted(EXPECTED_TABLES - tables)
            if missing:
                result["error"] = f"missing tables: {', '.join(missing)}"
        finally:
            conn.close()
    except sqlite3.Error as exc:
        result["error"] = f"{exc.__class__.__name__}: {exc}"
    return result
