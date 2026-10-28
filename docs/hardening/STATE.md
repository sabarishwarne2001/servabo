# Hardening campaign — STATE

_FlowPilot AI was renamed Servabo on 2026-10-16. Entries below that date keep the old name._

_Last updated: 2026-10-28 (Final session 2T started)_

## Current phase — Final session 2T (TRINETRA finished for Business and Enterprise) (2026-10-28)
Branch `claude/new-session-9f51dc` (the session's assigned branch; CLAUDE.md says `hardening/<topic>`, the brief says "use the assigned branch"),
based on `main` at `2041ef6` (PR #43 merged). Founder authority delegated (N-190): decisions are logged as `DECIDED (Final 2T)` from **N-200**,
findings from **F-641**, browser specs from **141**. Prompt: `docs/sessions/FINAL-2T-TRINETRA.md`. **If cut off, type `continue`: carry on from
the first unticked box. Never restart a ticked phase.** The completion matrix is `docs/trinetra/COMPLETION.md`.
Local stack: Postgres 16.15 (Ubuntu) with pgvector 0.8.0 (the files from the `pixeltable-pgserver` wheel copied into the system
extension folders after the owner allowed it; the Ubuntu 0.6.0 backed up in `/dev/shm/vector06-backup`) on :5434 (backend tests, cluster
in `/dev/shm/pgdata2`), Redis, backend venv Python 3.12 in the session scratchpad (`backend/.venv` is not git-ignored). Env block:
`testenv.sh` in the scratchpad. After a container restart recreate the cluster (initdb, role `servabo`, database `servabo_test`).
Decisions so far: **N-200** (TRINETRA's data lifecycle). Findings reserved: F-641 Helm hold, F-642 touch means changed, F-643 seller
check (a 500), F-644 capacities (Phase 2), F-645 one PAN two workspaces, F-646 no pilot mode (Phase 2), F-647 recompute does nothing
(Phase 7), F-648 case list queries, F-649 write forms (not a defect). Next free after these: **N-201**, **F-650**.
UI work owed to Phase 8 by Phase 1: a checkbox for `seller_name_confirmed` (create and reconfirm), the cockpit's
`withholding_holds` list on the Helm page, `cash_due_micros` / `reminder_held` in the ledger note.

- [x] 0. Start-up: docs and code read; stack; this checklist; draft PR #44
- [x] 1. Phase 0: `docs/trinetra/COMPLETION.md` (every brief sentence and every "like every other feature" row)
- [x] 2. Phase 1 (P0), DONE (commits 1.1 to 1.7; 1.6 is not a defect, pinned by a test; 1.7 decided as N-200), each test-first: 2.1 Helm hold (net cash due, Guard block, release list); 2.2 evidence fingerprint instead of `updated_at`;
  2.3 seller check (PAN normalized, from GSTIN, name-only needs confirmation, 422 not 500); 2.4 one PAN, one profile per organization;
  2.5 case list in batches (query-count test); 2.6 who sees the write forms; 2.7 one data-lifecycle rule
- [x] 3. Phase 2 (P0), DONE (N-201 modes, N-202 capacities; the figures: Business 2 profiles, 12 active snapshots, 500 open cases, 50 inquiries a month; Enterprise 10, 60, 5000, 500): three modes (off, pilot, on; ships "pilot") and one helper `live_for(org)`; platform enrolment; plans and capacities
  (active snapshots, open cases, inquiry allowance); `preflight.py`
- [x] 4. Phase 3 (backend DONE; screens in Phase 8; hostile-file corpus and speed budget in Phase 9; unverified readers wait for 2B; N-203): Servabo template (CSV/XLSX) and the readers for Form 26AS / Form 168 text and the AIS CSV; reader registry; limits
- [ ] 5. Phase 4: printed hints to suggestions; expectations template; Zoho customer-payment TDS; deductor directory
- [ ] 6. Phase 5: credit notes; reversals; advances; sourced taxable basis; split remittances; new statuses; reject and annotate
- [ ] 7. Phase 6: authorized inquiries (secure link, allowance, reply); approval chains (Enterprise); closure ledger; measured time
- [ ] 8. Phase 7: Getting started; search; notifications + `trinetra.recompute` doing real work; digest; value receipt and monthly; automation
  triggers; webhooks and API; warehouse dataset; organization view; Recoveries; Helm ledger; egress and legal holds
- [ ] 9. Phase 8: the screens (selector, filters, KPIs by confidence, waterfall, tutorial, import, inquiry, approvals, held reminders, states),
  USER-GUIDE, browser specs by role and plan
- [ ] 10. Phase 9: performance budgets, hostile files, isolation sweeps, prompt injection, privacy (TAN scrubber), threat model
- [ ] 11. Phase 10: docs/trinetra/*, campaign records, website, owner launch checklist, FINAL-2-LIVE.md, FINAL-SESSIONS.md
- [ ] 12. Finish line: backend, frontend, website and browser suites; `campaign_slices.py --check all`; one Alembic head, up/down/up populated;
  PR ready; CI green

- **Next action:** step 0, then Phase 0 (COMPLETION.md). Next free numbers: **N-200**, **F-641**, browser spec **141**.

## Current phase — Final session 2A (FINAL-2-UPGRADE) (2026-10-26)
Branch `claude/new-session-gbo9ee` (the session's assigned branch; CLAUDE.md says `hardening/<topic>`, the brief says "use the session's
assigned branch"), based on `main` at `5600d9d` (PR #42 merged). Founder authority delegated: decisions `DECIDED (Final 2A)` from **N-191**,
findings from **F-626**, browser specs from **137**. Prompt: `docs/sessions/FINAL-2-UPGRADE.md`. **If cut off, type `continue`: carry on from the
first unticked box. Never restart a ticked phase.**
Local stack this session: Postgres 16 with pgvector 0.8.7 from the `pgvector/pgvector:pg16` image (pulled through `mirror.gcr.io`; Docker Hub
answered 429) on :5433 (e2e) and :5434 (backend tests), Redis, backend venv Python 3.12 and `npm ci`. The environment block is `testenv.sh` in
the session scratchpad (outside the repo).

- [x] 0. Start-up: docs and code read; stack; this checklist; draft PR #43; `main`'s latest CI (run #482 on `5600d9d`) green
- [x] 0A. `docs/product/COMMERCIAL-READINESS.md`
- [x] 0B. `docs/product/RESOLUTION-ASSESSMENT.md` and the build decision: N-191, build a thin "Recoveries" layer after the must-haves
- [x] 1. Prices and packaging for India (N-187): catalogue per currency and interval, add-on prices, Dodo products, rupee checkout (currency,
  country, tax id), the ₹15,000 mandate notice, 14-day trial, "Starter", custom domains to Business and Enterprise, the Tally file on Starter,
  unit economics in every currency, the website, docs, tests. Findings F-626 to F-629; decisions N-192, N-193 (open: GSTIN on the
  Dodo invoice). Browser regression of the billing, plan and ERP specs: 175 passed, 4 failed and fixed (F-629, N-187 expected values,
  spec 137 isolation), re-run green. Unverified until 2B: Dodo's real rupee checkout, its exact refusal wording above the mandate.
- [x] 2. Safety jobs that cannot stop silently: run reports, the stale watcher and alert, readiness `safety_jobs`, the health page, the
  sweeps in the scheduler (or not, recorded), `servabo-install-host-jobs`, preflight, docs, tests. Sweeps stay on cron (N-194);
  readiness adds `safety_jobs: degraded` only when degraded (a healthy answer stays `{"status": "ready"}`, F-042). Unverified until
  2B: a real server's cron, and the stopped-cron email arriving the next day (checklist step 10).
- [x] 3. Prompt injection: `docs/hardening/PROMPT-INJECTION.md`, registry-walking invariants (a) to (f), the red-team corpus, fixes test-first.
  Six findings fixed test-first (F-631 to F-636): a learned address is never a recipient until confirmed (N-195, migration `s2a3`);
  no automatic approval on a document that reads like instructions; Helm never takes a payment decision alone (N-196: the act cap
  is gone for payments); every prompt fences document text; emails bound document values; a QR "number" that is a sentence is
  not read. Open: N-197 (ERP auto-post of a case completed by an outside upload). Unverified until 2B: the real models on the corpus.
- [x] 4. Leftovers: the GST speed test's timings, deletion warning emails, a zip in the upload tray, `k1a6`'s downgrade with rows, PR #39's
  loose ends. GST matching 2.23 s / import 1.80 s, as Session H (no code change, budget unchanged); deletion warnings at once and 5 days
  before (migration `s2a2`); the global tray takes a zip (spec 138); `k1a6` proven safe with rows (no change); spec 122 → 139.
  CI on the PR was red after Phases 1-2 and is fixed in code: F-630 (ERP plan check before lookup), the safety-job webhook through the
  egress gate, the data map, N-187 expected values, the website's fonts (Lighthouse 97 again). Spec 78 (Helm "already planning",
  409) failed once on CI and passed twice locally: watched, not yet explained.
- [x] 5. The proof kit: `scripts/accuracy_report.py`, `docs/product/PILOT-PLAYBOOK.md`. The report compares a truth sheet
  (`scripts/accuracy_truth_template.csv`) with the extraction: field and document accuracy, the review catch rate, every miss,
  no document values. Tested with an invented truth sheet; 2B runs it on the owner's invoices. Pilot price: N-198 (decided).
- [x] 6. The Resolution layer: first declined by the cut line, then **built at the owner's request (2026-10-27)**: Recoveries
  (N-191, docs/product/RECOVERIES.md). Five kinds, closure only on evidence, one outcome ledger with Helm's keys, Business and
  Enterprise with a preview, the receipt / monthly / digest / Getting started lines, migration `s2a4_recoveries`, the hourly
  `recoveries.sweep` job, 27 backend tests, 3 unit tests, browser spec 140 (Found to Verified on the sample company, axe light
  and dark). Found by the walk and fixed test-first: an organization owner could not own an issue (derived admin).
- [x] 7. Records and the docs customers see: PRODUCT-NEXT, COSTS, RUNBOOK, CONFIGURATION, the env templates, DODO.md and
  DODO-LOCAL-TEST.md (journey I: the rupee journey, the mandate notice, the GSTIN), the website (rupees and dollars, the 14-day
  trial, `/trinetra` per user), CHANGELOG, FINDINGS (F-626 to F-636), COVERAGE, NEEDS-OWNER (N-191 to N-198), FINAL-SESSIONS.
- [x] 8. `docs/sessions/FINAL-2-LIVE.md` rewritten (2T adds TRINETRA's phase and removes the note); HANDOFF "Final session 2A →
  Final session 2B". One small code change for it, test-first: the deletion-warning job honours `run-job --now` outside
  production, so 2B sees the "last chance" email. Finish-line checks run here: frontend typecheck, lint, `check:self`,
  `test:unit` (299) and build; the website's typecheck, build and checks; `campaign_slices.py --check all` 0; one Alembic head
  `s2a3_counterparty_contact_source`, up, down three (to `tr1a2_review_outcomes`) and up on an empty database. The full backend
  and browser suites: on the ready PR's CI (sabarishwarne2001/servabo#43).

- **Next action: Final session 2T** (`docs/sessions/FINAL-2T-TRINETRA.md`, TRINETRA for Business and Enterprise), after PR #43
  is merged with CI green. Then Final session 2B (`docs/sessions/FINAL-2-LIVE.md`) on the owner's PC. Next free numbers:
  **N-200**, **F-641**, browser spec **141**.
- **The owner's request of 2026-10-27, "finish everything in this session":** done. Recoveries (above); N-197 decided and built
  (ERP auto-post waits for a person on a case an outside upload completed); N-198 decided (the pilot: one month on Business,
  up to 3 seats, ₹9,999 plus GST, credited against the first year); the Gmail dark-mode logo (a white panel on the light
  logo); F-637 (spec 78's flake explained and fixed: a person's re-plan waits for a running plan). CI on run 502 was red on
  two things of this session's own making, both fixed and proven: the storage boundary rule (the logo file) and spec 115
  (N-195 made the reminder wait for a confirmed contact). Run 505 found four more, all fixed: the isolation rule (Recoveries had no isolation test: `tests/engines/test_recoveries_live.py`), F-638 (two radar findings on one invoice crashed the sweep) the generated TENANCY-AND-PLANS.md (regenerated) and the capability's name in a plan refusal (it showed its key). A dnspython advisory published that day (CVE-2026-114605) was fixed by 2.9.0, a minor bump. Run 510 found F-639 (spec 75 read one document's indexing as the finished rebuild; the test now waits for every document). Run 511 found F-640: the hourly Recoveries sweep, one job over every workspace, held the worker's queue for minutes; it now queues one job per workspace. The leftovers the owner listed (deletion warnings, a zip in the
  upload tray, the downgrade with rows, the GST speed test) were done in Phase 4. What only the real world can prove is
  Final session 2B's (HANDOFF "Final session 2A → Final session 2B").
- **Owner request during the finish (2026-10-27): the real logo in every email (N-199).** Built test-first: the logo
  (mark and wordmark, light and dark) is a picture carried inside each email (`templates/emails/inline_images.py`).
  Unverified until 2B: real inboxes.


## Current phase — the final sessions: 2A, then 2T (TRINETRA), then 2B (2026-10-26)
Branch `hardening/trinetra-to-ga`, based on `main` at `2e0d61c` (PR #41 merged). Docs only: no code, no migration, one Alembic head
`tr1a2_review_outcomes`. Decision N-190 (next free **N-191**); no finding (next free **F-626**); browser specs continue at **137**.

**Plan (N-189, N-190).** TRINETRA (PR #40) is merged and switched off. A review on 2026-10-26 found defects (HANDOFF "TRINETRA review and
the revised session 2A"), and its original brief is only partly built (`docs/trinetra/ORIGINAL-BRIEF.md`, added here). The owner wants it on
Business and Enterprise, working like every other feature, with nothing left behind. So finishing it is its own session, 2T, after 2A.

- [x] **Final session 2A** (cloud, Opus 5.5 High; done 2026-10-27, PR #43): `docs/sessions/FINAL-2-UPGRADE.md`: India prices, safety jobs, prompt injection, the proof
  kit, the Resolution assessment, Final 1's and PR #39's leftovers, the live prompt rewritten. It touches TRINETRA only for its plan row and copy
  and the injection map.
- [ ] **Final session 2T** (cloud, Opus 5.5 High): `docs/sessions/FINAL-2T-TRINETRA.md`: TRINETRA finished for Business and Enterprise, with
  a completion matrix with no row left missing, three modes (off, pilot, on; ships as "pilot"), statement readers, the full money model,
  authorized inquiries, approval chains, and every integration the other features have.
- [ ] **Final session 2B** (the owner's PC): `docs/sessions/FINAL-2-LIVE.md`, rewritten by 2A and 2T; it proves the TRINETRA readers on the
  owner's own Form 26AS / AIS files.
- [ ] The owner launch checklist (HANDOFF), from step 1, including TRINETRA's step: the CA's read, then the mode "on".

- **Next action:** the owner merges this PR once CI is green, then starts Final session 2A.

## Plan revision: Final session 2A revised after TRINETRA (2026-10-26, PR #41)
Docs only. N-189: 2A gained "Phase T" to fix what the TRINETRA review found; STATE was put in order. Superseded the same day by N-190
(above): Phase T moved into Final session 2T, which also finishes TRINETRA for Business and Enterprise.

## Project TRINETRA (2026-10-26) — merged as PR #40

_Record added 2026-10-26: PR #40 was merged at `04620e9` (11:49 UTC). Its final CI run 40282980125 (head `4eb7adac`) and `main`'s run #478
after the merge were green on every job. The checkpoint below was written before the merge; "Main is unchanged" and "mark it ready" describe
that moment. Live processing stays off (`TRINETRA_LIVE_ENABLED=false`). A review of the merged code found gaps that Final session 2A fixes
(its Phase T; HANDOFF "TRINETRA review and the revised session 2A")._

Branch `hardening/trinetra`, based on `main` at
`bf8f57f691aec7122d9ebaf4a4e13ae9d22ae19c`. Main is unchanged.
PR: https://github.com/sabarishwarne2001/servabo/pull/40.
The complete original Markdown specification, repository instructions and mandatory
audit documents have been read, including all of NEEDS-OWNER. Shell, attachment,
PostgreSQL, Redis and object storage work. The historical audit has been verified
against implementation; it is not counted as completed implementation.

The gated evidence workflow is implemented and documented in
`docs/trinetra/DELIVERY.md` (full changed-file inventory, architecture, API/UI,
migrations, visual direction and acceptance limits). Canonical source comparison,
multiple evidence attachments, jobs, reviewed withholding/Helm reminder hold,
previous-import outcomes and lifecycle/key rotation are included. Official ITD/CBDT
guidance was reached; official export fixtures, adviser approval and customer pilot
remain external gates. Other incomplete acceptance items are explicit in
`docs/trinetra/LAUNCH-GATES.md`. Live processing defaults off. No production, payment,
customer-data or external inquiry action, merge or main-branch change was performed.

Validation:
- Full CI `40254658271` on `bcec7de9` passed all four backend shards, frontend,
  website (including Lighthouse), migrations/drift, encoding and Python audit.
- Its browser run failed only autonomy spec 129's count-before-load race; Stripe
  and gated TRINETRA phases were not reached. A 500 ms delayed real response
  reproduced the failure. Commit `2189c8f2` adds a polling assertion; both autonomy
  scenarios passed three times (6 passes) and browser TypeScript passed.
- Local TRINETRA/lifecycle 326, Helm/engine 402, image/extraction 56 and document
  console 7 passed (overlapping sets). Frontend units 291 and contracts 12 passed.
- Sample browser 135: 6 passed; expanded live browser 136: 1 passed; existing
  review/procurement suites 92/96: 30 passed. See TEST-PLAN for actual limits/failures.
- Final API review found the organization release gate still returned 503. The new
  regression failed first; a shared structured 409 gate fixed it. All 77 TRINETRA
  and all-route isolation tests passed (104.29 s). CI on `265011a6` is superseded
  by the commit containing this correction; inspect the latest run, not that run.
- The final sample consistency check reproduced mismatched creation dates and case
  ages. They now agree at the fixed sample evidence date; 31 domain/API tests passed.
  Inspect CI on the latest commit containing this correction rather than intermediate runs.
- Migration head is `tr1a2_review_outcomes`; no new drift (282 baseline entries).
  Populated downgrade/upgrade passed; full chain rollback/upgrade passed in CI.

**Resume / final review:** inspect current PR checks on the latest pushed head.
If green, update the PR review description with the exact final run and mark it
ready; if red, investigate without weakening tests and record the result. Do not
repeat already-passed full suites without a new reason. Keep the live flag off and
all incomplete real-source/product acceptance explicit. The PR is for review, not
production approval. Process state can be lost across resets: inspect ownership
before restarting the local stack; only one pytest per test database. Raw Actions
logs may be blocked by the environment's network policy; check annotations remain
readable. The final PR description/checks are the authoritative result after this
committed checkpoint.

## Current phase — Plan change: Final session 2A before the live session (2026-10-23)
Branch `hardening/final-2-upgrade-plan`, based on `main` at `e51f736` (PR #37 merged; `main` run #464 green on every job, the advisory
`pip-audit` included; `e51f736` is the owner's lockfile update, which removed two optional peer entries). Docs only: no code, no
migration, one Alembic head `k1a7_pack_check_dismissals`. Decisions N-186 and N-187 (next free **N-188**); no finding (next free
**F-619**); browser specs continue at **135**.

**Final session 1 is complete.** Every box in its section below is ticked; PR #37's CI (run #462 on `2666ea0`) and `main` after the merge
(run #464) were green on every job. What it left is listed in HANDOFF "Final session 1 → Final session 2" §3 (warning emails after a
deletion, a zip in the global upload tray, `k1a6`'s downgrade with rows) and §4 (everything not yet tried against a real service).

**Next, in order** (N-186; HANDOFF "Plan change: the upgrade session before the live session"; the owner's guide `docs/FINAL-SESSIONS.md`):
- [ ] **Final session 2A** (cloud, Opus 5.5 High): India prices and packaging (N-187), the custom-domain contradiction, safety jobs that
  cannot stop silently, a prompt-injection map and tests, Final 1's leftovers, an accuracy report and a pilot playbook, the
  Evidence-to-Resolution assessment (and a thin build only if it passes), and a rewrite of the live prompt. Prompt: `docs/sessions/FINAL-2-UPGRADE.md`.
- [ ] **Final session 2B** (the owner's PC): everything for real; results in `docs/hardening/LIVE-VERIFICATION.md`. Prompt: `docs/sessions/FINAL-2-LIVE.md`
  (rewritten by 2A).
- [ ] The owner launch checklist (HANDOFF), from step 1.

- **`main` run #465 (on the owner's lockfile commit) failed one job:** the GST speed test ("matching took 10.23s", budget 10 s),
  in `pytest (shard 1/4)`. The commit touched only the frontend lockfile. The failed job was re-run to see if it is the shared CI
  machine; either way, Final session 2A finds out first (its Phase 4 item 0) and the budget does not move.
- **Next action:** the owner merges this PR once CI is green, then starts Final session 2A.

## Current phase — Final session 2 on the owner's PC (now 2B, after 2A; see above)
**Next action: Final session 2 on the owner's PC** (`docs/sessions/FINAL-2-LIVE.md`; the owner's guide `docs/FINAL-SESSIONS.md`). It trusts the hand-over in `docs/hardening/HANDOFF.md`
"Final session 1 → Final session 2" (a table of every outside connection to try for real, the commands, what was not reached, what is unverified). Before it starts: the owner merges
PR #37 once CI is green, and prepares what `docs/FINAL-SESSIONS.md` §4 lists. Findings continue from **F-619** (F-606 to F-618 are in `UPGRADE-AUDIT.md`; `FINDINGS.md` carries F-546 to F-605), decisions from **N-186**, browser specs from **135**.
- [ ] Final session 2 (the owner's PC): everything for real; results in `docs/hardening/LIVE-VERIFICATION.md`
- [ ] The owner launch checklist (HANDOFF), from step 1

## Current phase — Final session 1 (2026-10-22)
Branch `claude/focused-planck-g9363e` (the session's assigned branch; CLAUDE.md says `hardening/<topic>`, the brief says "use the assigned branch", so the assigned
branch is used), based on `main` at `7db95b1` (PR #36 merged), draft PR below. Founder authority: decisions in NEEDS-OWNER.md as `DECIDED (Final 1)` from **N-161**,
findings from **F-546**, browser specs from **118**. **If cut off, type `continue`: carry on from the first unticked box. Never restart a ticked phase.**
Local stack this session: Postgres 16 (apt) on :5434 with pgvector 0.8.0 (files from the PyPI wheel `pixeltable-pgserver==0.3.0`, data dir `/var/lib/pgtest`), Redis,
backend venv Python 3.12 and `npm ci` in the session scratchpad. The test environment block is `testenv.sh` in the scratchpad (outside the repo).

- [x] 0. Start-up: docs and code read; stack; this checklist; draft PR #37
- [x] 0b. Phase 0: `docs/hardening/UPGRADE-AUDIT.md` (the study) and its ranked list
- [x] 1A. Data lifecycle: one registry (`data_map.py`) and a test that keeps it complete; erasure, sweep, deletion and the tenant export follow it
- [x] 1B. Outdated AI models: suggested models, price book, BigQuery map, default platform model, `google-generativeai` removed, retired-model message
- [x] 1C. Libraries: Pillow 13 (or the blocker recorded), safe-now upgrades, pip-audit
- [x] 1D. Session J's leftovers: GST trigger upgrade dialog, lakh grouping in run history, `{{trigger.local_date}}`, e2e `dist` folder per run
- [x] 2A. Zip upload (spec 118)
- [x] 2B. Email-in through Postmark inbound (spec 119)
- [x] 2C. Getting started: "first money found"
- [x] 3A. GST notification category, in-app notices and the Monday digest
- [x] 3B. Upgrade moments: one test walks every locked surface; 80% usage email one-click
- [x] 3C. Zoho Books Connect (OAuth) and Tally Prime guided
- [x] 3D. E-invoice QR badge and signature line
- [x] 4A. Error tracking (Sentry / GlitchTip)
- [x] 4B. `scripts/preflight.py`
- [x] 5. Screens: accessibility sweep (specs 72, 74, 132 and a guard that every router page is walked), phone pass, money formatter guard, states (no raw error text), global search, website
- [x] 6. Public webhook events (migration k1a6), warehouse datasets (GST matches, Helm ledger), document packs that do everything they promise (migration k1a7)
- [x] 7. `PRODUCT-NEXT.md` rewritten; HANDOFF "Final session 1 → Final session 2"; records (UPGRADE-AUDIT, FINDINGS F-546 to F-605, COVERAGE, NEEDS-OWNER N-176 to N-184, CHANGELOG, RUNBOOK, CONFIGURATION)
- [x] 8. Added mid-session by the owner: Organization console tabs tested end to end (17 tabs, backend tests and specs 127 to 131, 19 defects fixed), resizable sidebars everywhere (spec 126), the new Servabo logo and a default workspace logo (spec 125)
- [x] Finish: all suites on the ready PR's CI, `campaign_slices.py --check all` (0 open rows: run locally), one Alembic head `k1a7_pack_check_dismissals` (up, down, up run locally for k1a6; CI runs all), PR ready, CI green: **GitHub Actions run 39895654498 on head `2666ea0`, all 11 jobs green** (four backend shards, browser tests, Frontend, Website, migration head and drift, encoding, pip-audit)
- CI took several rounds to get there; each red was a real cause, fixed and recorded as F-606 to F-618 in `UPGRADE-AUDIT.md`: two routes inside the API-key namespace, missing isolation proofs, migration drift, a second crontab line, rupee text and a label that specs still expected the old way, a purge deleting chunks without the workspace condition, two defects found by the browser suite (the autonomy confirmation, search results on an open Invoices tab), and three test races (midnight, an invitation revoke, the live-review websocket close) now made deterministic

## Current phase — Plan change: the two final sessions (2026-10-22)
Branch `hardening/final-two-sessions`, based on `main` at `3b2a7e2` (PR #35 merged; `main` run #417 green, only the advisory
`pip-audit` red, N-159). Docs only: no code, no migration, one Alembic head. Decision N-160 (next free N-161); no finding (next
free F-546); browser specs continue at 118.

**Session J is complete.** Every box below is ticked; PR #35's CI (run #415) was green on every job and the run on `main` after
the merge (#417) succeeded. Open, by decision: a real Slack or Teams channel (N-158), the Wait step (N-154, not now).

**Sessions D and E are replaced** by two final sessions (N-160; HANDOFF "Plan change: the two final sessions"; the owner's guide
`docs/FINAL-SESSIONS.md`):
- [ ] **Final session 1** (cloud, Opus 5.5 High): study, bring every part up to date, build the PRODUCT-NEXT items that earn money.
  Prompt: `docs/sessions/FINAL-1-UPGRADE.md`.
- [ ] **Final session 2** (the owner's PC, Sonnet 5.5 High): everything for real, results in `docs/hardening/LIVE-VERIFICATION.md`.
  Prompt: `docs/sessions/FINAL-2-LIVE.md`. Needs the owner's preparation (`docs/FINAL-SESSIONS.md` §4).
- [ ] The owner launch checklist (HANDOFF), from step 1.

- **Next action:** the owner merges this PR once CI is green, then starts Final session 1.

## Current phase — Session J: Automation, end to end (2026-10-21)
Branch `claude/new-session-otth8f` (the session's assigned branch; CLAUDE.md says `hardening/<topic>`, the brief says "use the assigned branch", so the
assigned branch is used), based on `main` at `c872828` (PR #34 merged), draft PR below. Founder authority: decisions in NEEDS-OWNER.md as
`DECIDED (Session J)` (next free N-149), findings from F-535 (used F-535 to F-545; next free F-546). **If cut off, type `continue`: carry on from the first unticked box. Never restart.**
Local stack this session: Postgres 16 (apt) on :5432 with pgvector 0.8.0 (files from the PyPI wheel `pixeltable-pgserver==0.3.0`), Redis, backend venv Python 3.12 and
`npm ci` in the session scratchpad. The test environment block is `testenv.sh` in the scratchpad (outside the repo).
Builder direction: the owner's sample UI (full-page editor, step cards joined by Yes/No branches, an inspector panel, a status bar, Test run and Publish) is the
look for the new builder, in Lumen colours (N-149 when decided).

- [x] 0. Start-up: docs and code read; `docs/automation/AUDIT.md` written (inventory, 13 native dialogs); this checklist
- [x] 0b. Emitter test (every catalog trigger's event has an emitter in `app/`), failing first
- [x] 1. (P0) Phase 1: conditions always right (money, dates, options, lists, finance schema + aliases, derived fields, trace) (F-535 to F-539)
- [x] 2. (P0/P1) Phase 2: engines become triggers: 14 new, 37 in all (GST, payment risk, schedule, manual, TruthMesh, legal hold, Helm, request link)
- [x] 3. (P0/P1) Phase 3: seven new actions (tag, assign review, legal hold, chat post, GST reminder, obligation, supplier request)
- [x] 4. (P0/P1) Phase 4: throttle and cooldown, pause switch, retry, preview, versions, "why didn't my rule run?". **The optional Wait step was not built (N-154)**
- [x] 5A. (P0) Phase 5A: no browser pop-ups (ConfirmDialog Esc fix, `useConfirmDialog`, 13 replacements, three guards, specs updated) (F-540, F-541)
- [x] 5. (P0) Phase 5: Automation home (cards with sentence, health, owner; filters), recipe gallery (16), the full-page builder, run history, document panel
- [x] 6. Tests: Vitest (+ `test:unit` in CI and its contract test), browser specs 109 to 117, backend suites
- [x] 7. Records: README, NEEDS-OWNER (N-149 to N-159), FINDINGS (F-535 to F-544), COVERAGE, CHANGELOG, CONFIGURATION, HANDOFF, website screenshot and paragraph
- [x] Finish: one Alembic head (up/down/up, also in CI), lint/typecheck/check:self clean, PR #35 ready, CI green (below)
- **Verified (CI run #415, head `f20658c`, all jobs green):** encoding, migration head and drift, frontend (typecheck, lint, self-checks, Vitest, build,
  audit), website, pytest shards 1 to 4, browser tests (main run and the Stripe journeys). The browser specs 109 to 117 also passed three times in a row locally.
- **Known red, not from this work:** `pip-audit (advisory)` (a Pillow advisory, N-159); it is advisory and does not fail the run.
- **Unverified:** a real Slack or Teams channel receiving the message (N-158; the test proves it is queued and the URL never shown, because the safe client refuses loopback
  addresses); the optional Wait step was not built (N-154). Findings this session: F-535 to F-545 (next free F-546); decisions N-149 to N-159 (next free N-160).
- **Next action:** the owner reviews PR #35 and merges, then confirms the run on `main` is green. Nothing else is open in Session J.

## Current phase — Session I: make CI green again after PR #33 (2026-10-20)
Branch `claude/new-session-ko5jbm` (the session's assigned branch), based on `main` at `068afea` (PR #33 merged), draft PR #34.
Founder authority: decisions in NEEDS-OWNER.md as `DECIDED (Session I)` (N-147 decided, N-148 open; next free N-149); findings
F-531 to F-534 (next free F-535). No migration; one Alembic head. **If cut off, type `continue`: carry on from the first unticked box. Never restart.**
Local stack this session: Postgres 16 (apt) on :5433 with pgvector 0.8.0 (the apt package is 0.6.0, below the 0.8 the migrations
require; GitHub and PGDG are blocked here, so the extension files came from the PyPI wheel `pixeltable-pgserver==0.3.0`, PG 16.4
build, copied into `/usr/lib/postgresql/16` and `/usr/share/postgresql/16`), Redis, backend venv Python 3.12 with the full
`requirements.txt` + dev, `npm ci`, system Chromium via `E2E_CHROMIUM_PATH`. The two environment blocks (browser stack, backend
tests) are in the session scratchpad, outside the repo. **The CI report of run #400 could not be downloaded (network policy), so
what the server and worker logged is unread: N-148.**

- [x] 0. Start-up: STATE read; evidence from the public CI pages and job logs; stack built; draft PR #34
- [x] 1. (P0) `aiohttp` 3.14.4 (+ `yarl` 1.25.1, which it needs): pip-audit fails before, clean after, both files; full install
  on 3.12; `test_image_requirements.py` and the AI-provider client tests (73) pass (F-533)
- [x] 2. (P0) The failing browser test: not reproduced by repetition (30 idle runs of the original test with the history emptied each time, a replay of the specs
  before 13 in CI's order; the upload steps alone: 0 lost in 60, 20 idle and 40 under load), reproduced by delay (CI's exact error); fixed by waiting on the real signals; spec 13 x10 beside
  105/107/108 passed (F-531)
- [x] 3. (P1) The slowdown found on the way: the QR search on every PDF (F-532, N-147): tests failed first, 12 documents
  113.0 s to 103.2 s, `PERFORMANCE.md`
- [x] 4. `main` run #401: all four pytest shards passed; only the advisory pip-audit was red (task 4)
- [x] Finish: records (F-531 to F-534, N-147, N-148, COVERAGE, CHANGELOG, STATE, HANDOFF, PERFORMANCE); PR marked ready; CI (below)
- **Verified (local).** See HANDOFF "Session I". Spec 13 x10 (110 tests) beside specs 105/107/108: all passed. Replay of specs
  00 to 03, 10 to 13 in CI's order with 2 workers: 307 passed; the one failure was spec 108's checkout page asking for a
  favicon the stand-in does not serve (sandbox Chromium; CI's Chromium passes it; not from this work).
- **Not run locally, on purpose** (the brief says CI runs the full suites): the full backend and browser suites.
- **Unverified.** That the reproduced mechanism is what happened in run #400 (N-148); that a real e-invoice with a printed QR
  code is still read (nothing about the reading changed, but no real invoice has ever been tried, N-140); F-534.
- **Next action:** CI on PR #34 (below), then the owner merges and confirms the run on `main` is green. Then Session D.

## Current phase — Session H: a green main, the GST Credit add-on, the monthly summary (2026-10-19)
Branch `claude/new-session-rtxwwe` (the session's assigned branch), based on `main` at `25bf99b` (PR #32 merged), draft PR #33.
Founder authority: decisions in NEEDS-OWNER.md as `DECIDED (Session H)` (used N-142 to N-146; next free N-147); findings F-528 to
F-530 (next free F-531). Two migrations (`h1a6_gst_credit_addon`, `h1a7_monthly_receipt_sends`); one Alembic head. **If cut off,
type `continue`: carry on from the first unticked box. Never restart.**
Local stack this session: Postgres 16 + pgvector 0.8.0 (built from source) on :5433 (e2e, DB `servabo_e2e`) and :5434 (backend
tests, DB `flowpilot_test`), Redis (db 0 tests, db 1 e2e), backend venv with the FULL `requirements.txt`, `npm ci` done. The two
environment blocks are in the session scratchpad (outside the repo): the CI variables with `POSTGRES_USER=postgres`, trust auth.

- [x] 0. Start-up: docs and code read; sandbox databases and venv; this checklist; draft PR #33
- [x] 1. (P0) Part 1: `main` green. Both red runs (#387, #394) had ONE red job, `pytest (shard 2/4)` (the GST speed test); the
  Frontend job was green because its audit step was `continue-on-error` (F-529, N-143). GST matching: `COPY` for the results,
  lookups by supplier and day (F-528, N-142, PERFORMANCE.md); audit gate (blocking on `--omit=dev`, report-only for build tools,
  `tests/infra/test_ci_workflow_contract.py` failed first); `ubuntu-24.04`; actions on Node 24 (N-144)
- [x] 2. (P0) Part 2: GST Credit add-on for Developer (N-145): catalogue + migration + seed rows + gate + checkout rules; GST page
  offer, Billing add-on list, value receipt line; Dodo (eight products) and docs; pricing export, website Add-ons section,
  `/gst-credit` line; backend tests (`test_gst_addon.py`, `test_gst_addon_api.py`, the Dodo reconciliation case); browser spec 108
  (9 tests, 3 repeats = 27 passed, axe light and dark)
- [x] 3. (P1) Part 3: the monthly summary email (N-146): `receipt.monthly` job, `monthly_receipt_sends`, "Monthly summary" category,
  `monthly_receipt` template (reuses the trial email's receipt block); 9 service tests + 4 template tests + the mail-client test
- [x] Finish: records (N-142 to N-146, F-528 to F-530, COVERAGE, CHANGELOG, STATE, HANDOFF); `campaign_slices.py --check all`
  exits 0; one Alembic head (up/down/up); frontend `lint`, `typecheck`, `check:self` clean; PR ready; CI green (below)
- **Verified (local).** Part 1: the GST budget test at `PERF_BUDGET_MULTIPLIER=1`: matching 4.0 to 4.3 s before, 2.0 to 2.4 s after
  (the first attempt, 2.3 to 3.2 s, still took 10.37 s on CI; the collector pause is the second); equivalence (`test_matching_equivalence.py`, 5 seeded workloads, fails when the day window is narrowed by one
  day) and `test_bulk.py`; CI-contract test 8 passed (it failed first on 4 of 8). Part 2: add-on tests 11 + 1 + the Dodo
  reconciliation add-on case, value receipt 34, `dodo_setup` 4; website `typecheck`, `build`, `check:links`, `check:html`,
  `check:a11y` clean, Lighthouse 96 to 100; browser 108 (27), 105/106/107/68/91 (34), 60/62/64 (3), 20 "Billing" (5).
  Part 3: 9 service + 5 template tests.
- **Not run locally, on purpose** (the brief says CI runs the full suites): the full backend and browser suites.
- **Unverified.** The add-on bought on a real Dodo test account (Session D: the eighth product and one purchase); the monthly email in
  a real mail client and on the 1st in a real zone (selection is proven with a controlled clock); the 390 px phone view of the new
  Billing "Add-ons" list and the GST offer (checked by axe, not by eye).
- **Next action:** CI on PR #33 (below), then mark ready; after the merge confirm the run on `main` is green. Then Session D.

## Current phase — Session G: the value receipt (2026-10-19)
Branch `claude/new-session-awa8gh` (the session's assigned branch), based on `main` at `e8509ac` (PR #31 merged).
Draft PR opened after the first push. Founder authority: decisions in NEEDS-OWNER.md as `DECIDED (Session G)`
(used N-141; next free N-142); new findings start at the next free F-number (F-528; F-527 used). No migration. **If cut off,
paste the prompt again: continue on this branch and PR from the first unticked box. Never restart.**
Local stack: Postgres 16 + pgvector 0.8.0 (built from source) on :5433 (e2e) and :5434 (backend tests), Redis,
backend venv Python 3.12 (`backend/.venv`), `npm ci` done. The test environment block is in the session scratchpad
(outside the repo): the CI variables with `POSTGRES_PORT=5434`, `POSTGRES_USER=postgres`, trust auth.

- [x] 0. Start-up: docs and code read; sandbox databases and venv; this checklist
- [x] 1. (P0) `app/services/value_receipt.py` + 23 service tests (they fail without it: the import is the first error)
- [x] 2. (P0) `GET /organizations/{org}/value-receipt?period=trial|month` (owner, admin, billing; Redis 10 min), ledger rows, API tests
- [x] 3. (P0) Trial banner headline (last three days) and the receipt card in the "trial has ended" dialog
- [x] 4. (P0) Trial emails (ENDING, ENDED) carry the headline and up to three findings; render tests with and without; first organization only
- [x] 5. (P0) Browser spec 107: 11 tests, 3 repeats = 33 passed, axe light and dark; specs 33 and 61: 6 passed
- [x] 6. (P1) Overview "Found this month" (every plan) and plan page "Your trial so far"; in spec 107
- [x] 7. (P2) `value-receipt.pdf` (reportlab), "Download as PDF" on the dialog and the Overview card; tests
- [x] Finish: records (N-141, F-527, COVERAGE, CHANGELOG, STATE, HANDOFF); `campaign_slices.py --check all` exits 0; frontend lint, typecheck and
  check:self clean; PR ready; CI (below).
- **Verified (local).** New backend tests: 23 service, 10 API (roles, cache, PDF), the email render tests and 4 handler tests added to `test_free_trial.py`, all pass; they failed first (import
  error without the service). Route walkers and role matrix (102 tests) pass with the new routes; Helm backtest report tests
  (18) pass after the writer gained `author`/`creator`; trial tests (50) pass. Browser: spec 107 33/33, specs 33 and 61 6/6.
  Spec 107's first axe run found F-527 (sidebar locked rows), fixed.
- **Not run locally, on purpose** (the brief says CI runs the full suites): the full backend and browser suites. The
  `ConfirmDialog` (a wider, scrollable variant) and the sidebar's locked rows are shared by other pages: CI covers them.
- **Unverified.** A real customer's GSTR-2B and invoices (the figures are proven on planted rows and on the model stand-in's
  invoices); the Time machine, duplicate, bank-change, overcharge and Helm-value findings are proven in service tests with
  planted rows but not in a browser (the browser customer is on Free, where only GST and the Time machine can show);
  the email in a real mail client; the 390 px phone view and the Overview card's look at 1440 px were checked by the
  card's classes (the Overview's own `fp-card`) and axe, not by eye.
- **Next action:** Session D (Dodo walk-through, a real GSTR-2B, an e-invoice PDF), plus a look at the receipt on a real account.

## Current phase — Session F: GST Credit (2026-10-19)
Branch `claude/new-session-5oe22r` (the session's assigned branch), based on `main` at `7185674` (PR #30 merged).
Draft PR opened at the start. Founder authority: decisions in NEEDS-OWNER.md as `DECIDED (Session F)` (next free
N-number: N-135); new findings start at the next free F-number (F-524). **If cut off, paste the prompt again:
continue on this branch and PR from the first unticked box. Never restart.**
Local stack: Postgres 16 + pgvector 0.8.0 (built from source) on :5433 (e2e) and :5434 (backend tests), Redis,
backend venv Python 3.12 (`backend/.venv`), `npm ci` done. Environment variables live outside the repo.

- [x] 0. Start-up: docs read; sandbox databases and venv; this checklist; draft PR.
- [x] 1. (P0) Finance-grade invoice reading (F-524, N-138): contract tests, prompt rewritten, stand-in answers only what is asked
- [x] 2. (P0) GST Credit engine: tables (migration `g1a1_gst_credit`), GSTR-2B parser, matching, statuses, IMS, API, export, tests, PERFORMANCE.md, docs/product/GST-CREDIT.md
- [x] 3. (P0) GST Credit page, `capability.gst_credit`, preview, sample company GSTR-2B, browser spec 105 (3 repeats, axe)
- [x] 4. (P1) Helm: 180-day mandate, hold-until-reported mandate, Guard check, Request action; equivalence test (60 seeds) passes
- [x] 5. (P2) Website `/gst-credit` (build, check, Lighthouse 96-97); Enterprise every-workspace page, API and `gst:read` scope (spec 106)
- [x] 6. (Stretch) e-invoice QR code: pictures read in the OCR worker, token trusted in the enrich worker (N-140)
- [x] Finish: suites run once (below), `campaign_slices.py --check all` exits 0, one Alembic head (up/down/up), frontend lint / typecheck / check:self clean, records, PR ready.
- **Verified.** Full backend suite: 5,456 passed / 14 failed / 13 skipped. Of the 14: 8 fail identically on unmodified
  `origin/main` (no embedding model in the sandbox), 2 Dodo-invoice tests pass alone (order-dependent, as Session E noted),
  1 GST budget test failed only because the browser suite was running at the same time (passes alone), and 3 were mine
  and are fixed (setting undocumented in CONFIGURATION.md x2; the web image must not carry OpenCV, so the QR picture
  reading moved to the OCR worker). Full browser suite: 972 passed / 3 failed / 2 skipped / 9 did not run; spec 85 passed
  alone (load), spec 26 failed because my specs created organizations named "... Plan ..." (fixed, passes), spec 105 matched
  two toasts (fixed, 11 of 11 pass). Not re-run in full after those two spec fixes.
- **Unverified.** See HANDOFF "Session F": real GSTR-2B file, real GST invoice through a real model, the wording of the
  sections against the official pages, the e-invoice payload and NIC's key.
- **Next action:** Session D (Dodo walk-through; now also a real GST invoice, a real GSTR-2B and an e-invoice PDF).

## Session E (2026-10-18): the UI gaps and defects Session C left open
Branch `claude/funny-sagan-n7gpqc` (the session's assigned branch), based on `main` at `b4b4c9c`. Findings F-518 to
F-523, decisions N-131 to N-134. No migration; one Alembic head (`h1a5_helm_ledger_incremental`).
- [x] 1. Identity console: GET + DELETE for role mappings, saved-mappings list with a confirmed Remove (F-518)
- [x] 2. Three-way match: stored reason shown, Re-score, replaced case read as history (F-519); supplier-cost
  "Reconcile anyway" (F-520). Case notes and a separate Reject: the API has neither, **not built, N-131 needs you**
- [x] 3. Password sign-in refused when useless everywhere, 403 `SSO_SIGN_IN_REQUIRED` (F-521, N-132)
- [x] 4. Last-workspace archive is 409 `LAST_WORKSPACE` (F-522)
- [x] 5. Undo needs a fitted model by design (N-133); the history is now a tested stand-in command
- [x] 6. Residency card lists only regions Save accepts (F-523)
- [x] 7. Shared price-book state: rule written in `frontend/e2e/README.md` (N-134)
- Verified: new backend tests failed against the unfixed `app/` first (5 of 5 behaviour tests) and pass now;
  full backend suite 5,274 passed / 24 failed, of which 22 fail identically on the unmodified code (sandbox: DB
  URL for script tests, ready check, free-trial and Helm timing) and 2 Dodo-invoice tests are order-dependent
  (pass alone, pass on the base code alone); the 2 route-coverage tests that my new routes broke are fixed.
  Full browser suite 967 passed / 2 skipped / 0 failed, including specs 20, 23, 26 and 43 (60 passed, 1 skipped
  when run alone), which the UI polish pass could not run. `tsc`, `npm run lint`, `npm run check:self` clean.
- **Next action:** you decide N-131 (build "Reject" and notes, or not). Session D (Dodo walk-through) is unchanged.

## UI polish pass (2026-10-18): Branding page and Dispatch policy card
Branch `claude/zealous-davinci-9q2hv9`. Frontend only; no API, schema or migration change.
- Branding & custom domains: colour picker + hex field + quick swatches + six presets (`components/branding/`),
  a two-surface live preview (sign-in page, inside the app) with contrast read-outs, logo/favicon tiles,
  "Discard changes", dark-mode-safe banners and pills. Test IDs and ids (`#brand-name`, `#color-<key>`,
  "Save brand", "Enable/Disable custom branding", `brand-colour-reach`) are unchanged.
- Dispatch policy: each threshold on its own full-width row (the overlap came from a viewport-breakpoint
  two-column grid inside a narrow card); lane scale bar added. `dispatch-policy`, `tag-documents-note` and the
  slider labels are unchanged.
- Verified: `tsc`, `npm run lint`, `npm run build`, `npm run check:self` clean; screenshots at 320/380/560 px and
  390/1440 px, light and dark, from a throwaway harness with mocked API; e2e interactions replayed against it.
  Unverified: the Playwright browser specs 20, 23, 26, 43 were not run (no backend stack in this session).

## Current phase — Session C: close the browser-test gaps (C1) and build the Dodo check kit (C2)
Branch `claude/new-session-janwly` (the session's assigned branch), based on `main` at `9d0fa4e` (PR #27 merged).
Draft PR opened at the start. Founder authority: decisions in NEEDS-OWNER.md as `DECIDED (Session C)`
(next free number N-125); new findings start at the next free F-number (F-500). **If cut off, paste the
prompt again: continue on this branch and PR from the first unticked box. Never restart.**
Local stack: Postgres 16 + pgvector 0.8.0 (built from source) on :5433, Redis, API, worker, model stand-in
(`E2E_LLM=1`), bundle served by `vite preview` on :3000. Environment variables live outside the repo.

- [x] 0. Start-up: docs read; stack up; specs 76 + 77 re-run green (10 passed); this checklist; draft PR.
- [x] C1. Browser specs, one file per feature (numbered after 85), each run `--repeat-each=3` before commit
  - [x] 1. ERP posting (spec 86, 7 tests, 3x green; no app bug found): "Post N", Retry, "Do not post"; target "Test connection", "Set credential"; mapping "Save as new version" / "Restore default"
  - [x] 2. Payment risk and anomalies (spec 87; F-503, F-505): "Confirm risk"; "Not a risk…" + reason, "Dismiss"; "This is a real finding"; "Not an anomaly"
  - [x] 3. Legal holds (spec 88; F-500, F-501 fixed test-first): "Place hold" + reason; deleting a held document refused; "Release"
  - [x] 4. Sessions and SSO (spec 89; F-504, F-506): "End session"; "Sign out everywhere" (fresh user); "Require single sign-on" + bypass; role mapping "Save mapping"
  - [x] 5. Entity 360 (spec 90; F-507 unverified): "Rename", "Erase record", "Split into a new record", "Undo merge"
  - [x] 6. Seats (spec 91, no bug) and RevOps money (spec 94, no bug): "One seat fewer" → "Confirm"; "Remove N unused seats"; RevOps "Publish", "Create code", "Void", "Issue due invoices"
  - [x] 7. (spec 92, no bug) Review hub decisions per kind (ERP, table, obligation, merge, corroboration); bulk "All pass" / "Dismiss all"
  - [x] 8. Tables (spec 93, no bug): "Accept figures", "Reject table", correct a cell
  - [x] Long tail, specs 95 to 104 (F-508 to F-517); not driven and why: HANDOFF "Session C → next sessions". (Task 4's order, grouped by area): three-way-match "Flag dispute"; supplier-cost "Record invoice" / "Reconcile"; partner manifest → marketplace install; document bulk "Reprocess" / "Retry processing"; workspace archive and logo; corroboration decisions; packet "Approve split"; case detail actions; obligation "Waive" / feeds "Revoke"; identity OIDC and SCIM rotate/revoke; credential rotation (API keys, webhooks, BYOK); data residency "Save region"; egress rule removal; process agent "Save policy" and proposal "Reject" / "Undo"; leave organization / decline invitation; recovery codes and "Stop requiring two-factor"; automation rule toggle/test/edit/duplicate/delete; clause assertion "It passes" / "Wrong paragraph" / "Test on a document"; extraction memory "Reset" / "Retire"; AI / email / document settings "Test connection" / "Send test"; analytics "Sync now"; sovereign licence "Verify and install"; resumable upload tray
- [x] C2. The Dodo check kit
  - [x] 1. `backend/scripts/dodo_probe.py` (GET only, shapes not values, refuses live mode) + tests against `fake_dodo.py`
  - [x] 2. `start_dev.ps1 -DodoWebhooks` / `start_dev.sh --dodo-webhooks` (Dodo CLI first, Cloudflare quick tunnel fallback, `-Stop`) + tests
  - [x] 3. `docs/billing/DODO-LOCAL-TEST.md`, linked from DODO.md §6, RUNBOOK §9, the owner launch checklist (step 9)
- [ ] Finish: full browser suite, `pytest -q`, `campaign_slices.py --check all` 0, one Alembic head, records (FINDINGS, COVERAGE.csv, STATE, HANDOFF "Session C → next sessions" incl. exactly what Session D must run, NEEDS-OWNER), CI green, PR description for a non-engineer, mark ready, stop.

**Final verification (Session C, 2026-10-18).**
- Full browser suite, 966 tests, local: 958 passed, 2 skipped (as before), 5 failed while the full backend suite ran on the same machine (specs 17, 60, 64, 68, 85: the worker was too busy to finish a document or the page in time). Re-run alone on an idle machine, twice each: 24 of 24 passed. None of them is a Session C spec.
- Full backend suite: CI's four shards pass. Locally, `test_free_trial.py::test_after_the_trial_queued_engine_work_is_skipped` (3 cases) and two tests in `test_helm_snapshot_consistency_live.py` fail in this sandbox, and fail identically on `main` at `9d0fa4e` (before this session), so they are a property of this machine, not of the branch; unverified locally, green in CI.
- `campaign_slices.py --check all` exits 0; one Alembic head (`h1a5_helm_ledger_incremental`); encoding check clean; frontend typecheck and e2e typecheck clean.

**Next action:** none for Session C once CI is green and PR #28 is marked ready. Session D: see HANDOFF "Session C → next sessions".

## Previous phase — Session B: finish the rename, fix the carried-over defects, make the ledger fast
Branch `claude/new-session-zo5d98` (the session's assigned branch), based on `main` at `682c9d5` (PR #26
merged). Draft PR opened at the start. Founder authority: decisions are built and recorded in
NEEDS-OWNER.md as `DECIDED (Session B)` (next free number N-118); new findings start at F-469.
**If cut off, paste the prompt again: continue on this branch and PR from the first unticked box. Never
restart.**

- [x] 0. Start-up: docs read; Postgres 16 + pgvector on :5433 (e2e) and :5434 (backend tests), Redis,
  API, worker, model stand-in (`E2E_LLM=1`); this plan; draft PR.
- [x] B1. The old name, gone for good
  - [x] B1a. Remove the aliases: `legacy_names.py`, `fp_` key prefixes, `LOOP_ALIASES`, `ROLE_ALIASES`,
    the `Use-PreRenameDockerData` shims, the `deploy/bin` fallbacks, `.gitignore` lines.
  - [x] B1b. README "Local data from before the rename" (two lines), clone URL, repository URL elsewhere,
    "Servabo … renamed … Servabo" comment damage, `.env.production.template` section 2.
  - [x] B1c. Compose binds Postgres, Redis, MinIO and its console to `127.0.0.1` (test reads the file).
  - [x] B1d. Guard test tightened; CHANGELOG line (operators must use `SERVABO_*`).
- [x] B2. The carried-over defects (each with its failing test first)
  - [x] Task 1 batch operations (6 items)
  - [x] Task 1 TruthMesh (6 items)
  - [x] Task 1 document packs (4 items, F-400 migration)
  - [x] Task 2 the N-077 rules
  - [x] Task 3 the session-3 leftovers
  - [x] Task 4b the first-run tier-ordering oddity
  - [x] NEXT-SESSION-PROMPT.md top line
- [x] B3. Helm's ledger truly incremental: failing budget test (4.07 s), incremental path
  (`ledger_incremental.py`, marks in `models/helm_dirty.py`), equivalence property test (300 seeds of 40
  changes), concurrency test, nightly check that repairs and alerts (`HELM_LEDGER_DRIFT`), 0.70 s at
  10,000 documents (PERFORMANCE.md, ARCHITECTURE §4.5 and §13)
- [x] B4. Decisions recorded: N-118 (Dodo hard limits), N-119 (Tailwind 4), N-120 (N-074), N-121 (aliases),
  N-122 (incremental ledger), N-123 (127.0.0.1), N-124 (Task 5)
- [x] B5. Task 5 deferred (N-124) and Task 4 handed to Session C (HANDOFF "Session B → next sessions")
- [x] Finish: CI green on c1e1b94 (all 11 checks, browser suite included); full backend suite (local: 4,986 passed in two halves, then 297 re-run after a clash between the halves, before the last records commits; CI is the
  judge), full browser suite (817 passed, 2 skipped, 1 timing test failed under load and passed alone),
  `campaign_slices.py --check all` 0, one Alembic head (up/down/up, no drift), frontend lint / typecheck /
  check:self / e2e typecheck clean, records, CI green, PR description for a non-engineer, mark ready.

**Next action:** none for Session B. PR #27 is marked ready for review. Session C: Task 4 of NEXT-SESSION-PROMPT.md.

## Previous phase — Helm visual session: Night Bridge, the switch, Lumen and the website's Helm page
Branch `claude/beautiful-dijkstra-yvlspo` (the session's assigned branch), based on `main` at `5e4366d`
(PR #25 merged). PR sabarishwarne2001/servabo#26. Founder authority on design: decisions in NEEDS-OWNER.md as
`DECIDED (Helm visual session)` (N-111 to N-116). The owner also asked for Documents to be upgraded in
its own style (Lumen, N-113). **If cut off, paste the prompt again: continue on this branch and PR from
the first unticked box. Never restart.** All boxes are ticked: the session is done; next is the owner's review of PR #26.

- [x] 0. Start-up: docs read; stack up (Postgres 16 + pgvector 0.8.0 on :5433 e2e and :5434 backend
  tests, Redis, API, worker, model stand-in); `seed_website_demo.py`; "before" shots of every Helm page
  and Documents (light, dark, 1440, 390; scratch only); Helm chunks measured (58.2 kB gzipped).
- [x] 1. Night Bridge design system (`styles/helm/`, `components/helm/ui/`, `docs/helm/VISUAL.md`).
- [x] 2. Rupees in Indian grouping in Helm (F-462, self-check failed first).
- [x] 3. Read-only promise calendar API and the ledger's due-day filter (backend tests failed first).
- [x] 4. Helm shell; Start no longer blinks before a book is chosen (F-463, spec 85 failed first).
- [x] 5. The switch and its view transition (F-464: the router's option is dropped; the switch starts it).
- [x] 6. Cockpit: KPI strip, fan chart, Promise calendar, pill bars, instruments, plan; spec 85.
- [x] 7. Plan, Mandates, ledger, Time machine (F-466), Bank, Certificates, Settings, Start, first run,
  tour, preview; F-467 (₹1.5T).
- [x] 8. Documents: Lumen.
- [x] 9. Website: Helm page in Night Bridge, switch demo, glass frames, `helm-certificate` rename and a
  true `helm-plan` shot, every screenshot recaptured as an Indian reader.
- [x] 10. Records: VISUAL.md, FLAGSHIP identity, NEEDS-OWNER, FINDINGS, COVERAGE (`--check all` exits 0),
  HANDOFF.
- [x] 11. Full browser suite (808 passed, 2 skipped, 0 failed, on 17f3896) and website checks.
- [x] 12. Owner's added task: the Documents Overview redesigned in Lumen (N-117), with two read-only
  overview fields (documents read, the last 14 days; test failed first).
- [x] 13. The Overview's specs re-run (10, 21, 22, 72, 74, 80, 85: 335 passed, 2 failed; spec 10's
  label fixed and re-run green; spec 22's is the pre-existing order dependence in HANDOFF).
- [x] 14. Finish: CI green on 0da2906 (all 11 checks, browser suite included), PR marked ready for review.

**Checkpoint (2026-10-17).** Helm specs 78–85 pass on the new look (axe in both themes; no sideways
scroll at 1440, 1024, 768, 375). Spec 85: six tests, including the cockpit ready within 1.5 s and no
long task over 200 ms after it. Backend: `tests/services/helm` and the route walkers 486 passed; the
role matrix 4 passed. Frontend: lint, typecheck, e2e typecheck, `check:self` clean. Bundle: Helm's lazy
chunks 59.0 → 76.1 kB gzipped (+17.1, allowance 35); the main stylesheet 23.5 → 24.8 kB gzipped (Helm's
CSS is in it because the switch sits in Documents' header). No new runtime dependency.
Backend (tests/api, core, security, services/helm and the Helm live tests): 2,206 passed, 11 skipped.
Website: typecheck 0 errors, 18 pages, 1,296 links, HTML valid, axe clean in 72 page views, Lighthouse
97/97/96 (other categories 100).

## Previous phase — Website and payments session: Servabo, the website and Dodo Payments
Branch `claude/new-session-3qnrpb` (the session's assigned branch), based on `main` at `906c921`
(PR #24, the flagship session, is merged; `docs/product/FLAGSHIP.md` and HANDOFF "Flagship session →
website and payments session" are present). The owner gave full founder authority: decisions are
built and recorded in NEEDS-OWNER.md as `DECIDED (website and payments session)`; the brief's own
decisions as `DECIDED (owner, planning chat, 2026-10-15)`. **If this session is cut off, paste the
same prompt again: continue on this branch and its open pull request, from the first unticked box
below. Never restart.**

**Plan (the brief's order A → B → C → D; each defect proven by a failing test first):**
- [x] 0. Start-up: docs read; live stack up (Postgres 16 + pgvector 0.8.0 on :5433 e2e and :5434
  backend tests, Redis, API, worker `--loop all --profile all`, model stand-in, production bundle
  with CSP), logs to files; this plan; draft PR.
- [x] A1. Rename what people see: UI strings, titles, meta, manifest, emails, PDFs and exports,
  calendar feed, redaction stamp, samples, notifications, OpenAPI title, README and current docs.
- [x] A2. Code identifiers (`FlowPilotError` → `ServaboError`, …), pure renames.
- [x] A3. Protocol identifiers (signature header, TXT record, WebSocket subprotocol, refresh
  cookie, key prefixes, local-storage keys), each listed in CHANGELOG.md.
- [x] A4. Database-level names in a new Alembic migration (the audit sweeper setting).
- [x] A5. Configuration `FLOWPILOT_*` → `SERVABO_*` with a one-release alias and one startup
  warning; database defaults and templates `servabo`, `servabo_e2e`, `servabo_test`.
- [x] A6. Operations: Docker names, cron files `servabo-sweepers`, `/etc/servabo/`, backup names,
  dev scripts, CI names, the e2e seed.
- [x] A7. History lines at the top of FINDINGS, NEEDS-OWNER, STATE, CHANGELOG.
- [x] A8. Brand assets: logo mark and wordmark (SVG), favicons, sign-in screen, emails, Open Graph.
- [x] A9. Guard test: the old name fails outside an explicit allowlist.
- [x] A10. Part A checkpoint: full backend suite, browser suite, frontend checks green.
  Checkpoint (2026-10-16): browser 825 passed, 1 skipped (1,472 jobs SUCCEEDED); backend 5,064
  passed with the 8 sandbox-only failures main also has, plus 4 the rename caused, now fixed with
  tests (old API key prefix, old-name passwords, a half-renamed test, a storage-boundary entry).
- [x] B1. `website/`: Astro + TypeScript + Tailwind on shared brand tokens, self-hosted fonts, no
  third-party scripts; layout, header, footer with every Dodo-required link.
- [x] B2. Pricing data: `backend/scripts/export_public_pricing.py` → `website/src/data/pricing.json`,
  drift test, build fails on an unlabelled plan.
- [x] B3. Pages: home, Helm (flagship), product, four solutions, pricing, security, about, contact.
- [x] B4. Legal: terms, privacy, refunds, acceptable use, subprocessors (data file from the code),
  cookies; 404, sitemap, robots, canonical, OG/Twitter, structured data.
- [x] B5. Real screenshots (`website/scripts/capture-screenshots`), light and dark.
- [x] B6. `_headers` (strict CSP, HSTS…), Caddy site block, `docs/website/DEPLOY.md`,
  `docs/website/DODO-REVIEW.md`.
- [x] B7. Joining to the app: `WEBSITE_URL` / `VITE_WEBSITE_URL`, app `/pricing` `/terms`
  `/privacy` redirect, links back, email footers, Billing → refunds link, `--website` dev switch.
- [x] B8. CI `website` job (install, typecheck, build, links, axe in both themes, HTML validation,
  Lighthouse ≥ 95 on home, pricing, Helm), required.
  Checkpoint (2026-10-16): 18 pages build; 1,275 links resolve; HTML valid; axe clean in both themes
  at 360 and 1280 px; Lighthouse 97/100/100/100 on home, pricing and Helm; `npm audit` 0. Browser
  specs 70, 72, 74 (signed out), 30, 01, 60 pass against the new bundle.
- [x] C1. `backend/tests/fakes/fake_dodo.py` (HTTP stand-in + Standard Webhooks signer);
  `scripts/e2e_stand_in.py --gateway dodo`; browser journeys on Dodo by default; Stripe journeys kept.
- [x] C2. Default gateway DODO everywhere; production guard (key, secret, live/test agreement).
- [x] C3. Reconciliation behaviour tests for every handled Dodo event, ordering, replay, grace,
  add-ons, customer adoption and racing checkouts; one live concurrency test.
- [x] C4. Dodo payments as invoice rows, PDF download route, merchant-of-record note.
- [x] C5. Refunds and disputes (record, notify, RevOps, lost dispute → read-only).
- [x] C6. Plan changes with Dodo's preview (amount and date first), upgrades now, downgrades at
  renewal, downgrade checks first; portal for payment method.
- [x] C7. Seats on Dodo proven end to end (`DODO_PREVIEW`).
- [x] C8. Overage capability: `ALLOW_AND_BILL` published as `REFUSE` without usage billing; copy.
- [x] C9. Customer details reach Dodo (or the page says where); never Stripe on a Dodo account.
- [x] C10. No Stripe where a customer looks; worker loop `billing` (alias `stripe`).
- [x] C11. Yearly products on Dodo; switch only when configured; website reads the same data.
- [x] C12. Dodo fees in unit economics and the margin console; ≥ 55% at ceilings after fees.
- [x] C13. Checkout return waits for the webhook, with a timeout message.
- [x] C14. `backend/scripts/dodo_setup.py` (test mode only); `docs/billing/DODO.md`.
  Checkpoint (2026-10-17): Part C done. Browser journeys bill through the stand-in Dodo by default
  (start-stack.sh; E2E_GATEWAY=stripe keeps the Stripe journeys, also run in CI): 60 pays on Dodo's
  checkout page and the return page confirms it (C13 proven), 62 buys seats through Dodo's preview,
  64 runs dunning on a held renewal and fixes the card in Dodo's portal, new 68 covers an upgrade at
  Dodo's price, the Dodo invoice download, a scheduled downgrade withdrawn, a refund and a portal
  cancellation; 60–67 also pass on Stripe. Found and fixed on the way: held Dodo renewals turned
  read-only silently (billing.hold_notices, migration w1a4); an upgrade was undone by Dodo's own
  webhooks (plan now from the billed product); two order-dependent tests. Live concurrency test
  (c3174eb); dodo_setup.py and docs/billing/DODO.md (C14).
- [x] D1. RUNBOOK §9 rewritten; CONFIGURATION.md and TENANCY-AND-PLANS.md regenerated (both were
  already current).
- [x] D2. HANDOFF: owner launch checklist rewritten (12 steps); "Website and payments session → next sessions".
- [x] D3. Finish: full suites, logs clean, ledgers, PR ready, final message.
  Checkpoint (2026-10-17): backend 5,162 passed, 11 skipped, 1 failed in four local shards (the
  stand-in test since fixed in 23b63dd, 3/3 passing); browser 802 passed, 2 skipped on a fresh e2e
  database, billing through the stand-in Dodo, production bundle, CSP enforced; Stripe journeys
  60–67 and spec 20's Billing group pass with E2E_GATEWAY=stripe. Logs: 0 tracebacks, 0 ERROR, one
  5xx (spec 31's expected 503); 1,465 jobs SUCCEEDED; 62 Dodo events PROCESSED. tsc, e2e typecheck,
  lint, check:self, build, no source maps; website typecheck, build, links, HTML, axe, Lighthouse
  97/97/96; export_public_pricing --check current; Alembic one head (w1a4_hold_notices), up / down
  to base / up; pip-audit no known vulnerabilities; npm audit --omit=dev 0 (app and website).
  Ledgers: F-444–F-461, N-103–N-110, COVERAGE rows.

## Previous phase — Flagship session: Helm, the flagship engine
Branch `claude/new-session-yviysi` (the session's assigned branch), based on `main` at `5e27687`
(PR #23, campaign session 4, is merged). Draft PR titled `Helm: the flagship engine`. The owner gave
full founder authority: decisions are built and recorded in NEEDS-OWNER.md as
`DECIDED (flagship session)`; the brief's own decisions as `DECIDED (owner and planning chat,
2026-10-15)`. The design is `docs/helm/ARCHITECTURE.md`. **If this session is cut off, paste the same
prompt again: continue on this branch and its open pull request, from the first unticked box
below. Never restart.**

**Build checklist (the brief's §12 order; each defect proven by a failing test first):**
- [x] 0. Start-up: docs read, engines studied, live stack up (Postgres 16 + pgvector 0.8.0 on
  :5433 for e2e and :5434 for backend tests, Redis, API, worker `--loop all --profile all`, model
  stand-in), `docs/helm/ARCHITECTURE.md` written, draft PR opened.
- [x] 1. Skeleton: migration `h1a1_helm`; payables ledger, settlement and cash; mandates 1, 2, 5, 7;
  the MILP and the Guard with certificates; `helm.plan`; mode switch, minimal cockpit, approving one
  action; one browser test (`78-helm-skeleton`). Push, checkpoint here, whole backend suite (run:
  4,576 passed, 5 failed: all five were Helm breaking platform contracts, fixed and re-run green).
- [x] 2. Widen the ledger: receivables, POs and deliveries, discounts, notices, compliance
  documents, MSME detection, counterparty behaviour (built with the skeleton; consistent snapshot
  reads proven live).
- [x] 3. The rest of the library (3, 4, 6, 8–12) and the simulation; hold releases and waivers.
- [x] 4. Time machine (backtest, forecast, value held) and the sample company
  (`backend/scripts/helm_demo_company.py`): its backtest finds exactly what was planted, to the paisa.
- [x] 5. Sentence drafting, readback, the validator, the gallery, autonomy and caps, approvals
  (`POST …/mandates/draft`, the Mandates composer and editor, spec 79; the Time machine page too).
- [x] 6. Experience: full cockpit and visual identity, first run, Monday briefing email, preview and
  upsell, the Overview card (instrument trends, the flight path scrubbing into a replay's past,
  `/helm/setup`, the sample company button, the Overview card, plan-card limits; specs 78–80).
- Owner additions (2026-10-15, after box 6), built before box 7:
  - [x] A. Bank statement import: CSV or Excel with a column mapping saved per bank account; cash
    positions; automatic matching of payments to scheduled or approved invoices (amount, date
    window, reference or payee) so "paid" and "value held" rest on evidence; unmatched lines listed.
    (`h1a2_helm_bank`, ARCHITECTURE §16, spec 81. An adversarial review found 34 issues: memory
    and zip-bomb limits, workspace read rules, rejected matches re-made, loose payee matching,
    newest-first balances, discount windows, value events surviving an undo, …; each was proven by
    a failing test and fixed before the first commit.)
  - [x] B. Supplier statement reconciliation mandate: monthly, every supplier statement against the
    Promise ledger, differences with evidence, a drafted reconciliation email. (Found and fixed
    first, proven by a failing test: a supplier's statement of account was read as a bank's, so it
    marked their invoices PAID and counted what we owe them as our cash. `h1a3_helm_reconcile`,
    library mandate 13, ARCHITECTURE §17, live test on the sample company's planted statement.)
  - [x] C. A guided Helm tour on the sample company (instruments, plan, Guard certificate, Time
    machine) for demos and first-time users. (ARCHITECTURE §18, spec 82.)
  - [x] D. If time remains: more hardening tests and a performance run at 10,000 documents.
    (`tests/performance/test_helm_budgets.py`, ARCHITECTURE §13: the plan, the simulation and the
    reconciliation are within budget at 10,000 documents; the ledger update after one change is
    not, 2.9 s against 1 s, above about 2,000 documents a workspace: next step in HANDOFF. The run
    found F-423, F-424 and F-425. Spec 83 checks every Helm page for accessibility and widths.)
- [x] 7. Should-ship: custom condition mandates, approval chains, backtest PDF, what-if, webhooks and
  API scopes. (ARCHITECTURE §11, §14.6, §19–§21; N-098 to N-102; spec 84 walks what-if, a custom
  condition and the approval chain, spec 80 downloads the replay PDF. Found and fixed, each proven
  by a failing test first: F-429 to F-437, among them an API key that opened every organization its
  issuer belonged to (F-435, High) and a payment Helm approved in Act mode that still ran after an
  approval chain was saved (F-438).)
- [x] 8. Hardening: isolation sweep (user and API key), role matrix, double clicks and concurrency,
  worker gates, performance budget, accessibility and widths, logs clean.
  (`test_helm_role_matrix_live.py`, `test_helm_api_scopes_live.py`, `test_helm_concurrency_live.py`
  (every Helm write sent 3 to 8 times at once), `test_helm_worker_gates_live.py`, the 10,000-document
  budget (§13), spec 83. The concurrency and gate tests failed 23 times before their fixes: F-439
  to F-441. COVERAGE.csv has a row for every Helm route, page, job and migration.)
- [x] 9. Finish (§13): full backend and browser suites, frontend checks, one Alembic head with
  up/down/up, live proof on the sample company, `docs/product/FLAGSHIP.md`, HANDOFF sections,
  `docs/helm/MANDATES.md`, NEEDS-OWNER, FINDINGS, COVERAGE, PR ready, final message.

**Progress (2026-10-15, after box 6):** boxes 1–6 done and pushed; CI green on c2b87d3. Fixed, each proven by a
failing test first: a plan could read half of a ledger rebuild; a failing hand left its action
stuck EXECUTING; undo lost a settlement's evidence; Helm's notice switches were shown to members and
the briefing could not be turned off; `helm_plans.conflict` stored JSON null; the dispute email
crashed the escape contract; the ledger paged on a non-unique key; the ledger keyed counterparties
by name only (two suppliers with one name merged); the sample workspace counted against
`limit.workspaces`. CI run 260's browser failure was spec 78 assuming which of two invoices the
radar marks (it depends on which the worker reads last): the spec now checks both orders.
Box 5 also fixed, each proven by a failing test first: a gallery mandate with no default (cash
floor, PO threshold) was saved and backtested with the gallery's example as if the owner had chosen
it; editing an active mandate was called a duplicate of itself. Box 6 fixed the Monday briefing's
links (no such page /helm/cockpit; "turn it off" went to the organization's page; the HTML had no
opt-out link). **Next:** owner addition A (bank statement import), then B, C, then box 7.
The full backend suite takes ~45 min on this sandbox; never edit backend code while it runs
(lazily imported modules load mid-run). Restart the e2e stack (`E2E_LLM=1
frontend/e2e/scripts/start-stack.sh`) after backend changes, and run browser specs with
`npx playwright test -c e2e/playwright.config.ts <spec>` from `frontend/`.

## Previous phase — Pre-launch campaign, session 4 of 4: experience, performance, operations, certification
Branch `claude/kind-hamilton-5lpp19` (the session's assigned branch), based on `main` at `6802a2b`
(PR #22, session 3, is merged; HANDOFF.md has "Session 3 → later sessions"). Draft PR titled
`Campaign session 4: experience, operations and launch certification`. Owner delegated founder
authority: decisions are taken, built and recorded in NEEDS-OWNER.md as
`DECIDED (campaign session 4)`. **If this session is cut off, re-run the same prompt: continue on
this branch and its open pull request, from the first unticked box in CAMPAIGN-MAP.md §4.**

**Plan for this slice (priority order; each fix proven by a failing test first):**
1. CI: keep it green on every push; remove the pytest duplication (F-030) and make the browser job
   a required check.
2. Carry-overs that can be wrong money or lost work: F-324 (verify, then fix), F-256 (late usage
   not disclosed), refunds recorded (credit note, negative revenue), the duplicate gateway
   subscription alert and its refund playbook, every "change plan" screen leading to the portal.
3. Operations (§C): configuration contract test and docs, the whole migration chain up/down/up,
   every host cron line run by hand against the stack the runbook builds, backup and timed restore
   drill, error and dead-job alerts for the owner, the Windows scripts, `COSTS.md`.
4. Customer journeys (§D) as Playwright specs against the production bundle with the worker on.
5. Item actions, the live collaborative-review WebSocket, the engine page journeys, the billing
   jobs through the fake gateway, ERP delivery through the mock targets (§4.1 rows).
6. Experience (§A): shell, every page at four widths in light and dark, accessibility (axe-core),
   first run, public pricing/terms/privacy pages, email rendering.
7. Performance (§B): bundle split and Lighthouse, Locust load run, N+1 and indexes, 10,000
   documents, 500-document bulk delete timing; `PERFORMANCE.md`.
8. Ledger to `--check all` = 0, `PRODUCT-NEXT.md`, the launch certification, the owner launch
   checklist, HANDOFF, final suites, CI green, PR ready.

**Progress (checkpoint 1, 2026-10-13):** items 1 and 2 done, item 5 partly. CI is green on every
complete run, pytest now runs once in four shards, the browser tests are a required job and the
whole migration chain goes down to base and up again (F-030, F-330). Fixed and proven, each with a
failing test first (FINDINGS.md, session 4 section): F-324 (a released document ran its rules
never, or twice), F-256 (late usage into an empty hour), F-327 (refunds recorded on the invoice,
negative revenue, the organization told; N-069), F-328 (API measurements written while it runs),
F-331/F-332 (the owner is emailed about dead jobs, unapplied payments, error bursts and a second
live subscription; RUNBOOK §9.8 refund playbook; N-070), F-333 to F-337 (closed cases, clause checks
and reviews, redaction previews, packet plans). Every one of the 30 engine item actions is now used
for real, and ERP delivery over HTTPS runs against the mock target. **Next:** the live
collaborative-review WebSocket, engine page journeys, the billing jobs through the fake gateway,
then operations (§C), the customer journeys (§D), experience (§A), performance (§B), the ledger.

**Progress (checkpoint 2, 2026-10-13):** items 3 (largely), 4 and 7 (bundle) done. All eight customer
journeys are Playwright specs that pass against the production bundle with the worker running
(`frontend/e2e/tests/60` to `67-journey-*.spec.ts`; journey 4, Enterprise, proves the domain over a
real DNS lookup, a SAML sign-in, SCIM, egress lockdown and the audit export). Every host cron line
runs as cron runs it (`backend/tests/operational/test_host_cron_lines.py`) and by hand against the
stack; the encrypted backup restores in a timed drill (RUNBOOK §9.4). The whole migration chain is
proven up, down to base and up. The first load is 191.9 KB gzipped (was 634 KB; Lighthouse
performance 91 on sign-in). Public pricing, terms and privacy pages (N-073). COSTS.md and
PRODUCT-NEXT.md written; the 17 integrations and every migration and job row closed in the ledger.
Fixed and proven since checkpoint 1: F-338 to F-348. **Next:** the configuration contract (282
rows, in progress), the Locust load run, the engine page journeys and the open endpoint, page and
navigation rows, accessibility and widths (§A), the Windows scripts, then the certification,
HANDOFF and the owner launch checklist.

**Progress (checkpoint 3, 2026-10-14 — session close):** all eight plan items done. Fixed and proven
since checkpoint 2: F-349 to F-364 (configuration contract, seeded workspaces ready, the audit sweep,
sealed redaction files, empty assistant answers, old links, the PDF viewer, line-item reviews, every
page WCAG 2.1 AA in light and dark, the reset link, the assistant freezing the API under load, old
document links), F-380 (emails for mail clients) and F-381 (four widths). First run: a
getting-started card with a sample invoice. At the owner's request the session then audited
TruthMesh, Batch Operations and Document Packs in depth: three new browser specs on tenants of their
own (75, 76, 77) and backend hardening tests; fixed F-382 (concurrent mesh builds), F-390 and F-407
(hostile or damaged packages), F-398/F-399 and F-406/F-408 (packs), F-409 (an empty mesh rebuilt on
every poll). Helper sessions proved the eight unproven settings (F-365, a legal name never reaching
Stripe) and fixed F-370 (key rotation missed 14 secret columns), F-371 and F-372. Decisions N-069 to
N-077. The audit's reproduced-but-unproven items, the N-076/N-077 builds and 32 features with
partial browser coverage are in **`docs/hardening/NEXT-SESSION-PROMPT.md`** (paste it into a new
session). `campaign_slices --check all` exits 0; one Alembic head (`s4b1_drop_email_settings`).

## Previous phase — Pre-launch campaign, session 3 of 4: consoles, identity, settings, security
Branch `claude/determined-planck-e5ftrx` (the session's assigned branch), based on `main` at
`3caab78` (PR #21, the campaign map, is merged; HANDOFF.md has "Campaign review before session 3").
Draft PR titled `Campaign session 3: consoles, identity, settings and security`. Owner delegated
founder authority: decisions are taken, built and recorded in NEEDS-OWNER.md as
`DECIDED (campaign session 3)`. **If this session is cut off, re-run the same prompt: continue on
this branch and its open pull request, from the first unticked box in CAMPAIGN-MAP.md §3.**

**Plan for this slice (priority order; each fix proven by a failing test first):**
1. CI trustworthy (CAMPAIGN-MAP §3.1): read the PR's check runs and annotations, fix every red or
   flaky test at its cause.
2. P0 security: non-human principals default deny (SCIM tokens, the public gateway, partner
   portal), F-124 (SCIM token key), the IDOR sweep over all 621 operations as tenant A with
   tenant B's ids (and as an API key, and in an ungranted workspace), privilege escalation and
   mass assignment, SSRF on every customer-chosen URL, uploads, tokens, enumeration, browser
   security, audit; git-history secret scan. Result: `SECURITY-REVIEW.md`.
3. Enterprise identity live: SCIM (13 endpoints) and SAML (5) against a self-signed test IdP,
   the identity console (domains, certificates, dry-run, activation, SCIM keys).
4. Unbuilt logic (§3.3): notification preferences, billing and plan-limit emails, organization
   "require two-factor", `idp_session_sync`, data residency truthfulness, the step-up dialog test.
5. Settings truthfulness: one formatting layer (workspace date format, time zone, currency; the
   person's own profile wins in the app) replacing the ad-hoc calls; `SETTINGS-LEDGER.md`.
6. Carry-overs (§3.2): access screens name people, assignment without an explicit grant, a
   per-tenant request limit decision, the trial's emails and read-only consoles, the platform
   consoles as an operator, the partner portal.
7. Ledger rows (`campaign_slices.py --check 3`), host sweeps, finish checks, HANDOFF, PR ready.

**Progress (checkpoint 1, 2026-10-12):** items 2 (largely), 3 and 4 done and committed; item 1
waiting on the first CI run's pytest job (every other job green). Fixed and proven, each with a
failing test first (FINDINGS.md, session 3 section): F-276 (require SSO enforced nowhere, critical),
F-277 (IP allowlist never read), F-124 (SCIM token key), F-278 (live review WebSocket skipped the
sign-in policy), F-279 to F-282 (SCIM and SSO after a downgrade, read-only or archive), F-283
(invalid IdP certificates accepted), F-284 (partner standing self-declared), F-285 (markup and
header injection in emails), F-286 (per-person rate limits), F-287 to F-290 (billing and security
notices emailed, notification preferences, Stripe announcements, 80%/100% limit alerts, addresses
in logs). Built and decided: N-057 to N-062 (sign-in policy everywhere, `idp_session_sync` removed,
SCIM/SSO after downgrade, require two-factor, per-person limits, which notifications are emailed).
Proven with no defect: non-human principals default deny, IDOR sweeps (attackers B and an
enterprise X against C: 353 reads, 832 writes, 789 as an API key, an ungranted workspace), privilege
escalation as a viewer and as billing, SAML/OIDC attacks, CSV formula neutralisation, image uploads
re-encoded, git-history secret scan (placeholders only). Local full backend suite on the
checkpoint's first half: 3985 passed. **Next:** SSRF probes, tokens, enumeration, cookies/CORS/
redirects, audit immutability, then `SECURITY-REVIEW.md`; the formatting layer and
`SETTINGS-LEDGER.md`; §3.2 carry-overs; ledger rows; CI.

**Progress (checkpoint 2, 2026-10-12, evening):** items 1, 2, 4 and 5 done. CI green on every
complete run (§3.1 ticked). Security review written (`SECURITY-REVIEW.md`, F-291 to F-295). The
display layer is one module per side (F-298, N-064) and `SETTINGS-LEDGER.md` lists every setting
with its reader, effect and test; on the way, settings that changed nothing or said more than they
did were fixed, each with a failing test first: chunking controls (F-299), brand colours (F-300,
N-065), data residency's promise (F-301, N-066), webhook redelivery crashing the worker (F-302),
the transfer form's double password dialog (F-303), audit log retention ignored and a fixed
400-day delete (F-304, N-067, High), the organization mail page (F-305), workspace reply-to
(F-306), AI settings reach (F-307), the identifier's support promise (F-308). Partner portal
routes proven end to end; a partner's rate could never change (F-309) and a new partner could
never be used (F-310). Proven with no defect: egress lockdown, document controls, the step-up
dialog (F-117). Ledger: 88 session 3 rows open (from 145). **Next:** platform consoles as an
operator (RevOps, Unit economics, Sovereign, Audit explorer), the partner portal page and nav,
host crons (arch07, arch09, identity, invitations), remaining ledger rows, HANDOFF, finish line.

**Final checkpoint (session 3 finished, 2026-10-12, night):** all seven items done. Platform
consoles proven as an operator (RevOps, Unit economics, Sovereign, audit explorer: F-311 to F-317);
partner portal page and suspended read-only state (F-319); profile save no longer pins the clock
(F-318, the 14-configuration CI failure); workspace regional settings checked and every zone and
currency offered (F-320, F-321, N-068); the settings page keeps its section (F-322); a public-API
workflow trigger now reaches the engine (F-323, High); erasure by a person's name, not an unseen
user ID (F-325), and member lists no longer fail once someone has been erased (F-326, found by
the full browser run). F-324 (a verification/automation race) is recorded as **unverified** and handed
to session 4. Host crons (arch07, arch09, identity, invitations) proven. New tests: console routes
by effect, custom domains and TLS, warehouse connectors on the wire, DNS lookup, AI settings at the
provider, browser specs 48 (console effects) and 49 (account changes and emailed links).
`campaign_slices --check 3` exits 0 (one row, `branding.domain`, blocked with its reason).
HANDOFF.md has "Session 3 → later sessions". **Next action:** session 4 (CAMPAIGN-MAP §4); the PR
is marked ready once CI is green on its last commit.

## Before session 3 — campaign review (2026-10-12)
A review of the whole repository after sessions 1 and 2 found work no session prompt named or that
a session handed on: 711 coverage rows still `smoke` or `untested`, 9 pieces of code with no ledger
row, dead or unbuilt features (billing and limit emails, notification preferences, the date-format
setting, `idp_session_sync`), host cron sweeps never run against the compose stack, and CI red on most
runs since 2026-10-06 without any session noticing (F-275). **Everything left is assigned, item by
item, in `docs/hardening/CAMPAIGN-MAP.md`; read it right after this file.** Who owns each open
ledger row is computed by `python docs/hardening/tools/campaign_slices.py` (session 3: 145 rows;
session 4: 575, of which 282 configuration variables and 163 migrations). A session is finished
only when `campaign_slices.py --check <its number>` exits 0, every box in its section of the map is
ticked or in BLOCKERS.md, and CI is green on its pull request.

## Previous phase — Pre-launch campaign, session 2 of 4: documents, AI and every engine
Branch `claude/trusting-ptolemy-yiz005` (the session's assigned branch), draft PR #20 opened early.
Based on `main` at `340a8c4` (session 1's PR #19 is merged; HANDOFF.md has its section). Owner
delegated founder authority: decisions are taken, built and recorded in NEEDS-OWNER.md as
`DECIDED (campaign session 2)`. **If this session is cut off, re-run the same prompt: continue from
the checklist below; do not restart.**

**Plan for this slice (priority order; each fix proven by a failing test first):**
1. [done] Build the owner's one-week trial (N-052, HANDOFF spec): clock per owner account, 402
   `TRIAL_ENDED` on every write/intake path and in the worker, subscribing lifts it, banner and
   full-page notice, two emails, e2e tenants S and T, tenancy doc regenerated.
2. [done] Test corpus under `backend/tests/fixtures/corpus/` (generated, no copyrighted material).
3. [done] P0 sweep of AI safety and isolation: prompt injection through documents (assistant,
   automations, exception agent, assertions), canary isolation across organizations and
   ungranted workspaces (search, assistant, citations, embeddings, caches, suggestions), metering
   exactly once (retries, cancelled streams, fallbacks, BYOK), model list hygiene.
4. [done] Known leftovers: the assistant stream's Redis frame buffer off the event loop (live /health
   proof); the matching queue lists one case per invoice copy (one case, duplicates flagged).
5. [done] Every engine control does something real (AI defaults, presets, legal hold, autonomy
   thresholds, re-index status) and every engine is checked against the new plan matrix.
6. [done] Document life: every intake path, every state, hostile timing (delete/archive/downgrade during
   processing), stuck-job sweeper, idempotent re-runs, provenance.
7. [done] The worker: every handler and sweep by hand and on schedule, two workers never run one job,
   DLQ visible, graceful shutdown, 1,000+ jobs RSS, timeouts, shared models serialized, pool.
8. [done] Automations: action catalog live, loops and budgets; review, collaborative review,
   verifications and assertions agree.
9. [done] COVERAGE.csv rows in the slice to `deep` or `blocked`; finish checks; HANDOFF; PR ready.

**Progress (checkpoint 1, 2026-10-11):** items 1 to 5 done and pushed. Fixed and proven:
F-257 to F-266 (FINDINGS.md, session 2 section), decisions N-053 to N-055. Live proofs with no
defect: retrieval isolation (55 checks), prompt injection, metering exactly once. Engine controls
proven real by new live tests: presets reach the extraction prompt (and stop when disabled), the
autonomy error limit moves the cut-off, the re-index card stops polling, Streaming responses
(F-266), AI defaults on a new organization (F-260); legal hold was already covered
(`tests/api/test_legal_hold_enforcement.py`).

**Progress (checkpoint 2, 2026-10-11):** items 6 to 8 done and pushed. Fixed and proven: F-267
(Reprocess did nothing and left documents Queued; AI never re-ran), F-268 (Reprocess twice ran and
charged twice), F-269 (two workers ran one job; a stopping worker ran its whole batch), F-270 (the
dead-letter queue made visible: /admin/jobs), F-271 (API keys acted with their issuer's full rights
whatever their scopes; N-056). Proven sound with new live tests: deletes mid-pipeline, duplicate
job delivery, every scheduled sweep, 1,200-job memory soak, the rest of the automation action
catalog, API-key uploads. The sandbox restarted once mid-session (databases on the RAM disk were
lost; `frontend/e2e/scripts/start-db.sh` then `start-stack.sh` bring everything back). **Next:**
item 9 (ledger, full suites, PR ready).

**Finished (2026-10-11).** Fixed and proven this session: F-257 to F-274 (18), plus the owner's
trial (N-052). Decisions N-053 to N-056. Finish checks, all on the final code:
- backend: full suite **3,915 passed, 9 skipped, 0 failed** (`POSTGRES_DB=flowpilot_test`);
- browser: full suite on a fresh e2e database, production bundle, CSP enforced, model stand-in on
  (`E2E_LLM=1`, as CI): **409 passed, 1 skipped** (the provider-down test, which only runs without
  a model), 0 failed;
- frontend: `tsc -b`, the browser tests' typecheck, `npm run lint`, `npm run check:self`,
  `npm run build`: all clean (the build's large-chunk notice is pre-existing);
- Alembic: one head (`s2a1_free_trial_clock`), upgrade, downgrade, upgrade on a scratch database;
- audits: `pip-audit -r requirements.txt` and `npm audit --omit=dev`: no known vulnerabilities;
- live logs of the browser run: 0 tracebacks, 0 ERROR lines (API and worker); the one 5xx is the
  expected 503 for a seat purchase with no gateway key in the sandbox; all 468 jobs SUCCEEDED.
Ledger, session 2's slice: 362 `deep`, 9 `blocked`, 83 `smoke`, 18 `untested`; what is left is
listed in HANDOFF.md for session 4. **Next:** the owner merges PR #20; then session 3.

## Previous phase — Pre-launch campaign, session 1 of 4: tenancy, roles, plans, seats, billing, usage limits
Branch `claude/new-session-ejp1sm` (the session's assigned branch), draft PR opened early. The four
sessions run one after another; the hand-over notes between them are in `docs/hardening/HANDOFF.md`.
Owner delegated founder authority: decisions are taken, built and recorded in NEEDS-OWNER.md as
`DECIDED (campaign session 1)`.

**Plan for this slice (priority order; each fix proven by a failing test first):**
1. P0 money/access, found by reading before the stack was up (to be proven):
   - a new organization is put on no plan at all (no Free tier assigned): AI is refused and the
     platform-wide defaults (20x Free) apply instead of Free's allowance;
   - seat changes on paid organizations never reach the payment gateway (the internal outbox
     queue that carries `billing.seat_added/removed` has no consumer), so members are not billed;
   - `organizations.seat_limit` is never written, so every organization, Free included, can add
     unlimited members.
2. One seat model, enforced at every entry path (invitation, direct add, reactivation, SCIM, SSO
   JIT, ownership transfer, partner tenancy): Free capped by the plan; paid organizations hold a
   purchased seat quantity; adding past it buys a seat after the price is shown and confirmed, or
   is refused with the way to buy; Owner and Billing can buy seats.
3. Free made deliberately small: new meters `document.upload` and `assistant.message`, per-plan
   file size, pages per document, workspaces and seats; enforced on every path (browser, multipart,
   API key, batch, public link, re-processing, the assistant) and in the worker; charged at upload
   (reserve) so nothing is left half-processed; one Free organization per account; atomic.
4. The paid ladder: same counts on Developer/Business/Enterprise, a monotonic test over the seed,
   unit economics against the margin service, overage policies doing what they say.
5. `docs/hardening/TENANCY-AND-PLANS.md` generated from the code, with a drift test.
6. Role matrix on the server; removal revokes every kind of access; restricted screens name who
   to ask.
7. Subscription lifecycle through the webhook paths (Stripe test signatures, Dodo), downgrade
   handling (N-003), archive/delete with an active subscription.
8. Live concurrency tests (seats, quota units, webhooks), the worker's tenant gate, revenue truth,
   the admin area refusing tenants, plan cards from the source of truth.

**Session 1 finished (2026-10-11).** All eight plan items done; PR #19 marked ready.
- **Fixed, each with a test that failed first (FINDINGS.md F-236 to F-255):** new organizations
  start on Free; seats enforced on every entry path and purchasable by Owner, Admin and Billing; the
  decided plan table enforced on every upload path, the assistant, workspaces and the worker
  (charged once, at acceptance); one Free allowance per owner account; resumable uploads bounded in
  total; the paid ladder monotonic and every paid seat at least 60% gross margin at its ceilings
  (50% on the dearest platform model); Gemini overage billed and own-key tokens never billed as
  overage; automations from Developer up; a paying organization is never sold a second
  subscription; an organization cannot be deleted while its subscription renews; no automations
  or engine work for an organization that has not paid; allowance shown where it is spent; every
  "ask someone" line names the owners; calendar feeds for owners and admins; an invitation race
  deadlock removed. Proven with no defect: role escalation, Billing-role sweep, add-on lifecycle,
  promo codes (live race).
- **Owner decisions:** N-040 to N-051 taken under delegated authority; **N-052 (the owner's own
  decision): Free becomes a one-week trial, then subscribe. Not built in session 1; the spec and
  the build plan for sessions 2 to 4 are in HANDOFF.md.**
- **Open:** F-256 (P3, late usage into an empty hour not disclosed; the late-usage test fails at
  minute 59), refunds not modelled, plan switching depends on the Stripe portal setting (N-050).
- **Verification:** full backend suite 3,760 passed, 1 failed (F-256's minute-59 case; passes on
  rerun and in sequence), 9 skipped; full browser suite on a fresh e2e database, production bundle with the production CSP enforced: 400 passed, 1 failed, 1 skipped on the final bundle (the one failure was a test-isolation flaw, another test signing C.admin out everywhere; fixed, and both specs repeated three times in parallel pass 45/45). The first full run's 11 failures were two regressions in this session's own F-252/F-253 work, caught and fixed; all 11 pass; `tsc -b`, browser-test typecheck, `npm run
  lint`, `npm run check:self`, `npm run build` clean; pip-audit and `npm audit --omit=dev` no known
  vulnerabilities; one Alembic head (`s1b1_calendar_feed_org_member`), up/down/up on a fresh
  database; no new model drift; live API and worker logs 0 tracebacks, 0 ERROR, the only 5xx the deliberate 503 for buying seats with no gateway configured; 643 background jobs SUCCEEDED, none failed.
- **Next:** session 2 (documents, AI, engines, jobs), starting with the owner's trial (HANDOFF.md).

**Progress (checkpoint 1, 2026-10-11):** items 1 to 5 done and pushed; item 6 partly.
- Fixed, each with a test that failed first (FINDINGS.md F-236 to F-249): new organizations start
  on Free; seats enforced on every entry path and purchasable by Owner and Billing; the decided plan
  table (N-040 to N-047) enforced on every upload path, the assistant, workspaces and the worker
  (charged once, at acceptance, under the organization's lock); one Free allowance per owner
  account; resumable uploads bounded in total (migration s1a1); the paid ladder monotonic and every
  paid seat at least 60% gross margin at its ceilings; allowance shown where it is spent; every
  "ask someone" line names the person; calendar feeds work for owners and admins (migration s1b1);
  an invitation race deadlock removed.
- `TENANCY-AND-PLANS.md` is generated from the code (drift test).
- Verification so far: targeted backend runs 1,076 passed and 580 passed; full browser suite
  397 passed, 3 failed (all one cause, the billing role refused the summary: fixed and tested),
  1 skipped; live logs 0 tracebacks, 0 ERROR, one deliberate 503 (seat purchase with no gateway
  configured, F-213's answer). One Alembic head (s1b1), up/down/up verified, no new model drift.
- Next: E.3 rest (self-escalation, last owner, viewer cannot write), D (overage policies proven,
  add-ons, frontend parity), F (subscription lifecycle via webhooks), G (worker tenant gate,
  webhook concurrency, cache keys, per-tenant rate limits), H (revenue truth, /admin refusal),
  COVERAGE.csv, then the finish checks.


## Latest pass — owner decisions N-034 to N-039 applied (2026-10-10)
The owner delegated founder authority for the six open questions; engineering decided and built
them on the same branch and PR (#18), each proven by a failing test first (FINDINGS.md F-230 to
F-235, NEEDS-OWNER.md for the reasoning):
- **N-037 / F-230:** invitation links last 7 days (`INVITATION_TTL_HOURS` 168).
- **N-036 / F-231:** accepting never lowers an active member's role, only raises it.
- **N-034 / F-232:** a platform-delivered invitation's sign-up takes over an account nobody
  verified (new password, verified, old sessions ended); verified accounts still sign in.
- **N-035 / F-233:** organizations that require SSO are joined through SSO: the preview says so, the
  page offers "Sign in with single sign-on", the password sign-up is refused (409).
- **N-039 / F-235:** the first SSO sign-in takes over an unverified account (verified, password
  unusable, sessions ended, audited).
- **N-038:** torch 2.13.0, setuptools 83.0.0, paramiko 5.0.0 (pip-audit clean on these).
- **F-234:** the "no seats" email to the inviter goes once per invitation per day, not on every
  refused attempt.
Verification: the new tests (11) and the invitation, SSO and SFTP suites (613) pass; the torch and
embedding suites pass apart from the 4 sandbox-only vector tests; browser specs touching
invitations, the team and auth: 143 passed, the new SSO screen test included (one dev-mode-only
miss in 21-live-feedback, which needs the production bundle's hashed chunks and passes there);
`tsc -b`, the browser-test typecheck and lint clean. Full CI runs on the push.

## Earlier pass — invitations, the workspace team and the event loop (2026-10-10)
Same branch and PR as the bug hunt below (`claude/jolly-keller-d0jscd`, PR #18), continued after
a usage-limit pause, on the owner's list (required.txt). **Fourteen defects and builds, F-216 to
F-229, each proven by a failing test first** (FINDINGS.md, "Invitations, the workspace team and
the event loop"), plus the owner's N-032/N-033 decision applied and backend CI made green again.
- **F-218 (High):** the routes that await (uploads, the assistant stream, upload parts, webhooks)
  and the sign-in dependency every request runs did blocking work on the event loop; a slow step
  in any of them stalled the whole API. All of it runs in the threadpool now; a live-server test
  slows each step to 3 s and requires `/health` under 1 s (10 of 10 failed before).
- **Invitations:** F-216 the pending list showed accepted and revoked invitations (the "zombie");
  F-217 removing a member left their pending invitation, whose link let them back in; F-221 the
  last seat could never be filled by an invitation; F-222 a newcomer now signs up from the
  invitation in one step (address locked, account verified by the token) and an existing user is
  sent to sign in and back; F-224 "switch account" now signs out on the server; F-223 the email is
  rebuilt for Outlook, Gmail and Apple Mail (card, bulletproof button, security footer).
- **F-219:** Workspace Settings → Team members has role controls and Remove, or a badge, in every
  Actions cell. **F-220:** an empty or oversized public document-request upload was a 500.
- **N-032 / N-033 decided:** Batch operations and TruthMesh on Business and Enterprise (deploy step:
  `seed_quota_tiers.py --carry-forward`).
- **Review:** an independent adversarial review of the diff found **F-226 (High)**: an
  organization sending mail through its own SMTP could turn an invitation into a verified account
  for any address; now only a link FlowPilot's relay delivered proves an address. Also F-227
  (switch account sent a newcomer to sign-in), F-228 (sign-up dead ends), F-229 (presence order).
- **CI:** backend CI was red on main since the platform relay became mandatory (24 tests); the
  backend steps now declare a relay. `pip-audit (advisory)` stays red on main (N-038).
Verification: see "What is done" below (CI green on the final code).

## Earlier pass — live bug hunt: fuzzing, double clicks, dev-mode rendering (2026-10-09)
Branch `claude/jolly-keller-d0jscd` (the session's assigned branch). Real live stack: Postgres 16 +
pgvector 0.8.0 (built from source), Redis, uvicorn API, the real worker `--loop all --profile all`
(full `requirements.txt`, Paddle included), model stand-in, Vite dev server on :5173. Previous
sweeps had found nothing new, so this pass attacked the stack differently: an OpenAPI-driven fuzzer
over all 609 operations as real users (bad ids, edge values, wrong types, malformed JSON), a
double-click sweep (every write sent 3 to 8 times at once), odd uploads and delete-during-processing
races, and the browser suite against the dev server. **Eight live defects, F-208 to F-215, each
proven by a failing test and fixed** (FINDINGS.md, "Live bug hunt"). The serious ones:
**F-212** two quick clicks on "Change role" froze the whole API until restart (129 `async def`
routes did blocking database work on the event loop); **F-214** concurrent duplicate submits were
500s on 8 routes; **F-215** an OCR worker could not shut down gracefully once Paddle was loaded;
**F-209** re-inviting a pending address crashed; **F-211** an SSO connection made from a metadata
URL was a 500. After the fixes the fuzzer and the double-click sweep return no 500s (the only 5xx
are the intended 503 "billing not configured" answers).
Verification on a fresh e2e database: browser suite against the production bundle with the
production CSP **380 passed, 0 failed, 1 skipped** (by design); against the Vite dev server 379
passed, 1 skipped, and the only failure is the F-144 test, which removes a hashed production chunk
and so only works against the production bundle. API and worker logs over both runs: **0 tracebacks,
0 5xx, 0 ERROR lines; 640 jobs of 38 types, all SUCCEEDED.** Backend suite (full, on the final head): **3,592 passed, 0 failed, 9 skipped** (65 more tests than Phase 3).
Frontend: `tsc -b`, `npm run lint`, `npm run check:self` clean; encoding check clean; one Alembic
head (no migration in this pass). The sweep scripts are kept as `docs/hardening/tools/live_api_fuzz.py`
and `live_double_click_sweep.py`.

## Earlier pass — final systemic polish & traceback sweep
Branch `hardening/final-systemic-polish-and-traceback-sweep` (after PR #15). Real live stack
(API + worker `--loop all` + Postgres/pgvector 0.8 + Redis + production bundle): browser suite 380
passed, 0 failed; 0 tracebacks, 0 5xx, 0 ERROR log lines; 400 jobs all SUCCEEDED. One polish fix,
F-207 (materiality shown as "90%" instead of "0.90"), proven red then green. Stopped early on the
owner's usage budget; the remaining small items below are still open (the corroborator item is done).


## Earlier pass — budget-capped header polish (2026-10-09)
Branch `claude/sweet-hopper-l4varl`. The owner had ~1% of weekly usage for this run, so the live
stack was NOT stood up (the sandbox had no Python dependencies or pgvector build). Only change: ERP
posting and Process intelligence now open with the shared `PageHeader` (icon tile, eyebrow, title,
description underneath, actions on the right) instead of a description squeezed beside the title.
Verified: `tsc -b`, eslint on both files, `npm run build`. Unverified: the browser suite and a live
look (route titles `/ERP posting/` and `/Process intelligence/` in `e2e/support/routes.ts` still
match the same `<h1>` text).

## Earlier phase — Phase 3 (complete)
**Phase 3 — Final commercial hardening: COMPLETE, merged.** Branch
`hardening/phase-3-final-commercial-hardening`; PR #13
(https://github.com/sabarishwarne2001/flowpilot-ai/pull/13). Builds on Phase 2 (merged
into `main`).

- **Live defects (each with a failing test first): F-182 to F-206** (FINDINGS.md, "Phase 3").
  The heavy ones: F-182/F-183 the nightly retention purge never ran, and when run it left the files
  in storage; F-188 requiring SSO with no identity provider locked out the whole organization;
  F-195 a failed request re-asked ~30 times a second (976 failed requests in 15 s from one tab);
  F-196 every new workspace was set to a Groq model Groq had retired; F-204 an organization's
  maximum session age was shown as in force but never applied; F-205 the public SAML logout
  endpoint signed people out on an unsigned request. Also role-matrix truthfulness (F-192 to
  F-201), the job SLOs never measured (F-189), BYOK and margin miscounts (F-190, F-202), RevOps
  prompts that sent on Cancel (F-186), billing in internal keys (F-187), a phone-width overflow
  (F-203), and a deliberate sign-out that sent people back where they were (F-206).
- **Elevation:** one console header (`PageHeader`) and URL-synced keyboard tabs across every
  organization console, the identity and billing hubs, marketplace, autonomy, audit and the platform
  admin consoles; sentence case and labelled fields on the remaining settings and auth screens.

## What is done
- **Invitations, the workspace team and the event loop (2026-10-10)** (PR #18): F-216 to F-229
  fixed, each proven by a failing test first.
  - **GitHub CI on the final code (`bfe1836`): green**: the full pytest job (Phase 2 security
    proofs, Phase 4 engine proofs, the whole suite), browser tests, frontend, migration head and
    drift. Only `pip-audit (advisory)` is red, as on `main` (N-038).
  - Browser suite on a fresh e2e database, production bundle with the production CSP: **393
    passed, 0 failed, 1 skipped** (by design; 13.2 min). API and worker logs: 0 tracebacks, 0 5xx,
    0 ERROR lines; 410 jobs of 38 types, all SUCCEEDED.
  - Backend, full suite locally in CI's environment: **3,631 passed, 9 skipped, 8 failed**. The 8
    are sandbox-only and pass in CI (the embedding model cannot be downloaded here, plus one
    readiness check).
  - `tsc -b`, the browser-test typecheck, `npm run lint`, `npm run check:self`, `npm run build`
    (no source maps) and the encoding check are clean. One Alembic head
    (`r1a1_invitation_delivery`); up, down and up again; no new drift (283 known).
- **Phases 0 to 5, final release, production configuration & UI elevation, final systemic
  polish, live feedback & Tier-1 elevation, Phase 1 (document intelligence), Phase 2 (enterprise
  processing and TruthMesh):** merged.
- **Phase 3 — final commercial hardening** (this branch): F-182 to F-206 fixed, each proven.
  - Backend suite (full): **3,527 passed, 0 failed, 9 skipped** (48 min; 48 more tests than Phase 2).
  - Browser suite (full, fresh database, production preview, CSP, model stand-in): **380 passed, 0 failed, 1 skipped** (by design; 12.3 min). The first full run had 2
    failures, both fixed and re-proven: the API-keys header added here matched a test's phrase
    (`a29d764`) and F-206. Logs clean; 403 jobs of 38 types, all SUCCEEDED.
  - `npm run build`, both `tsc` projects, lint, `npm run check:self`, `check-no-sourcemaps
    --dist`, encoding check, `npm audit --omit=dev` (0): clean. One Alembic head
    (`q1a1_retired_groq_models`); migration up, down and up again checked; drift 283 known, 0 new.
  - `COVERAGE.csv` (1,400 rows): deep 380 → **408**.
  - Release certification: `05-release-readiness.md` (Phase 3), verdict **GO**.

## Owner decisions in force (do not re-ask)
**N-032 and N-033 decided 2026-10-10:** Batch operations and TruthMesh are on Business and
Enterprise. **N-034 to N-039 decided 2026-10-10** under delegated founder authority: unverified
accounts are taken over by a platform-delivered invitation or an SSO sign-in, SSO-required
organizations are joined through SSO, accepting never lowers a role, invitations last 7 days, the
flagged dependencies are upgraded.
Everything else in NEEDS-OWNER.md is decided. Previous release: **N-026** Stripe (test mode) for
launch, Dodo selectable; **N-027** Postmark before the first paying customer; **N-028**
`app.flowpilot.ai` / `admin@flowpilot.ai`; **N-029** no unbacked trust claims; **N-030** seat price =
plan card price; **N-031** local model at a declared zero.

## Next action (exact)
_Updated 2026-10-17 (website and payments session close):_ once CI is green on pull request #25,
merge it. Then the owner works through HANDOFF.md "Owner launch checklist" (12 steps; step 9 is the
first run against a real Dodo test account, checking docs/billing/DODO.md §6). The next session
removes the one-release aliases for the old name and takes up anything step 9 finds.

_Updated 2026-10-14 (session 4 close):_ merge pull request #23 once CI is green, then start a new
session with `docs/hardening/NEXT-SESSION-PROMPT.md`; the owner works through HANDOFF.md
"Owner launch checklist". The list below is the earlier (session 3) text, kept for history.

_Updated 2026-10-12. The earlier list here (merge PR #18; the Redis frame buffer; one matching case
per invoice copy) is done: PR #18 merged, the buffer moved off the event loop (F-263), one case per
invoice (F-264, N-055)._
1. Session 3 is done (its PR is "Campaign session 3: consoles, identity, settings and security").
   Next: session 4 (experience, performance, operations, certification), with its section of
   `docs/hardening/CAMPAIGN-MAP.md`, starting from HANDOFF.md "Session 3 → later sessions"
   (F-324 to verify first).
2. Still open from earlier passes, assigned to session 4 in the map: the main JavaScript chunk's
   size, measured fresh, and the Tailwind 4 move.
3. The owner's own launch steps (Stripe test prices and webhook secret F-125, Postmark N-027, rolling
   the keys pasted into chats, the first deploy RUNBOOK §9, and the rest) are collected in section 5
   of the campaign map; session 4 turns them into the final "Owner launch checklist".

How to bring the test stack up in a fresh sandbox: `frontend/e2e/scripts/start-db.sh` (pgvector
0.8.0 built from source: `apt-get update && apt-get install postgresql-server-dev-16`, then
`make && make install` in a v0.8.0 checkout), `backend/.env` from `.env.example` plus the block in
`frontend/e2e/README.md` (and `POSTGRES_PORT=5433`, `POSTGRES_DB=flowpilot_e2e`, the CI secrets from
`.github/workflows/ci.yml`), `python3.12 -m venv backend/.venv && pip install -r requirements.txt
-r requirements-dev.txt`, `npm ci` in `frontend`, then `E2E_LLM=1 frontend/e2e/scripts/start-stack.sh`
and `E2E_LLM=1 E2E_CSP=1 npx playwright test -c e2e`. Backend tests: the CI environment block
(`POSTGRES_*` pointing at port 5434 — a second cluster — `ARCH40_CONTRACT=1`, the CI secrets), then
`pytest -q`. For a fresh browser run also flush the e2e Redis database (`redis-cli -n 0 flushdb`)
and delete `frontend/e2e/.state/`.

## Blockers
None in engineering. Not verifiable from this environment: the production compose stack on a real
server (F-006) and the CPU-only torch image (F-045).

## Budget notes
One long session (continued after its context filled): the live stack with log watch across every
console, hub, admin page, role and plan; a crawler pass per seeded person and at phone and tablet
widths; every scheduled sweep by hand; 25 fixes each proven by a failing test; the console
elevation; one full backend run and one full browser run on a fresh database; the documentation.
The exact spend is not visible from inside the session; check your usage page.

## Environment notes (for the next session)
- **Event-loop freezes**: `tests/engines/test_blocking_io_does_not_freeze_the_api_live.py` is the
  pattern: slow one blocking call to 3 s inside a route on a real uvicorn and time `/health`. The
  guard `tests/core/test_async_routes_must_await.py` now also checks async dependencies and the
  app coroutines a route awaits.
- **Context variables and the threadpool**: a value set with `set_current_principal` inside a
  `run_in_threadpool` call is lost when the thread returns; set it on the loop (see
  `deps.get_current_user`).
- **The worker with `--profile all` needs the full `requirements.txt`** (Paddle, torch): with only
  `requirements-web.txt` it refuses to start (ProfileError), by design. `pip install -r
  requirements.txt` takes ~10 minutes in the sandbox.
- **A frozen API**: `pip install py-spy` then `py-spy dump --pid <uvicorn pid>` shows what the event
  loop thread is blocked on, and `pg_stat_activity` / `pg_blocking_pids()` shows who holds the lock.
  This is how F-212 was traced.
- Concurrency defects only show under a real server: `tests/engines/test_concurrent_*_live.py`
  start uvicorn in a thread (TestClient serialises requests differently).
- **Two pytest processes against one Postgres server corrupt each other** (fixed database names,
  e.g. `flowpilot_svc_test`). Use the second cluster (`POSTGRES_PORT=5434`) and, for a targeted run
  next to a full one, `TEST_DB_NAME=<other>`; the services suite still shares its fixed name.
- **Do not edit backend source while a full suite runs**: several security tests read source with
  `inspect`/`ast` and see the edited file at the old line numbers.
- After changing `backend/requirements.txt`, run `python scripts/image_requirements.py`.
- FastAPI is pinned below 0.137 on purpose (route walkers; see Phase 5 notes).
- The browser suite needs a restart of the stack after backend changes (`start-stack.sh`; uvicorn
  runs without reload). `E2E_LLM=1` starts the model stand-in; `E2E_CSP=1` enforces the Caddyfile CSP.
- `pkill -f <pattern>` can kill the calling shell; use anchored `pgrep -f '^...'` and kill by PID.
- Model hosts, Stripe, Groq and Dodo are blocked; PyPI and npm are reachable. PyPI throttles
  repeated installs: resolve with `pip install --dry-run --report`, fetch the wheels once, then
  `pip install --no-index --find-links`.
- In dev mode (`E2E_MODE=dev`, Vite on :5173) set `E2E_API_ORIGIN=http://localhost:8000`, or the
  refresh cookie's domain does not match and every page signs out.
- `frontend/e2e/probe/` (untracked, excluded in `.git/info/exclude`) holds screenshot probes:
  `E2E_TEST_DIR=./probe npx playwright test -c e2e p8` writes PNGs to `/tmp/shots`.
- **Live sweeps**: the crawler and API sweep scripts used in this pass are described in
  FINDINGS.md ("Final systemic polish"); the jobs table (`select job_type, status, count(*) from
  jobs group by 1,2`) is the record of every background job the live stack ran, and survives the
  log rotation that `start-stack.sh` does on every restart.
- The browser suite reuses a preview server on port 3000 if one is running (outside CI), so a run
  started while another is serving tests the older bundle.
- **Fresh e2e database**: `psql -h localhost -p 5433 -U postgres -c "DROP DATABASE flowpilot_e2e WITH (FORCE)"`
  then `CREATE DATABASE flowpilot_e2e` and `start-stack.sh` (migrates). Some browser tests create
  organizations; archived ones count towards an account's limit of three, so a database that has
  seen many runs eventually refuses new ones.
- The browser-suite seed now finds its sample documents by name (F-168); before that, a database
  with more than 50 documents in Tenant C received a second copy of each sample on every run.
- Ad-hoc screenshot probes (not part of the suite) can be written under `frontend/e2e/tools/`
  and run with `E2E_TEST_DIR=./tools`; this phase's probes were kept out of the repository.
- `seed_price_book.py --version auto` publishes the next price book only when the seed changed;
  the start scripts and the e2e seed use it.
- **TanStack Query**: the client refetches on mount ("always"); `retryOnMount: false` (F-195) stops a
  failed query being re-asked whenever another component reading it mounts. Do not gate a page on
  `isLoading` while a child reads the same query without it.
- **Groq models**: Groq retired `mixtral-8x7b-32768` (March 2025), `llama-3.3-70b-versatile` and
  `llama-3.1-8b-instant` (16 August 2026). The platform default is `openai/gpt-oss-20b`; check
  https://console.groq.com/docs/deprecations before adding a model to `app/core/ai_models.py`.
- Sessions live in the `sessions` table; a refresh that fails revokes the family, so a script that
  ages a session and refreshes loses its access token too.
- **The sandbox's databases live in memory** (`/dev/shm/pgdata` :5433 for e2e, `/dev/shm/pgdata2`
  :5434 for backend tests): a container restart wipes them. Recreate both clusters with
  `initdb --encoding=UTF8 --locale=C.UTF-8` (the container's POSIX locale otherwise gives
  SQL_ASCII and the tests fail on the first non-ASCII character), the `vector` extension, the
  `flowpilot` role and the `flowpilot_test` / `flowpilot_e2e` databases, and start Redis; then
  `start-stack.sh` migrates. On a fresh e2e database the very first browser run can fail with
  `UnmappableTierError` (the seed publishes the plans at that instant); the next run passes.
