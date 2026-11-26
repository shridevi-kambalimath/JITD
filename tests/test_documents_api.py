"""API tests for document ingestion, run through the real app with a temporary database and upload folder."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from medusa.core.errors import ConflictError
from medusa.db import documents as repo
from medusa.db.connection import connect, transaction
from medusa.db.schema import SCHEMA_VERSION, init_db
from medusa.main import create_app

from factories import PATIENT, header, note, note_lines, scanned_pdf, text_pdf

URL = f"/api/patients/{PATIENT}/documents"


@pytest.fixture()
def settings(settings, tmp_path):
    return settings.model_copy(update={"upload_dir": tmp_path / "uploads", "max_upload_bytes": 200_000})


def upload(client, name, data):
    return client.post(URL, files={"file": (name, data, "application/octet-stream")})


def stored_files(settings):
    return sorted(p.name for p in settings.upload_dir.glob("*")) if settings.upload_dir.exists() else []


# =========================================================================== happy paths
def test_upload_txt_processed(client, settings):
    r = upload(client, "progress_note.txt", note().encode())
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "processed" and d["file_format"] == "txt" and d["extraction_method"] == "utf8_text"
    assert d["document_type"] == "Progress Note" and d["document_date"] == "2026-03-12"
    assert d["source_document_id"] == "DOC-PRG-003" and d["metadata"]["PATIENT ID"] == PATIENT
    assert d["extracted_text"].startswith("DOCUMENT TYPE") and d["char_count"] == len(d["extracted_text"])
    assert d["error_code"] is None and d["filename"] == "progress_note.txt"
    assert [e["status"] for e in d["events"]] == ["uploaded", "processing", "processed"]
    assert stored_files(settings) == [f"{d['document_id']}.txt"]


def test_upload_pdf_processed_with_pages(client):
    data = text_pdf([note_lines(document_type="Discharge Summary"), [], ["DISCHARGE MEDICATIONS:",
                                                                         "Metformin 500 mg orally twice daily."]])
    d = upload(client, "discharge.pdf", data).json()
    assert d["status"] == "processed" and d["extraction_method"] == "pdf_text_layer"
    assert d["page_count"] == 3 and len(d["page_spans"]) == 3
    assert d["warnings"] == ["Page 2 has no extractable text (it may be a scanned image); its content is not included."]
    a, b = d["page_spans"][2]
    assert d["extracted_text"][a:b].startswith("DISCHARGE MEDICATIONS")


def test_document_ids_are_deterministic_and_unique(client):
    a = upload(client, "a.txt", note().encode()).json()["document_id"]
    b = upload(client, "b.txt", note(document_id="DOC-OTHER").encode()).json()["document_id"]
    assert a != b and a.startswith("DOC-") and len(a) == 20
    client.delete(f"/api/documents/{a}")
    assert upload(client, "renamed.txt", note().encode()).json()["document_id"] == a  # same bytes, same id


def test_list_detail_and_status_filter(client):
    upload(client, "ok.txt", note().encode())
    upload(client, "bad.txt", b"No header in this synthetic note, so processing fails.")
    docs = client.get(URL).json()
    assert len(docs) == 2 and all("extracted_text" not in d for d in docs)
    assert [d["status"] for d in client.get(URL, params={"status": "failed"}).json()] == ["failed"]
    assert len(client.get(URL, params={"status": "processed"}).json()) == 1
    assert client.get(URL, params={"status": "done"}).status_code == 422
    assert client.get("/api/patients/SYN-0002/documents").json() == []


# =========================================================================== processing failures (stored as failed)
@pytest.mark.parametrize("name,make,code", [
    ("scan.pdf", lambda: scanned_pdf(note_lines()), "no_text_layer"),
    ("locked.pdf", lambda: text_pdf([note_lines()], password="pw"), "encrypted_pdf"),
    ("broken.pdf", lambda: text_pdf([note_lines()])[:300], "corrupted_pdf"),
    ("blank.txt", lambda: b"   \r\n\r\n   ", "empty_text"),
    ("tiny.txt", lambda: b"BP ok", "insufficient_text"),
    ("noheader.txt", lambda: b"PLAN:\nWarfarin held due to upper gastrointestinal bleed.\n", "missing_header"),
    ("other_patient.txt", lambda: note(patient_id="SYN-0002").encode(), "patient_mismatch"),
    ("bad_date.txt", lambda: header(document_date="12-03-2026").encode() + b"PLAN:\nNo change today.\n",
     "invalid_date"),
])
def test_failed_processing_is_recorded(client, name, make, code):
    r = upload(client, name, make())
    assert r.status_code == 201
    d = r.json()
    assert d["status"] == "failed" and d["error_code"] == code and d["error_message"]
    assert [e["status"] for e in d["events"]] == ["uploaded", "processing", "failed"]
    assert d["document_type"] is None  # nothing is guessed for a failed document


def test_failed_metadata_keeps_text_for_inspection(client):
    d = upload(client, "noheader.txt", b"PLAN:\nWarfarin held due to upper gastrointestinal bleed.\n").json()
    assert d["status"] == "failed" and "Warfarin" in d["extracted_text"]


# =========================================================================== rejections (nothing stored)
@pytest.mark.parametrize("name,data,status,code", [
    ("empty.txt", b"", 422, "empty_file"),
    ("report.docx", b"PK\x03\x04 not supported", 415, "unsupported_type"),
    ("fake.pdf", b"plain text with a pdf extension", 415, "content_mismatch"),
    ("latin1.txt", "Patient café".encode("latin-1"), 422, "invalid_encoding"),
    ("big.txt", b"x" * 200_001, 413, "file_too_large"),
])
def test_rejected_uploads_store_nothing(client, settings, name, data, status, code):
    r = upload(client, name, data)
    assert r.status_code == status and r.json()["error"]["code"] == code
    assert client.get(URL).json() == [] and stored_files(settings) == []


def test_oversized_body_rejected_before_parsing(client):
    r = client.post(URL, content=b"x" * 300_000, headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_duplicate_upload_conflicts(client, settings):
    first = upload(client, "a.txt", note().encode()).json()
    r = upload(client, "copy.txt", note().encode())
    assert r.status_code == 409 and r.json()["error"]["details"]["document_id"] == first["document_id"]
    assert len(client.get(URL).json()) == 1 and len(stored_files(settings)) == 1


def test_missing_file_field_and_bad_ids(client):
    assert client.post(URL).status_code == 422
    assert client.post("/api/patients/bad id!/documents", files={"file": ("a.txt", note().encode())}).status_code == 422
    assert client.get("/api/documents/not-an-id").status_code == 422
    assert client.get("/api/documents/DOC-0000000000000000").status_code == 404


def test_path_traversal_filename_is_harmless(client, settings):
    d = upload(client, "../../../windows/system32/evil.txt", note().encode()).json()
    assert d["filename"] == "evil.txt"
    assert stored_files(settings) == [f"{d['document_id']}.txt"]


# =========================================================================== deletion
def test_delete_removes_row_events_and_file(client, settings):
    doc_id = upload(client, "a.txt", note().encode()).json()["document_id"]
    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.get(f"/api/documents/{doc_id}").status_code == 404
    assert stored_files(settings) == []
    with transaction(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM document_events").fetchone()[0] == 0
    assert client.delete(f"/api/documents/{doc_id}").status_code == 404


# =========================================================================== demo bundle
def test_load_demo_is_idempotent(client):
    first = client.post(f"/api/patients/{PATIENT}/demo/load").json()
    assert len(first["loaded"]) == 7 and all(d["status"] == "processed" for d in first["loaded"])
    types = {d["document_type"] for d in first["loaded"]}
    assert {"Admission Note", "Laboratory Report", "Discharge Summary"} <= types
    second = client.post(f"/api/patients/{PATIENT}/demo/load").json()
    assert second["loaded"] == [] and len(second["skipped_existing"]) == 7
    assert client.post("/api/patients/NOBODY/demo/load").status_code == 404


# =========================================================================== status machine and recovery
def test_illegal_transition_rejected(client, settings):
    doc_id = upload(client, "a.txt", note().encode()).json()["document_id"]
    with pytest.raises(ConflictError):
        with transaction(settings.db_path) as conn:
            repo.mark_processing(conn, doc_id)  # processed -> processing is not allowed


def test_database_refuses_processed_without_text(client, settings):
    doc_id = upload(client, "a.txt", note().encode()).json()["document_id"]
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(settings.db_path) as conn:
            conn.execute("UPDATE documents SET extracted_text = '   ' WHERE document_id = ?", (doc_id,))


def test_interrupted_documents_fail_on_startup(settings):
    init_db(settings.db_path)
    with transaction(settings.db_path) as conn:
        repo.insert_uploaded(conn, document_id="DOC-00000000000000AA", patient_id=PATIENT, filename="x.txt",
                             file_format="txt", size_bytes=5, sha256="x", storage_path="DOC-00000000000000AA.txt")
        repo.mark_processing(conn, "DOC-00000000000000AA")
    with TestClient(create_app(settings)) as c:
        d = c.get("/api/documents/DOC-00000000000000AA").json()
    assert d["status"] == "failed" and d["error_code"] == "interrupted"


# =========================================================================== migration from stage 1
def test_upgrade_from_schema_v1_preserves_documents_and_foreign_keys(tmp_path):
    from medusa.db import schema
    path = tmp_path / "v1.db"
    conn = connect(path)
    conn.executescript("BEGIN;" + schema._V1 + "PRAGMA user_version = 1; COMMIT;")
    conn.execute("INSERT INTO documents (document_id, patient_id, document_type, document_date, filename, sha256, data)"
                 " VALUES ('DOC-OLD', 'P1', 'Note', '2026-01-01', 'old.txt', 'abc', "
                 "json_object('text', 'DOCUMENT TYPE: Note', 'metadata', json_object('A', 'b')))")
    conn.execute("INSERT INTO passages VALUES ('DOC-OLD:P001', 'DOC-OLD', 'P1', 0, '{}')")
    conn.commit()
    conn.close()

    assert init_db(path) == SCHEMA_VERSION
    conn = connect(path)
    row = conn.execute("SELECT status, extracted_text, metadata FROM documents").fetchone()
    assert tuple(row) == ("processed", "DOCUMENT TYPE: Note", '{"A":"b"}')
    # v1 placeholder passages are discarded by v3 (no build ever wrote them); the new table cascades from documents
    assert conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == 0
    conn.execute("INSERT INTO passages VALUES ('DOC-OLD:P001', 'DOC-OLD', 'P1', 0, 'X', 0, 5, 'DOCUM')")
    conn.execute("DELETE FROM documents")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == 0


# =========================================================================== shipped sample files (README walkthrough)
SAMPLES = {
    "endoscopy_report.pdf": (201, "processed", None),
    "scanned_admission_note.pdf": (201, "failed", "no_text_layer"),
    "corrupted_report.pdf": (201, "failed", "corrupted_pdf"),
    "no_header_note.txt": (201, "failed", "missing_header"),
    "wrong_patient_note.txt": (201, "failed", "patient_mismatch"),
    "empty_note.txt": (422, None, "empty_file"),
    "unsupported_notes.csv": (415, None, "unsupported_type"),
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_shipped_samples_behave_as_documented(client, name):
    from medusa.core.config import PROJECT_ROOT
    status_code, status, code = SAMPLES[name]
    r = upload(client, name, (PROJECT_ROOT / "data" / "samples" / name).read_bytes())
    assert r.status_code == status_code
    body = r.json()
    if status_code == 201:
        assert body["status"] == status and body["error_code"] == code
    else:
        assert body["error"]["code"] == code


# =========================================================================== demo reset (Phase 2)
def test_demo_reset_replaces_everything_through_the_real_pipeline(client, settings):
    client.post(f"/api/patients/{PATIENT}/demo/load")
    extra = upload(client, "extra.txt", note(document_id="DOC-EXTRA").encode()).json()
    failed = upload(client, "noheader.txt", b"PLAN:\nWarfarin held due to upper gastrointestinal bleed.\n").json()
    assert len(client.get(URL).json()) == 9 and len(stored_files(settings)) == 9

    r = client.post(f"/api/patients/{PATIENT}/demo/reset")
    assert r.status_code == 200
    body = r.json()
    assert body["removed"] == 9 and len(body["loaded"]) == 7 and body["skipped_existing"] == []
    ids = {d["document_id"] for d in client.get(URL).json()}
    assert len(ids) == 7 and extra["document_id"] not in ids and failed["document_id"] not in ids
    assert len(stored_files(settings)) == 7
    with transaction(settings.db_path) as conn:  # status history of removed documents is gone too
        assert conn.execute("SELECT COUNT(DISTINCT document_id) FROM document_events").fetchone()[0] == 7


def test_demo_reset_leaves_other_patients_alone(client):
    other = client.post("/api/patients/SYN-0002/documents",
                        files={"file": ("n.txt", note(patient_id="SYN-0002").encode())}).json()
    client.post(f"/api/patients/{PATIENT}/demo/reset")
    assert client.get(f"/api/documents/{other['document_id']}").status_code == 200


def test_demo_reset_unknown_patient_deletes_nothing(client):
    unknown_patient = "SYN-9999"
    doc = client.post(f"/api/patients/{unknown_patient}/documents",
                      files={"file": ("n.txt", note(patient_id=unknown_patient).encode())}).json()
    assert client.post(f"/api/patients/{unknown_patient}/demo/reset").status_code == 404
    assert client.get(f"/api/documents/{doc['document_id']}").status_code == 200
