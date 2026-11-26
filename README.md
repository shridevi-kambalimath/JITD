# MEDUSA-X

Evidence-driven clinical record reconstruction and reconciliation. National hackathon prototype.

MEDUSA-X reconstructs what synthetic clinical documents record, links every claim to its source passage,
and surfaces documentation discrepancies for human review. It is **not** a diagnostic, treatment,
prescribing or clinical decision system, and it never decides which conflicting record is correct.
**Synthetic data only. Never upload real patient records.**

* Plan, schema, API contracts: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)
* Build status, tests run, known issues: [`docs/PROGRESS.md`](docs/PROGRESS.md)
* Clinical rule tables (reconciliation, verification, gate): [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
* QA checklist and failure drills: [`docs/QA.md`](docs/QA.md)
* Limitations, stated plainly: [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)

**Current state: all 11 phases built and tested on Linux; the Windows run-through in [`docs/QA.md`](docs/QA.md) (Part A) is still to be done on a Windows machine.** Every screen is built; the synthetic demo bundle (7 documents) covers nine demo scenarios, checked against ground truth by `python -m medusa.evaluate`; failure cases show a clear message and recover ([`docs/QA.md`](docs/QA.md)); and the demo runs from one process on one port. Demo guide and demo-day checklist: [`docs/DEMO.md`](docs/DEMO.md). What it does not do: [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

---

## Easiest: VS Code

1. File, Open Folder, choose this `medusa-x` folder. Accept the recommended extensions.
2. Terminal, Run Task, **Setup: everything** (once).
3. **Ctrl+Shift+B** starts backend and frontend. Open http://127.0.0.1:5173.
4. Terminal, Run Test Task runs every test. Debug with F5 (**Backend: FastAPI (debug)** or **Full stack**).

The manual commands below do the same thing without VS Code.

## Requirements (Windows)

* Python 3.10 to 3.13 from [python.org](https://www.python.org/downloads/) (tick "Add python.exe to PATH")
* Node.js 22 LTS from [nodejs.org](https://nodejs.org/) (Vite needs Node 20.19+ or 22.12+)

Use **Command Prompt** for the commands below. In PowerShell, `.venv\Scripts\activate.bat` and `npm` may be
blocked by execution policy; fix once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then
activate with `.venv\Scripts\Activate.ps1`.

## One-time setup

```bat
cd medusa-x
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
copy .env.example .env
pytest

cd frontend
npm ci
npm test
cd ..
```

Expected: `pytest` reports **376 passed**; `npm test` reports **92 passed**. In VS Code, the task **QA: everything** runs both, the build and the ground-truth check.

## Demo: one process, one port

For presenting. Builds the UI, then the backend serves it and the API on http://127.0.0.1:8000. No Vite server, one
terminal. Stop any running backend first.

* VS Code: Terminal, Run Task, **Demo: single process**.
* Command Prompt:

```bat
cd medusa-x\frontend
npm run build
cd ..\backend
..\.venv\Scripts\activate.bat
set MEDUSA_SERVE_FRONTEND=true
python -m medusa
```

Rebuild (`npm run build`) after any frontend change; the sidebar footer flags a UI and API version mismatch if you
forget.

## Run (two terminals)

Terminal 1, backend API on http://127.0.0.1:8000:

```bat
cd medusa-x
.venv\Scripts\activate.bat
cd backend
python -m medusa
```

Terminal 2, frontend on http://127.0.0.1:5173:

```bat
cd medusa-x\frontend
npm run dev
```

Open **http://127.0.0.1:5173**. Click **Open synthetic demo workspace** to load the fictional documents
through the real ingestion pipeline, or **Enter workspace** to start empty.

The frontend proxies `/api` to the backend using `MEDUSA_API_HOST` and `MEDUSA_API_PORT` from the root `.env`,
so the port is configured in one place. API docs: http://127.0.0.1:8000/api/docs.

## Checks you can run

| Command (from) | What it verifies |
|---|---|
| `pytest` (root, venv active) | backend: config, database + migrations, errors, logging, ingestion, extraction, LLM providers (mocked), analysis, timeline, reconciliation rules and evidence states against ground truth, verification checks, gate rules, evidence inspector, evidence search, overview counts, review queue, evidence summary |
| `npm test` (frontend) | API client, navigation, landing flows, overview and analysis states, document claims and source highlighting, timeline filters and source links, reconciliation side by side with states, review status, evidence inspector and links to it, evidence search tabs, review queue, summary, every sidebar screen |
| `python -m medusa.evaluate` (backend, venv active) | demo bundle analysed in a temporary database and scored against `data/demo/expected.json`: every state, issue, date and scenario |
| `npm run typecheck` (frontend) | TypeScript, strict mode |
| `npm run build` (frontend) | production bundle |
| `curl.exe http://127.0.0.1:8000/api/health/ready` | database ready at schema v5 |

### Ingestion in the browser

Open **Documents** in the sidebar. Drop files on the drop zone (or **Choose files**), watch each file's progress
and outcome, click a document to see its metadata, extracted text and status history, and use **Reset demo data**
to return to the synthetic demo documents.

### Ingestion from the command line

Use `curl.exe` (in PowerShell plain `curl` is a different command):

```bat
curl.exe -X POST http://127.0.0.1:8000/api/patients/SYN-0001/demo/load
curl.exe -X POST http://127.0.0.1:8000/api/patients/SYN-0001/demo/reset
curl.exe -F "file=@data\samples\endoscopy_report.pdf" http://127.0.0.1:8000/api/patients/SYN-0001/documents
curl.exe -F "file=@data\samples\scanned_admission_note.pdf" http://127.0.0.1:8000/api/patients/SYN-0001/documents
curl.exe "http://127.0.0.1:8000/api/patients/SYN-0001/documents?status=failed"
```

| Sample in `data\samples` | Result |
|---|---|
| `endoscopy_report.pdf` | 201, `processed` |
| `scanned_admission_note.pdf` | 201, `failed`, `no_text_layer` |
| `corrupted_report.pdf` | 201, `failed`, `corrupted_pdf` |
| `no_header_note.txt` | 201, `failed`, `missing_header` |
| `wrong_patient_note.txt` | 201, `failed`, `patient_mismatch` |
| `empty_note.txt` | 422, `empty_file` (nothing stored) |
| `unsupported_notes.csv` | 415, `unsupported_type` (nothing stored) |

### Claim extraction (Phase 3)

On the **Overview**, click **Run analysis**. The backend splits every processed document into passages and extracts
claims (medications, diagnoses, allergies, labs, symptoms, procedures, encounters, record references). The demo
bundle gives **51 rule claims**. On **Documents**, each card shows its claim count; open one to see its claims, each
with its source sentence and the quoted words marked. **Show in text** highlights them in the full document text. Adding, deleting or re-uploading a document marks the results
**stale** until you run the analysis again.

```bat
curl.exe -X POST http://127.0.0.1:8000/api/patients/SYN-0001/analysis
curl.exe "http://127.0.0.1:8000/api/patients/SYN-0001/claims?category=medication"
curl.exe http://127.0.0.1:8000/api/patients/SYN-0001/analysis/latest
```

### Clinical timeline (Phase 4)

After an analysis, open **Clinical Timeline** in the sidebar. Entries are in date order. Each is placed by the
event date its passage states (solid border) or, when the passage states none, by its document's date (dashed
border, and it says so). Approximate dates keep `~`, year-only dates stay year-only, and lab results are placed by
collection date with the report date shown beside it. Filter by category, search, and use **View source** to jump
to the document with that claim highlighted.

```bat
curl.exe "http://127.0.0.1:8000/api/patients/SYN-0001/timeline?category=lab_result"
curl.exe "http://127.0.0.1:8000/api/patients/SYN-0001/timeline?q=warfarin"
```

### Reconciliation (Phase 5)

After an analysis, open **Reconciliation**. The demo bundle gives **7 of 17 subjects with a potential discrepancy**:
warfarin (held, then listed active; not on the discharge list), drug allergies (penicillin vs no known allergies),
metformin (500 mg vs 1000 mg), chronic kidney disease (absent vs present), amlodipine (not on the discharge list) and
two referenced reports that are not in the bundle. Each shows the sources side by side (A, B, C) with the exact words
marked. The other 10 subjects are listed under **No discrepancy found**, with the reason where a rule looked and
deliberately did not flag (documented regimen change, diagnostic evolution, family history).

Set a **review status** (Pending review, Reviewed, Flagged for follow-up) with an optional note. It survives
re-analysis; if a later analysis changes an item's issues, it is marked **Changed since review**. A review status
is not medical approval and never changes a finding. **Reset demo data** clears findings and reviews.

Try it: upload `data\samples\endoscopy_report.pdf` and re-run the analysis. The "Endoscopy report" item moves to
No discrepancy found, because the referenced record is now in the bundle.

```bat
curl.exe http://127.0.0.1:8000/api/patients/SYN-0001/reconciliation
curl.exe http://127.0.0.1:8000/api/patients/SYN-0001/reconciliation/FND-MED-warfarin
curl.exe http://127.0.0.1:8000/api/patients/SYN-0001/review-queue
```

### Verification, evidence states and the evidence inspector (Phase 6)

Every claim is checked against the stored text on each analysis: the document and passage exist, the cited text
matches exactly, the offsets are inside the passage, the quoted words sit at their offsets, and the event date is not
after the document date (plus one advisory keyword-search check). Only claims that pass appear on the timeline and
count in reconciliation. Each reconciliation item then gets one evidence state from an ordered rule table (first
match wins): **Review required**, **Conflicting evidence**, **Insufficient evidence** or **Evidence-supported**, with
the rule (GATE-01 to GATE-07) and the reason shown. The demo gives 2, 2, 3 and 10.

**Inspect** (on claim rows, timeline entries and reconciliation sources) opens the evidence inspector: the stored text
around the passage with the quoted words marked, offsets, both dates, every check re-run against the text as stored
now, the claim's timeline entry and the items that use it. If the stored text changes after an analysis, the
inspector shows the failed check at once and says the claim no longer matches what was verified.

```bat
curl.exe http://127.0.0.1:8000/api/patients/SYN-0001/claims/<claim id>/evidence
```

### Evidence search (Phase 7)

Open **Evidence Search** and type a word (or click an example). Results come from BM25 keyword ranking over the stored
passages, with brand/generic drug names and common lab abbreviations expanded: **metformin** finds the admission note's
"Glycomet" line first and says it also matched `glycomet, glucophage`; **Hb** finds the haemoglobin result; section
names count too, so **allergies** finds the lines under ALLERGIES. Tabs show the passages (matched words marked), the
claims and timeline entries they lead to, and the reconciliation items with their evidence states. Every result links
to the evidence inspector, the document or the reconciliation item.

```bat
curl.exe "http://127.0.0.1:8000/api/patients/SYN-0001/search?q=metformin"
curl.exe "http://127.0.0.1:8000/api/patients/SYN-0001/search?q=allergies&scope=reconciliation"
```

### Overview, Review Queue and Summary (Phase 8)

* **Overview**: all six stages and the evidence-state bar come from one call, `GET /api/patients/{id}/overview`.
  Hover a bar segment for its count; the legend below lists every state with its count and share.
* **Review Queue**: everything that needs a person, grouped as Review required, Conflicting evidence, Insufficient
  evidence, claims that failed verification, and uncertain dates (approximate, year-only, relative). Set a status from
  the dropdown; filter by status; **Sources** opens the side-by-side view.
* **Summary**: a template-built reconstruction (encounter, evidence states, unresolved issues, diagnoses,
  medication mentions, allergies, procedures, labs, symptoms, patterns not flagged, dated timeline). Every content
  line cites its passages and each citation opens the evidence inspector. **Download Markdown** saves it as a file.

```bat
curl.exe http://127.0.0.1:8000/api/patients/SYN-0001/overview
curl.exe http://127.0.0.1:8000/api/patients/SYN-0001/review-queue
curl.exe -o summary.md http://127.0.0.1:8000/api/patients/SYN-0001/summary.md
```

### Demo dataset and ground truth (Phase 9)

`data/demo/SYN-0001` holds seven synthetic documents; the seventh, a clinic follow-up, adds a later warfarin restart,
a further pantoprazole change and an ambiguous date ("dizziness since last week", kept as written and never resolved).
`data/samples/endoscopy_report.pdf` now has real synthetic findings (a bleeding gastric ulcer). Check everything:

```bat
cd backend
python -m medusa.evaluate
```

It loads the bundle into a temporary database through the real upload and analysis code, then scores 17 findings,
6 date checks and 9 scenarios. Expected last line: `All expected states matched, every planted issue found, 0 false
conflicts.` In VS Code: **Terminal, Run Task, Evaluate: ground truth**. `--current` scores the app's own database,
`--json` prints a machine-readable report. The step-by-step demo is in [`docs/DEMO.md`](docs/DEMO.md).

### Optional LLM extraction

Rules always run and need no key. To let an LLM propose additional claims, set in `.env`:

```ini
MEDUSA_LLM_PROVIDER=anthropic            # or openai_compatible (OpenAI, Ollama, LM Studio, vLLM)
MEDUSA_LLM_MODEL=claude-haiku-5-5        # your model name
MEDUSA_LLM_API_KEY=...                   # never commit; optional for local servers
MEDUSA_LLM_BASE_URL=                     # e.g. http://127.0.0.1:11434/v1 for Ollama
```

Then check the connection (prints no secrets):

```bat
cd backend
python -m medusa.analysis.llm.check
```

Every LLM claim must quote its source passage word for word or it is rejected; dates and offsets are computed by
the server, not the model. LLM claims are labelled **LLM** in the UI and `llm:<provider>/<model>` in the API. If
the LLM fails (bad key, timeout, rate limit), the run still completes with rule claims and the Overview says so.

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI shows "Backend offline" | Start terminal 1 first. Check `MEDUSA_API_PORT` in `.env`. |
| Sidebar still shows **Documents P2**, or the footer says an old UI version | An old frontend is still running on port 5173, so the new one could not start (its terminal says `Error: Port 5173 is already in use`). Run `netstat -ano \| findstr :5173`, then `taskkill /PID <pid> /F`, restart, then press Ctrl+F5 in the browser. |
| Banner **Frontend and backend are from different builds** | Backend and frontend come from different project folders. Stop every MEDUSA-X terminal and start both from one folder. The sidebar footer shows both versions. |
| UI shows "Incompatible backend" | An older MEDUSA-X backend is on port 8000. Run `netstat -ano \| findstr :8000`, then `taskkill /PID <pid> /F`, then start `python -m medusa` from this project's `backend` folder. |
| `No module named medusa` | Run `python -m medusa` from inside `backend`. |
| Backend prints **MEDUSA-X backend not started.** *Port 8000 ... is already in use* | Another backend (or another program) holds the port. The message says which. Close that terminal, or `netstat -ano \| findstr :8000` then `taskkill /PID <pid> /F /T`, or set `MEDUSA_API_PORT` in `.env`. |
| Amber banner **The database is not ready**, or the message *"The database file was missing or replaced, so an empty one was created"* | `data\medusa.db` was deleted or replaced. An empty database is created automatically; load the demo bundle again and run the analysis. |
| Upload says **payload_too_large** | Files are limited to 5,000,000 bytes (`MEDUSA_MAX_UPLOAD_BYTES`). Nothing was stored. |
| **MEDUSA-X backend not started (MEDUSA_SERVE_FRONTEND=true)** ... *frontend build was not found* | Run `npm run build` in `frontend` first, or use the task **Demo: single process**, which builds for you. |
| Single-process demo shows an old screen | Rebuild with `npm run build`, restart the backend, then press Ctrl+F5. |
| `Port 5173 is already in use` | Close the other Vite window; the port is fixed so the proxy stays predictable. |
| `npm ci` fails on Node version | Install Node 22 LTS; check with `node --version`. |
| `Database schema version N is newer...` | Delete `data\medusa.db` (synthetic data only). |
| Overview says **LLM misconfigured** | Set `MEDUSA_LLM_MODEL` and (for anthropic) `MEDUSA_LLM_API_KEY` in `.env`, restart the backend, run `python -m medusa.analysis.llm.check`. |
| Analysis says **LLM failed (auth: ...)** | The key was rejected. Rule claims are still complete. Fix the key and re-run. |

## Stack

Backend: Python, FastAPI, Pydantic, SQLite (`sqlite3` with versioned migrations), pypdf, httpx (optional LLM calls).
Frontend: React 19, TypeScript, Vite, Tailwind CSS 4, TanStack Query, React Router, Lucide, shadcn-style components.
Tests: pytest, Vitest, Testing Library. No Docker, no vector database, no agents framework.
