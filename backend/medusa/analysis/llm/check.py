"""Live LLM connection check. Run from the backend folder:

    python -m medusa.analysis.llm.check

Sends one tiny synthetic passage through the real provider and the real verification step, then prints
what happened. Prints no secrets. Exit code 0 = working, 1 = not working, 2 = LLM disabled.
"""
from __future__ import annotations

import sys
from datetime import date

from ...core.config import get_settings
from ...schemas.domain import Document, Passage
from ..dates import DateContext
from .extractor import extract_with_llm
from .provider import LLMError, build_provider, llm_configuration

TEXT = "PLAN:\nWarfarin held due to upper gastrointestinal bleed."


def main() -> int:
    settings = get_settings()
    status, reason = llm_configuration(settings)
    print(f"Provider: {settings.llm_provider}   Model: {settings.llm_model or '(not set)'}   Status: {status}")
    if status == "disabled":
        print("LLM extraction is disabled (MEDUSA_LLM_PROVIDER=none). Rules-only analysis works without it.")
        return 2
    if status == "misconfigured":
        print(f"Not usable: {reason}")
        return 1
    provider = build_provider(settings)
    assert provider is not None
    doc = Document(document_id="DOC-CHECK000000000", patient_id="CHECK", document_type="Progress Note",
                   document_date=date(2026, 3, 12), metadata={}, text=TEXT, filename="check.txt", sha256="-")
    passage = Passage(passage_id="DOC-CHECK000000000:P001", document_id=doc.document_id, section="PLAN",
                      char_start=6, char_end=len(TEXT), text=TEXT[6:])
    try:
        result = extract_with_llm(provider, doc, [passage], [], DateContext(document_date=doc.document_date))
    except LLMError as exc:
        print(f"FAILED ({exc.code}): {exc.message}")
        return 1
    print(f"OK: {len(result.accepted)} claim(s) accepted, {result.rejected_count} rejected by quote verification.")
    for c in result.accepted:
        print(f"  {c.claim_type:<12} {c.entity!r:<30} quote={c.surface!r}")
    for r in result.rejected:
        print(f"  rejected: {r['reason']} quote={r['quote']!r}")
    return 0 if result.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
