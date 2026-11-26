"""Text extraction for TXT and PDF, followed by quality gates.

Rules
* PDFs are never assumed to contain text. Pages without a text layer produce a warning; a PDF with
  no extractable text on any page fails with `no_text_layer`. OCR is out of scope for the prototype.
* An empty, too-short or unreadable extraction is never accepted. It fails with a specific code.
* The returned text is normalised once (newlines, Unicode NFC, control characters). It becomes the
  canonical text of the document: every later character offset indexes into it.
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field

from . import IngestionError

logger = logging.getLogger("medusa.ingestion")

PAGE_SEPARATOR = "\n\n"
_CONTROL_EXCEPT_WS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MIN_PRINTABLE_RATIO = 0.95
MAX_REPLACEMENT_RATIO = 0.01


@dataclass
class ExtractionResult:
    text: str
    method: str
    page_count: int | None = None
    page_spans: list[tuple[int, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ExtractionError(IngestionError):
    def __init__(self, code: str, message: str, partial: ExtractionResult | None = None):
        super().__init__(code, message)
        self.partial = partial


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return _CONTROL_EXCEPT_WS.sub("", text)


def _extract_txt(data: bytes) -> ExtractionResult:
    try:
        text = data.decode("utf-8-sig")  # strips a UTF-8 byte order mark written by some Windows editors
    except UnicodeDecodeError as exc:  # validation normally catches this first
        raise ExtractionError("invalid_encoding", "Text file is not valid UTF-8.") from exc
    return ExtractionResult(text=normalize_text(text), method="utf8_text")


def _extract_pdf(data: bytes, max_pages: int) -> ExtractionResult:
    from pypdf import PdfReader
    from pypdf.errors import DependencyError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except (DependencyError, NotImplementedError) as exc:
                raise ExtractionError("encrypted_pdf", "PDF is encrypted with an unsupported method.") from exc
            if not unlocked:
                raise ExtractionError("encrypted_pdf", "PDF is password protected. Upload an unprotected copy.")
        page_count = len(reader.pages)
    except ExtractionError:
        raise
    except Exception as exc:  # pypdf raises many exception types for malformed files
        logger.info("PDF could not be opened: %s: %s", exc.__class__.__name__, exc)
        raise ExtractionError("corrupted_pdf", f"PDF could not be read ({exc.__class__.__name__}). "
                                               f"The file may be damaged or truncated.") from exc

    if page_count == 0:
        raise ExtractionError("corrupted_pdf", "PDF contains no pages.")
    if page_count > max_pages:
        raise ExtractionError("too_many_pages", f"PDF has {page_count} pages; the limit is {max_pages}.")

    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    warnings: list[str] = []
    unreadable = 0
    cursor = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            page_text = normalize_text(page.extract_text() or "").strip("\n")
            if not page_text.strip():
                warnings.append(f"Page {i} has no extractable text (it may be a scanned image); "
                                f"its content is not included.")
                page_text = ""
        except Exception as exc:  # one damaged page must not hide the readable ones
            unreadable += 1
            warnings.append(f"Page {i} could not be read ({exc.__class__.__name__}); its content is not included.")
            page_text = ""
        if parts:
            cursor += len(PAGE_SEPARATOR)
        spans.append((cursor, cursor + len(page_text)))
        parts.append(page_text)
        cursor += len(page_text)

    text = PAGE_SEPARATOR.join(parts)
    result = ExtractionResult(text=text, method="pdf_text_layer", page_count=page_count, page_spans=spans,
                              warnings=warnings)
    if unreadable == page_count:
        raise ExtractionError("corrupted_pdf", "No page of the PDF could be read.", partial=result)
    if not text.strip():
        raise ExtractionError(
            "no_text_layer",
            f"No extractable text on any of the {page_count} page(s). The PDF is probably scanned images. "
            f"OCR is not enabled in this prototype: upload a text-based PDF or a .txt file.",
            partial=result)
    return result


def _quality_gate(result: ExtractionResult, min_chars: int) -> None:
    stripped = result.text.strip()
    if not stripped:
        raise ExtractionError("empty_text", "The document contains no text (only whitespace).", partial=result)
    if len(stripped) < min_chars:
        raise ExtractionError("insufficient_text",
                              f"Only {len(stripped)} characters of text were extracted; at least {min_chars} "
                              f"are required.", partial=result)
    printable = sum(1 for c in stripped if c.isprintable() or c in "\n\t")
    if printable / len(stripped) < MIN_PRINTABLE_RATIO:
        raise ExtractionError("unreadable_text", "Extracted text is mostly non-printable characters.", partial=result)
    if stripped.count("�") / len(stripped) > MAX_REPLACEMENT_RATIO:
        raise ExtractionError("unreadable_text",
                              "Extracted text contains many undecodable characters (font encoding problem).",
                              partial=result)


def extract_text(file_format: str, data: bytes, *, max_pdf_pages: int, min_chars: int) -> ExtractionResult:
    if file_format == "txt":
        result = _extract_txt(data)
    elif file_format == "pdf":
        result = _extract_pdf(data, max_pdf_pages)
    else:
        raise ExtractionError("unsupported_type", f"No extractor for format '{file_format}'.")
    _quality_gate(result, min_chars)
    return result
