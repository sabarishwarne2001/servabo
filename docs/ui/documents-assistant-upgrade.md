# Documents and AI Assistant upgrade

The Documents console and AI Assistant now share navy surfaces, blue/violet accents, restrained glow, clear hierarchy and responsive panels. Light mode and organization navigation remain supported. Figures, prices, document scope and source references come from the application; the reference images' sample statistics and trends are not copied.

## Documents

- Workspace-wide total, processing, completed and failed counts come from `GET /workspaces/{id}/work-items/counts`, using one grouped query under `RequireWorkspaceViewer`. Queued documents are shown separately in the processing card's detail. Failed processing is not presented as a review status.
- Filename, status, format and inclusive upload dates persist in the URL along with sorting, page and page size. Dates use UTC. Invalid URL values fall back safely; reversed form dates show an error. Reset clears filters, and pages outside the result range return to the last available page.
- Corrected the existing API mismatch: the frontend now sends `skip`, `limit`, `sort_by`, and `sort_order`, and normalizes the server's `totalItems`. Rows and totals use the same filters; sorting retains the existing ID tie-breaker.
- Upload progress, partial failures, duplicates, retry/delete confirmations, details and bulk actions continue to use existing workflows. Narrow screens retain document cards with full filenames. Content search and historical trends were not introduced without a supporting data contract.

## AI Assistant

- Retains the session list, search, rename, pin/archive/delete, scope picker, provider/model registry, real price-book information, organization templates, exports, message persistence and citations.
- Starter actions insert prompts into the composer; from an empty workspace they first create an actual conversation. They never fabricate or automatically submit answers.
- Conversation previews contain up to 180 characters of the latest actual user message, fetched inside the existing owner-and-workspace-scoped session query. No migration or per-row request is needed.
- Unsent drafts stay in memory with their own conversation. Switching workspace clears them. Conversation keys and placeholder handling prevent old history or another workspace's list from carrying into the next selection.
- Multiline input supports Enter to send and Shift+Enter for a newline. Failed sends retain the question and show a persistent recovery message. Message scrolling stays inside the chat panel.
- Assistant Markdown uses the existing sanitized renderer. Inline numeric citations are only interactive when a corresponding source exists; existing source cards remain available even when the model emits no inline markers. User messages remain plain text.
- The citation drawer uses a body portal above the application header, traps keyboard focus, restores focus on close and retains source navigation/copy/document links. Viewer mutation controls are withheld or disabled.
- Desktop grid rows constrain long histories so the composer stays inside the viewport. On smaller screens the history and chat stack, with internal scrolling. Reduced motion is respected.

## Verification

Validated with Python 3.12, Node 24 and Chromium. Dependencies and lockfiles are unchanged. No schema migration is required.

| Check | Command / scope | Result |
|---|---|---|
| Frontend build | `cd frontend && npm run build` | Passed; existing chunk-size advisory remains |
| Lint | `cd frontend && npm run lint` | Passed; generated `dist-e2e-*` output is now excluded |
| Types | `cd frontend && npm run typecheck && npx tsc -p e2e/tsconfig.json` | Passed |
| Unit tests | `cd frontend && npm run test:unit` | 283 passed |
| API contracts | `cd frontend && npm run verify:contracts` | 12 contracts agreed with the live server |
| Backend | `cd backend && env -u AWS_PROFILE .venv/bin/python -m pytest tests/api/test_document_console.py tests/api/test_work_item_list_filters.py tests/api/test_assistant_session_preview.py tests/security/test_work_item_child_routes_are_workspace_scoped.py -q --maxfail=3` | 19 passed |
| Browser regressions | Selected Documents/AI Assistant checks from `22-phase1-documents`, `11-assistant-intelligence`, plus `139-premium-documents-assistant` | 19 passed; 1 expected skip |
| Visual/accessibility | Light/dark, 1440/768/390 pixels, no horizontal viewport overflow; axe WCAG A/AA scans on both pages at desktop/phone widths | Passed, including a separate rerun asserting the desktop composer remains in the viewport |

The browser stack uses the separate `servabo_ui_e2e` database, repository ML stubs and the existing deterministic local model (`E2E_LLM=1`). Database persistence, upload/processing orchestration, retrieval, citations, scope, templates and export run through the real application. These results do not establish live Groq/Gemini model quality or credential availability. The skipped existing test expects a genuinely unavailable provider; a new controlled 503 browser test independently verifies composer recovery.

Reproduce the browser run after starting `frontend/e2e/scripts/start-stack.sh` with the documented test overrides:

```bash
cd frontend
E2E_LLM=1 E2E_API_ORIGIN=http://127.0.0.1:8001 \
E2E_CHROMIUM_PATH=/usr/bin/chromium E2E_WORKERS=1 \
npx playwright test --config e2e/playwright.config.ts \
  e2e/tests/139-premium-documents-assistant.spec.ts \
  e2e/tests/22-phase1-documents.spec.ts \
  e2e/tests/11-assistant-intelligence.spec.ts \
  --grep 'document filters survive|sort and rows|starters fill|scope and templates|unsent drafts|both themes|failed sends|readers are|AI Assistant|Documents list filters|Uploading from|no upload zone|documents read as|link can open'
```

Pass the same database/test environment settings to the runner and stack script so the idempotent seed targets the test database. The setup run used `ENVIRONMENT=test POSTGRES_DB=servabo_ui_e2e ML_STUBS=true STORAGE_BACKEND=local RATE_LIMIT_ENABLED=false`, plus the local mail sink settings described in `frontend/e2e/README.md`. Never point test seeding at production data.

## CI regression follow-up

The CI self-check caught two document count displays bypassing the shared locale formatter. KPI counts, queued counts and pagination ranges now use `formatNumber` from the display-preferences layer. `npm run check:self` passes without relaxing its guard.

Two existing browser checks assumed a named fixture would appear on the first unfiltered page. With server pagination active, newer uploads can move it onto a later page. The list test now explicitly searches for the purchase order and checks its completed status and exclusion of the invoice. The workspace-switch test searches for the invoice in Operations, then repeats that search in Finance and requires an empty result. These assertions exercise the whole filtered collection rather than treating absence from page one as an isolation guarantee.

The two corrected browser checks passed locally against the production bundle with `E2E_CSP=1`; lint, both type checks and the 283 frontend unit tests were also rerun. The GitHub PR checks are the authority for the complete remote CI result.

## Screenshots

Captured using synthetic seeded test accounts/documents. The before images use the unchanged frontend at `02063e4ad7ace92515cc79ab2aa90608405e8fe1`, built from an archive outside the checkout. After images use this implementation. Browser test output also includes tablet and light-theme captures.

| Page | Before | After | Phone |
|---|---|---|---|
| Documents | [Before](screenshots/documents-before.png) | [After](screenshots/documents-after.png) | [Phone](screenshots/documents-mobile.png) |
| AI Assistant | [Before](screenshots/assistant-before.png) | [After](screenshots/assistant-after.png) | [Phone](screenshots/assistant-mobile.png) |

## Completion audit

- [x] Both pages use the shared visual treatment without redesigning unrelated routes.
- [x] Existing supported controls and workflows remain connected to the application.
- [x] Counts, filters, pagination, scope, templates, exports and citations use real contracts.
- [x] Backend workspace isolation and private session previews are tested.
- [x] Upload behavior and viewer restrictions have browser coverage.
- [x] Markdown sanitization has targeted XSS and citation tests.
- [x] Builds, lint, types, unit/backend/browser checks and visual review completed.
- [x] Desktop, tablet, phone, both themes, reduced motion and practical accessibility checked.
- [x] No dependency, lockfile, migration, production secret or production-data change.
- [ ] Live external AI-provider validation: not performed; deterministic test provider used.

The implementation is available for review in [pull request #39](https://github.com/sabarishwarne2001/servabo/pull/39), targeting `main` from `feat/premium-documents-ai-assistant-ui`.
