"""Evidence sufficiency gate.

An ordered rule table; the first matching rule decides the state. Inputs are only the
finding's issues, its verified claim count and its configured risk flag. No model
confidence, no scores, no thresholds that a model produces.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..schemas.domain import EvidenceState, Finding

S = EvidenceState


@dataclass(frozen=True)
class GateInput:
    verified_claims: int
    conflicts: list[str]
    gaps: list[str]
    integrity: list[str]
    unextracted: bool
    high_risk: bool
    risk_reason: str | None


@dataclass(frozen=True)
class GateRule:
    rule_id: str
    description: str
    applies: Callable[[GateInput], bool]
    state: Callable[[GateInput], EvidenceState]
    rationale: Callable[[GateInput], str]


def _risk(g: GateInput) -> str:
    return f" ({g.risk_reason})" if g.risk_reason else ""


RULES: list[GateRule] = [
    GateRule("GATE-01", "No verified claims remain",
             lambda g: g.verified_claims == 0,
             lambda g: S.REVIEW if g.high_risk else S.INSUFFICIENT,
             lambda g: "No claim for this item passed verification, so nothing can be stated from the records."
                       + (f" High-risk item{_risk(g)}." if g.high_risk else "")),
    GateRule("GATE-02", "Possible evidence the extractor did not capture",
             lambda g: g.unextracted,
             lambda g: S.REVIEW,
             lambda g: "Retrieval found text that may change this item but was not captured as a claim. "
                       "Extraction may be incomplete, so a reviewer must read the source."),
    GateRule("GATE-03", "Conflict on a high-risk item",
             lambda g: bool(g.conflicts) and g.high_risk,
             lambda g: S.REVIEW,
             lambda g: f"Records conflict ({', '.join(g.conflicts)}) on a high-risk item{_risk(g)}. "
                       f"The system does not choose between records."),
    GateRule("GATE-04", "Conflict",
             lambda g: bool(g.conflicts),
             lambda g: S.CONFLICTING,
             lambda g: f"Records conflict ({', '.join(g.conflicts)}). Both sources are preserved; neither is "
                       f"selected as correct."),
    GateRule("GATE-05", "Gap or integrity issue on a high-risk item",
             lambda g: bool(g.gaps or g.integrity) and g.high_risk,
             lambda g: S.REVIEW,
             lambda g: f"Information is missing or unverifiable ({', '.join(g.gaps + g.integrity)}) on a "
                       f"high-risk item{_risk(g)}."),
    GateRule("GATE-06", "Gap or integrity issue",
             lambda g: bool(g.gaps or g.integrity),
             lambda g: S.INSUFFICIENT,
             lambda g: f"The records do not establish this item ({', '.join(g.gaps + g.integrity)})."),
    GateRule("GATE-07", "Otherwise",
             lambda g: True,
             lambda g: S.SUPPORTED,
             lambda g: f"{g.verified_claims} verified source claim(s); no conflict or gap detected by the rules."),
]


def gate_input(f: Finding, verified_ids: set[str]) -> GateInput:
    return GateInput(
        verified_claims=sum(1 for c in f.claim_ids if c in verified_ids),
        conflicts=sorted({i.issue_type for i in f.issues if i.kind == "conflict"}),
        gaps=sorted({i.issue_type for i in f.issues if i.kind == "gap"}),
        integrity=sorted({i.issue_type for i in f.issues if i.kind == "integrity"}),
        unextracted=any(i.issue_type == "possible_unextracted_evidence" for i in f.issues),
        high_risk=f.high_risk,
        risk_reason=f.risk_reason,
    )


def evaluate(g: GateInput) -> tuple[EvidenceState, str, str]:
    for rule in RULES:
        if rule.applies(g):
            return rule.state(g), rule.rule_id, rule.rationale(g)
    raise AssertionError("GATE-07 always applies")  # pragma: no cover


def apply_gate(findings: list[Finding], verified_ids: set[str]) -> list[Finding]:
    out = []
    for f in findings:
        state, rule_id, rationale = evaluate(gate_input(f, verified_ids))
        out.append(f.model_copy(update={"state": state, "gate_rule": rule_id, "gate_rationale": rationale}))
    return out
