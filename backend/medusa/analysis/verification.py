"""Deterministic evidence verification, per claim.

A claim is `verified` only if every hard check passes. Checks re-read the stored document
text, so a claim whose span was altered, invented or mis-attributed is caught here
regardless of how it was produced (rules or a quote-verified LLM proposal).

Hard checks (all must pass): V1 source document exists for this patient, V2 passage exists in that document,
V3 cited span equals the stored text, V4 offsets lie inside the passage, V5 the entity text at its offsets is
the quoted surface, V6 the event date is not after the document date. Advisory: V7 the passage is found by
keyword search for the entity (shows the evidence is discoverable, never decides anything).
"""
from __future__ import annotations

from ..schemas.domain import CheckResult, Claim, Document, Passage, Verification
from .retrieval import EvidenceIndex

VERIFY_RETRIEVAL_TOP_K = 10


def _date_not_after(claim: Claim) -> tuple[bool, str]:
    ev, doc_date = claim.event_date, claim.document_date
    if ev.value is None or doc_date is None:
        return True, "not applicable (event date or document date not stated)"
    if ev.precision == "year":
        ok = ev.value.year <= doc_date.year
    elif ev.precision == "month":
        ok = (ev.value.year, ev.value.month) <= (doc_date.year, doc_date.month)
    else:
        ok = ev.value <= doc_date
    return ok, f"event {ev.display()} vs document {doc_date.isoformat()}"


def verify_claim(claim: Claim, docs: dict[str, Document], passages: dict[str, Passage],
                 index: EvidenceIndex | None = None) -> Verification:
    s = claim.source
    checks: list[CheckResult] = []

    def add(check_id: str, passed: bool, detail: str, severity: str = "hard") -> None:
        checks.append(CheckResult(check_id=check_id, passed=passed, severity=severity, detail=detail))

    doc = docs.get(s.document_id)
    add("V1_source_document_exists", doc is not None and doc.patient_id == claim.patient_id,
        f"document {s.document_id}" + ("" if doc else " not found"))

    p = passages.get(s.passage_id)
    add("V2_passage_exists", p is not None and p.document_id == s.document_id,
        f"passage {s.passage_id}" + ("" if p else " not found"))

    if doc is not None:
        actual = doc.text[s.char_start:s.char_end]
        add("V3_span_exact_match", actual == s.evidence_text,
            "stored text matches cited span" if actual == s.evidence_text else f"stored text is {actual!r}")
        entity_text = doc.text[s.entity_char_start:s.entity_char_end]
        add("V5_entity_grounded", entity_text.lower() == claim.surface.lower(),
            f"entity text at offsets is {entity_text!r}")
    else:
        add("V3_span_exact_match", False, "document unavailable")
        add("V5_entity_grounded", False, "document unavailable")

    within = (p is not None and p.char_start <= s.char_start and s.char_end <= p.char_end
              and s.char_start <= s.entity_char_start and s.entity_char_end <= s.char_end)
    add("V4_span_within_passage", within, "span and entity offsets inside passage" if within else "offsets out of bounds")

    ok, detail = _date_not_after(claim)
    add("V6_event_not_after_document", ok, detail)

    refs: list[str] = []
    if index is not None and s.section != "HEADER":
        hits = index.search(claim.surface if claim.claim_type != "encounter" else claim.entity,
                            k=VERIFY_RETRIEVAL_TOP_K)
        refs = [h.passage_id for h in hits[:5]]
        found = any(h.passage_id == s.passage_id for h in hits)
        add("V7_retrievable", found, f"passage {'in' if found else 'not in'} top {VERIFY_RETRIEVAL_TOP_K} keyword hits",
            severity="advisory")
    else:
        add("V7_retrievable", True, "not applicable (header field)", severity="advisory")

    checks.sort(key=lambda c: c.check_id)
    verified = all(c.passed for c in checks if c.severity == "hard")
    return Verification(claim_id=claim.claim_id, verified=verified, checks=checks, retrieval_refs=refs)


def verify_all(claims: list[Claim], docs: list[Document], passages: list[Passage],
               index: EvidenceIndex | None = None) -> list[Verification]:
    d = {x.document_id: x for x in docs}
    p = {x.passage_id: x for x in passages}
    return [verify_claim(c, d, p, index) for c in claims]
