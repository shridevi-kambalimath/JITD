"""Reconciliation: potential documentation discrepancies across documents.

This module reports incompatibility between records. It never decides which record is
correct: no majority voting, no recency preference, no source-authority override.
Patterns that look like conflicts but are explained by the records themselves (documented
dose change, diagnostic evolution, family history) become Observations, so the UI can show
why they were not flagged.

Rule ids are referenced in docs/ARCHITECTURE.md section 5.

Input is rule-extracted claims only. LLM claims carry no structured attributes (action, dose, list
context), so they cannot be compared field by field; they stay visible as evidence but are not reconciled.
"""
from __future__ import annotations

import re
from collections import defaultdict

from ..schemas.domain import ISSUE_KIND, Claim, Finding, InvestigationStep, Issue, LlmAttrs, Observation
from . import lexicon as lx
from .retrieval import EvidenceIndex

# Prototype risk configuration, chosen to demonstrate risk-weighted escalation. Not a clinical standard.
HIGH_RISK_DRUG_CLASSES = frozenset({"anticoagulant", "insulin", "opioid"})
ALLERGY_FINDINGS_ARE_HIGH_RISK = True

_RESOLVING_TERMS = {
    "restarted": r"restarted|re-started|resumed|recommenced",
    "discontinued": r"discontinued|stopped|ceased",
    "changed": r"changed|switched|increased|decreased|reduced|titrated",
}


def _issue(issue_type: str, rule_id: str, description: str, claims: list[Claim]) -> Issue:
    return Issue(issue_type=issue_type, kind=ISSUE_KIND[issue_type], rule_id=rule_id, description=description,
                 claim_ids=list(dict.fromkeys(c.claim_id for c in claims)))


def _src(c: Claim) -> str:
    d = c.effective_date()
    return f"{c.document_type}, {d.isoformat() if d else 'undated'}"


def _order(claims: list[Claim]) -> list[Claim]:
    return sorted(claims, key=lambda c: (c.effective_date() is None, c.effective_date(), c.source.document_id,
                                         c.source.char_start))


# ============================================================================ medications
def _investigate(drug: str, category: str, rule_id: str, all_claims: list[Claim], index: EvidenceIndex | None
                 ) -> tuple[InvestigationStep | None, list[str]]:
    """INV-01: section-scoped search for resolving evidence the sentence-level extractor did not capture.

    A passage is a candidate if it contains a resolving term and either names this drug, or names no
    drug at all while the previous passage in the same section names this drug (anaphora, e.g. 'It was
    resumed'). A candidate is 'unextracted' when no claim for this drug with the matching action was
    extracted from it.
    """
    if index is None:
        return None, []
    term_re = re.compile(rf"\b({_RESOLVING_TERMS[category]})\b", re.IGNORECASE)
    query = f"{drug} " + _RESOLVING_TERMS[category].replace("|", " ")
    hits = index.search_sections(query, k=5)
    captured = {c.source.passage_id for c in all_claims
                if c.claim_type == "medication" and c.entity == drug and c.attributes.action == category}
    unextracted_passages: list[str] = []
    for hit in hits:
        group = index.section_by_first.get(hit.passage_id, [])
        for i, p in enumerate(group):
            if not term_re.search(p.text):
                continue
            drugs_here = {m.canonical for m in lx.find_drugs(p.text)}
            prev_has_drug = i > 0 and drug in {m.canonical for m in lx.find_drugs(group[i - 1].text)}
            candidate = drug in drugs_here or (not drugs_here and prev_has_drug)
            if candidate and p.passage_id not in captured:
                unextracted_passages.append(p.passage_id)
    if unextracted_passages:
        outcome = (f"Found possible '{category}' evidence not captured as a claim in "
                   f"{', '.join(unextracted_passages)}. Extraction may be incomplete; not used to resolve anything.")
    else:
        outcome = f"No uncaptured '{category}' evidence for {drug} in {len(hits)} section(s) searched."
    step = InvestigationStep(rule_id=rule_id, query=query, scope="section", hits=hits, outcome=outcome)
    return step, unextracted_passages


def _reconcile_medication(drug: str, claims: list[Claim], verified: list[Claim], has_discharge_list: bool,
                          all_claims: list[Claim], index: EvidenceIndex | None) -> Finding:
    f = Finding(finding_id=f"FND-MED-{lx.slug(drug)}", patient_id=claims[0].patient_id, category="medication",
                subject=drug, claim_ids=[c.claim_id for c in claims])
    cls = lx.drug_class(drug)
    if cls in HIGH_RISK_DRUG_CLASSES:
        f.high_risk, f.risk_reason = True, f"drug class '{cls}' is configured as high risk"

    v = _order(verified)
    active = [c for c in v if c.attributes.action == "listed_active"]
    stops = [c for c in v if c.attributes.action in ("held", "discontinued")]
    restarts = [c for c in v if c.attributes.action == "restarted"]
    changes = [c for c in v if c.attributes.action in ("changed", "started", "restarted")]
    investigate: list[str] = []

    # MED-STATUS-01
    for s in stops:
        for a in active:
            ds, da = s.effective_date(), a.effective_date()
            if ds is None or da is None or ds > da or s.source.document_id == a.source.document_id:
                continue
            if any(ds <= r.effective_date() <= da for r in restarts if r.effective_date()):
                continue
            same_day = " (same date; order within the day is not documented)" if ds == da else ""
            f.issues.append(_issue(
                "medication_status_conflict", "MED-STATUS-01",
                f"{drug.capitalize()} documented as {s.attributes.action} ({_src(s)}) but listed as active "
                f"({_src(a)}){same_day}. No restart is documented between these dates.", [s, a]))
            investigate.append("restarted")

    # MED-DOSE-01 / MED-CHANGE-01
    by_dose: dict[tuple, list[Claim]] = defaultdict(list)
    for a in active:
        if a.attributes.daily_dose is not None:
            by_dose[(a.attributes.daily_dose, a.attributes.dose_unit)].append(a)
    if len(by_dose) > 1:
        dated = [c.effective_date() for c in active if c.effective_date()]
        lo, hi = min(dated), max(dated)
        explaining = [c for c in changes if c.effective_date() and lo <= c.effective_date() <= hi]
        variants = "; ".join(
            f"{group[0].attributes.regimen()} [{'; '.join(_src(c) for c in group)}]" for group in by_dose.values())
        if explaining:
            f.observations.append(Observation(
                rule_id="MED-CHANGE-01",
                text=f"Different regimens listed ({variants}), and a regimen change is documented "
                     f"({'; '.join(_src(c) for c in explaining)}). Not flagged as a discrepancy.",
                claim_ids=[c.claim_id for c in active + explaining]))
        else:
            f.issues.append(_issue("medication_dose_discrepancy", "MED-DOSE-01",
                                   f"Daily dose differs between medication lists: {variants}. "
                                   f"No dose change is documented.", active))
            investigate.append("changed")
    for c in v:
        if c.attributes.action == "changed":
            f.observations.append(Observation(
                rule_id="MED-CHANGE-01", text=f"Regimen change documented: '{c.source.evidence_text}' ({_src(c)}).",
                claim_ids=[c.claim_id]))

    # MED-OMIT-01
    on_admission = [c for c in v if c.attributes.list_context == "admission"]
    on_discharge = [c for c in v if c.attributes.list_context == "discharge"]
    discontinued = [c for c in v if c.attributes.action == "discontinued"]
    if on_admission and has_discharge_list and not on_discharge and not discontinued:
        held = [c for c in v if c.attributes.action == "held"]
        extra = f" A hold is documented ({'; '.join(_src(c) for c in held)}), but no discontinuation." if held else ""
        f.issues.append(_issue("unexplained_discharge_omission", "MED-OMIT-01",
                               f"{drug.capitalize()} is listed on admission ({_src(on_admission[0])}) but not on the "
                               f"discharge medication list, and no discontinuation is documented.{extra} "
                               f"Status at discharge cannot be established from the records.",
                               on_admission + held))
        investigate.append("discontinued")

    # INV-01
    for category in dict.fromkeys(investigate):
        step, unextracted = _investigate(drug, category, "INV-01", all_claims, index)
        if step:
            f.investigation.append(step)
        if unextracted:
            f.issues.append(Issue(issue_type="possible_unextracted_evidence", kind="integrity", rule_id="INV-01",
                                  description=step.outcome, claim_ids=[]))
    return f


# ============================================================================ diagnoses
def _reconcile_diagnosis(entity: str, claims: list[Claim], verified: list[Claim]) -> Finding:
    f = Finding(finding_id=f"FND-DX-{lx.slug(entity)}", patient_id=claims[0].patient_id, category="diagnosis",
                subject=entity, claim_ids=[c.claim_id for c in claims])
    v = _order(verified)
    present = [c for c in v if c.attributes.assertion == "present"]
    absent = [c for c in v if c.attributes.assertion == "absent"]
    possible = [c for c in v if c.attributes.assertion == "possible"]
    definite = present + absent

    if present and absent:  # DX-STATUS-01
        f.issues.append(_issue(
            "diagnosis_status_conflict", "DX-STATUS-01",
            f"{entity.capitalize()} documented as present ({'; '.join(_src(c) for c in present)}) and as absent "
            f"({'; '.join(_src(c) for c in absent)}). The records do not establish which is correct.",
            present + absent))
    if possible and definite:  # DX-EVOL-01
        seq = "; ".join(f"{c.attributes.assertion} ({_src(c)})" for c in _order(possible + definite))
        f.observations.append(Observation(
            rule_id="DX-EVOL-01",
            text=f"Documented sequence: {seq}. A 'possible' assertion followed by a definite one is diagnostic "
                 f"evolution, not a conflict.", claim_ids=[c.claim_id for c in possible + definite]))
    if possible and not definite:  # DX-NOTEST-01
        f.issues.append(_issue("diagnosis_not_established", "DX-NOTEST-01",
                               f"{entity.capitalize()} is only documented as possible; no later record confirms "
                               f"or excludes it.", possible))
    return f


def _family_finding(entity: str, claims: list[Claim]) -> Finding:
    return Finding(finding_id=f"FND-FH-{lx.slug(entity)}", patient_id=claims[0].patient_id,
                   category="family_history", subject=entity, claim_ids=[c.claim_id for c in claims],
                   observations=[Observation(rule_id="DX-FAMILY-01",
                                             text="Family history assertion. Not attributed to the patient and "
                                                  "not reconciled against patient diagnoses.",
                                             claim_ids=[c.claim_id for c in claims])])


# ============================================================================ allergies
def _reconcile_allergies(claims: list[Claim], verified: list[Claim]) -> Finding:
    f = Finding(finding_id="FND-ALG-drug-allergies", patient_id=claims[0].patient_id, category="allergy",
                subject="drug allergies", claim_ids=[c.claim_id for c in claims])
    if ALLERGY_FINDINGS_ARE_HIGH_RISK:
        f.high_risk, f.risk_reason = True, "allergy findings are configured as high risk"
    specific = [c for c in verified if not c.attributes.no_known_allergies]
    nkda = [c for c in verified if c.attributes.no_known_allergies]
    if specific and nkda:
        names = ", ".join(sorted({c.attributes.substance for c in specific}))
        f.issues.append(_issue("allergy_conflict", "ALG-01",
                               f"Specific allergy documented ({names}: {'; '.join(_src(c) for c in specific)}) "
                               f"while another record states no known drug allergies "
                               f"({'; '.join(_src(c) for c in nkda)}).", specific + nkda))
    return f


# ============================================================================ references
def _reconcile_reference(entity: str, claims: list[Claim], verified: list[Claim]) -> Finding:
    f = Finding(finding_id=f"FND-REF-{lx.slug(entity)}", patient_id=claims[0].patient_id,
                category="record_reference", subject=entity, claim_ids=[c.claim_id for c in claims])
    missing = [c for c in verified if not c.attributes.available_in_bundle]
    if missing:
        f.issues.append(_issue("missing_referenced_record", "REF-01",
                               f"The records refer to {'an' if entity[0] in 'aeiou' else 'a'} {entity} ({'; '.join(_src(c) for c in missing)}), "
                               f"but no such document is in the bundle. Its content is unknown.", missing))
    elif verified:
        f.observations.append(Observation(rule_id="REF-01", text=f"Referenced {entity} is present in the bundle.",
                                          claim_ids=[c.claim_id for c in verified]))
    return f


# ============================================================================ entry point
def reconcile(claims: list[Claim], index: EvidenceIndex | None = None,
              verified_ids: set[str] | None = None) -> list[Finding]:
    """Group claims by subject and apply the rules. verified_ids=None treats every claim as usable;
    claims outside a given set are excluded and reported as an integrity issue (VER-01)."""
    claims = [c for c in claims if not isinstance(c.attributes, LlmAttrs)]
    ok = {c.claim_id for c in claims} if verified_ids is None else verified_ids
    groups: dict[tuple[str, str], list[Claim]] = defaultdict(list)
    for c in claims:
        if c.claim_type == "medication":
            groups[("medication", c.entity)].append(c)
        elif c.claim_type == "diagnosis":
            key = "family_history" if c.attributes.assertion == "family" else "diagnosis"
            groups[(key, c.entity)].append(c)
        elif c.claim_type == "allergy":
            groups[("allergy", "drug allergies")].append(c)
        elif c.claim_type == "record_reference":
            groups[("record_reference", c.entity)].append(c)

    has_discharge_list = any(c.claim_type == "medication" and c.claim_id in ok
                             and c.attributes.list_context == "discharge" for c in claims)
    findings: list[Finding] = []
    order = {"medication": 0, "allergy": 1, "diagnosis": 2, "family_history": 3, "record_reference": 4}
    for (category, entity), group in sorted(groups.items(), key=lambda kv: (order[kv[0][0]], kv[0][1])):
        verified = [c for c in group if c.claim_id in ok]
        if category == "medication":
            f = _reconcile_medication(entity, group, verified, has_discharge_list, claims, index)
        elif category == "diagnosis":
            f = _reconcile_diagnosis(entity, group, verified)
        elif category == "family_history":
            f = _family_finding(entity, group)
        elif category == "allergy":
            f = _reconcile_allergies(group, verified)
        else:
            f = _reconcile_reference(entity, group, verified)
        failed = [c for c in group if c.claim_id not in ok]
        if failed:
            f.issues.append(Issue(issue_type="unverified_claim", kind="integrity", rule_id="VER-01",
                                  description=f"{len(failed)} claim(s) failed deterministic verification and were "
                                              f"excluded from reconciliation.",
                                  claim_ids=[c.claim_id for c in failed]))
        findings.append(f)
    return findings
