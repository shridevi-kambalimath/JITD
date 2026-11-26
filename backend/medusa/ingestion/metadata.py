"""Document header metadata.

Synthetic documents start with a header block terminated by a line containing only '---':

    DOCUMENT TYPE: Admission Note        (required)
    PATIENT ID: SYN-0001                 (required; must match the patient the file is uploaded to)
    DOCUMENT DATE: 2026-03-10            (required, ISO date)
    DOCUMENT ID: DOC-ADM-001             (optional; kept as source_document_id)
    ADMISSION DATE: 2026-03-10           (optional; any '... DATE' field must be an ISO date)
    ---

A document without a valid header fails processing. Downstream modules need its date and type,
and guessing them would put unsupported facts into the evidence chain.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from . import IngestionError

REQUIRED_FIELDS = ("DOCUMENT TYPE", "PATIENT ID", "DOCUMENT DATE")
MAX_HEADER_LINES = 60
MAX_VALUE_CHARS = 500
_FIELD = re.compile(r"^\s*([A-Za-z][A-Za-z ]{0,40}?)\s*:\s*(.*?)\s*$")


@dataclass(frozen=True)
class HeaderMetadata:
    document_type: str
    patient_id: str
    document_date: date
    source_document_id: str | None
    fields: dict[str, str]


class MetadataError(IngestionError):
    pass


def parse_header(text: str, expected_patient_id: str) -> HeaderMetadata:
    lines = text.split("\n")
    try:
        end = next(i for i, ln in enumerate(lines[:MAX_HEADER_LINES + 1]) if ln.strip() == "---")
    except StopIteration:
        raise MetadataError("missing_header",
                            "No document header found: expected 'KEY: value' lines ending with a '---' line "
                            "at the top of the document.") from None

    fields: dict[str, str] = {}
    for n, line in enumerate(lines[:end], start=1):
        if not line.strip():
            continue
        m = _FIELD.match(line)
        if not m:
            raise MetadataError("malformed_header", f"Header line {n} is not 'KEY: value': {line.strip()[:80]!r}")
        key, value = " ".join(m.group(1).upper().split()), m.group(2)
        if key in fields and fields[key] != value:
            raise MetadataError("malformed_header", f"Header field {key!r} appears twice with different values.")
        if len(value) > MAX_VALUE_CHARS:
            raise MetadataError("malformed_header", f"Header field {key!r} is longer than {MAX_VALUE_CHARS} characters.")
        fields[key] = value

    missing = [f for f in REQUIRED_FIELDS if not fields.get(f)]
    if missing:
        raise MetadataError("missing_field", f"Required header field(s) missing: {', '.join(missing)}.")

    dates: dict[str, date] = {}
    for key, value in fields.items():
        if key.endswith(" DATE"):
            try:
                dates[key] = date.fromisoformat(value)
            except ValueError:
                raise MetadataError("invalid_date", f"{key} must be an ISO date (YYYY-MM-DD), got {value!r}.") from None

    if fields["PATIENT ID"] != expected_patient_id:
        raise MetadataError("patient_mismatch",
                            f"Document header says PATIENT ID {fields['PATIENT ID']!r} but it was uploaded to "
                            f"patient {expected_patient_id!r}.")

    return HeaderMetadata(document_type=fields["DOCUMENT TYPE"], patient_id=fields["PATIENT ID"],
                          document_date=dates["DOCUMENT DATE"], source_document_id=fields.get("DOCUMENT ID") or None,
                          fields=fields)
