"""Upload validation. Runs before anything is written to disk or the database.

Rejected uploads are never stored. The file type is decided by extension AND content
(magic bytes, encoding); the client's Content-Type header is ignored because it is untrusted.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

from ..core.errors import AppError
from ..schemas.documents import FileFormat

ALLOWED_EXTENSIONS: dict[str, FileFormat] = {".pdf": "pdf", ".txt": "txt"}
MAX_FILENAME_CHARS = 200
_PDF_MAGIC = b"%PDF-"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class UploadRejected(AppError):
    def __init__(self, status_code: int, code: str, message: str, details=None):
        super().__init__(message, details)
        self.status_code = status_code
        self.code = code


def sanitize_filename(raw: str | None) -> str:
    """Display-only name. Never used to build a filesystem path.

    Drops any directory part (both / and \\ separators, so Windows paths from browsers are handled),
    control characters and leading dots, normalises Unicode and caps the length.
    """
    name = unicodedata.normalize("NFC", raw or "")
    name = name.replace("\\", "/")
    name = PurePosixPath(name).name
    name = _CONTROL.sub("", name).strip().lstrip(".")
    if len(name) > MAX_FILENAME_CHARS:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: MAX_FILENAME_CHARS - len(ext) - 1] + "." + ext) if dot and len(ext) <= 10 \
            else name[:MAX_FILENAME_CHARS]
    return name or "upload"


def validate_upload(filename: str, data: bytes, max_bytes: int) -> FileFormat:
    """Return the file format, or raise UploadRejected with an HTTP status and a stable error code."""
    if len(data) == 0:
        raise UploadRejected(422, "empty_file", "The uploaded file is empty (0 bytes).")
    if len(data) > max_bytes:
        raise UploadRejected(413, "file_too_large", f"File exceeds the {max_bytes:,} byte limit.",
                             {"max_bytes": max_bytes})

    suffix = PurePosixPath(filename.lower()).suffix
    fmt = ALLOWED_EXTENSIONS.get(suffix)
    if fmt is None:
        raise UploadRejected(415, "unsupported_type",
                             f"Unsupported file type '{suffix or '(none)'}'. Upload a .pdf or .txt file.",
                             {"allowed": sorted(ALLOWED_EXTENSIONS)})

    looks_like_pdf = _PDF_MAGIC in data[:1024]  # the PDF spec allows the header anywhere in the first 1 KB
    if fmt == "pdf" and not looks_like_pdf:
        raise UploadRejected(415, "content_mismatch", "File has a .pdf extension but is not a PDF.")
    if fmt == "txt":
        if looks_like_pdf:
            raise UploadRejected(415, "content_mismatch", "File has a .txt extension but contains a PDF.")
        if b"\x00" in data:
            raise UploadRejected(415, "binary_content", "File has a .txt extension but contains binary data.")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UploadRejected(422, "invalid_encoding",
                                 f"Text file is not valid UTF-8 (invalid byte at position {exc.start}). "
                                 f"Save it as UTF-8 and upload again.") from exc
    return fmt
