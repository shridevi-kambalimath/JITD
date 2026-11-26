"""Builders for synthetic test inputs. Every patient, document and value here is fictional."""
from __future__ import annotations

import io

PATIENT = "SYN-0001"


def header(patient_id: str = PATIENT, document_type: str = "Progress Note", document_date: str = "2026-03-12",
           document_id: str | None = "DOC-PRG-003", **extra: str) -> str:
    lines = [f"DOCUMENT TYPE: {document_type}"]
    if document_id:
        lines.append(f"DOCUMENT ID: {document_id}")
    lines += [f"PATIENT ID: {patient_id}", f"DOCUMENT DATE: {document_date}"]
    lines += [f"{k.replace('_', ' ').upper()}: {v}" for k, v in extra.items()]
    return "\n".join(lines) + "\n---\n"


def note(patient_id: str = PATIENT, body: str = "PLAN:\nWarfarin held due to upper gastrointestinal bleed.\n",
         **kw) -> str:
    return header(patient_id, **kw) + body


def note_lines(patient_id: str = PATIENT, **kw) -> list[str]:
    return note(patient_id, **kw).rstrip("\n").split("\n")


def text_pdf(pages: list[list[str]], password: str | None = None) -> bytes:
    """A text-layer PDF; each inner list is the lines of one page. An empty list makes a blank page."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, encrypt=password) if password else canvas.Canvas(buf)
    for lines in pages:
        y = 800
        for line in lines:
            c.drawString(50, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


def scanned_pdf(lines: list[str]) -> bytes:
    """An image-only PDF: the text is drawn into a picture, so there is no text layer (like a scan)."""
    from PIL import Image, ImageDraw
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = Image.new("RGB", (1200, 900), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((40, 40 + i * 28), line, fill="black")
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawImage(ImageReader(img_buf), 30, 200, width=540, height=405)
    c.showPage()
    c.save()
    return buf.getvalue()


def insert_raw_document(conn, document_id: str = "DOC-0000000000000001", patient_id: str = "P1",
                        status: str = "uploaded") -> None:
    """Direct row insert for database-level tests (bypasses the ingestion service on purpose)."""
    conn.execute(
        "INSERT INTO documents (document_id, patient_id, filename, file_format, size_bytes, sha256, storage_path, "
        "status, error_code, uploaded_at, updated_at) VALUES (?, ?, 'f.txt', 'txt', 10, 'x', '', ?, ?, "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
        (document_id, patient_id, status, "test" if status == "failed" else None))
