import sqlite3

import pytest

from medusa.db import schema
from medusa.db.connection import DatabaseError, connect, transaction
from medusa.db.schema import EXPECTED_TABLES, SCHEMA_VERSION, check_database, init_db

from factories import insert_raw_document


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "sub" / "m.db"  # parent folder does not exist yet
    init_db(path)
    return path


def _insert_doc(conn, doc_id="DOC-1"):
    insert_raw_document(conn, doc_id)


def test_init_creates_schema(db):
    conn = connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_init_is_idempotent(db):
    assert init_db(db) == SCHEMA_VERSION


def test_foreign_keys_enforced_and_cascade(db):
    with transaction(db) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO passages VALUES ('X:P001', 'MISSING', 'P1', 0, 'PLAN', 0, 5, 'Plan.')")
    with transaction(db) as conn:
        _insert_doc(conn)
        conn.execute("INSERT INTO passages VALUES ('DOC-1:P001', 'DOC-1', 'P1', 0, 'PLAN', 0, 5, 'Plan.')")
    with transaction(db) as conn:
        conn.execute("DELETE FROM documents WHERE document_id = 'DOC-1'")
    with transaction(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == 0


def _insert_claim(conn, **over):
    conn.execute("INSERT INTO analysis_runs (run_id, patient_id, status, started_at, extractor, llm_status, document_fingerprint) "
                 "VALUES ('RUN-1', 'P1', 'completed', 'now', 'rules', 'disabled', 'fp') ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO passages VALUES ('DOC-1:P001', 'DOC-1', 'P1', 0, 'PLAN', 0, 10, 'Warfarin x') ON CONFLICT DO NOTHING")
    row = dict(claim_id="CLM-1", run_id="RUN-1", patient_id="P1", document_id="DOC-1", passage_id="DOC-1:P001", seq=0,
               category="medication", entity="warfarin", surface_text="Warfarin", entity_start=0, entity_end=8,
               assertion=None, document_date=None, event_date=None, event_date_precision="unknown",
               event_date_approximate=0, event_date_basis="none", event_date_raw=None, event_date_note=None,
               extraction_method="rule:MED-v1", attributes="{}", created_at="now") | over
    conn.execute(f"INSERT INTO claims ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


@pytest.mark.parametrize("bad", [
    {"category": "opinion"},                         # not a documented category
    {"extraction_method": "guess"},                  # every claim says how it was produced
    {"entity_start": 8, "entity_end": 8},            # empty span
    {"event_date": "2026-03-10"},                    # a date without a precision
    {"event_date_precision": "day"},                 # a precision without a date
    {"assertion": "probably"},
])
def test_claim_constraints(db, bad):
    with transaction(db) as conn:
        _insert_doc(conn)
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(db) as conn:
            _insert_claim(conn, **bad)


def test_claims_cascade_with_their_document(db):
    with transaction(db) as conn:
        _insert_doc(conn)
        _insert_claim(conn)
    with transaction(db) as conn:
        conn.execute("DELETE FROM documents")
    with transaction(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == 0


def test_transaction_rolls_back_on_error(db):
    with pytest.raises(RuntimeError):
        with transaction(db) as conn:
            _insert_doc(conn)
            raise RuntimeError("boom")
    with transaction(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_newer_database_is_refused(db):
    conn = connect(db)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(DatabaseError, match="newer"):
        init_db(db)


def test_failed_migration_is_atomic(db, monkeypatch):
    bad = (SCHEMA_VERSION + 1, "broken", "CREATE TABLE partial (id INTEGER); INSERT INTO nope VALUES (1);")
    monkeypatch.setattr(schema, "MIGRATIONS", schema.MIGRATIONS + [bad])
    monkeypatch.setattr(schema, "SCHEMA_VERSION", bad[0])
    with pytest.raises(DatabaseError, match="broken"):
        init_db(db)
    conn = connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == bad[0] - 1
    assert not conn.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchone()


def test_check_database(db, tmp_path):
    ok = check_database(db)
    assert ok["reachable"] and ok["schema_version"] == SCHEMA_VERSION and "error" not in ok
    assert check_database(tmp_path / "absent.db")["error"] == "database file does not exist"
    with transaction(db) as conn:
        conn.execute("DROP TABLE claims")
    assert "claims" in check_database(db)["error"]
