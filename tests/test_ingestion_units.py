"""Unit tests: upload validation, text extraction and quality gates, header metadata, file storage."""
from datetime import date

import pytest

from medusa.ingestion.metadata import MetadataError, parse_header
from medusa.ingestion.storage import FileStore
from medusa.ingestion.text_extraction import ExtractionError, extract_text, normalize_text
from medusa.ingestion.validation import UploadRejected, sanitize_filename, validate_upload

from factories import PATIENT, header, note, note_lines, scanned_pdf, text_pdf

MAX = 100_000


def _extract(fmt, data, min_chars=20, max_pages=50):
    return extract_text(fmt, data, max_pdf_pages=max_pages, min_chars=min_chars)


# =========================================================================== filenames
@pytest.mark.parametrize("raw,expected", [
    ("admission.txt", "admission.txt"),
    ("../../etc/passwd.txt", "passwd.txt"),
    ("C:\\Users\\x\\Desktop\\note.pdf", "note.pdf"),
    ("bad\x00name\n.txt", "badname.txt"),
    ("...hidden.txt", "hidden.txt"),
    ("", "upload"),
    (None, "upload"),
    ("/", "upload"),
])
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_long_filename_keeps_extension():
    name = sanitize_filename("a" * 500 + ".pdf")
    assert len(name) == 200 and name.endswith(".pdf")


# =========================================================================== validation
def test_valid_formats():
    assert validate_upload("a.txt", note().encode(), MAX) == "txt"
    assert validate_upload("A.PDF", text_pdf([note_lines()]), MAX) == "pdf"
    assert validate_upload("bom.txt", b"\xef\xbb\xbf" + note().encode(), MAX) == "txt"


@pytest.mark.parametrize("name,data,status,code", [
    ("a.txt", b"", 422, "empty_file"),
    ("a.txt", b"x" * (MAX + 1), 413, "file_too_large"),
    ("a.docx", b"PK\x03\x04", 415, "unsupported_type"),
    ("noext", b"hello", 415, "unsupported_type"),
    ("a.pdf", b"just text pretending", 415, "content_mismatch"),
    ("a.txt", b"%PDF-1.4 hidden pdf", 415, "content_mismatch"),
    ("a.txt", b"text\x00with nul", 415, "binary_content"),
    ("a.txt", "caf\u00e9".encode("latin-1") + b" note", 422, "invalid_encoding"),
])
def test_rejections(name, data, status, code):
    with pytest.raises(UploadRejected) as exc:
        validate_upload(name, data, MAX)
    assert (exc.value.status_code, exc.value.code) == (status, code)


# =========================================================================== TXT extraction
def test_txt_normalisation():
    raw = ("\ufeff" + note().replace("\n", "\r\n") + "Cafe\u0301 \x07bell\r").encode("utf-8")
    r = _extract("txt", raw)
    assert "\r" not in r.text and "\ufeff" not in r.text and "\x07" not in r.text
    assert "Caf\u00e9" in r.text  # NFC: e + combining accent becomes one character
    assert r.method == "utf8_text" and r.page_count is None


@pytest.mark.parametrize("text,code", [
    ("   \n\t\n  ", "empty_text"),
    ("too short", "insufficient_text"),
    ("\ufffd" * 10 + "a" * 40, "unreadable_text"),
])
def test_txt_quality_gates(text, code):
    with pytest.raises(ExtractionError) as exc:
        _extract("txt", text.encode())
    assert exc.value.code == code


def test_normalize_keeps_tabs_and_newlines():
    assert normalize_text("a\tb\r\nc\x0cd") == "a\tb\ncd"


# =========================================================================== PDF extraction
def test_pdf_text_and_page_spans():
    r = _extract("pdf", text_pdf([note_lines(), ["Second page: Started pantoprazole 40 mg IV twice daily."]]))
    assert r.method == "pdf_text_layer" and r.page_count == 2 and not r.warnings
    assert r.text.startswith("DOCUMENT TYPE: Progress Note\n")
    (a1, b1), (a2, b2) = r.page_spans
    assert "PATIENT ID: SYN-0001" in r.text[a1:b1] and r.text[a2:b2].startswith("Second page")


def test_pdf_blank_page_is_a_warning_not_silent():
    r = _extract("pdf", text_pdf([note_lines(), []]))
    assert r.page_count == 2 and len(r.warnings) == 1 and "Page 2 has no extractable text" in r.warnings[0]
    assert r.page_spans[1][0] == r.page_spans[1][1]  # empty span recorded for the blank page


@pytest.mark.parametrize("make,code", [
    (lambda: scanned_pdf(note_lines()), "no_text_layer"),
    (lambda: text_pdf([[], []]), "no_text_layer"),
    (lambda: text_pdf([note_lines()], password="secret"), "encrypted_pdf"),
    (lambda: text_pdf([note_lines()])[:300], "corrupted_pdf"),
    (lambda: b"%PDF-1.7\n" + bytes(range(256)) * 10, "corrupted_pdf"),
    (lambda: text_pdf([["short"]]), "insufficient_text"),
])
def test_pdf_failures(make, code):
    with pytest.raises(ExtractionError) as exc:
        _extract("pdf", make())
    assert exc.value.code == code and exc.value.message


def test_scanned_pdf_keeps_partial_result_for_inspection():
    with pytest.raises(ExtractionError) as exc:
        _extract("pdf", scanned_pdf(note_lines()))
    assert exc.value.partial.page_count == 1 and exc.value.partial.warnings


def test_pdf_page_limit():
    with pytest.raises(ExtractionError) as exc:
        _extract("pdf", text_pdf([note_lines()] * 3), max_pages=2)
    assert exc.value.code == "too_many_pages"


# =========================================================================== metadata
def test_header_parsed():
    m = parse_header(note(admission_date="2026-03-10"), PATIENT)
    assert (m.document_type, m.patient_id, m.document_date) == ("Progress Note", PATIENT, date(2026, 3, 12))
    assert m.source_document_id == "DOC-PRG-003" and m.fields["ADMISSION DATE"] == "2026-03-10"


def test_header_tolerates_pdf_spacing():
    text = "DOCUMENT  TYPE :  Admission Note \n PATIENT ID: SYN-0001\nDOCUMENT DATE:2026-03-10\n---\nBODY:\nx\n"
    m = parse_header(text, PATIENT)
    assert m.document_type == "Admission Note" and m.source_document_id is None


@pytest.mark.parametrize("text,code", [
    ("PLAN:\nWarfarin held.\n", "missing_header"),
    ("DOCUMENT TYPE: Note\nPATIENT ID: SYN-0001\n---\n", "missing_field"),
    (header(document_date="12/03/2026") + "x", "invalid_date"),
    (header(admission_date="yesterday") + "x", "invalid_date"),
    (header(patient_id="SYN-9999") + "x", "patient_mismatch"),
    ("DOCUMENT TYPE: Note\nthis line is not a field\nPATIENT ID: SYN-0001\nDOCUMENT DATE: 2026-01-01\n---\n",
     "malformed_header"),
    ("DOCUMENT TYPE: A\nDOCUMENT TYPE: B\nPATIENT ID: SYN-0001\nDOCUMENT DATE: 2026-01-01\n---\n",
     "malformed_header"),
])
def test_header_errors(text, code):
    with pytest.raises(MetadataError) as exc:
        parse_header(text, PATIENT)
    assert exc.value.code == code


# =========================================================================== storage
def test_file_store_roundtrip_and_containment(tmp_path):
    store = FileStore(tmp_path / "uploads")
    name = store.save("DOC-0123456789ABCDEF", "pdf", b"%PDF-data")
    assert name == "DOC-0123456789ABCDEF.pdf" and store.read(name) == b"%PDF-data"
    assert list((tmp_path / "uploads").iterdir()) == [tmp_path / "uploads" / name]  # no temp files left
    assert store.delete(name) and not store.delete(name)
    for bad in ("../evil.pdf", "DOC-0123456789ABCDEF.exe", "CON", "..\\x.txt"):
        with pytest.raises(ValueError):
            store.save(bad.split(".")[0], "pdf", b"x") if bad == "CON" else store.read(bad)
