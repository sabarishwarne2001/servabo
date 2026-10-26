# Performance — measurements before launch (campaign session 4, §B)

Measured, not estimated. Each figure names the machine, the command and the date, so a later run
can be compared with it. The sandbox is a shared cloud container (4 vCPU class); a production VPS
of the size RUNBOOK §9.1 asks for is in the same range.

## Bulk delete of 500 documents (HANDOFF carry-over, CAMPAIGN-MAP §4.1)

- **Question:** does one `POST /workspaces/{id}/work-items/bulk` deleting 500 documents (the
  per-request maximum, `MAX_BULK_IDS`) finish well inside a proxy's timeout, or must it move onto
  the `work_items.bulk` job?
- **Run (2026-10-13):** the browser-test stack (uvicorn, the worker with every profile, Postgres 16,
  local storage), Enterprise tenant. 500 one-page PDFs uploaded through the real upload API (8 at a
  time), processing settled, then one bulk delete of all 500.
  Script: `backend/perf/bulk_delete_timing.py` (its docstring has the command).
- **Result:** HTTP 200 in **6.0 s**, 500 deleted, 0 refused (uploads took 67 s including processing).
- **Limits it must stay under:** production Caddy sets no response timeout on `/api/*`
  (`backend/deploy/Caddyfile`); uvicorn has none. A CDN in front would cut at 100 s (Cloudflare) or
  60 s (a typical load balancer). With object storage over the network (MinIO), each of the 500
  object deletions adds a few milliseconds: an estimated 7 to 9 s in production, still far inside.
- **Decision:** the bulk delete stays inline, with its per-document results in the response. The
  `work_items.bulk` job stays registered and unused (the ledger row is `blocked` with this reason);
  it is the path to take if `MAX_BULK_IDS` is ever raised far above 500.

## Frontend first load (session 4, §B.1)

**What "first load" means.** Before the first screen appears, the browser has to download the
JavaScript and CSS that `dist/index.html` points at: the entry script, every file it lists as
`modulepreload` or `stylesheet`, and anything those files import directly. Everything else (each
page's own code, loaded with `import()`) comes later, only when someone opens that page. The
sizes below are gzipped (level 9), which is close to what Caddy actually sends over the network.
Goal: under about 200 KB.

**Result: 634.2 KB to 191.9 KB gzipped (-70%).**

| Step (one commit each) | First load, KB gzipped |
| --- | ---: |
| Before (main at `6802a2b`) | 634.2 |
| 20 pages that `App.tsx` still imported directly are now lazy, like the other 54 | 331.8 |
| The `markdown` manual chunk removed from `vite.config.ts` | 255.3 |
| The two-factor panel (and its QR code library) in the policy notice is lazy | 244.1 |
| The dashboard and organization layouts are lazy, like the platform layout already was | **191.9** |

| First-load file | Before, KB gz | After, KB gz |
| --- | ---: | ---: |
| Entry script (`index-*.js`) | 409.6 | 169.2 |
| `pdf-*.js` (pdf.js, preloaded) | 125.5 | not in first load |
| `markdown-*.js` (marked, DOMPurify, highlight.js, preloaded) | 76.4 | not in first load |
| Stylesheet (`index-*.css`, Tailwind and font faces) | 22.3 | 22.3 |
| `theme-boot.js` | 0.4 | 0.4 |
| **Total** | **634.2** | **191.9** |

What a whole first screen costs now (first load plus that page's lazy chunks):

| Screen | KB gzipped |
| --- | ---: |
| `/login` | 196.7 |
| `/register` (adds the form and validation libraries) | 225.7 |
| Workspace dashboard (adds the dashboard layout and the dashboard page) | 269.7 |

**What was wrong, in plain terms.**

1. *Pages loaded for everyone.* 54 routes were already lazy, but 20 pages were still imported at
   the top of `App.tsx` (sign-in, registration, dashboard, work items, assistant, automation,
   settings, workspace pickers). An import at the top of a file is downloaded before anything
   renders, so a visitor opening the login page also downloaded the assistant canvas, which
   brought pdf.js (125 KB) with it, and the settings pages with their QR code, form and schema
   libraries. They now load with their route.
2. *A shared helper dragged the markdown libraries in.* `vite.config.ts` grouped marked,
   DOMPurify and highlight.js into one "markdown" chunk. Rollup (the tool Vite uses to bundle)
   also puts a group's dependencies into the group. highlight.js is an older (CommonJS) package,
   so the group received Rollup's small shared CommonJS helper. React needs the same helper, so
   the entry script imported the whole markdown chunk to get it, and `index.html` preloaded it
   for every visitor (76 KB). The group is gone; the three libraries now load with the assistant
   canvas, the one page that renders markdown. The `pdf` group has no such dependency and stays.
3. *A dialog mounted everywhere carried a settings panel.* The "your organization requires
   two-factor sign-in" notice is mounted on every screen and imported the two-factor settings
   panel directly. The panel now loads only when that notice actually shows it.
4. *The signed-in chrome loaded on the login page.* The workspace and organization layouts
   (sidebars, menus, command palette, notification tray, billing banners, and the floating-ui
   library that positions menus and tooltips) were imported directly, about 52 KB a signed-out
   visitor never sees. They are lazy now, as the platform layout already was. So a workspace page
   does not wait first for the layout and then for its own chunk, the tenant and organization
   guards start downloading the layout while the tenant is being looked up.

**What is still in the first load, and why.** React and react-dom, React Router, TanStack Query,
axios and the API client (the session is restored before anything renders), sonner (the toast
area is mounted app-wide), the route table, the guards, the sign-in shell, the step-up and policy
dialogs, the loading screen, and the one stylesheet. React and react-dom alone are roughly a third
of the entry. Going much lower would mean removing or replacing one of these, which changes
behaviour, so it was not done.

**Behaviour.** Nothing visible changed except that the pages and layouts listed above now show the
same "Loading…" screen the 54 lazy pages already showed while their code downloads (only on the
first visit after a release: Caddy serves `/assets/*` as immutable for a year, so the files are
cached afterwards), and the two-factor notice shows a small spinner for a moment before its panel.
The Content-Security-Policy is unchanged: `index.html` still has no inline script, and every chunk
is served from the same origin.

**Largest chunks after the change** (only the entry script and the stylesheet are in the first load):

| Chunk | KB gzipped | Loaded when |
| --- | ---: | --- |
| zxcvbn English dictionary (`index-*.js`) | 591.1 | the first keystroke in a "choose a password" field |
| zxcvbn common dictionary (`index-*.js`) | 216.5 | same |
| Entry script (`index-*.js`) | 169.2 | first load |
| `pdf-*.js` | 125.5 (144.5 since F-359: pdf.js's legacy build, for browsers without `getOrInsertComputed`) | pages that show a PDF |
| `AssistantCanvas-*.js` (with the markdown libraries) | 87.1 | the assistant canvas |
| `Automation-*.js` | 44.0 | the automation page |
| `Settings-*.js` | 30.7 | personal settings |
| Stylesheet | 22.3 | first load |
| `ReviewHub-*.js` | 21.0 | the review hub |
| `TruthMesh-*.js` | 18.5 | TruthMesh |

`npm run build` still prints "Some chunks are larger than 1000 kB": that is the zxcvbn English
dictionary (1,172 KB before gzip). It is the password-strength word list, loaded only while
someone types a new password; splitting it would not make any screen faster, so it was left.

**Lighthouse 12.2.1** (mobile profile, simulated slow 4G; Chromium 141 headless; `vite preview`
serving `dist/` with no backend; one run each, so expect a few points of noise):

| Page | Performance before | Performance after | Accessibility | Best practices |
| --- | ---: | ---: | ---: | ---: |
| `/login` | 68 | 91 | 100 (before and after) | 96 (before and after) |
| `/register` | 60 | 86 | 100 (before and after) | 96 (before and after) |

First contentful paint went from 4.6 s to 2.6 s on `/login` and from 4.7 s to 2.8 s on `/register`;
largest contentful paint from 4.7 s to 2.8 s and from 5.0 s to 3.3 s. The 4 points missing in
best practices are one console error that exists only in this setup: with no backend behind
`vite preview`, `GET /api/v1/branding/manifest` answers 404.

**Later in session 4.** The getting-started card (§A.4), the accessibility fixes (F-362) and the
pdf.js legacy build (F-359, outside the first load) leave the first load at **193.0 KB gzipped**
(2026-10-14), still under the 200 KB goal.

**Re-measure:**

```bash
cd frontend
npm run build
node scripts/measure-first-load.mjs                    # first load + the 10 largest chunks
node scripts/measure-first-load.mjs --plus Login       # add a lazy page (chunk name before the hash)
node scripts/measure-first-load.mjs --max-kb 200       # exits 1 above a budget, usable in CI
```

Lighthouse, as run here (any free port; Chromium from the Playwright browser folder; this sandbox
also needed `--no-proxy-server` in the Chrome flags because it routes traffic through a proxy;
stop the preview server afterwards):

```bash
cd frontend && npx vite preview --port 4317 --strictPort --host 127.0.0.1 &
CHROME_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome npx --yes lighthouse@12.2.1 \
  http://127.0.0.1:4317/login --only-categories=performance,accessibility,best-practices \
  --chrome-flags="--headless=new --no-sandbox" --output=json --output-path=./lh-login.json
```

## A workspace with 10,000 documents (session 4, §B.3)

- **Question:** do the document list and its search and filters stay fast when one workspace holds
  10,000 documents, through the real API (authentication, tenant checks, serialization)?
- **Run (2026-10-14):** the browser-test stack (uvicorn, Postgres 16), the Business tenant
  `load-tenant-1` from `perf/load_seed.py`, 10,000 processed documents added as rows (no files: the
  list is what is measured). Each read five times as the tenant's owner.
  Script: `backend/perf/many_documents.py --org load-tenant-1 --count 10000`.

| Read (50 per page) | Median ms | Slowest ms | Rows |
| --- | ---: | ---: | ---: |
| First page | 40 | 42 | 50 |
| A page near the end (offset 9,950) | 41 | 44 | 50 |
| Search by name | 39 | 41 | 10 |
| Status filter | 37 | 46 | 50 |

- **Database plan for the first page:** an index scan of `ix_work_items_workspace_created`
  (workspace, newest first), 8.4 ms inside Postgres; the rest is the API around it. (The seeded rows
  share one `created_at`, which forces the tie-break sort to read them all; real uploads have
  distinct times, so production does less work than this.)
- **Verdict:** no change needed. A customer with ten thousand documents sees the same list speed
  as one with ten.

## Queries per list request (session 4, §B.3)

`backend/tests/api/test_list_queries_do_not_grow.py` counts the SQL statements one request runs
with 3 and with 30 rows behind it, for the document list, the member directory and the audit log.
The member directory ran one query per member (10 statements for a handful, 37 after adding 27):
**F-350**, fixed by loading the people in one query. The document list and the audit log did not
grow. The test stays in the suite, so a new per-row query fails CI.

## Indexes (session 4, §B.4; F-017)

- The slow paths measured above use indexes: the document list (`ix_work_items_workspace_created`),
  the audit log (`ix_audit_logs_organization_id_created_at_id` and the partial index for denials), the status filter (`ix_work_items_workspace_status`) and
  the per-organization lookups behind every tenant check (primary and foreign keys).
- **F-017's 283 lines** are indexes and constraints that exist in the database (created by
  migrations: partial indexes, GIN and vector indexes, check constraints, trigger-backed rules) but
  are not declared on the SQLAlchemy models. They are real, wanted objects, not drift: the drift
  gate (`backend/scripts/check_migration_drift.py`, run in CI) compares against a recorded baseline
  of exactly these lines (`backend/alembic/drift_baseline.txt`) and fails on any new difference; the
  baseline can only shrink.
  **DECIDED (campaign session 4):** they stay as they are; declaring 283 database objects on the
  models would change nothing the database does, and the ratchet already stops new drift.

## Load test (session 4, §B.2)

**Tool and scripts:** Locust (`backend/perf/locustfile.py`), 5 tenants × 10 people seeded by
`backend/perf/load_seed.py`, verdict by `backend/perf/load_report.py` (p95s, 5xx in the API log,
tracebacks, pool exhaustion, `/health` latency as the event-loop probe). 50 simulated people, 5 per
second ramp, 15 minutes, against one API process and one worker on the test machine:

```
LOAD_USERS=/tmp/servabo-load-users.json locust -f perf/locustfile.py --headless \
    --host http://127.0.0.1:8000 -u 50 -r 5 -t 15m --csv /tmp/servabo-load
python perf/load_report.py --csv /tmp/servabo-load --api-log /tmp/servabo-e2e-logs/api.log
```

| | Before F-363 | After F-363 (2026-10-14) |
|---|---:|---:|
| Requests | 12,015 | 27,102 |
| Median | 200 ms | 130 ms |
| p95 / p99 | 10,000 / 21,000 ms | **670 / 1,300 ms** |
| `/health` p95 | 9,900 ms (event loop blocked) | **150 ms** |
| Server errors (5xx) | 172 | **0** |
| Tracebacks in the API log | 205 | **0** |
| Database pool exhausted | yes | no |

Per request after the fix (p95): dashboard 550 ms, document list 480 ms, one document 490 ms, my
organizations 420 ms, admin pages 470–580 ms, a new assistant conversation 690 ms, a streamed answer
1,400 ms (the model stand-in answers instantly; a real model adds its own time), a PDF upload 1,500 ms.

**What it found:** F-363 — a commit inside the streamed answer's preparation expired the
conversation, and its next attribute read ran a query on the event loop, freezing every request for
seconds at a time. Fixed (the expired objects are reloaded in the threadpool) and guarded by a test
that fails on any query run on the event loop.

**The 9 dropped connections** (of 27,102) are the local server's 5-second keep-alive closing an
idle connection just as Locust reused it; production runs gunicorn with `--keep-alive=75` behind
Caddy (`backend/docker-compose.prod.yml`). They are not server errors.

**Sizing note:** one API process served 30 requests a second at these latencies; production runs
four (`--workers=4`) on COSTS.md's server (4 vCPU, 16 GB). Re-run this before a large customer onboards, against the real server.

## Helm's Promise ledger after one document changes (Session B, 2026-10-18; F-498)

- **Question:** the ledger update that follows a document change recomputed the whole workspace and took
  2.9 s at 10,000 documents (the budget is 1 s). Can it cost what the change costs?
- **Run (2026-10-18):** the sandbox (4-core container, Postgres 16, one run at a time, nothing else
  running), `HELM_PERF_DOCUMENTS=10000 pytest tests/performance/test_helm_budgets.py -q -s`. One workspace
  with a distributor's year (about 6,200 invoices, orders, receipts, credit notes, 13 bank statements, 40
  supplier statements), the ledger built, then one invoice created and marked changed
  (`hooks.document_changed`), then the job the worker runs for it (`handle_ledger_build`) timed from the
  call to its return, so it includes opening the session, finding the books, the ledger update, the value
  sweep and the re-plan request.
- **Before (the same test, the whole workspace recomputed):** **4.07 s** through the job (2.76 s for the
  ledger update alone). Over budget; the test failed.
- **After:**

  | | 1,000 documents | 10,000 documents |
  |---|---|---|
  | Update after one document changes (budget 1 s) | 0.29 to 0.33 s | **0.69 to 0.72 s** (three runs) |
  | The first update after a worker starts (reads the bank statements; budget 2 s) | 0.27 to 0.31 s | 1.40 to 1.59 s |
  | First full build of a workspace | 2.2 to 2.5 s | 23.3 to 23.7 s |

  About half of the 0.7 s is the ledger update itself; the rest is the value sweep (it reads every payable
  promise of the book) and the job's own sessions.
- **Why it is that fast, and what it costs:** only the changed document, what its promises were fulfilled
  by, the documents of its procurement cases, and the invoices that can take the same bank line are
  re-projected (`docs/helm/ARCHITECTURE.md` §4.5). The bank statements' lines are the one thing read every
  time; a long statement is kept in the worker's memory after its first read (24 statements), so the first
  update in a fresh worker costs about 0.8 s more.
- **It is the same answer as a full rebuild.** `tests/services/helm/test_ledger_incremental_equivalence.py`
  compares them row for row after every change of 300 random runs of 40 changes (and four people changing
  at once); the nightly job compares them again on real data and alerts the operator on a difference.
- **What is still full:** the first update on a new day (statuses depend on today), a change of who we are
  or of the workspace's date format or currency, a first build, and more than 200 documents changed at once
  (a bulk import). The nightly rebuild is a full one by design (23 s at 10,000 documents, in the worker,
  at 02:40 UTC).
- **Decision:** N-122.

## GST Credit: importing 10,000 GSTR-2B records and matching them against 10,000 documents (Session F, 2026-10-19)

- **Question:** the brief asks that importing 10,000 records and matching them against 10,000 book documents each
  stay under 5 s on the sandbox.
- **Measured by** `tests/performance/test_gst_budgets.py`: a workspace with 10,000 purchase invoices from 40
  suppliers (bulk inserts), and a 10,000-record GSTR-2B built from them (about 75% reported as booked, 10% with
  an amount off, 5% with another number format, 15% not reported at all, plus records Servabo has not seen).
  The first run (before any tuning) took **3.55 s** to import and **9.51 s** to match: over budget.
- **What made matching slow, and the change:** the full money reader ran six times per document (plain numbers,
  which is what the extraction prompt asks for, now take a fast path); every unmatched pair was compared by
  number with `difflib` before the cheap date and value tests (now last, behind `quick_ratio`); a UUID was turned
  into text to sort 10,000 times (now sorted by its integer); the reconciliation read each document's text and
  verification state it does not use (a lean loader reads only what it needs); the matches were inserted through
  the ORM (now one Core insert in chunks of 2,000).
- **After:**

  | | 10,000 records / 10,000 books |
  |---|---|
  | Import (parse the file, store the return and its records) | **3.3 s** |
  | Matching (read the books, reconcile, store the result) | **4.4 s** |

  Matching reads the books (about 1.3 s), reconciles in memory (about 1.0 s) and writes 10,000 rows (the rest).
  The test holds each to 5 s times `PERF_BUDGET_MULTIPLIER` (2 by default so a shared CI machine does not flake;
  set it to 1 to hold the sandbox to the brief's figure). A change of one document re-reconciles the whole GSTIN
  for the workspace, debounced to one job every ten seconds.
- **Decision:** N-136.

## GST Credit: the matching step on a shared CI machine (Session H, 2026-10-19)

- **Question:** after Session F and Session G merged, the CI run on `main` failed `test_import_and_matching_stay_inside_their_budgets`
  with "matching took 11.48s" (the budget is 5 s times `PERF_BUDGET_MULTIPLIER` 2 = 10 s). It had passed in the
  session sandbox, which is faster than a CI runner. The budget and the multiplier were **not** changed: the code was.
- **Where the time went** (measured on the sandbox with the multiplier at 1, `cProfile` and wall-clock timers around
  each step; matching was 4.0 to 4.3 s before, in three runs):

  | Step of `engine.recompute` at 10,000 / 10,000 | before | after |
  |---|---|---|
  | Writing the 11,457 result rows (`INSERT` through SQLAlchemy, then `COPY`) | about 2.0 s | about 0.7 s |
  | Reading the books (`load_books`, one Python view per document) | about 0.95 s | about 0.8 s |
  | Reconciling in memory (`reconcile`) | about 0.9 s | about 0.3 to 0.5 s |
  | Reading the records, building rows, IMS | about 0.4 s | about 0.4 s |
  | **Matching, whole** | **4.0 to 4.3 s** | **2.0 to 2.4 s** (2.3 to 3.2 s before the collector pause) |
  | **Import** (parse, store 10,000 records) | 2.7 to 3.2 s | 1.5 to 2.0 s |

- **What the brief guessed, and what the measurement said:** the suggestion loop (every free record against every
  remaining book of its supplier) was a smaller cost than assumed (under 0.2 s of `reconcile`), and the duplicate-notes
  loop does nothing when no document is entered twice. The biggest single cost was storing the rows: each value was
  adapted one at a time in Python and sent in a multi-row `INSERT`.
- **The changes:**
  1. `app/services/gst/bulk.py`: the matches and the imported records are written with one `COPY` per 5,000 rows.
     `tests/services/gst/test_bulk.py` proves it stores exactly what the old insert stored, including quotes,
     commas, new lines, a backslash, the two characters `\N`, an empty string, non-ASCII text, nested JSON and NULLs.
  2. Suggestion candidates are looked up by supplier, kind and day (the seven days a record can match) instead of
     scanning every book of the supplier; the "entered twice in your books" notes use an index by document.
  3. The plain-key check in `books._flat` is remembered (a bounded cache) and uses `collections.abc.Mapping` (the
     `typing.Mapping` check was 0.2 s of the profile by itself).
  `tests/services/gst/test_matching_equivalence.py` keeps the earlier `reconcile` as a frozen reference
  (`reference_matching.py`) and holds the new one to it, row for row, on five seeded random workloads of 400
  documents that reach exact, number-format, suggested, amount-off, duplicate, amended, credit-note, name-only
  supplier, entered-twice and decided cases. It was checked to fail when the new day window is narrowed by one day.
- **What CI said about that first fix (and the second fix).** The first push still failed on CI: matching took **10.37 s**
  (11.48 s before), against 10 s. On the build machine the same change had saved about 30%, on CI about 10%: CI's
  processor is about 3 to 3.5 times slower than the build machine's, so the Python work (not the database) is what has
  to shrink. A `cProfile` run showed the cyclic garbage collector as the largest single cost (about 0.9 s of 2.9 s here,
  so about 3 s on CI): a recompute builds about half a million short-lived objects and none of them forms a cycle, but the
  collector kept walking the growing heap. `app/services/gst/gcpause.py` now pauses it while a recompute or an import
  runs. It is a process-wide switch, so it is counted (back on only when the last section ends, and only if it was on when
  the first began), always undone, and a section lasts seconds; `test_gcpause.py` proves each of those. The `COPY` rows are
  also written with Python 3.12's C `csv` writer (`QUOTE_STRINGS`) instead of one function call per value.
  Matching on the build machine is now **2.0 to 2.4 s** and the import **1.3 to 1.7 s** (`PERF_BUDGET_MULTIPLIER=1`).
  Expect about 6 to 8 s on CI; CI on this pull request is the proof.
- **Why not a stricter test:** a second, tighter budget would flake on the same shared machines this fix is for.
  The existing budget stays as it was.
- **Decision:** N-142.

## GST Credit: the speed test's steps after Final session 1 (Final session 2A, 2026-10-26)

- **Question:** the speed test flapped once on CI with only "matching took …s" in its message, so nobody could tell which
  step was slow, or whether Final session 1 (the GST notices, the Monday digest, the e-invoice check) had made matching slower.
- **Change to the test only:** `tests/performance/test_gst_budgets.py` now times each step by wrapping the functions
  `recompute` and `import_file` call, prints them with `-s`, and puts them in the failure message, for example
  "matching took 11.48s (budget 10.0s): read records …; read books …; reconcile …". **The budget did not move** (5 s times
  `PERF_BUDGET_MULTIPLIER`, 2 on CI).
- **Measured on the build machine** (`PERF_BUDGET_MULTIPLIER=1`, 10,000 records and 10,000 books, one run):

  | Step | seconds |
  |---|---|
  | Import: parse the file | 0.78 |
  | Import: write the 10,000 records (`COPY`) | 0.65 |
  | Import: the rest (the return row, checks) | 0.37 |
  | **Import, whole** | **1.80** |
  | Matching: read the records | 0.21 |
  | Matching: read the books (`load_books`) | 0.88 |
  | Matching: reconcile | 0.19 |
  | Matching: IMS, exposure and building the rows | 0.12 |
  | Matching: write the 11,457 result rows (`COPY`) | 0.75 |
  | Matching: ask Helm to replan (`hooks.replan`) | 0.01 |
  | **Matching, whole** | **2.23** |

- **Verdict:** the same as Session H's after-figures (matching 2.0 to 2.4 s, import 1.3 to 1.7 s; the import's 1.8 s is one
  run on a busy machine). Final session 1 did not make matching slower, so nothing in the code changed. Reading the books
  and writing the rows remain the two largest steps; if CI ever fails again, the message now says which.

## The e-invoice QR search on documents that cannot hold a code (Session I, 2026-10-20; F-532)

Session F's e-invoice reading (PR #31) renders up to three pages of every PDF in the OCR worker and runs OpenCV over each.
The worker runs one job at a time, so every second spent there is a second every queued job waits.

- **Where the time goes** (one A4 page at the render scale in use, 2.5; idle build machine, best of 3): the WeChat detector
  1,557 ms, the standard detector 86 ms, the Aruco detector 15 ms; rendering 2 to 38 ms. At scale 2.0, 1.5 and 1.0 the
  WeChat detector takes 513, 291 and 95 ms. The WeChat detector is the only one that reads dense signed codes: on codes as dense as
  a real token (868 characters) it read every one tried, Aruco read 5 of 8 and the standard detector none. It is fast when a
  code is present (13 to 147 ms); the cost is the search of a page that has none.
- **What was tried and rejected:** a smaller render scale (a printed code is small: a 3 cm code of about 110 modules is
  about 1.9 px a module at scale 2.5 and about 1.2 px at 1.5, below what decoders usually read) and the quick detectors first (they miss codes the slow one reads). Neither was
  worth a risk that cannot be checked here without a real e-invoice (still unverified, N-140).
- **The change:** a page whose objects are all text is not rendered or read (`page_may_hold_a_code`). Pictures, drawings and
  forms are read as before (N-147).
- **Figures** (idle build machine; `PERF_BUDGET_MULTIPLIER=1` where a budget applies):

| Measure | Before | After |
|---|---|---|
| `token_texts` on 3 pages of text (`tests/performance/test_einvoice_scan_budget.py`, budget 250 ms) | 2,888 ms | 1 ms |
| The 7 browser-suite sample PDFs, all together | 12,105 ms (1.2 to 1.5 s each; the 3-page packet 4.0 s) | 6 ms |
| 12 one-page invoices, upload to every job finished | 113.0 s (111.4, 114.8, 112.7) | 103.2 s (103.6, 103.5, 102.6) |
| The same, with the scan removed altogether | 102.3 s (103.1, 101.5) | |

  Per document that is 9.4 s before, 8.6 s after (8.5 s with no scan at all): about 0.9 s, 10%, and the fix gives back 92% of
  what the scan took. The rest of the 8.5 s is the pipeline itself (about eight jobs one after another, each waiting for the
  worker's next pass). Method: a script uploads 12 unique one-page invoices to the browser tests' workspace and waits for
  the job queue to be empty; the worker was restarted between variants, with the scan call replaced by "find nothing" for the
  "removed" row.
- **Not covered by these figures:** a document with a picture on every page still pays 1.6 s a page (3 pages at most). That
  is the cost of looking for a code that is not there, and the next step if it matters would be reading only the region of
  the page where the picture is.
