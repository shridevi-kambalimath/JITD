"""Score an analysis run against the synthetic ground truth (data/demo/expected.json).

    cd backend
    python -m medusa.evaluate              # load the demo bundle into a temporary database, analyse, score
    python -m medusa.evaluate --current    # score the results already in the configured database (after a demo)
    python -m medusa.evaluate --json       # machine-readable report

Checks: every expected finding has the expected evidence state and exactly the expected issues; no unexpected
findings; decoys raise no conflict; the date checks; and the nine demo scenarios. Exit code 0 only if all pass.
The fresh mode goes through the real upload, analysis and API code paths; nothing is read from the ground truth
except to compare.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .core.config import PROJECT_ROOT, Settings, get_settings

CONFLICTS = {"medication_status_conflict", "medication_dose_discrepancy", "diagnosis_status_conflict", "allergy_conflict"}


@dataclass
class Check:
    group: str
    name: str
    passed: bool
    detail: str


@dataclass
class Report:
    patient_id: str
    mode: str
    checks: list[Check] = field(default_factory=list)

    def add(self, group: str, name: str, passed: bool, detail: str) -> bool:
        self.checks.append(Check(group, name, bool(passed), detail))
        return bool(passed)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _api(settings: Settings):
    from fastapi.testclient import TestClient

    from .main import create_app
    return TestClient(create_app(settings))


def evaluate(settings: Settings, patient_id: str, fresh: bool, expected_path: Path) -> Report:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    report = Report(patient_id, "fresh demo bundle" if fresh else "current database")
    with _api(settings) as c:
        base = f"/api/patients/{patient_id}"
        if fresh:
            c.post(f"{base}/demo/reset")
            run = c.post(f"{base}/analysis")
            if run.status_code != 200:
                report.add("run", "analysis", False, f"analysis failed: HTTP {run.status_code} {run.text[:200]}")
                return report
        overview = c.get(f"{base}/overview").json()
        if overview["analysis"]["results_run"] is None:
            report.add("run", "analysis", False, "no analysis results for this patient; run the analysis first")
            return report
        recon = {f["finding_id"]: f for f in c.get(f"{base}/reconciliation").json()["findings"]}
        details = {fid: c.get(f"{base}/reconciliation/{fid}").json() for fid in recon}
        claims = c.get(f"{base}/claims").json()
        timeline = c.get(f"{base}/timeline").json()
        queue = c.get(f"{base}/review-queue").json()

    report.add("run", "documents processed", overview["documents"]["processed"] == expected["documents"],
               f"{overview['documents']['processed']} processed (expected {expected['documents']})")
    report.add("run", "results current", overview["analysis"]["is_current"], "analysis covers the current documents"
               if overview["analysis"]["is_current"] else str(overview["analysis"]["stale_reason"]))
    report.add("run", "claims verified", overview["claims"]["failed_verification"] == 0,
               f"{overview['claims']['verified']} of {overview['claims']['total']} claims pass every hard check")

    # findings: state and issues
    for fid, spec in expected["findings"].items():
        f = recon.get(fid)
        if f is None:
            report.add("findings", fid, False, "not found")
            continue
        issues = sorted(set(f["issue_types"]))
        ok = f["state"] == spec["state"] and issues == sorted(spec["issues"])
        report.add("findings", fid, ok, f"{f['state']} via {f['gate_rule']}, issues {issues or 'none'}"
                   + ("" if ok else f" (expected {spec['state']}, {sorted(spec['issues']) or 'none'})"))
    extra = sorted(set(recon) - set(expected["findings"]))
    report.add("findings", "no unexpected findings", not extra, ", ".join(extra) if extra else "none")
    false_conflicts = [fid for fid, spec in expected["findings"].items() if "decoy" in spec and fid in recon
                       and CONFLICTS & set(recon[fid]["issue_types"])]
    decoys = sum("decoy" in s for s in expected["findings"].values())
    report.add("findings", "0 false conflicts on decoys", not false_conflicts,
               f"{decoys} decoys, conflicts on: {', '.join(false_conflicts) or 'none'}")

    # date checks
    for dc in expected["date_checks"]:
        cands = [c for c in claims if c["entity"] == dc["entity"]
                 and ("action" not in dc or c["attributes"].get("action") == dc["action"])]
        ev = cands[0]["event_date"] if cands else None
        ok = ev is not None and ev["value"] == dc["event_date"]
        for key in ("approximate", "basis", "precision", "raw_text"):
            if ok and key in dc:
                ok = ev[key] == dc[key]
        if ok and "document_date" in dc:
            ok = cands[0]["document_date"] == dc["document_date"]
        shown = "missing" if ev is None else f"{ev['value'] or 'unresolved'} ({ev['basis']}, raw {ev['raw_text']!r})"
        report.add("dates", f"{dc['entity']}{' ' + dc['action'] if 'action' in dc else ''}", ok, shown)

    # scenarios
    def state(fid):
        return recon.get(fid, {}).get("state")

    entries = timeline["entries"]
    placed = [e["event_date"]["value"] if e["ordering_basis"] == "event_date" else e["document_date"] for e in entries]
    sc = {
        "chronology": (placed == sorted(placed) and bool(entries) and entries[0]["when"] == "2015"
                       and entries[-1]["document_date"] == "2026-03-29",
                       f"{len(entries)} entries from {entries[0]['when'] if entries else '-'} to {entries[-1]['when'] if entries else '-'}"),
        "event_vs_document_date": next(((e["when"] == "2026-03-11" and e["document_date"] == "2026-03-12",
                                         f"hemoglobin at {e['when']}, report {e['document_date']}")
                                        for e in entries if e["entity"] == "hemoglobin"), (False, "hemoglobin missing")),
        "medication_change": (
            [o["rule_id"] for o in details.get("FND-MED-pantoprazole", {}).get("observations", [])].count("MED-CHANGE-01") >= 2
            and not details.get("FND-MED-pantoprazole", {}).get("issue_types")
            and [c["attributes"]["action"] for c in details.get("FND-MED-warfarin", {}).get("claims", [])][-1:] == ["restarted"],
            "pantoprazole: " + str([o["rule_id"] for o in details.get("FND-MED-pantoprazole", {}).get("observations", [])])
            + "; warfarin: " + " > ".join(c["attributes"]["action"] for c in details.get("FND-MED-warfarin", {}).get("claims", []))),
        "cross_source_discrepancy": (state("FND-DX-chronic-kidney-disease") == "CONFLICTING_EVIDENCE",
                                     f"chronic kidney disease: {state('FND-DX-chronic-kidney-disease')}"),
        "missing_reference": (state("FND-REF-endoscopy-report") == state("FND-REF-histopathology-report") == "INSUFFICIENT_EVIDENCE",
                              f"endoscopy {state('FND-REF-endoscopy-report')}, histopathology {state('FND-REF-histopathology-report')}"),
        "ambiguous_date": next(((u["event_date"]["value"] is None and u["event_date"]["raw_text"] == "since last week",
                                 f"{u['entity']}: {u['reason']}") for u in queue["uncertain_dates"] if u["entity"] == "dizziness"),
                               (False, "dizziness not in the review queue's uncertain dates")),
        "supported_claim": (state("FND-MED-atorvastatin") == "EVIDENCE_SUPPORTED"
                            and all(c["verified"] for c in details.get("FND-MED-atorvastatin", {}).get("claims", [])),
                            f"atorvastatin: {state('FND-MED-atorvastatin')}, "
                            f"{len(details.get('FND-MED-atorvastatin', {}).get('claims', []))} verified claims"),
        "review_required": (state("FND-MED-warfarin") == "REVIEW_REQUIRED" and recon["FND-MED-warfarin"]["gate_rule"] == "GATE-03",
                            f"warfarin: {state('FND-MED-warfarin')} via {recon.get('FND-MED-warfarin', {}).get('gate_rule')}"),
        "insufficient_evidence": (state("FND-MED-amlodipine") == "INSUFFICIENT_EVIDENCE", f"amlodipine: {state('FND-MED-amlodipine')}"),
    }
    for s in expected["scenarios"]:
        ok, detail = sc.get(s["id"], (False, "no check implemented"))
        report.add("scenarios", s["title"], ok, detail)
    return report


def print_report(r: Report) -> None:
    print(f"MEDUSA-X ground-truth evaluation · patient {r.patient_id} · {r.mode}")
    group = None
    for c in r.checks:
        if c.group != group:
            group = c.group
            print(f"\n{group.upper()}")
        print(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name:<40} {c.detail}")
    failed = [c for c in r.checks if not c.passed]
    docs = next((c for c in r.checks if c.name == "documents processed"), None)
    if docs and not docs.passed and r.mode == "current database":
        print("\nNote: the database holds a different document set from the demo bundle (for example an uploaded "
              "endoscopy report), so some differences are expected. Use Reset demo data and re-run the analysis "
              "to score the bundle itself.")
    print(f"\n{len(r.checks) - len(failed)} of {len(r.checks)} checks passed. "
          + ("All expected states matched, every planted issue found, 0 false conflicts." if not failed
             else f"{len(failed)} FAILED."))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--patient", default="SYN-0001")
    ap.add_argument("--current", action="store_true", help="score the configured database instead of a fresh run")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--expected", type=Path, default=PROJECT_ROOT / "data" / "demo" / "expected.json")
    args = ap.parse_args(argv)
    logging.disable(logging.WARNING)
    base = get_settings()
    if args.current:
        report = evaluate(base, args.patient, fresh=False, expected_path=args.expected)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            settings = base.model_copy(update={"db_path": Path(tmp) / "evaluate.db", "upload_dir": Path(tmp) / "uploads",
                                               "llm_provider": "none"})
            report = evaluate(settings, args.patient, fresh=True, expected_path=args.expected)
    if args.json:
        print(json.dumps({"passed": report.passed, **asdict(report)}, indent=2))
    else:
        print_report(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
