"""Evidence-linked summary, assembled from templates over verified claims and gated findings.

There is no free-text generation: every content line restates stored claims and cites them, so the summary
cannot say anything that is not in a cited, verified passage. Conflicting and insufficient items are labelled
with their evidence state and are never smoothed into a single version. Only count lines carry no citation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from ..schemas.analysis import AnalysisStatus, ClaimRecord
from ..schemas.domain import EvidenceState, Finding
from ..schemas.summary import Citation, EvidenceSummary, SummaryLine, SummarySection

S = EvidenceState
DISCLAIMER = ("Synthetic demonstration data. MEDUSA-X reconstructs what the supplied records state and where they "
              "disagree. It does not diagnose, recommend treatment, prescribe, or decide which conflicting record is "
              "clinically correct. Evidence states describe what the documents establish, not clinical truth. Every "
              "item requires review by a qualified clinician.")
STATE_TEXT = {S.SUPPORTED: "Evidence-supported", S.CONFLICTING: "Conflicting evidence",
              S.INSUFFICIENT: "Insufficient evidence", S.REVIEW: "Review required"}


def _cite(c: ClaimRecord) -> Citation:
    p = c.source.passage_id.split(":")[-1]
    return Citation(claim_id=c.claim_id, document_id=c.source.document_id, document_type=c.document_type,
                    section=c.source.section, passage_id=c.source.passage_id,
                    label=f"{c.document_type}, {c.source.section}, {p}")


def _when(c: ClaimRecord) -> str:
    if c.event_date.value:
        return c.event_date.display()
    return f"document dated {c.document_date.isoformat()}" if c.document_date else "undated"


def _ordered(cs: list[ClaimRecord]) -> list[ClaimRecord]:
    return sorted(cs, key=lambda c: (c.effective_date() is None, c.effective_date() or datetime.max.date(),
                                     c.source.document_id, c.source.entity_char_start))


def build_summary(status: AnalysisStatus, claims: list[ClaimRecord], findings: list[Finding]) -> EvidenceSummary:
    usable = {c.claim_id: c for c in claims if c.verified}  # only verified claims are restated

    def vc(ids) -> list[ClaimRecord]:
        return _ordered([usable[i] for i in ids if i in usable])

    def line(text: str, cs: list[ClaimRecord], f: Finding | None = None) -> SummaryLine:
        return SummaryLine(text=text, citations=[_cite(c) for c in cs], state=f.state if f else None,
                           finding_id=f.finding_id if f else None)

    def labelled(f: Finding, text: str) -> str:
        return text if f.state in (None, S.SUPPORTED) else f"[{STATE_TEXT[f.state]}] {text}"

    sections: list[SummarySection] = []
    add = lambda key, title, desc, lines: sections.append(SummarySection(key=key, title=title, description=desc, lines=lines))

    # scope
    enc = defaultdict(list)
    for c in usable.values():
        if c.claim_type == "encounter":
            enc[(c.entity, c.event_date.display())].append(c)
    add("encounter", "Encounter", "Admission and discharge dates as documented.",
        [line(f"{e.capitalize()} documented as {d}.", cs) for (e, d), cs in sorted(enc.items(), key=lambda kv: kv[0][1])])

    counts = defaultdict(int)
    for f in findings:
        if f.state:
            counts[f.state] += 1
    add("states", "Evidence states", "How many reconciled subjects fall in each state.",
        [SummaryLine(text=f"{STATE_TEXT[s]}: {counts[s]} subject(s).", citations=[], state=s, kind="count")
         for s in (S.REVIEW, S.CONFLICTING, S.INSUFFICIENT, S.SUPPORTED)])

    # unresolved issues, first after the counts so they are not missed
    unresolved = []
    for f in sorted(findings, key=lambda f: [S.REVIEW, S.CONFLICTING, S.INSUFFICIENT, S.SUPPORTED].index(f.state)
                    if f.state else 9):
        if f.state in (None, S.SUPPORTED):
            continue
        for i in f.issues:
            cs = vc(i.claim_ids)
            unresolved.append(line(labelled(f, i.description), cs or vc(f.claim_ids), f))
    add("unresolved", "Unresolved issues", "Potential documentation discrepancies and missing information. "
        "The system does not decide which record is correct.", unresolved)

    def by_category(cat: str, render) -> list[SummaryLine]:
        return [line(labelled(f, render(f, cs)), cs, f) for f in findings if f.category == cat and (cs := vc(f.claim_ids))]

    add("diagnoses", "Diagnoses as documented", "Each diagnosis with every assertion the records make about it.",
        by_category("diagnosis", lambda f, cs: f"{f.subject.capitalize()}: " + "; ".join(
            f"{c.attributes.assertion} ({c.document_type}, {_when(c)})" for c in cs) + "."))

    def med(f, cs):
        parts = []
        for c in cs:
            a = c.attributes
            alias = f" as “{c.surface}”" if c.surface.lower() != c.entity else ""
            parts.append(f"{a.action.replace('_', ' ')}{alias}, {a.regimen()} ({c.document_type}, {_when(c)})")
        return f"{f.subject.capitalize()}: " + "; ".join(parts) + "."
    add("medications", "Medication mentions", "Every documented mention, in date order, with the list it appears on.",
        by_category("medication", med))

    def allergy(f, cs):
        return "Allergies: " + "; ".join(
            ("no known drug allergies" if c.attributes.no_known_allergies else
             c.attributes.substance + (f" ({c.attributes.reaction})" if c.attributes.reaction else ""))
            + f" ({c.document_type}, {_when(c)})" for c in cs) + "."
    add("allergies", "Allergies as documented", "Allergy statements from every record.", by_category("allergy", allergy))

    procs = [c for c in _ordered(list(usable.values())) if c.claim_type == "procedure"]
    add("procedures", "Procedures", "Procedures documented as performed.",
        [line(f"{c.entity.capitalize()} ({c.document_type}, {_when(c)}).", [c]) for c in procs])

    labs = [c for c in _ordered(list(usable.values())) if c.claim_type == "lab_result"]

    def lab(c):
        a = c.attributes
        flag = f", flagged {a.flag} in the report" if a.flag else ", no flag printed"
        ref = f", reference {a.reference_range}" if a.reference_range else ""
        name = c.entity.upper() if len(c.entity) <= 3 else c.entity.capitalize()
        reported = f", report dated {c.document_date.isoformat()}" if c.document_date else ""
        return f"{name} {a.value:g}{' ' + a.unit if a.unit else ''}{flag}{ref} (collected {_when(c)}{reported})."
    add("labs", "Laboratory mentions", "Values and flags exactly as printed; nothing is computed or interpreted.",
        [line(lab(c), [c]) for c in labs])

    symptoms = [c for c in _ordered(list(usable.values())) if c.claim_type == "symptom"]
    add("symptoms", "Symptoms", "Symptoms documented as present, with their onset as stated.",
        [line(f"{c.entity.capitalize()} (“{c.surface}”, {c.document_type}, onset {_when(c)}).", [c])
         for c in symptoms])

    observations = [line(f"{f.subject.capitalize()}: {o.text}", vc(o.claim_ids or f.claim_ids), f)
                    for f in findings for o in f.observations if vc(o.claim_ids or f.claim_ids)]
    add("observations", "Patterns examined and not flagged", "Where a rule looked at a pattern and found it explained "
        "by the records (a documented change, diagnostic evolution, family history).", observations)

    dated = [c for c in _ordered(list(usable.values()))
             if c.event_date.value and c.claim_type in ("encounter", "symptom", "procedure", "lab_result")]
    add("timeline", "Timeline of dated events", "Events whose own passage states a date, in date order.",
        [line(f"{c.event_date.display()}: {c.claim_type.replace('_', ' ')}, {c.entity} ({c.document_type}).", [c])
         for c in dated])

    return EvidenceSummary(patient_id=status.patient_id,
                           results_run_id=status.results_run.run_id if status.results_run else None,
                           is_current=status.is_current, stale_reason=status.stale_reason,
                           generated_at=datetime.now(timezone.utc), disclaimer=DISCLAIMER, sections=sections)


def to_markdown(s: EvidenceSummary) -> str:
    out = [f"# Evidence-linked reconstruction: {s.patient_id}", "",
           f"Analysis run {s.results_run_id or 'none'} · generated {s.generated_at:%Y-%m-%d %H:%M} UTC", "",
           f"> {s.disclaimer}", ""]
    if not s.is_current and s.results_run_id:
        out += [f"> **Out of date:** {s.stale_reason}", ""]
    for sec in s.sections:
        out += [f"## {sec.title}", "", f"_{sec.description}_", ""]
        if not sec.lines:
            out.append("- None identified by the rules.")
        for ln in sec.lines:
            refs = "; ".join(c.label for c in ln.citations)
            out.append(f"- {ln.text}" + (f" [{refs}]" if refs else ""))
        out.append("")
    return "\n".join(out)
