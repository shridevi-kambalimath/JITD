# MEDUSA-X limitations

Stated plainly so nobody has to discover them. Each one is a known boundary of the prototype, not a bug. The pitch
deck's limitations slide is a short version of this page.

## What the evaluation does and does not show

* **Synthetic data only.** The demo bundle has 7 documents for one fictional patient (`data/demo/SYN-0001`), written
  by the team. The tool has not been run on real or de-identified records.
* **The ground truth is ours.** `data/demo/expected.json` was written alongside the rules. `python -m medusa.evaluate`
  scoring 37 of 37 shows the rules do what they were designed to do on the planted scenarios: 17 expected findings,
  6 dates, 9 scenarios, run checks, and 7 decoys that must not raise conflicts. It is not a measure of accuracy on
  real documentation and not clinical validation.
* **Not a medical device.** Evidence states describe what the documents establish, not clinical truth. A review status
  is a workflow note, not medical approval. Nothing is diagnosed, recommended or prescribed.

## Extraction and dates

* **Rule extraction is lexicon-bound.** Drugs, conditions, labs and procedures not in `analysis/lexicon.py` are not
  extracted. Brand and generic names are mapped by hand for the demo's drugs only. English only.
* **A fixed document header is required.** Every file must start with `DOCUMENT TYPE`, `PATIENT ID` (matching the
  patient it is uploaded to) and `DOCUMENT DATE` lines. A file without them is rejected as `missing_header`. Real
  documents would need a metadata step in front.
* **Section headings carry context.** List membership (admission, inpatient, discharge) comes from headed sections such
  as MEDICATION LIST or PLAN.
* **Relative dates need an anchor in the same document.** "3 days prior to admission" resolves; "since last week" is
  shown as written and deliberately left unresolved.
* **PDFs need a text layer.** Scanned pages are rejected with a clear message; there is no OCR.

## Reconciliation and the gate

* **High-risk classes are prototype settings** (for example anticoagulants), not a clinical standard.
* **Rules, not judgement.** A discrepancy the rules do not describe is not raised. The retrieval check looks for
  evidence the extractor may have missed (for example a restart), but it is keyword-based.

## Search

* **BM25 keyword search.** Every hit is exactly traceable and works offline, but paraphrase is missed. Brand/generic and
  lab-abbreviation expansion is hand-written. The search sits behind an interface a semantic retriever can implement.

## LLM (optional)

* **Verified only against fakes.** The LLM path is tested with mocked transports and `scripts/fake_llm_server.py`
  (prose, broken JSON, fabricated quotes). No real provider has been exercised end to end in this build.
* **Fenced by design.** LLM claims must quote the source word for word or they are rejected, and they are never
  reconciled. If the LLM fails, the run completes on rules and says so.

## Deployment

* **Single user, local, no authentication, no audit trail, no encryption at rest.** Not fit for real patient data.
* **SQLite** with one writer at a time. Fine for a demo, not for concurrent users.
* **Windows:** the QA checklist (`docs/QA.md`, Part A) has to be run on a Windows machine. The builder's environment is
  Linux.
* While the backend is down, screens keep showing the last loaded numbers under a red banner until it returns.
