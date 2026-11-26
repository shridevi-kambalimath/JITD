# MEDUSA-X Implementation Plan

Master specification: the hackathon development prompt. This plan is the source of truth for stack,
layout, API paths, schema and sequence. `ARCHITECTURE.md` remains valid for the clinical rule tables
(reconciliation rules, verification checks, gate rules); where the two differ, this file wins.

Synthetic data only. Documentation reconciliation and review prototype, not a clinical decision system.

---

## 0. Decisions against the master spec

| Spec item | Decision | Reason |
|---|---|---|
| React + TS + Vite + Tailwind + TanStack Query + React Router + Lucide | **Adopted.** Replaces the Streamlit UI. | The spec's screens need precise interaction: side-by-side passages, clickable timeline, claim-to-source navigation. Streamlit cannot do these well. |
| shadcn/ui | **Adopted as a pattern, written by hand.** Same structure (cva variants, `cn`, Radix only where needed). | The shadcn CLI downloads from its own registry, which may be unreachable on venue Wi-Fi. Hand-written components have no runtime dependency on it. |
| SQLAlchemy | **Not adopted.** Keep `sqlite3` + repository modules + versioned migrations. | Ingestion already runs on it, with 117 passing tests, migrations and DB-level CHECK constraints. Switching ORMs mid-project rewrites working code for no feature gain (spec: "do not start a second architecture without a clear reason"). Normalisation is done in the schema, not by the ORM. |
| Configurable LLM extraction | **Adopted as a hybrid.** A deterministic rule extractor always runs. The LLM extractor runs when configured; every LLM claim must quote text that exists verbatim in its passage, or it is rejected. Each claim records which method produced it. | Works offline on demo day. LLM output is never trusted unverified. Rule output is never presented as AI output. |
| Recharts | **Dropped.** Evidence distribution is a single stacked bar drawn with divs. | One chart does not justify a dependency. |
| Timeline events table | **Not a table.** The timeline is a query over verified claims. | A copy of claim data would need syncing and could drift from its source. |
| OCR | **Dropped.** Scanned PDFs fail with `no_text_layer`. | Tesseract on Windows is a setup risk; OCR errors create false claims. |
| Docker / deployment config | **Deferred** to Phase 11, only if time allows. | Not needed to demonstrate the core mechanism. |
| Single-command demo | **Added** (Phase 11): FastAPI serves the built React app, one process, one port. | Fewer moving parts on demo day. |

## 1. Final architecture

```
Browser (React SPA)
   |  fetch /api/...     (dev: Vite proxy :5173 -> :8000; demo: same origin :8000)
FastAPI  /api
   |-- ingestion      upload -> validate -> store -> extract text -> header metadata   [done]
   |-- segmentation   text -> passages with absolute offsets
   |-- extraction     passages -> claims (rules always; LLM optional, quote-verified)
   |-- verification   claim -> source exists, span matches, entity grounded, dates consistent
   |-- timeline       query over verified claims (event date vs document date)
   |-- reconciliation deterministic rules + retrieval investigation -> items with side A / side B
   |-- gate           ordered rules -> EVIDENCE_SUPPORTED | CONFLICTING_EVIDENCE | INSUFFICIENT_EVIDENCE | REVIEW_REQUIRED
   |-- retrieval      BM25 over passages, claims, reconciliation items (interface ready for semantic search)
   |-- review         persisted human review status (never medical approval)
   |-- summary        templated, cited, no free text generation
SQLite (sqlite3, migrations via PRAGMA user_version)
```

One analysis run = segmentation -> extraction -> verification -> reconciliation -> gate -> review sync,
triggered by `POST /api/patients/{pid}/analysis`. Deterministic for a given document set and extractor configuration.

## 2. Folder structure

```
medusa-x/
  .env.example  requirements.txt  requirements-dev.txt  pyproject.toml  README.md
  docs/         IMPLEMENTATION_PLAN.md  PROGRESS.md  ARCHITECTURE.md
  data/demo/SYN-0001/   data/samples/
  backend/medusa/
    main.py  __main__.py
    core/        config.py  logging.py  errors.py
    db/          connection.py  schema.py  documents.py  claims.py  findings.py  reviews.py  runs.py
    ingestion/   validation.py  text_extraction.py  metadata.py  storage.py  service.py
    analysis/    segmentation.py  lexicon.py  dates.py  assertion.py  rule_extractor.py
                 llm/ (provider.py  anthropic.py  openai_compatible.py  extractor.py)
                 verification.py  timeline.py  reconciliation.py  gate.py  retrieval.py  summary.py  pipeline.py
    api/         health.py  documents.py  analysis.py  claims.py  timeline.py  reconciliation.py
                 search.py  reviews.py  summary.py  demo.py
    schemas/     common.py  documents.py  analysis.py
  frontend/
    package.json  vite.config.ts  tsconfig.json  index.html
    src/
      main.tsx  App.tsx  index.css
      lib/       api.ts (client + error envelope)  utils.ts  format.ts
      api/       health.ts  documents.ts  ... (typed calls + TanStack Query hooks per resource)
      components/ui/   button  badge  card  skeleton  input  (shadcn-style primitives)
      components/      status-badge  empty-state  error-state  health-indicator  page-header  sidebar
      layouts/   workspace-layout.tsx
      pages/     landing  overview  documents  timeline  reconciliation  evidence  search  review  summary  not-found
      context/   workspace.tsx (active patient)
      test/      setup.ts
  tests/        backend pytest suite
```

## 3. Database schema

Existing (migrations v1, v2): `documents`, `document_events`. Tables from v1 that were never written
(`passages`, `claims`, `verifications`, `findings`, `review_items`, `runs`) are rebuilt with real
columns in migration v3 (Phase 3), so they can be queried and constrained.

| Table | Key columns | Notes |
|---|---|---|
| documents | document_id PK, patient_id, status, document_type, document_date, extracted_text, ... | done (v2) |
| document_events | event_id PK, document_id FK cascade, status, at | done (v2) |
| passages | passage_id PK, document_id FK cascade, seq, section, char_start, char_end, text | offsets index into `documents.extracted_text` |
| analysis_runs | run_id PK, patient_id, started_at, finished_at, status, extractor ('rules' / 'rules+llm:<model>'), llm_error, stats JSON | |
| claims | claim_id PK, run_id FK, document_id FK, passage_id FK, category, entity, surface_text, attributes JSON, entity_start, entity_end, document_date, event_date, event_date_precision, event_date_approximate, event_date_basis, event_date_raw, extraction_method, created_at | `extraction_method` is `rule:<rule>` or `llm:<model>` |
| verifications | claim_id PK FK cascade, verified, checks JSON | |
| findings | finding_id PK (deterministic), run_id FK, patient_id, category, subject, state CHECK(4 codes), gate_rule, rationale, high_risk, issues JSON, observations JSON | the reconciliation item |
| finding_claims | finding_id FK, claim_id FK, role CHECK('side_a','side_b','support') | drives side-by-side view |
| reviews | finding_id PK, status CHECK('pending_review','reviewed','flagged'), note, updated_at | survives reruns; never deleted by a rerun |

Demo reset: deletes the patient's rows (cascades) and stored files, then reloads the bundle through the real upload path.

## 4. API contracts (all under `/api`)

| Method | Path | Response | Phase |
|---|---|---|---|
| GET | /health, /health/ready | liveness; DB readiness (503 + reason) | 1 |
| POST | /patients/{pid}/documents | DocumentDetail, 201 (`status` processed/failed); 409/413/415/422 | 2 |
| GET | /patients/{pid}/documents?status= | DocumentSummary[] | 2 |
| GET / DELETE | /documents/{id} | DocumentDetail / 204 | 2 |
| POST | /patients/{pid}/demo/load, /patients/{pid}/demo/reset | DemoLoadResult | 2, 9 |
| POST | /patients/{pid}/analysis | AnalysisRun (stage stats, extractor used, LLM error if any) | 3 |
| GET | /patients/{pid}/analysis/latest | AnalysisRun | 3 |
| GET | /patients/{pid}/claims?category=&document_id= | Claim[] (+ verification state) | 3 |
| GET | /claims/{id}/evidence | claim, document meta, passage, context, verification checks, related finding, related timeline entry | 6 |
| GET | /patients/{pid}/timeline?category=&q= | TimelineEntry[] | 4 |
| GET | /patients/{pid}/reconciliation?state=&category= | ReconciliationItem[] with side_a / side_b passages | 5 |
| GET | /reconciliation/{finding_id} | ReconciliationItem detail | 5 |
| GET | /patients/{pid}/search?q=&scope= | SearchHit[] (documents, claims, timeline, reconciliation) | 7 |
| GET | /patients/{pid}/review-queue | ReviewItem[] | 5 |
| PUT | /reviews/{finding_id} | {status, note} -> ReviewItem | 5 |
| GET | /patients/{pid}/summary | EvidenceSummary (sections, citations) | 8 |
| GET | /patients/{pid}/overview | counts for the dashboard, all computed | 8 |

Errors everywhere: `{"error": {"code", "message", "details", "request_id"}}`. Evidence states are
codes in the API and human labels in the UI.

## 5. Frontend component structure

* `App.tsx`: routes. `/` landing. `/workspace` layout with `overview`, `documents`, `timeline`,
  `reconciliation`, `reconciliation/:id`, `evidence/:claimId`, `search`, `review`, `summary`.
* `WorkspaceLayout`: sidebar (six spec items + Summary), top bar (patient context, backend health).
  Nav items for screens not built yet are disabled and labelled with their phase, never dead links.
* Data: one typed function per endpoint in `src/api/*`, wrapped in TanStack Query hooks. Mutations
  invalidate the queries they affect. No component calls `fetch` directly.
* States: every data view handles loading (skeleton), error (message + request id + retry), empty (what to do next).
* Design system: tokens in `index.css` (`@theme`), primitives in `components/ui`. Status colours are
  defined once and used for documents, evidence states and review states.

## 6. Dependencies

Backend: fastapi, uvicorn, pydantic, pydantic-settings, python-dotenv, python-multipart, pypdf,
httpx (LLM calls, Phase 3). Dev: pytest, reportlab, pillow.
Frontend: react, react-dom, react-router, @tanstack/react-query, lucide-react, class-variance-authority,
clsx, tailwind-merge, @fontsource-variable/inter, @fontsource-variable/jetbrains-mono (fonts bundled, no CDN).
Dev: vite, @vitejs/plugin-react, typescript, tailwindcss, @tailwindcss/vite, vitest, jsdom,
@testing-library/react, @testing-library/jest-dom, @testing-library/user-event.
Removed: streamlit, requests.

## 7. Implementation sequence

| Phase | Scope | Exit criterion |
|---|---|---|
| 1 Foundation | plan, `/api` prefix, React scaffold, design system, layout, landing, overview (real data), health | both apps run together; backend + frontend tests pass; production build passes |
| 2 Ingestion | backend done; add demo load/reset routes, Documents screen (drag-drop, progress, statuses, viewer, delete) | upload every sample through the UI with the documented outcome |
| 3 Extraction | migration v3, segmentation, rule extractor, LLM provider abstraction + quote verification, analysis run endpoint | claims persisted with offsets; LLM failure falls back with a visible label |
| 4 Timeline | timeline query + API + screen | event vs document date and approximate dates visible |
| 5 Reconciliation | rules, finding_claims sides, review status API, reconciliation screen with side-by-side passages | planted discrepancies detected; decoys not flagged |
| 6 Verification | checks + gate + evidence inspector API and screen | every displayed claim navigates to its source span |
| 7 Retrieval | BM25 across passages, claims, items; search screen | results show passage, document, date, state |
| 8 Frontend integration | overview metrics endpoint, review queue, summary screens | no hardcoded numbers anywhere |
| 9 Demo dataset | add follow-up document and ambiguous-date scenario; ground truth file; reset | evaluation script matches ground truth |
| 10 QA | end-to-end tests, Windows run-through, failure drills (no LLM key, backend down) | all suites green |
| 11 Polish | single-process demo, pitch, limitations, final checklist | demo script rehearsed |

## 8. Critical risks (24 hours)

| Risk | Mitigation |
|---|---|
| LLM unavailable, slow or rate-limited on demo day | Rules always run; LLM is additive. Timeout + retries with backoff; failure recorded on the run and shown in the UI. Never block the demo on the network. |
| LLM invents text | Quote must exist verbatim in the passage; offsets computed by the server; otherwise rejected and counted. |
| Frontend scope explosion (9 screens) | Shared primitives and one data pattern; screens built only after their API exists and is tested. |
| Windows setup (Node, Python, PowerShell policy, ports) | Exact commands in README; Node 22 LTS; `curl.exe`; port settings in `.env`; Phase 10 Windows run-through. |
| Rule extractor recall | Section-scoped retrieval investigation escalates possible missed evidence to REVIEW_REQUIRED instead of resolving it. |
| Over-claiming | Fixed disclaimer; wording "potential documentation discrepancy"; review status never described as medical approval. |
| Time | Each phase ends runnable. If time runs out, the last green phase is the demo. |

## 9. Integration strategy

* Dev: Vite on :5173 proxies `/api` to the backend; host and port come from the same root `.env`
  (`MEDUSA_API_HOST`, `MEDUSA_API_PORT`). No CORS configuration needed.
* Demo (Phase 11): `npm run build`, FastAPI serves `frontend/dist` at `/`. One process.
* Contract: backend Pydantic models are the source; frontend types in `src/api/*` mirror them.
  API tests pin response shapes so drift fails a test.

## 10. Test strategy

| Layer | Tool | Focus |
|---|---|---|
| Backend units | pytest | validation, extraction, dates, assertion, rules, gate table, retrieval |
| Backend API | pytest + TestClient | contracts, error envelope, persistence, status transitions |
| LLM | pytest with an in-process fake provider | malformed JSON, missing fields, invented quotes, timeouts, rate limits, fallback labelling. Live provider check is a manual command (needs your key). |
| Pipeline | pytest | demo bundle vs ground-truth file |
| Frontend | Vitest + Testing Library | navigation, loading/error/empty states, upload states, evidence navigation |
| Integration | real servers + Playwright screenshots (run here); Windows run-through (run by you) | full demo flow |
| Mutation checks | planted bugs per phase | prove tests can fail |
