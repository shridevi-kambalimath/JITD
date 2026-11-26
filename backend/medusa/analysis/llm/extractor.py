"""LLM claim extraction with server-side verification.

The model proposes; deterministic code decides:
  * the reply must be JSON matching LlmResponse (Pydantic), else the call is a malformed_output failure;
  * each candidate must name a real passage of this document and a known category;
  * its quote must occur verbatim in that passage, else it is rejected (no fuzzy matching: an LLM that
    paraphrases has not cited anything);
  * offsets, the event date and the assertion are computed by the server from the passage, never taken
    from the model (the model's own assertion word is kept only for comparison);
  * a candidate the rules already found (same passage, same category, overlapping span) counts as agreement
    and is not stored twice.
Accepted claims carry extraction_method "llm:<provider>/<model>" so they are never shown as rule output.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...schemas.domain import Claim, Document, LlmAttrs, Passage, SourceRef
from ..assertion import classify
from ..dates import DateContext, extract_date, undated
from ..rule_extractor import claim_id
from .provider import LLMError, LLMProvider

CATEGORIES = ("medication", "diagnosis", "allergy", "lab_result", "symptom", "procedure", "encounter", "record_reference")
MAX_REJECTIONS_KEPT = 50


class LlmClaimCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    passage_id: str = Field(max_length=80)
    category: str = Field(max_length=40)
    entity: str = Field(default="", max_length=200)
    quote: str = Field(max_length=600)
    assertion: str | None = Field(default=None, max_length=40)
    statement: str | None = Field(default=None, max_length=400)


class LlmResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    claims: list[LlmClaimCandidate] = Field(default_factory=list, max_length=300)


SYSTEM_PROMPT = f"""You extract documented facts from SYNTHETIC clinical records for a documentation-review prototype.
Rules:
- Extract only what a passage explicitly states. Do not infer, diagnose, summarise or fill gaps.
- Every claim must include "quote": text copied EXACTLY, character for character, from the passage it cites.
  The quote must be the shortest span that states the fact. Never paraphrase the quote.
- "passage_id" must be one of the ids shown in square brackets.
- "category" must be one of: {", ".join(CATEGORIES)}.
- "entity": the thing mentioned (drug, condition, test, symptom, procedure, record), in plain words.
- "assertion": present, absent, possible, historical or family, as the passage words it.
- Do not output dates, offsets or confidence scores.
Answer with JSON only: {{"claims": [{{"passage_id": "...", "category": "...", "entity": "...", "quote": "...", "assertion": "...", "statement": "..."}}]}}"""


def build_prompt(doc: Document, passages: list[Passage]) -> str:
    lines = [f"Document type: {doc.document_type}", f"Document date: {doc.document_date}", "", "Passages:"]
    lines += [f"[{p.passage_id}] ({p.section}) {p.text}" for p in passages]
    return "\n".join(lines)


def parse_response(text: str) -> LlmResponse:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("malformed_output", "Reply contained no JSON object.")
    try:
        return LlmResponse.model_validate(json.loads(cleaned[start:end + 1]))
    except (ValueError, ValidationError) as exc:
        raise LLMError("malformed_output", f"Reply JSON did not match the expected schema ({exc.__class__.__name__}).") from None


@dataclass
class LlmExtraction:
    accepted: list[Claim] = field(default_factory=list)
    agreed_with_rules: int = 0
    rejected: list[dict[str, str]] = field(default_factory=list)
    rejected_count: int = 0

    def reject(self, cand: LlmClaimCandidate, reason: str, document_id: str) -> None:
        self.rejected_count += 1
        if len(self.rejected) < MAX_REJECTIONS_KEPT:
            self.rejected.append({"document_id": document_id, "passage_id": cand.passage_id, "category": cand.category,
                                  "reason": reason, "quote": cand.quote[:160]})


def verify_candidates(doc: Document, passages: list[Passage], response: LlmResponse, rule_claims: list[Claim],
                      ctx: DateContext, provider_name: str) -> LlmExtraction:
    out = LlmExtraction()
    by_id = {p.passage_id: p for p in passages}
    seen: set[str] = set()
    for cand in response.claims:
        if cand.category not in CATEGORIES:
            out.reject(cand, "unknown_category", doc.document_id)
            continue
        p = by_id.get(cand.passage_id)
        if p is None:
            out.reject(cand, "unknown_passage", doc.document_id)
            continue
        if not cand.quote.strip():
            out.reject(cand, "empty_quote", doc.document_id)
            continue
        idx = p.text.find(cand.quote)
        if idx == -1:
            out.reject(cand, "quote_not_in_passage", doc.document_id)
            continue
        start = p.char_start + idx
        end = start + len(cand.quote)
        if any(c.source.passage_id == p.passage_id and c.claim_type == cand.category
               and c.source.entity_char_start < end and start < c.source.entity_char_end for c in rule_claims):
            out.agreed_with_rules += 1
            continue
        entity = " ".join(cand.entity.split()).lower()[:120] or cand.quote.lower()[:120]
        server_assertion = (classify(p.text, idx, idx + len(cand.quote), p.section)[0]
                            if cand.category in ("diagnosis", "symptom") else None)
        cid = claim_id(doc.document_id, start, end, cand.category, entity, "llm")
        if cid in seen:
            continue
        seen.add(cid)
        out.accepted.append(Claim(
            claim_id=cid, patient_id=doc.patient_id, claim_type=cand.category, entity=entity, surface=cand.quote,
            attributes=LlmAttrs(statement=cand.statement, model_assertion=cand.assertion, assertion=server_assertion),
            source=SourceRef(document_id=doc.document_id, passage_id=p.passage_id, section=p.section,
                             char_start=p.char_start, char_end=p.char_end, evidence_text=p.text,
                             entity_char_start=start, entity_char_end=end),
            document_date=doc.document_date, document_type=doc.document_type,
            event_date=extract_date(p.text, ctx) or undated(), extraction_method=f"llm:{provider_name}"))
    return out


def extract_with_llm(provider: LLMProvider, doc: Document, passages: list[Passage], rule_claims: list[Claim],
                     ctx: DateContext) -> LlmExtraction:
    reply = provider.complete_json(SYSTEM_PROMPT, build_prompt(doc, passages))
    return verify_candidates(doc, passages, parse_response(reply), rule_claims, ctx, provider.name)
