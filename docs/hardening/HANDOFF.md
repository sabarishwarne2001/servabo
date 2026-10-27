# Hand-over between the four pre-launch campaign sessions

The final pre-launch campaign is split into four Claude Code sessions that run one after another,
each owning one slice of the product: **session 1** tenancy, roles, plans, seats, billing and usage
limits (the money and access model); **session 2** documents, AI and every engine, the whole
document-to-decision pipeline and every background job; **session 3** the organization, identity
and governance consoles, settings truthfulness and the security red team; **session 4** the
product shell and experience, performance, operations, end-to-end customer journeys and launch
certification. A session that finds a defect in another session's slice fixes it when that takes
under about 30 minutes; otherwise it writes it here, under the session that owns it, with enough
detail to reproduce. Each session appends a section "Session N → later sessions" when it finishes:
what it changed that later sessions must build on (limits, capability keys, metered keys,
migrations, renamed routes, shared components), defects it saw in their slices, and what in its
own slice is unfinished, with why.

## Owner request: the one-week trial (must be built in a later session)

The owner decided on 2026-10-11 (NEEDS-OWNER.md **N-052**, superseding the trial part of N-051) that
**Free is a one-week trial; when it ends the organization is asked to subscribe to a paid plan**, as
Claude does. Session 1 recorded it but did not build it. **Session 2 builds it** (ending a trial
stops uploads, the assistant, automations and engine work, which session 2 owns); **session 3**
checks the consoles, emails and settings it adds; **session 4** proves the whole journey (sign up →
trial → reminder → trial ends → subscribe → everything back) in the browser and certifies it. The
spec, with what already exists to build on:
1. **Clock.** One trial per owner account, starting when the person creates their first
   organization (`organization_service._start_on_free_plan` is the moment; the Free pool,
   `quota_service.usage_pool`, already groups an owner's organizations). Store when it ends
   (for example `users.trial_ends_at`, or on the pool's anchor organization) in a migration after
   `s1b1_calendar_feed_org_member`; length from a setting `FREE_TRIAL_DAYS = 7`.
2. **Gate, server side, every path.** After the end, without a live paid subscription: refuse new
   work with a 402 `TRIAL_ENDED` (`remedy: SUBSCRIBE`, `trial_ended_at`) in `plan_admission`
   (documents, re-processing, assistant, workspaces), in `app/api/billing_write_gate.py` (the
   read-only write gate, so every write route refuses the same way), and in
   `app/workers/tenant_gate.unpaid_reason` (so queued jobs skip, like F-255). Reading, search,
   export, member management, deletion, checkout and the billing portal stay open.
3. **Subscribing lifts it.** A live paid subscription (`subscription_service.live_subscription_for_organization`)
   overrides the trial at once; the checkout already works for a Free organization.
4. **Screens.** A trial banner with the days left (from day 5); after the end, owners get a
   full-page "Your trial has ended; choose a plan" with `PlanSelector`, others "Ask <owner> to
   subscribe" (`useAskPlanOwners`). The plan-allowance read (`GET /workspaces/{id}/usage/plan-allowance`)
   should carry `trial_ends_at` so every screen reads one source.
5. **Emails.** Two days before the end and on the day it ends (session 3 owns the templates).
6. **Tests.** Proven by failing tests first: the clock per owner account (a second organization does
   not restart it), each refused path after the end, the worker skip, subscribing lifting it, and
   a browser journey. The e2e Free tenant P must be seeded inside its trial (or with a fixed clock)
   so the existing Free-plan specs keep testing the Free limits.
7. **Docs.** Regenerate `docs/hardening/TENANCY-AND-PLANS.md` once the trial is in the code
   (`backend/scripts/generate_tenancy_doc.py`), and mark N-052 built.

## For session 2 (documents, AI, engines, background jobs)

_Session 2 is finished (PR #20); nothing was left here._

## For session 3 (organization, identity and governance consoles, security)

Everything left for session 3, including what sessions 1 and 2 handed on below, is itemised in
`docs/hardening/CAMPAIGN-MAP.md` §3 (written 2026-10-12, before session 3 started).

## For session 4 (shell, experience, performance, operations, journeys, certification)

Everything left for session 4 is itemised in `docs/hardening/CAMPAIGN-MAP.md` §4, and the owner's
launch steps collected so far in §5.

## Session 1 → later sessions

Session 1 (tenancy, roles, plans, seats, billing, usage limits) fixed F-236 to F-255 and took the
product decisions N-040 to N-051 (NEEDS-OWNER.md, each marked `DECIDED (campaign session 1)`).
The generated source of truth for who a customer is, what each role and plan allows and how every
request resolves its organization and plan is `docs/hardening/TENANCY-AND-PLANS.md`
(regenerate with `python backend/scripts/generate_tenancy_doc.py`; a test fails when it drifts).

**Build on these (all sessions):**
- **Plans.** Free is deliberately small and charged at acceptance: 25 `document.upload`, 50
  `ocr.page` (reserved at upload, including documents still waiting for OCR), 30
  `assistant.message` a month, 10 MB files, 10 pages a document, 250 MB stored, one workspace,
  two seats, no API keys, webhooks, automations, batch or Business engines. One Free allowance per
  owner account (`quota_service.usage_pool`). Paid allowances are **per seat** (multiplied by the
  live subscription's seats). Plan limits are `limit.*` rows (`app/core/plan_limits.py`).
- **One admission point.** Every way a document enters goes through
  `app/services/plan_admission.py` (`admit_document`, `assert_reprocess_admitted`,
  `assert_workspace_available`, `admit_assistant_message`). A new intake path must call it; a
  refusal is a machine-readable 402 (`SPEND_LIMIT_EXCEEDED` / `PLAN_LIMIT_EXCEEDED` with `reason`,
  `limit_key`, `remedy`, `resets_at`).
- **New capability `capability.automations`** (Developer and up). The worker's automation handler
  and marketplace installs check it; a new automation entry point must too.
- **Seats.** Every way a person joins checks `seat_capacity_service` under the per-organization
  seat lock (take it before any invitation row lock). Owner, Admin and Billing buy seats
  (`PUT /organizations/{id}/billing/seats`, price shown first).
- **Worker gate.** `app/workers/tenant_gate.py` skips tenant-activity jobs for archived or
  suspended organizations and, now, for organizations read-only for non-payment
  (`BILLING_GATED_JOB_TYPES`). A new tenant job type belongs in `TENANT_ACTIVITY_JOB_TYPES`.
- **"Ask someone" names people.** `AskPlanOwners` / `useAskPlanOwners` (frontend) read the plan
  owners from the member-readable billing summary; use them instead of "ask an administrator".
- **Migrations.** Head is `s1b1_calendar_feed_org_member` (after `s1a1_upload_session_part_sizes`).
- **Seeds.** `seed_quota_tiers.py` and `seed_price_book.py --version auto` must be re-run on deploy
  (new tiers, the automations capability, Gemini overage rates); existing paid subscribers keep the
  version they bought (`--carry-forward` moves only to equal-or-better).

**For session 2 (documents, AI, engines, jobs):**
- Any new job type that does work for one tenant: add it to `TENANT_ACTIVITY_JOB_TYPES` (and it is
  then billing-gated too unless it is an export).
- Re-processing and packet splits already go through plan admission; a new engine that runs OCR or
  stores bytes must reserve through `plan_admission` rather than meter after the fact.
- Free-plan e2e tenant P is on Free: browser tests there only exercise refusals, never spend its
  allowance.

**For session 3 (consoles, identity, security):**
- `NoAccess` ("Contact an organization owner…") and `AccessRestricted` (`askWho` role names) still
  name roles, not people; `useAskPlanOwners` can supply names where the viewer is a member.
- Review-assignment and obligation ownership still require an explicit workspace grant (org
  owners/admins without one cannot be assigned); deliberate, but worth a product look.
- Rate limits are per IP and per API key; there is no per-tenant request limit for browser
  sessions (cost is bounded by the quotas). Decide whether one is needed.

**For session 4 (journeys, operations, certification):**
- **Owner actions before launch:** enable plan switching in the Stripe customer portal (N-050);
  publish yearly plan prices (N-051); re-run the seeds on deploy.
- F-256 (open, P3): late usage into an hour that had no earlier usage is not disclosed as late, so
  `test_late_usage_is_disclosed_rather_than_hidden` fails when it runs at minute 59. Reproduce by
  pinning that test's `now` to `datetime.now(timezone.utc).replace(minute=59, second=30) - timedelta(hours=1)`.
  The fix is in how rollup windows are sealed (a late event into an hour with no window should be
  disclosed too).
- Refunds are not modelled: a Stripe `charge.refunded` is recorded as "credit note not modelled",
  so invoices stay "paid" and RevOps revenue does not subtract refunds (Dodo, as merchant of
  record, owns refunds). Unverified how far this skews the revenue dashboard; needs a decision.
- Browser-suite isolation: a test that signs a shared persona out everywhere breaks other tests
  running as that persona in parallel. Session 1 changed `30-auth`'s "session ended elsewhere" to end
  only its own sign-in (`DELETE /auth/sessions/{sid}`); keep new tests to that pattern.
- The admin RevOps / COGS endpoints are proven to refuse tenants; their operator behaviour was not
  exercised end to end in session 1.

**Unfinished in session 1, and why:**
- Plan changes for paying customers go through the gateway's own portal (N-050); an in-app
  "change plan" that modifies the live subscription was not built, because it could not be
  verified without live gateway credentials.
- A second gateway subscription that somehow arrives anyway (e.g. completed from an old checkout
  tab opened before the first) still fails to record (one live subscription per account) and
  dead-letters; it is not refunded automatically. Rare after F-253; an alert and refund playbook
  would close it.

## Session 2 → later sessions

Session 2 (documents, AI, every engine, every background job) built the owner's one-week trial
(N-052, details N-053), fixed F-257 to F-271 (FINDINGS.md, session 2 section) and took decisions
N-053 to N-056 (NEEDS-OWNER.md, each `DECIDED (campaign session 2)`).

**Build on these (all sessions):**
- **The trial.** Free is a seven-day trial per owner account (`organizations.trial_ends_at`,
  migration `s2a1_free_trial_clock`, now the one head; `FREE_TRIAL_DAYS`). After it a Free
  organization is read-only: 402 `TRIAL_ENDED` (remedy `SUBSCRIBE`) from
  `app/services/trial_service.py`, enforced in `billing_write_gate`, `plan_admission` (every
  intake path, public links included) and the worker gate (`tenant_gate.unpaid_reason`).
  A new write path or intake path inherits it by going through those, as before. New hourly job
  `trial.reminders` (two emails). e2e tenants S (two days left) and T (ended).
- **Models and money (N-054).** The platform's own keys serve only GPT-OSS 20B and 120B; any other
  model runs on the organization's own key, and a platform call naming one is answered by the
  default (`app/core/ai_models.py`: `platform_safe`, `requires_own_key`). Costs are the suppliers'
  list prices. **Re-run `seed_price_book.py --version auto` and `seed_quota_tiers.py` on deploy**
  (supplier costs; Business 40,000 OCR pages and 100M input tokens a seat; Enterprise 300M/75M).
- **API keys (N-056, F-271).** Default deny: an API key may call only a route in
  `ROUTE_SCOPE_MAP` (`app/core/scopes.py`) or one declaring `RequireScope(...)`, checked centrally
  in `get_current_user`. **A new route meant for integrations must be added to the map**, or keys
  get 403.
- **Reprocess** (single and bulk) goes through `document_intake_service.queue_reprocess`: it locks
  the document, refuses while a read or enrichment job is live, resets the pipeline stage and
  queues a new run whose `run_id` gives enrichment its own metering scope
  (`llm_metering.enrichment_scope`). Anything else that re-runs a document should call it.
- **Worker.** A job's lease now starts when it starts (`claim.start_job`), a running job's lease is
  renewed by a heartbeat (`worker._LeaseKeeper`), settling is fenced to the worker holding the job,
  and a stopping worker hands back unstarted jobs. A new loop that runs jobs must use the same.
  Platform staff see the queue and the dead-letter queue at **/admin/jobs** and can retry a dead job.
- **Matching (N-055).** One case per invoice; later copies are listed on it.
- **Running the backend tests locally:** point the app at the test database too
  (`POSTGRES_DB=servabo_test pytest …`); otherwise code that opens its own `SessionLocal` (the
  worker gate) reads the development database and the trial worker tests fail.

**For session 3 (consoles, identity, security):**
- F-271 was found from the document side: scopes had been checked only where a route opted in.
  Worth the same look at the other non-human principals (partner portal tokens, SCIM tokens, the
  public gateway's own key check) to confirm each is limited to its routes.
- `GET /organizations/{id}/members` and invitations are now refused to API keys (no scope covers
  invitations; `members:read` covers the list). If an enterprise asks for user provisioning by
  key, that is SCIM's job, not a new scope.

**For session 4 (journeys, operations, performance, certification):**
- **Real-model spot-checks** (this sandbox has no Groq/Gemini key and cannot reach the Hugging Face
  hub, so the model stand-in and a local embedding model were used): with a real key, check
  prompt-injection resistance on the corpus's injection documents, line-item extraction on the
  invoices, and the GST invoice; with real PaddleOCR weights, the photographed and handwritten
  corpus pages; confirm Groq's and Google's current prices against `seed_price_book.py`.
- New browser spec `35-platform-jobs.spec.ts` (the e2e seed puts one dead job back on every run).
- Dormant handlers, not defects: `batch.expand_archive` (zip intake is not offered in the
  product) and `work_items.bulk` (the bulk API runs inline, up to 500 documents). Time a 500-document
  bulk delete behind the production proxy; if it nears the gateway timeout, move bulk delete onto
  the existing `work_items.bulk` job.
- The production build warns that the main chunk is over 1,000 kB (pre-existing); worth a
  code-split pass for first-load time.
- **Late fixes from the ledger push (F-272 to F-274).** Using every item action for real found
  three more: replaying a finished answer ended in a traceback (F-272); a document with line
  items could not be reviewed at all (F-273: lists are never part of a review decision now);
  a goods receipt naming one order was attached to another order's invoice (F-274). The review
  and matching specs (13, 24, 34) pass on the production bundle.
- **Ledger, session 2's slice:** 362 rows `deep`, 9 `blocked` (dormant handlers and the jobs that
  need gateway, warehouse, ERP or supplier credentials), 83 `smoke`, 18 `untested`. What is left:
  the pages and navigation items are proven to render live with the CSP but their journeys are
  yours; the ops crons (backups, PITR drills, watchdog, DR heartbeat) are yours; and these item
  actions still have only their refusals proven: assertions (rule detail, simulate, resolve,
  delete a clause check), case files (detail, remove a document, close, revoke a request),
  corroboration (refresh, review, page image, delete), extraction memory (edit a template or
  rule), packet splits (start, edit boundaries, reject), process proposals (detail, approve,
  reject, undo), redactions (page image, edit a region), an ERP target credential and a failed
  posting's retry, the public workflow trigger, analytics schedules. The pattern to copy is
  `backend/tests/engines/test_item_actions_*.py`; `docs/hardening/tools/coverage_from_engines.py`
  turns a test run's route log into ledger rows (engine tests: `ENGINE_ROUTE_LOG`; API tests:
  `API_ROUTE_LOG`).

## Campaign review before session 3 (2026-10-12)

Not a session: a review of the whole repository between sessions 2 and 3, so that sessions 3 and 4
cover what no prompt named. Its output is `docs/hardening/CAMPAIGN-MAP.md` (every open item with
its owner session, why, and how to close it) and `docs/hardening/tools/campaign_slices.py` (which
session owns each coverage row that is not `deep`; `--check <3|4|all>` is the finish line).

What later sessions must know:
- **CI runs on every pull request, and has been red on most runs since 2026-10-06** (F-275). Sessions
  1 and 2 read the commit status API, found nothing and wrote "no CI runs on this repo's PRs";
  Actions reports through check runs (`gh pr checks <number>`). A red pytest or browser job now
  names each failing test in an annotation and in the job summary
  (`.github/scripts/annotate_test_failures.py`). A session's pull request is ready only when CI is
  green on its last commit.
- `docs/hardening/tools/extract_endpoints.py` now mounts `document_evidence.py` and
  `document_fields.py` under `/work-items` and resolves an imported path constant (the review
  WebSocket's `v.WS_SUFFIX`), so its output matches the code: 621 operations, of which 4 have no
  ledger row yet.
- Re-running a session prompt after a cut-off: continue on the open pull request of that session
  (title starts "Campaign session 3" or "Campaign session 4"), not on a new branch from `main`;
  the unticked boxes in CAMPAIGN-MAP.md are where to resume.

## Session 3 → later sessions

Session 3 (organization, identity and governance consoles, settings truthfulness, security,
notifications and email) fixed F-276 to F-325 (FINDINGS.md, session 3 section; F-324 is recorded
as **unverified**, below), took decisions N-057 to N-068 (NEEDS-OWNER.md, each
`DECIDED (campaign session 3)`), wrote `SECURITY-REVIEW.md` and `SETTINGS-LEDGER.md`, and closed
every session 3 ledger row (`campaign_slices --check 3` exits 0; `branding.domain` is blocked with
its reason).

**Build on these (all sessions):**
- **Sign-in policy everywhere (N-057, F-276 to F-278).** "Require single sign-on", the IP
  allowlist and "require two-factor" (N-060, every plan) are enforced at sign-in, on refresh and on
  the live review WebSocket. The IP allowlist pins SSO sessions only; for password sessions the
  console shows it as unavailable. A new way to authenticate must go through the same policy check.
- **Identity after a downgrade (N-059, F-279 to F-282).** SCIM tokens and SSO provisioning stop
  when an organization leaves Enterprise, is read-only or archived. `idp_session_sync` is gone (N-058).
- **Notifications (N-062, F-287 to F-290).** Every notice appears in the app; billing and security
  notices are always emailed, others per the person's preferences (`/me/notification-preferences`).
  A new notice goes through `organization_notification_service.emit` with a category; plan-limit
  alerts at 80% and 100% are the `usage.limit_alerts` job.
- **Rate limits (N-061, F-286).** Signed-in traffic is limited per person, not per network address.
- **Egress (F-291).** Every outbound connection goes through `app/core/egress.py`; a structural
  test fails on a new raw client. An organization's lockdown and rules are enforced (live test).
- **Audit (F-294, F-295, F-304, N-067).** Identity and webhook changes are audited. The nightly
  ARCH-07 sweep deletes audit entries per organization by its own retention period (blank keeps
  them). **On deploy:** the four host crons installed (session 4, F-355: the sweep deletes through
  the application's database unless `AUDIT_SWEEPER_DATABASE_URL` names a separate login; before,
  it skipped or was refused by the audit trigger every night)
  (`backend/deploy/cron.d/servabo-sweepers`: arch07, arch09, identity, invitations).
- **Display layer (N-064, F-298).** One module per side: `frontend/src/utils/displayTime.ts` and
  `backend/app/core/display_format.py`. The person's own zone and language win; the open
  workspace's clock and date format stand in. `npm run check:self` ("one display layer") fails on
  a stray `Intl.DateTimeFormat`. A change to the workspace clock or date format re-renders the
  workspace's pages; pages keep their place through the address (the settings page writes
  `?section=`, F-322).
- **Workspace regional settings (N-068, F-320, F-321).** `app/schemas/regional.py` checks time zone,
  currency, date format and language on workspace and organization creation and update. Rows saved
  before F-320 are not migrated: **check once on deploy** that no workspace holds a value outside
  those checks (one SQL query; the page accepts any value the browser can use).
- **Brand colours (N-065, F-300)** reach the sign-in pages and the app on a verified domain
  (`frontend/src/utils/brandTheme.ts`); **data residency (N-066, F-301)** states what the region
  pins, kept equal to the code by a structural test.
- **Rules from events.** An event meant for workflow rules must be written with
  `outbox_service.emit_trigger` (event and `automation.execute` job together). `emit_internal`
  alone reaches no rule; that is how the public API's trigger did nothing (F-323).
- **People, not IDs.** Access screens and the erasure form name people (F-325). Anything new that
  asks an administrator to choose a person should offer a picker from the member list
  (`include_inactive=true` for former members), never a raw ID.
- **Partners.** A partner is created with its first owner (`owner_user_id`, F-310); a
  revenue-share agreement is ended with `POST /partners/{id}/agreements/{agreement_id}/end` (F-309);
  a suspended partner's portal is read-only (F-319).

**For session 4:**
- **F-324 (unverified, verify first).** With multi-agent verification on, a document's "Document
  processed" rules may be skipped for good when the engine job runs while the verify job is
  mid-flight: the verify job commits a PENDING record before calling the agents, the engine skips
  rules while one is pending, and the agents' release event is written with `emit_internal` and no
  engine job (the human-review path re-queues it; this path does not). Not reproduced in tests; a
  fix must not run rules twice (runs are de-duplicated per rule and event, not per document).
  `test_verified_documents_run_their_rules_live.py` pins "exactly once" for the ordering that works.
- **`/no-access`** is registered and now tested by address, but nothing routes there; the guards
  handle suspended and archived tenants inline (`16-lifecycle`). Wire it to `TENANT_SUSPENDED` or
  remove it.
- **Browser-test re-runs on one database.** On a reused local e2e database, `22` and `23` fail on
  leftover "rescan" documents from earlier runs; CI (fresh database) passes. Make them re-runnable.
- **Unproven settings** (SETTINGS-LEDGER "Still unproven"): the assistant's temperature, dispatch
  tagging off, extraction memory off, SLA at-risk and alerts, agent policy fields, procurement
  tolerances, conversation retention.
- **Legal name** reaches the payment provider only when the customer is first created; later edits
  do not (SETTINGS-LEDGER). Decide: push updates, or say so on the page.
- **Dead or partial:** the `EmailSettings` table is read by nothing; platform staff have no screen
  for a partner's status or agreements (API only); the organization identifier cannot be changed
  anywhere (the page says so, F-308; offering a rename is a product choice with redirects to build).
- **Consistency nits:** OIDC configuration errors answer 400 where SAML answers 422; Unit economics
  says "0 events" where suppression would read the same; RevOps does not list promo redemptions;
  the Developer "Issue key" dialog has no `role="dialog"`; BYOK "Retire" has no confirmation.
- **`branding.domain` (blocked):** the claim/verify screens need a real DNS zone; worth one check on
  a staging domain before launch. Every route they call is live-tested.
- **Docs:** CONFIGURATION.md drifts from the settings when regenerated; the Tailwind 4 move and the
  main chunk's size are still in the map.
- **Running tests locally:** never run two pytest sessions at once (the conftest truncates the
  test database at start); after a backend change restart the e2e API (`kill` the pid in
  `/tmp/servabo-e2e-logs/pids/api.pid`, then `E2E_LLM=1 frontend/e2e/scripts/start-stack.sh`)
  before running browser specs.

## Session 4 → later sessions

Session 4 (experience, performance, operations, launch certification; then, at the owner's
request, TruthMesh, Batch Operations and Document Packs in depth) fixed F-324 to F-409 (FINDINGS.md,
session 4 sections), took decisions N-069 to N-077 (NEEDS-OWNER.md, each
`DECIDED (campaign session 4)`), and closed every ledger row (`campaign_slices --check all` exits 0).
**What is left is listed, with instructions, in `docs/hardening/NEXT-SESSION-PROMPT.md`** — paste it
into a new Claude Code session to continue.

**Build on these (all sessions):**
- **Browser tests are the proof for screens.** The suite (`frontend/e2e/tests`, 58 files, 811 tests) runs
  in CI against the production bundle with the worker on; it is a required check. New since this
  session: every page at four widths (74), every page in light and dark through axe-core (72), the
  first run (73), TruthMesh (75), batch operations (76) and document packs (77) in depth, each on a
  tenant of its own so they never race the shared seeded tenants.
- **No database work on the event loop.** An `async def` route must hand database work to the
  threadpool and reload expired objects there (F-218, F-363); a test fails on a query run on the loop.
- **Mesh writes are serialized per workspace (F-382).** Anything that writes TruthMesh rows takes
  `truthmesh.service.lock_workspace` first.
- **Uploaded archives are hostile (F-390, F-407).** Package verification caps what it reads and
  turns every unreadable entry into a verdict; any new upload parser needs the same.
- **Encryption-key rotation covers every secret column (F-370).** A new `*_encrypted` or
  `*_ciphertext` column fails a test until the rotation sweep covers it.
- **Emails:** every transactional email uses `BASE_EMAIL_HTML_LAYOUT` (F-380); a new one must pass
  `test_emails_render_in_mail_clients.py`.
- **Say what a feature does.** Document packs today apply their field list only (N-075, F-408);
  PRODUCT-NEXT item 10 wires the rest.

**Known, not done (details and order in NEXT-SESSION-PROMPT.md):** the audit's unverified TruthMesh,
batch and pack items (FINDINGS.md, "Session 4 (continued) — … unverified"); N-076 and N-077 to build;
32 features whose browser coverage is partial (the coverage-gap table in the prompt file); Tailwind 4
and least-privilege database roles (N-074).

## Flagship session → website and payments session

The flagship session built **Helm** (docs/helm/ARCHITECTURE.md is the design, kept current;
docs/helm/MANDATES.md lists the mandates in plain words; docs/product/FLAGSHIP.md is the product
story for the website). Its decisions are N-082 to N-102 in NEEDS-OWNER.md (`DECIDED (owner and
planning chat, 2026-10-15)` or `DECIDED (flagship session)`); its defects are in FINDINGS.md under
"Flagship session". Migrations `h1a1_helm`, `h1a2_helm_bank`, `h1a3_helm_reconcile`, `h1a4_helm_api_vocabulary` (one head).

**For the website and payments session:**
- **Plans and copy.** The plan cards already list Helm (`frontend/src/constants/planEntitlements.ts`:
  `capability.helm`, `limit.helm_mandates`, `limit.helm_backtest_months` and the Enterprise
  capabilities). Prices did not change (N-082). Use FLAGSHIP.md for the website's Helm page and its
  "what we never claim" list; screenshots come from the sample company (Meridian Wholesale), which
  any account can build from Helm → Start and delete afterwards.
- **The rename to Servabo.** No new "Servabo" strings were added; Helm's own strings say "Helm".
  The sample company's documents name only invented companies.
- **Payments stay out of Helm.** Helm never moves money (N-088): the payment run is a list a person
  pays from their bank, and bank statement imports bring the evidence back. Nothing in the payment
  gateway work should change that.
- **Mail.** Helm sends through the organization's transactional sender ladder: the Monday briefing,
  receivables reminders, compliance-document requests, disputes and supplier reconciliations (the
  last two only in Act mode with a known contact). A new branded email layout must keep
  `test_emails_render_in_mail_clients.py` green; Helm's notices now carry an "Open Helm" button
  (`organization_notification_service.APP_ACTIONS`).
- **Performance.** ARCHITECTURE §13 has the budget measured at 1,000 and 10,000 documents
  (`tests/performance/test_helm_budgets.py`; `HELM_PERF_DOCUMENTS=10000` reruns the large one).
  One item is over budget: the ledger update after one document change takes 2.9 s at 10,000
  documents in a workspace (budget 1 s; within it up to about 2,000). Nobody waits on it (it runs in
  the worker, debounced), but the next step is a truly incremental ledger: today
  `ledger_store.rebuild_workspace` re-projects the whole workspace; instead re-project only the
  promises of the changed document, its counterparty and the bank lines that can match it
  (`lines_by_amount` already narrows them), and keep the full rebuild as the nightly check that the
  two agree.

- **API keys and webhooks.** Enterprise keys reach Helm with `helm:read` / `helm:write`; approving and
  Helm's rules stay with people (N-102). A key now works only in the organization that issued it
  (F-435): if the developer portal shows keys across organizations, it must keep to that.

**Build on these:**
- Every Helm decision is deterministic code in `backend/app/services/helm/`; the only model call
  drafts a mandate from a sentence (`drafting.py`, metered under `llm:helm:`).
- A bank statement is evidence only when a bank issued it: `ledger.statement_kind` keeps a
  supplier's statement of account out of payments and cash.
- Matching a payment to an invoice (bank imports and statement documents alike) uses one rule set,
  `bank_match.mentions_document` and `mentions_payee`: a whole invoice number, or every distinctive
  word of the payee; never one shared word.

## Website and payments session → next sessions

This session (branch `claude/new-session-3qnrpb`, PR #25) renamed the product to **Servabo**, built
the public website in `website/` and joined it to the app, and made **Dodo Payments** the real
payment gateway. Its decisions are in NEEDS-OWNER.md as `DECIDED (website and payments session)`
(and the owner's own as `DECIDED (owner, planning chat, 2026-10-15)`); its defects are in
FINDINGS.md under "Website and payments session". Migrations `w1a1_servabo_database_names`,
`w1a2_billing_disputes`, `w1a3_scheduled_plan_change`, `w1a4_hold_notices` (one head).

**What changed (build on these):**
- **Name.** Everything people see says Servabo. History files (FINDINGS, NEEDS-OWNER, STATE,
  CHANGELOG entries before 2026-10-16) keep the old name; `backend/tests/core/test_the_old_name_is_gone.py`
  fails when the old name appears anywhere else outside its allowlist. The old-prefix settings, `fp_live_`/
  `fp_test_` API keys and the `--loop stripe` / `worker-stripe` names still work **for one release**
  with a start-up warning; remove those aliases in the next release (`app/core/legacy_names.py`,
  `api_key_secret.LEGACY_PREFIX`, `app/worker.py` `LOOP_ALIASES`, `app/db/session.py` `ROLE_ALIASES`).
- **Renamed protocol identifiers** (each breaks once for an existing integration; the table with
  old and new values is in CHANGELOG.md, the rename entry of 2026-10-16): the outgoing webhook
  signature and delivery headers (`X-Servabo-*`), User-Agent strings, the API version and spend-limit
  headers, the domain-verification TXT value and record names (`servabo-site-verification`,
  `_servabo.`, `_servabo-challenge.`), the live-review WebSocket subprotocol (`servabo.review.v1`), the
  refresh cookie (`servabo_refresh`: everyone signs in once more), API key prefixes (`svb_live_`,
  `svb_test_`), browser storage keys and the sovereign licence format (`servabo-licence/1`).
- **Website.** `website/` (Astro, static) with home, Helm, product, four solutions, pricing, security,
  about, contact and the legal pages; its prices come from `backend/scripts/export_public_pricing.py`
  (`website/src/data/pricing.json`, checked in CI), so the site and the app cannot disagree. Deploy:
  `docs/website/DEPLOY.md`. The app's `/pricing`, `/terms` and `/privacy` now redirect to it
  (`WEBSITE_URL` / `VITE_WEBSITE_URL`); emails carry its legal links. CI job `website`.
- **Dodo is the default gateway** (`BILLING_GATEWAY=DODO`). Everything Servabo calls and receives is
  in `docs/billing/DODO.md`. Checkout returns wait for the webhook; Dodo payments become invoices
  issued by Dodo with a download; refunds and disputes are recorded (a lost dispute makes the
  organization read-only until a later payment or the operator lifts it, RevOps → Disputes); plan
  changes happen on Servabo's Billing page with Dodo's own quoted amount (upgrades now, downgrades at
  the renewal, `billing.plan_changes`); a held renewal sends a reminder, a final notice and the
  read-only notice (`billing.hold_notices`); customer details are sent to the Dodo customer; yearly
  plans appear when their products are configured; the margin console counts Dodo's fees; every paid
  plan keeps at least 55% after fees at its ceilings (Enterprise pages per seat 95,000).
- **Usage on Dodo is hard limits.** Dodo cannot bill usage lines, so overage is refused, never billed
  (the plan cards and usage page say so). Usage billing is a product decision for later (NEEDS-OWNER).
- **Tests.** The stand-in Dodo is `backend/tests/fakes/fake_dodo.py` (API, checkout page, customer
  portal, Standard Webhooks signing). The browser suite bills through it by default
  (`E2E_GATEWAY=dodo`); CI also runs the customer journeys on Stripe. New journey 68 covers upgrade,
  invoice download, scheduled downgrade, refund and cancellation on Dodo.
  `tests/engines/test_dodo_concurrent_deliveries_live.py` delivers one subscription's whole life
  twice, at once, to a real server with four reconciling workers.
- **The database keeps historical names** (`stripe_inbound_events` holds Dodo events too, etc.;
  DODO.md §7). Do not rename them without a reason a customer would notice.

**Not yet verified against a real Dodo account** (everything was built from Dodo's documentation
and proven against the stand-in): the ten points in DODO.md §6 — the payment's `refunds`/`disputes`
fields, change-plan's body and `do_not_bill`, the preview amount equalling the charge, metadata after
a plan change, the return URL's parameters, the products list's paging, how live and test keys
differ, Dodo's own retry window, the webhook body's timestamp and the fee figures. The first session
with a Dodo test account should run `scripts/dodo_setup.py`, one checkout, one upgrade, one
downgrade, one refund and one card decline (Dodo's test cards), and compare with DODO.md.

**What is left:**
- Remove the one-release aliases (above) in the next release.
- Usage billing on Dodo (if the owner wants overage billed rather than refused): Dodo's usage-based
  billing or add-on quantities; a product decision first.
- Real Dodo test-account verification (above) and Dodo's account verification (KYC; the website must
  be online with pricing, terms, refund policy and contact).
- The ledger performance item from the flagship section is unchanged.

## Helm visual session → next sessions

_2026-10-17. Branch `claude/beautiful-dijkstra-yvlspo`, PR sabarishwarne2001/servabo#26._

**What changed.** Helm wears Night Bridge on every page (`docs/helm/VISUAL.md`), the Documents | Helm
switch glides and reveals Helm with a circle from the switch, Documents wears its own calm look (Lumen),
and the website's Helm page and every screenshot were redone. Decisions N-111 to N-116; findings F-462
to F-468.

**How to see it locally.** `.\start_dev.ps1` (or `./start_dev.sh`), sign in, open the sample company
from Helm's Start page (or press Helm in the header), then press Documents and Helm again to see the
switch. Try both themes (the sun/moon button) and a phone width.

**Keep in mind.**
- Read `docs/helm/VISUAL.md` before touching a Helm page. Use the classes and `components/helm/ui/`;
  every number on screen must come from the data (leave a badge out rather than invent it).
- Helm money goes through `formatHelmMoney` / `formatHelmMoneyCompact` (`components/helm/money.ts`);
  never `formatMoneyMicros` directly in Helm.
- The switch starts its own view transition (N-114). If the routes are ever moved to a data-router
  route tree, React Router's `viewTransition` option would work and the switch could use it instead.
- The entrance animations are short so axe never sees text mid-fade; keep them under a second.
- The website's CSP forbids inline styles and `data:` images: no `style=` in `.astro` pages, and the
  Helm page has no grain layer. Its switch demo is `public/helm-switch-demo.js` plus CSS in
  `website/src/styles/global.css`.
- Bundle: Helm's lazy chunks grew from 58.2 kB to the figure in STATE.md (gzipped), inside the 35 kB
  allowance; no new runtime dependency.

**Seen, not fixed (pre-existing).** Spec 34 leaves a rescanned copy of Tenant C's INV-E2E-1001 in
the workspace, so spec 22's "a filtered list pages over the matches only" finds 3 rows instead of 2
when it runs after 34 on the same database (a partial re-run). In a full run 22 comes first and
passes; a fresh database also passes. Spec 34 should delete its copy at the end.

**Not done / for later.** The Plan page's what-if is still the cockpit's panel (not a drawer of its
own); the template gallery's sheen is the shared panel hover. Findings F-465 to F-468 are fixed but proven
by screenshots only.

## Session B → next sessions

_2026-10-18. Branch `claude/new-session-zo5d98`, PR sabarishwarne2001/servabo#27. Decisions N-118 to N-124;
findings F-469 to F-499._

**What changed.**
- *The old name is gone for good (N-121).* No old-name setting, API key prefix, backup name, `--loop
  stripe`/`worker-stripe` alias, Docker-volume shim or `legacy_names.py` is left (N-121 lists them); the guard test allows the old
  name only in history files and in the secret values the production guard refuses. Operators use the
  `SERVABO_*` names (CHANGELOG). The README's data section is two lines; the dev compose file listens on
  127.0.0.1 only (N-123).
- *The carried-over defects (NEXT-SESSION-PROMPT Tasks 1–3 and 4b)*: batch operations, TruthMesh (including
  a GDPR gap: erased people's documents stayed in the mesh, F-485), document packs (the F-400 PAN card
  phrase, migration `b1a1`), the N-077 rules, the session-3 leftovers, and the deterministic first-run
  catalog. Every API list endpoint now bounds its `offset` (a test over the API's own schema keeps it so).
- *Helm's ledger is incremental (N-122, F-498).* A document change re-projects that document and what depends
  on it: 4.07 s → 0.70 s at 10,000 documents. The nightly rebuild checks the incremental updates and raises
  an operator alert (`HELM_LEDGER_DRIFT`) when they differ. Design in `docs/helm/ARCHITECTURE.md` §4.5.

**Session C: Task 4 of NEXT-SESSION-PROMPT (browser-test gaps) is yours.** Tasks 1–3 and 4b are done.
Task 5 is deferred (N-124: Tailwind 4 is N-119, least-privilege database roles N-120).

**Keep in mind (Helm's ledger).**
- *Anything that changes what the ledger reads must be marked.* ORM writes to documents, roles,
  verifications, field corrections, payments (settlements), obligations and procurement cases are marked
  automatically (`app/models/helm_dirty.py`). A write that bypasses the ORM (a Core `update()`/`delete()`,
  an `INSERT … ON CONFLICT`) is not seen: call `helm_dirty.mark(db.connection(), workspace_id, [ids], reason)`
  (or `mark_obligations_of`) next to it, as `role_service` and the obligation deletes do. If you forget, the
  nightly check finds it, repairs it and tells the operator (the alert lists example promises).
- A change that every promise depends on (who we are, date format, currency, price tolerance, which books
  read the workspace) is `request_full`; the next update is a full rebuild.
- `tests/services/helm/test_ledger_incremental_equivalence.py` is the safety net: change what the ledger
  reads, then run it wide, `HELM_EQUIVALENCE_SEEDS=200 HELM_EQUIVALENCE_STEPS=40 pytest …` (about 3 s a
  seed). 300 seeds of 40 changes passed when this was written.
- The first update of each day is a full rebuild (statuses depend on today); the first update after a
  worker restart reads the long bank statements again (they are kept in memory afterwards).
- The job after an update also runs `value.sweep`, which reads every payable promise of the book: about
  0.5 s of the 0.7 s at 10,000 documents. It is the next thing to make incremental if the budget is tightened.

**Seen, not fixed.** When two live procurement cases disagree about a purchase order line's price (the order
was edited between them), the ledger now uses the latest scoring (F-499), but nothing tells a person that
the cases disagree; re-scoring the older case would settle it.

## Session F → next sessions

_2026-10-19. Branch `claude/new-session-5oe22r`, PR #31. Finding F-524 to F-526; decisions N-131 (closed: not now), N-135 to N-140. Migration `g1a1_gst_credit` (one head)._

**What changed.** (1) The production extraction prompt now asks a model for every field the product reads (F-524).
(2) **GST Credit**: import a GSTR-2B (JSON, or a zip of it), match it one-to-one with the purchase invoices Servabo has
read, six figures, a supplier list, an invoice list with the books beside GSTR-2B, IMS recommendations, the 180-day
exposure, an Excel export and a supplier reminder; Documents → GST credit. A preview on every plan, everything on
Business and Enterprise, the sample company's own GSTR-2B with planted cases. (3) **Helm** learned GST: the 180th day is
a law deadline next to the MSME one, and "hold until reported" is an optional mandate that never makes a payment late;
the Guard asks a person before paying an invoice the supplier has not reported; Helm drafts a request to the supplier.
(4) The website has `/gst-credit`. (5) Enterprise: GST credit across every workspace (page, API, `gst:read` key scope).
(6) Stretch: the e-invoice QR code is read during processing (IRN etc.).

**Session D (now Final session 2) must also check, with the owner's help.** (a) **A real GST invoice through the new extraction schema**
with the real model (F-524, N-138): every invoice field Helm and GST Credit read, in particular `vendor_gstin`,
`buyer_gstin`, the tax heads and the IRN. (b) **A real GSTR-2B JSON** from the GST portal, if the owner or the CA can get
one: the parser follows the documented layout and the fixtures are invented; anything unexpected is reported in words on
import and never dropped silently. (c) A real e-invoice PDF and NIC's public key (N-140).

**Unverified (say so to customers).** The GSTR-2B file layout against a real download; the wording of Section 16(2)(aa),
16(4), the second proviso, Rule 37 and the IMS tutorial (the official pages could not be opened from the build sandbox;
each statement cites its section and an official link, "not tax advice"); the IMS "Pending" limits from October 2025 are
not stated; the `rsn` reason codes are shown as given; the 180-day figure counts only payments Servabo knows about; the
e-invoice QR payload layout and signature (no NIC key); a real model on a real GST invoice.

**What is left, in order of value.** The QR provenance is not shown on the document screen. The Helm UI shows the new
mandates through its generic mandate cards only (no GST-specific copy beyond the readback). The organization page is
computed on demand (N-139): store it if a GSTIN has tens of thousands of invoices. "Flag dispute" with its reason covers
rejection (N-131); case notes and a Reject status wait for a customer to ask. Tally and Zoho Books posting of GST fields is
unchanged.

**For whoever runs the suites here.** Browser specs 105 (workspace page; ran three times in a row) and 106 (all
workspaces) need the stack from `frontend/e2e/scripts/start-stack.sh`; both read real PDFs through the worker with the
model stand-in. The website's screenshots (`gst-credit-*`) come from `website/scripts/capture-screenshots.mjs`.
`qrcode` is a dev-only dependency (generated QR images in tests).

## Session E → next sessions

_2026-10-18. Branch `claude/funny-sagan-n7gpqc`. Findings F-518 to F-523; decisions N-131 to N-134._

**What changed.** An owner can now see and remove saved SSO role mappings; the three-way match page shows why
a case was approved or disputed and can re-score it (a re-score keeps the case when nothing it reads has
changed, and replaces it otherwise); supplier-cost "Reconcile" offers "Reconcile anyway" after the
period-not-closed refusal; a correct password for an SSO-only organization is refused at sign-in instead of
opening a useless session (only when no organization of the person would accept it); the last-workspace
archive refusal is a 409; the residency card no longer lists a region that Save would refuse.

**Needs you.** N-131: the API has no "Reject" and no case notes (the Session C list said it had). Building them
is a product decision (a new final status that ERP posting, the ledger and automation must learn).

**Not changed on purpose.** The process agent's Undo still needs a fitted model (N-133). Spec 94's INR price book
still stays in force; the rule for specs is in `frontend/e2e/README.md` (N-134).

**For whoever runs the suites here.** The sandbox needs Python 3.12 (the pinned libraries do not run on 3.13),
pgvector 0.8 built from source, and `FRONTEND_URL=http://localhost:3000` in `backend/.env` for the SSO specs.

## Session C → next sessions

_2026-10-18. Branch `claude/new-session-janwly`, draft PR sabarishwarne2001/servabo#28. Decisions N-125 to
N-130; findings F-500 to F-517._

**What changed.**
- *Browser specs 86 to 104* press the buttons no browser test had pressed (ERP posting, payment risk and
  anomalies, legal holds, sessions and single sign-on, Entity 360, seats, review hub decisions, tables,
  RevOps money actions, account security, procurement, credential rotation, automation / clause checks /
  obligations, residency and egress, exception agent / partner marketplace / identity credentials,
  documents bulk and workspace, connection tests, upload tray, Sync now and licence). Each runs on a tenant
  of its own, checks the page and the API (or a reload), and was run three times in a row without retries.
- *Eighteen defects found by those specs were fixed test-first* (F-500 to F-517; F-507 is unverified: seen
  once, a timing race). The serious ones: a second workspace could see and release another workspace's
  legal holds (F-501); the assistant page's upload box refused every file (F-514); an owner could save only
  one role mapping per identity connection (F-504); a partner's sample workflow could not be installed by
  anyone (F-517); sign-out added a stale `?redirect=` (F-506).
- *The Dodo check kit (C2)* is built and proven against `fake_dodo.py`: `backend/scripts/dodo_probe.py`
  (read-only), `backend/scripts/dodo_relay.py`, `start_dev.ps1 -DodoWebhooks` / `start_dev.sh --dodo-webhooks`,
  and `docs/billing/DODO-LOCAL-TEST.md`. **It has never talked to Dodo.** Every Dodo point in DODO.md §6 stays
  "not confirmed" until Session D (below; now Final session 2, `docs/sessions/FINAL-2-LIVE.md`).

**Session D (now Final session 2): what to run, exactly** (needs the owner's PC, a Dodo *test-mode* account and its keys; never a
live key). Follow `docs/billing/DODO-LOCAL-TEST.md` from the top:
1. Test mode on; put the test API key and webhook key in `backend/.env` (§1–2).
2. `cd backend; .\.venv\Scripts\python.exe scripts\dodo_setup.py --create-test-products`, paste the eight
   `GATEWAY_PRICE_ID_…` / `DODO_ADDON_PRODUCT_…` lines into `.env`, then `scripts\dodo_setup.py` until every line says `OK` (§3).
3. `.\start_dev.ps1 -Stop; .\start_dev.ps1` (§4), then `.\start_dev.ps1 -Stop; .\start_dev.ps1 -DodoWebhooks` (§5).
4. Walk journeys A to E in the browser (§6).
5. `scripts\dodo_probe.py`, then with `--subscription-id sub_… --after-plan-change --payment-id pay_…`, once
   more with the refunded payment, and with `--webhook-file` for one saved webhook body (§7).
6. Fill the results table (§8). Move each confirmed point out of "not yet confirmed" in DODO.md §6, describe
   each difference, fix what differs (test-first), and tick step 9 of the owner launch checklist below.

**Not driven in a browser (and why).** OIDC client-secret rotation (the feature does not exist); the
organization-email "Send test" and the document-settings "Test" (need a mail server / a configured model
provider; the stand-ins do not cover them); a *successful* residency repin (local file storage refuses any
region but the default, N-130; needs MinIO/S3); installing a *valid* sovereign licence (it is global
state, so it would affect every parallel test); the nightly learning pass (spec 98 runs the operator script
instead); the identifier merge through a GSTIN (the model stand-in never extracts one).

## Owner launch checklist

Only you can do these. Do them in this order; each step says what you need, where to click and how
you know it worked. Nothing here needs code changes. Rewritten in the website and payments session
(2026-10-17) for Servabo, the website and Dodo Payments. Tick them in a copy of this file.

**Before you start these:** run the final sessions (`docs/FINAL-SESSIONS.md`). Final session 2B (live) proves on your PC
what can be proven without a server: step 9's test-mode part, step 12's real-model spot checks, the CPU-only image build and a
backup and restore rehearsal; it ticks them here. `backend/scripts/preflight.py` (from Final session 1) tells you, on the server,
which settings are still missing.

**Step 1 — Rotate every key that was ever pasted into a chat or committed.**
SECURITY-REVIEW.md lists them. In each provider's dashboard create a new key and delete the old
one. *Done when:* every old key is deleted (the provider shows it as revoked).

**Step 2 — Buy the domain and add it to Cloudflare.**
Buy `servabo.app` (or your choice) at Cloudflare Registrar, or move an existing domain's DNS to
Cloudflare (free plan). You will create two addresses: `servabo.app` for the website and
`app.servabo.app` for the app. *Done when:* the domain shows "Active" in Cloudflare.

**Step 3 — Put the website online (about 15 minutes).**
Follow `docs/website/DEPLOY.md`, Option A (Cloudflare Pages). Set `PUBLIC_CONTACT_EMAIL`; leave the
phone number empty unless you want it public (never commit it). *Done when:* `https://servabo.app`
opens and its Pricing, Terms, Privacy and Refunds pages load. Have a lawyer read the terms, privacy
and refund pages before the first paying customer (N-029, N-073).

**Step 4 — Apply to Dodo Payments.**
Sign up at dodopayments.com. Verification asks for your ID and a selfie, your bank account (in your
own name) and your website: it must be online first (step 3). It takes 1–3 working days. Meanwhile
everything below works in **Test Mode**. *Done when:* Dodo's dashboard shows your business verified.

**Step 5 — Email, AI and alerts accounts.**
- **Postmark** (N-027): create a server, add the SPF and DKIM records it shows you in Cloudflare
  DNS, and a sender signature for `no-reply@servabo.app`. Keep its SMTP host and token for step 7.
- **Groq**: create an API key at console.groq.com/keys. Check the model prices in
  `backend/scripts/seed_price_book.py` against Groq's price page (N-054).
- **Cloudflare R2** (decided: EU jurisdiction): create a bucket with "EU" jurisdiction and an API
  token for it, for customers' documents.
*Done when:* you have the Postmark token, the Groq key and the R2 bucket name, endpoint and keys in
your password manager.

**Step 6 — Rent the server (Hetzner, decided).**
4 vCPU, 16 GB RAM, 160 GB disk, Ubuntu 24.04 (COSTS.md has the current price). In Cloudflare DNS add
an **A record** `app` → the server's IP address, **DNS only** (grey cloud), **before** the first
start, so the app can get its HTTPS certificate. *Done when:* `ping app.servabo.app` answers from
your server's address.

**Step 7 — Install Servabo on the server.**
Follow RUNBOOK §9.2 steps 1 to 7 exactly: the user and folders, the code, `.env.production` from the
template (secrets generated with the commands shown; Postmark, Groq, R2 from step 5;
`OPERATOR_ALERT_EMAILS` = your own address; `FRONTEND_URL=https://app.servabo.app`,
`WEBSITE_URL=https://servabo.app`; Dodo's **test** API key and `DODO_LIVEMODE=false`), the build, the
migrations and the start. **Before the first start, and after every change of settings, run**
`docker compose ... run --rm web python scripts/preflight.py` (RUNBOOK §9.14): it prints OK, MISSING, WRONG or SKIPPED for every setting with
the one-line fix and where to click, never a secret, and says READY or NOT READY. Add `--online` for read-only checks of the database, Redis,
the R2 bucket, the mail login, Groq and Dodo, and `--send-test-email you@yourcompany.com` to send exactly one message.
*Done when:* preflight says READY and `https://app.servabo.app/api/v1/health/ready` says ready.

**Step 8 — Create the plans in Dodo (test mode) and publish them.**
RUNBOOK §9.2 step 8: `dodo_setup.py --create-test-products` creates the **fifteen** products (Final session 2A, N-187):
ten plan products (Starter, Business and Enterprise in dollars and in rupees, monthly and yearly; Enterprise monthly only)
and five add-on products (GST Credit in both currencies, monthly and yearly; warehouse sync in dollars) and prints fifteen
lines for `.env.production`; then `dodo_setup.py` must say OK for all fifteen; then the two seed commands and the first
administrator. *Done when:* signed in as a new user whose workspace is in India's time zone, the Billing page opens in
rupees and shows Starter ₹1,499, Business ₹4,999 and Enterprise ₹14,999 per user; switching the currency shows $49,
$299 and $799.

**Step 9 — Connect Dodo's webhooks and buy a plan with a test card.**
RUNBOOK §9.2 step 9: add the webhook endpoint in Dodo (Test Mode), put its secret in
`DODO_WEBHOOK_SECRET`, restart. Then, as a new customer, buy Starter with Dodo's test card, and once more **in rupees**
with Dodo's test UPI id (`success@upi`) or Indian test card, giving a GSTIN at checkout: check that Dodo's invoice shows
that GSTIN and the CGST and SGST (or IGST) lines (N-193).
*Done when:* back in Servabo the page says "Payment confirmed", Billing shows the plan and the
invoice "issued by Dodo Payments", and its "Download invoice" opens Dodo's PDF. Also try: upgrade to
Business (the amount shown is what is charged), a refund from Dodo's dashboard (the invoice says
"Refunded"), and cancelling in "Manage payment method" (Billing says the plan ends at the period's
end). Compare what you see with `docs/billing/DODO.md` §6 and note anything different. On your own PC,
`docs/billing/DODO-LOCAL-TEST.md` walks through all of this with a read-only probe and a results table.

**Step 10 — Backups, scheduled jobs and monitoring (same day as step 7).**
RUNBOOK §9.4 and §9.6: create `/etc/servabo/backup.key` and copy it into your password manager
**now**; set `SERVABO_BACKUP_MIRROR_CMD` to copy backups to another provider; install the sweeper
cron files with `sudo /srv/servabo/backend/deploy/bin/servabo-install-host-jobs` (Final session 2A: it checks cron is
running, installs the files, and proves each job can report to the app; set `SAFETY_JOB_REPORT_TOKEN` to the same value
in `.env.production` and `/etc/servabo/sweepers.env` first); create the free Healthchecks.io checks (uptime, backup,
restore drill, retention sweep) and set `ALERT_WEBHOOK`. Run one backup and one restore drill by hand. Then **stop cron
on purpose** (`sudo systemctl stop cron`) and wait: the next day an email "Safety job stopped" (or "never reported")
arrives at `OPERATOR_ALERT_EMAILS`, Platform admin, Background jobs, shows the jobs in red, and
`/api/v1/health/ready` says `"safety_jobs": "degraded"` while the site stays up. Start cron again
(`sudo systemctl start cron`). *Done when:* the install prints "Ready", the drill prints its restore time, every
Healthchecks.io check is green, and the stopped-cron email arrived and cleared after cron restarted.

**Step 11 — Go live with Dodo.**
Only after step 4 says verified and step 9 worked. In Dodo, switch off Test Mode, create the same
fifteen products in live mode (same prices and currencies: plan products per seat, recurring, tax not included), a
live webhook endpoint (same URL) and a live API key. In `.env.production`: the live key, the live
webhook secret, the fifteen live product ids, `DODO_LIVEMODE=true`; restart, and run the seed commands
again (step 8). Buy one seat of Starter in rupees with your own UPI or card, then refund it from Dodo's dashboard.
*Done when:* your own live payment shows in Billing and the refund shows as "Refunded".

**Step 12 — Before the first customer.**
- **Legal:** a lawyer reads the website's terms, privacy and refund pages (`servabo.app/terms`,
  `/privacy`, `/refunds`; N-029, N-073) and you publish their changes (edit `website/src/pages/`).
- **Real-model spot checks** (sessions 2 and 3; Final session 2 does them on your PC): a prompt-injection document, an invoice with many
  line items, an Indian GST invoice, a photographed page and a handwritten page; check the fields
  and the review queue. Real OCR (PaddleOCR) on scans was never run in the test sandbox.
- **Enterprise identity on a staging domain:** claim and verify a real domain with a TXT record
  (`servabo-site-verification=…`) and sign in once through a real Okta or Entra ID test tenant
  (`branding.domain` and the live IdP were stood in by tests).
- **One SQL check** for workspace regional settings saved before F-320 (HANDOFF, session 3).
- **The CPU-only image** (F-045): build it on a machine that can reach download.pytorch.org, push it
  to your registry and use its digest; pin the other images by digest too (RUNBOOK §9.2 step 11).
- Merge the last pull request; deploy (RUNBOOK §9.3); sign up as a new customer yourself and go
  through the first-run checklist end to end.

**Later, whenever it applies**
- **After any encryption-key rotation** (`EMAIL_ENCRYPTION_KEYS`): run the re-encryption sweep and
  its `--verify` (RUNBOOK) before removing the old key; F-370 made it cover every secret.
- **Healthcare customers:** tell them the HIPAA redaction profile removes names, dates of birth,
  SSNs, card numbers, emails and phone numbers; the other Safe Harbor identifiers need a manual
  pass (N-077).
- **Next release:** remove the one-release aliases for the old name (HANDOFF, "Website and payments
  session → next sessions").


## Session G → next sessions

_2026-10-19. Branch `claude/new-session-awa8gh`, PR #32. Decision N-141; finding F-527. No migration (one Alembic head)._

**What changed.** The **value receipt**: real figures from a customer's own documents, in rupees, at the moments that decide a
purchase and every month after. One read-only service (`app/services/value_receipt.py`), two routes
(`GET /organizations/{org}/value-receipt` and `.pdf`, owners, admins and billing, kept ten minutes in Redis), and these
places: the trial banner's headline in the last three days, a receipt card in the "Your free trial has ended" dialog, "Your
trial so far" above the plan cards, "Found this month" on the Documents Overview (every plan), "Download as PDF", and both
trial emails (the first organization's figures only). Members see exactly what they saw before.

**The honesty rules are tested** (`tests/services/test_value_receipt.py`): stored figures only, currencies and the Time machine's
confirmed / likely / potential never added, zero left out, the sample company never counted, a locked engine silent, windows
in the zone of the oldest workspace. What it counts and the judgement calls are in N-141 (read them: the trial window, the month's
zone, duplicates coming from the radar rather than payment-risk flags, the unaudited PDF).

**For Session D (now Final session 2) / the owner.**
- Try the receipt on a **real account**: upload real invoices, import a real GSTR-2B, open the Overview. The browser test proves the
  wiring and the GST figures on invented invoices; the radar, procurement and Helm figures are proven on planted rows only.
- The receipt reads the usage ledger for "documents read"; it counts what the plan meters count (uploads accepted), not documents that
  finished reading.
- Possible follow-ups, none started: audit the PDF as an export (needs a new audit action, so a migration); a monthly email of the
  receipt for paying customers (the retention loop, reuses `trial_notice.py`'s block); the receipt on the website's pricing page.
- Test tooling: `e2e_stand_in.py trial-ends --backdate-days N` moves the organization's usage events back by lifting the append-only
  trigger for one statement on the throwaway test database. Never used outside the browser tests.
- `ConfirmDialog` gained optional `children` and `wide`, and now scrolls inside a short window; other dialogs are unchanged.

## Session H → next sessions

_2026-10-19. Branch `claude/new-session-rtxwwe`, PR #33. Decisions N-142 to N-146; findings F-528 to F-530. Two migrations (one Alembic head)._

**What changed.** (1) **`main`'s red CI.** Both red runs had one failing job: the GST speed test on a slower CI machine
(matching took 11.48 s against a 10 s budget). The budget did not move; matching is now faster (a bulk `COPY` for the results,
lookups by supplier and day), and a test proves the rows are exactly the earlier ones. The frontend `npm audit` now blocks on what
ships and only reports build tools (`braces` under Tailwind 3, no fix exists, Tailwind 4 removes it, N-119); CI runs on
`ubuntu-24.04` and on Node 24 actions. (2) **GST Credit is the third add-on**: $49 a month per organization, Developer only;
Business and Enterprise include it; on lapse the page returns to the preview and the data is kept (N-145). (3) **The monthly
summary email** to owners of paying organizations on the 1st (N-146).

**For Session D (now Final session 2) / the owner.**
- **Create the eighth Dodo product.** `scripts/dodo_setup.py --create-test-products` now creates five plan products and **three**
  add-ons and prints **eight** lines (the new one: `DODO_ADDON_PRODUCT_GST_CREDIT`, $49, monthly, one per organization, tax not
  included). Paste it into `backend/.env`, run `dodo_setup.py` until all eight say OK, and later do the same in live mode and
  in `.env.production`. The launch checklist above says eight everywhere it said seven.
- **Buy the add-on once in test mode** (DODO-LOCAL-TEST.md, journey H): on a Developer organization open GST credit, import a
  GSTR-2B, press "Add GST Credit — $49 a month for your organization" (an owner), pay with the test card, see the lists open and
  Billing → Add-ons say "Active"; then cancel it from Dodo's customer portal and see "Ends on …" for 14 days, then the preview
  with every import still there.
- Set `BILLING_CHECKOUT_SUCCESS_URL` / `_CANCEL_URL` only if you want a different return page; unset, an add-on's checkout now
  returns to the organization's Billing page (F-530).
- **The monthly email** needs the platform mail relay (the same one the trial emails use). Look at one on the 1st with a real
  paying organization that has a finding; the selection rules are tested with a controlled clock, the rendering in a mail-client
  checklist (not a real mail client).
- After the merge, confirm the CI run on `main` is green (the point of Part 1). If the GST speed test is red again on CI,
  `PERFORMANCE.md` ("the matching step on a shared CI machine") says where the time goes; the next step would be reading the
  books faster (about 0.8 s) and the insert (about 0.7 s, indexes and foreign keys).
- Possible follow-ups, none started: an annual price for the add-on; the monthly summary for organizations on an invoiced
  contract; a rupee price for the add-on; moving CI to the next Ubuntu image on purpose (N-144); `upload-artifact` has a newer major (v7, twelve
  days old when chosen) than the v6 CI uses.


## Session I → next sessions

_2026-10-20. Branch `claude/new-session-ko5jbm`, PR #34. Decisions N-147 (decided) and N-148 (open); findings F-531 to F-534. No migration; one Alembic head._

**What changed.** PR #33 was merged while its last CI run (#400) was red. (1) **The browser test** that failed
(`13-automation-review.spec.ts`, "an upload fires the 'Document uploaded' rule…") clicked "Start Ingestion" and went to the
next page at once; leaving a page cancels a request still on its way, so the file reaches the server only if the server wins
the race. Held back by one second, the *original* test fails here with CI's exact error. It now waits for the server's answer
to the upload, finds that document's run through the API and opens that run's chain, and a second test keeps the race from
returning (F-531). (2) **Plain-text PDFs are no longer searched for a QR code** (about 0.9 s a document, 10% of the browser
suite's pipeline; F-532, N-147). (3) **`aiohttp` 3.14.4 and `yarl` 1.25.1** (F-533). `main`'s run #401 was green except the
advisory pip-audit this fixes.

**What is proven and what is not.**
- Proven: the mechanism (the exact CI error reproduced with the original code and a 1 s delay; the upload cancelled by the
  browser in 20 of 20 idle runs and 17 of 40 loaded runs), the fix (spec 13 x10 beside specs 105/107/108; the delayed test), the
  QR change (tests failed first; 12 documents 113.0 s to 103.2 s), the advisory (pip-audit before and after).
- **Unverified: that this mechanism is what happened in run #400.** The run's report holds the API and worker logs and could
  not be downloaded (the sandbox refuses GitHub's artifact host). On the build machine the original test passed 30 of 30 runs and the upload was never actually lost in
  60 chances without an injected delay, and the worst job wait in a replay of the specs before 13 was 8 s, so a CI-only slowness
  is not ruled out either. **N-148 says how to read the report (kept until 2026-11-02).**
- Unverified: that CI's own run is now green on the first try. It is the proof; look at it first.

**For the next session / the owner.**
- Read N-148 once. If the log shows no `POST .../work-items` from the failed test at about 17:21 UTC, F-531 is proven; if it
  shows one, the upload arrived and something else was slow: look at `jobs` (the `automation.execute` wait) in the same log.
- The brief called `e8509ac` "before the QR reading"; it is PR #31's merge and has it. The commit before is `7185674`.
- If a browser test again waits two minutes for something that "should" appear, ask first whether the page left before a
  request finished; `page.waitForResponse` for the request, then the API for the result, is the pattern now in spec 13.
- F-534 (one pytest shard took 2 h 25 min in run #400) is not explained; if it happens again look at the shard's Postgres
  checkpoint line first (283 s, 704,952 files synced).
- Possible follow-ups, none started: read only the picture's region of a page instead of the whole page (a document with a
  picture on every page still pays 1.6 s a page); a CI step that installs the pinned requirements (a bump such as `aiohttp`
  needs its partner pinned too, and `pip-audit --no-deps` cannot see that).

## Session J → next sessions

_2026-10-21. Branch `claude/new-session-otth8f`, PR #35. Decisions N-149 to N-157 (decided), N-158 and N-159 (open); findings F-535 to F-545. Three migrations (`j1a1_automation_triggers`, `j1a2_automation_actions`, `j1a3_automation_volume_safety`); one Alembic head._

**What changed.** Workspace Automation was rebuilt end to end. (1) **Conditions** are decided by one typed evaluator (amounts with a currency, dates,
fixed values, lists), read through the finance schema's alias map, with a trace of what each condition read and why (F-535 to F-539). (2) **37 triggers**
(14 new): GST, payment risk, legal holds, TruthMesh, schedules, by hand, Helm, request links; each announced once through `emitters.emit_once`
(a mark row plus an outbox event in one transaction, only when a rule listens). (3) **16 steps** (7 new, none can move money). (4) **Safe at volume**: throttle
(200 an hour), cooldown, a workspace pause, retry, versions with a plain diff and Restore, a 30-day preview, "why didn't my rule run?". (5) **A full-page flow
builder**, a recipe gallery (16), rule cards with health and owner, Run history filters and retry, a document Automation tab. (6) **No browser pop-ups anywhere**:
13 replaced, three guards (ESLint `no-alert`, two `check:self` scans, the browser fixture). Vitest is now the frontend's unit runner and runs in CI.

**What is proven and what is not.**
- Proven by tests that failed first, then passed: the evaluator table (96 cases; 37 answered differently), the compatibility corpus (rules saved before answer the same),
  every emitter exactly once, every new action live, throttle, cooldown, pause, retry, preview (writes nothing), versions and restore, the explainer, "every recipe saves",
  all new routes refused through a second workspace, the repo's route sweeps over the new routes (F-542 found by the paging sweep), the builder covers every action
  (`test_automation_frontend_forms.py`), the dialogs (F-540), Vitest (26 tests), and browser specs 109 to 117 (each x3, each on its own tenant, axe in light and dark).
  F-545 (no GST supplier could ever be reminded) was found by spec 115 and fixed with a test that failed first.
- Looked at on screen, 1440 and 390 px, light and dark: the builder (found and fixed: cramped condition row, a currency box off its edge, canvas squeezed on a phone, header
  buttons running off the edge), recipes, Test & preview, Run history, the home page.
- **Unverified.** (a) A message reaching a real Slack or Teams channel (N-158); not even a stand-in receiver receives it, because the delivery path is https only and the
  SSRF client refuses loopback: spec 111 proves the message is queued, its URL is never shown and a second sweep sends nothing more. A development-only switch in
  `webhook_dispatch.attempt_delivery` and `webhook_service._preflight_check_url` would let a local receiver in (see spec 111). (b) The CI run of this branch (below).
  (c) The Wait step (N-154): not started. Design notes: an execution status `WAITING` with `resume_at`, a job that resumes it, re-reading the rule version it started
  on, cancelled when the rule is edited or off or the document deleted, idempotent through the run's own key.

**For the next session / the owner.**
- N-158 (a real Slack and Teams channel, now Final session 2), N-159 (the Pillow 13 advisory, now Final session 1 with Final session 2's real OCR).
- The upgrade dialog for a GST trigger names Business and Enterprise but not the GST Credit add-on, because the trigger passes its capability, not the add-on key
  (`TriggerCard` → `onUpgrade`). Small, cosmetic.
- Run history reasons still use Western grouping ("INR 1,250,000.00") while the builder's sentences use lakh grouping; the evaluator's reason text is the place to change it.
- The schedule trigger's field is `{{event.local_date}}` in a message; `{{trigger.local_date}}` is refused with "Unknown template variable(s)".
- Browser specs run on a shared stack: two Playwright runs that share `frontend/dist` can wipe each other's bundle mid-run (give each its own `E2E_WEB_PORT`, or its own build).
- `docs/automation/README.md` is the user guide; `docs/automation/AUDIT.md` the starting inventory.

## Plan change: the two final sessions (2026-10-22)

_Decision N-160. Docs-only change; no code, no migration._

**What changed.** Sessions D and E were never run. They are replaced by two final sessions that cover the whole product,
not one feature each. The owner's guide is `docs/FINAL-SESSIONS.md`; the prompts are in `docs/sessions/`.

| Session | Where | What | Prompt |
| --- | --- | --- | --- |
| **Final session 1** | Claude Code on the web, Opus 5.5 High | Study the whole product (`docs/hardening/UPGRADE-AUDIT.md`), bring every part up to date (data lifecycle, outdated model lists and libraries, Session J's leftovers, every screen), and build the PRODUCT-NEXT items that earn money: zip upload, email-in, "first money found", the GST digest, upgrade moments, Zoho Books Connect and Tally, the QR badge, error tracking, `preflight.py` | `docs/sessions/FINAL-1-UPGRADE.md` |
| **Final session 2** | Claude Code in VS Code on the owner's PC, Sonnet 5.5 High | Everything for real: every suite on Windows, real email, real OCR and AI, email-in through Postmark, a real GSTR-2B and e-invoice, Helm, Slack and Teams, Dodo journeys A to H, Zoho Books and Tally, the public API and webhooks, Sentry, the website, a new-customer walk-through, a production rehearsal, a live smoke suite; results in `docs/hardening/LIVE-VERIFICATION.md` | `docs/sessions/FINAL-2-LIVE.md` |

**Where the earlier lists went.**
- Old Session E (error tracking, zip upload, email-in, correct-a-field) → Final session 1, Phases 2 and 4. "Correct a field
  beside the page" was already built (`f53ccc8`, `field_correction_service.py`); PRODUCT-NEXT now says so.
- Old Session D (real Dodo, a real GSTR-2B and e-invoice, real AI and OCR, the receipt and emails in Gmail) → Final session 2,
  Phases 3, 5 and 8, unchanged in substance. "Session D" in the sections above means Final session 2.
- Open decisions: N-140 (QR provenance) → Final 1 Phase 3D shows it, Final 2 Phase 5 tries a real e-invoice; N-148 (run #400's
  report) → Final 2 Phase 1 step 6, before the report expires on 2026-11-02; N-158 (a real Slack and Teams channel) → Final 2
  Phase 7; N-159 (Pillow 13) → Final 1 Phase 1C, with Final 2 Phase 3 as the real-OCR proof.

**What a read of the code found on 2026-10-22,** for Final session 1 to verify first (its §0 table has the files):
erasure keeps the document row, so GST and Helm rows, automation traces, outbox and webhook payloads and notifications have no
erasure rule of their own; the tenant export has no GST, Helm or automation data; BYOK suggests retired Gemini models and old
OpenAI ones; `google-generativeai` (deprecated) is still installed; GST has no notification category; global search cannot find
GST suppliers, GST invoices or automation rules; Getting started stops at "ask"; there is no `gst.*` or automation-run webhook
event and no GST or Helm warehouse dataset; the zip handler is never queued and the upload screen refuses `.zip`; nothing receives
email; there is no error tracker; ERP OAuth is "paste your tokens", with no Connect button; nothing on screen shows a value came
from the e-invoice QR code; axe runs in 11 of 99 browser spec files.

**Numbers.** N-160 is this decision; Final session 1 starts at N-161 and F-546; browser specs continue at 118.

## Final session 1 → Final session 2 (2026-10-22)

Final session 2 runs on the owner's Windows PC, with the owner present, and connects the real accounts. Everything below was built and proven in the cloud
sandbox against **stand-ins** (a stand-in Postmark, Zoho, Dodo, SMTP and DNS; `frontend/e2e/scripts/start-stack.sh` starts them). **Nothing that talks to an
outside service has been run against the real service.** Read the tables; do not take "passed" to mean "tried for real". Findings F-546 to F-605 and decisions
N-161 to N-184 are in FINDINGS.md and NEEDS-OWNER.md; the study is `docs/hardening/UPGRADE-AUDIT.md`.

### 1. What Final session 2 must try for real

Settings go in `backend/.env` (local) or `.env.production`; the web app's go in `frontend/.env` **before building the frontend**. Run `python scripts/preflight.py --online`
after every change: it says what is missing or wrong without printing a secret.

| Feature | Settings | Turn it on locally | The stand-in that proved it here | A real success looks like |
| --- | --- | --- | --- | --- |
| **Email-in** (RUNBOOK 9.10) | `POSTMARK_INBOUND_WEBHOOK_USER`, `POSTMARK_INBOUND_WEBHOOK_PASSWORD`, `POSTMARK_INBOUND_HASH` (later `INBOUND_EMAIL_DOMAIN`, `POSTMARK_INBOUND_ALLOWED_IPS`) | Create a Postmark **inbound** server; put its hash in `.env`; start a tunnel (cloudflared or ngrok) to the API; set the server's Webhook to `https://<user>:<password>@<tunnel>/api/v1/inbound/postmark`; in a workspace open Settings → Email-in, allow your address, forward an invoice to the address shown | `python scripts/e2e_stand_in.py inbound-email --org <slug> --file invoice.pdf --from you@example.com --subject Test --message-id m1` plays Postmark against the real webhook (browser spec 119, 26 live tests) | Postmark's Activity page shows the webhook answered **200**; the document appears in the workspace labelled "Arrived by email from you@example.com"; mail from an unlisted sender sits under "Waiting for you"; a zip attachment becomes all its documents |
| **Error tracking** (RUNBOOK 9.13) | `SENTRY_DSN` (API and workers, https), `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE`; `VITE_SENTRY_DSN` (web, baked in at build) and `SENTRY_INGEST_HOST` (the web DSN's host, for the Content-Security-Policy) | Create two Sentry projects in the **EU region** (Python, Browser JavaScript); set the DSNs; rebuild the frontend; restart | The scrubber is proven by unit tests (nothing sensitive leaves); no real receiver was reached | `python scripts/preflight.py --send-test-error` run **in the API container and again in the worker container** shows one "Servabo preflight test error (safe to ignore)" in the Python project, tag `area=preflight`, `service=preflight`; in the browser console on the app, `setTimeout(() => { throw new Error("web sentry test") })` shows one event in the JavaScript project; open an event and see **no email, token, GSTIN, amount or document text** |
| **Zoho Books Connect** (RUNBOOK 9.12; N-173) | `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REDIRECT_URI` (`<API>/api/v1/erp/zoho/callback`) | In api-console.zoho.in create a **Server-based Application**; register that exact redirect URI; use a free Zoho Books organization in the **India data centre**; in a Business workspace: ERP posting → Connect your books | `ZOHO_ACCOUNTS_URL_OVERRIDE` / `ZOHO_API_URL_OVERRIDE` point at a stand-in Zoho (`E2E_ZOHO_URL`, started by `start-stack.sh`; the API refuses to start in production with them set); 15 live tests, browser spec 122 | Zoho's consent screen, then back in Servabo "Connected to <your organization>"; an approved bill posts once and appears in Zoho Books as a bill with the vendor's GSTIN, the GST treatment, source and destination of supply, and per line the HSN/SAC code and tax; posting it again does not duplicate it. **If Zoho rejects a scope, a host or a field, write down the exact message**: the docs could not be opened from the build sandbox |
| **Tally Prime file** (N-174) | none | ERP posting → a Tally target (company and five ledger names) → download the file for an approved bill | The file's structure is tested (one balanced Purchase voucher per bill; CGST and SGST to their own Input ledgers for a same-state supplier, IGST to one for another state) | Import it into **Tally Prime** (the free Educational mode is enough). **The exact menu steps for importing are unverified**: write them down (RUNBOOK 9.12 gets them). The voucher must appear balanced, with the right ledgers, and the totals must agree with the bill |
| **GST digest and notices** (RUNBOOK 9.12; N-170) | the mail relay (`PLATFORM_SMTP_*`) | A **throwaway** organization and workspace with a GSTR-2B imported and at least one invoice waiting for its supplier; set the workspace time zone; `python scripts/e2e_stand_in.py run-job --org <slug> --job gst.digest --now 2026-10-19T09:30:00+00:00` (a Monday) | The same command against the SMTP catcher; the job code is the production code; spec 121 | One email in a **real inbox** (Gmail and Outlook): the headline in lakh grouping, the list of what to do, the right button, and on a plan that shows only the headline figures one line about what the add-on adds. Run it twice: the second run sends nothing (once a week). Switching "GST credit" off under Notifications stops it |
| **Pillow 13 with real PaddleOCR** (F-567) | `ML_STUBS=false` | Build the backend image (or the venv) as production does; upload a scanned PDF and a phone photo of an invoice | The suite runs with stubs; Pillow 13.0.0 imports; PaddleOCR 3.7.0 itself was **not** run | The scan is read (text and fields appear with the page evidence). If PaddleOCR fails on Pillow 13, pin `pillow` to the newest 12.x in `backend/requirements.txt`, record the error, and re-open F-567 |
| **Updated model lists** (F-564 to F-566; RUNBOOK on BYOK) | `GROQ_API_KEY`; a Gemini key for BYOK | Organization → Enterprise BYOK & models: add each provider and use "Test connection" on every suggested model id; `python scripts/preflight.py --online` lists Groq's models | Model ids come from the providers' pages as read on 2026-10-22 and the lists' tests; **no real key was used** | Every suggested model answers; any that does not is **removed from the list** (`byok_providers.py`) and recorded; a retired model gives the plain sentence, never a raw 404 |
| **`preflight.py --online`** (RUNBOOK 9.14) | all of the above | `python scripts/preflight.py --online` (then `--send-test-email you@example.com`); against a **live** Dodo account it refuses without `--i-mean-live` (it still only reads) | Probes run against `httpx.MockTransport` and fake SMTP/database/storage; 24 tests | Every line OK or an intended SKIPPED; no MISSING or WRONG; the output contains no secret (check by eye once) |
| **E-invoice QR badge** (N-175) | `EINVOICE_QR_PUBLIC_KEY_PEM` (NIC's published public key, if you have it) | Upload a **real e-invoice PDF** that carries the QR code (from the GST portal or an invoicing tool) | `python scripts/e2e_stand_in.py einvoice-qr --org <slug> --document <id> --signature not_checked\|checked\|does_not_match` sets the three states on a document | Values read from the code show "From the e-invoice QR code"; the IRN has a copy button; with no key "signature not checked"; with the right key "signature checked". **A wrong key makes every code read "does not match"** |
| **Public webhook events** (docs/product/WEBHOOK-EVENTS.md; N-179) | none (webhooks need a plan that includes them) | Webhooks tab: add an endpoint (webhook.site or your own) subscribed to `gst.return.imported`, `gst.invoice.at_risk`, `gst.supplier.not_reported`, `automation.run.failed`, `automation.run.held`; import a GSTR-2B; run `run-job --org <slug> --job automation.sweep --now <a day 31 days after an invoice entered the books>` for the two clock events; make a workflow fail (point a "send to webhook" step at a disabled endpoint) or pause (the workspace pause switch, or a rule's hourly limit of 1) | 13 live tests (`test_engine_public_webhooks_live.py`) | A signed POST per occurrence, once, with only ids, GSTINs, micros, dates, counts and states; the signature verifies with the endpoint's secret; the same GSTR-2B again sends nothing |
| **Warehouse datasets** (N-180) | the warehouse add-on; a real bucket (S3 or R2) | An **Enterprise** organization: Analytics → Schedules, tick GST matches and Helm promise ledger, "Sync now" to a real bucket | A stub S3 connector (`test_warehouse_engine_datasets.py`, 13 tests, Parquet round trip) | Parquet files in the bucket open in DuckDB or Excel with the columns listed under Analytics → datasets; no supplier or counterparty name anywhere; a Business organization is refused with a plain sentence |
| **Pack checks and the Redact suggestion** (N-181) | a real model key | An Enterprise workspace: enable the NDA and Master services agreement packs; Clause assertions → add "Add, read by an AI model" on "A governing law is named."; process a real NDA | Recorded model readings (`test_pack_checks_live.py`, spec 134) | The check runs on a real NDA with a sensible verdict and the usage shows as assistant usage; the Redact menu on the NDA offers the pack's profile first |
| **The new logo** (N-176) | none | Look at the app, the website, a verification email and an invitation email in Gmail and Outlook, and the browser tab icon | Rendering tests; screenshots retaken | The mark looks right in all of them. **It is a recreation**: if it is not close enough, put the original files in `brand/assets/` and run `build_brand_assets.py` |
| **Resizable sidebars on a phone** (N-177) | none | Open the app on a real phone (or a touch device), open the menu, drag its edge | Playwright touch events at 390 px (spec 126) | The drawer follows the finger, stops at 85% of the screen, and the width is remembered after a reload |

### 2. Commands Final session 2 can use

All in `backend/`; development and test databases only (they refuse to run in production).

| Command | What it is for | Throwaway organization only? |
| --- | --- | --- |
| `python scripts/preflight.py [--online] [--json] [--send-test-email ADDR] [--send-test-error] [--i-mean-live]` | Is this setup ready. `--send-test-error` sends one safe test error to the tracker (needs `SENTRY_DSN`) | No (it only reads, apart from the one message or event you ask for) |
| `python scripts/e2e_stand_in.py inbound-email --org SLUG --file F --from ADDR --subject S --message-id ID [--address A]` | Play Postmark against the real webhook; repeat a `--message-id` to replay a delivery | **Yes**: it adds documents to the organization's first workspace |
| `python scripts/e2e_stand_in.py run-job --org SLUG --job JOB [--now ISO]` with `JOB` = `gst.digest`, `gst.notices`, `automation.sweep`, `trial.reminders`, `billing.hold_notices`, … | Queue a scheduled job now, with a clock you choose | **Yes**: `gst.digest` and `gst.notices` **send real email to the organization's owners** when a real relay is configured |
| `python scripts/e2e_stand_in.py einvoice-qr --org SLUG --document ID --signature STATE` | Put a document's QR signature in one of the three states | **Yes**: it edits the document's extraction record |
| `python scripts/e2e_stand_in.py fail-document --document ID` | Make a document read FAILED (to try "Retry processing") | **Yes** |
| `python scripts/e2e_stand_in.py subscribe / seats / change-plan / cancel / trial-ending / trial-ends / …` | The billing steps (Session G/H); unchanged | **Yes** |
| `python scripts/sweep_compliance.py --archived [--apply]` | What deleting a workspace or organization purges, and when (dry run by default; RUNBOOK 9.11) | **Yes** with `--apply` |
| `python scripts/seed_website_demo.py` and `node website/scripts/capture-screenshots.mjs` | The demo company and the website's screenshots (needs the stack and a built bundle) | The demo organization only |
| `bash frontend/e2e/scripts/start-stack.sh [stop]` | Start or stop the API, worker and the stand-ins | n/a |

### 3. What was not reached, in the order to do it next

1. **A full run of every suite on CI** is the last thing before the owner merges: this session ran each changed area locally and the whole browser regression of the
   touched areas, and left the full backend and browser suites to the ready PR's CI (STATE says whether it was green).
2. **The downgrade of migration `k1a6` with delivery rows present** was proven only on an empty database (up, down, up and one head). Try it once with a webhook endpoint
   that listens to a new event.
3. **Day-1 and day-25 emails after a customer deletes a workspace** ("it will be erased on…", "last chance to restore"): the purge runs, nothing warns.
4. **The global upload tray accepts a zip** (the Documents page does).
5. **A shared "could not be loaded, try again" block** for the organization console pages (polish; PRODUCT-NEXT 2.8).
6. **The ranked list in PRODUCT-NEXT**: the annual and rupee price for the GST add-on first, then the CA-firms channel.

### 4. What is unverified, in plain words

- **The new logo is a recreation** drawn from a picture, not the original artwork (N-176).
- **Real Postmark inbound**, the real header and basic-auth form, and the tunnel: only a stand-in has delivered mail to the webhook.
- **Real Zoho Books**: the data-centre hosts, scope names, token and revoke paths and the bill's GST fields are from Zoho's documentation as known and a search summary; Zoho's pages
  could not be opened from the build sandbox (N-173).
- **Real Tally Prime**: how the file imports, and the exact menu steps.
- **Real Sentry (EU region)**: no event has reached a real tracker; the scrubbing is proven by tests only.
- **NIC's real QR signature**: the check uses a key you configure; no real e-invoice was verified.
- **Model ids against real keys**, and **Pillow 13 with PaddleOCR 3.7.0** on real scans.
- **Real email in Gmail and Outlook** (the GST digest and the new header).
- **The legal paragraph in N-163** (the basis for keeping GST rows after erasure) was read in practitioner copies, not on indiacode.nic.in; a lawyer should confirm it.
- **Real webhook receivers and a real bucket** for the new events and datasets.
- **The AI-read pack checks with a real model**: twelve of the fourteen shipped checks are read by an AI model (N-181).
- **Whether any outside tool of yours expects rupees grouped in thousands**: the formatter now groups rupees the Indian way everywhere (N-182).

## Plan change: the upgrade session before the live session (2026-10-23)

_Decisions N-186 and N-187. Docs-only change; no code, no migration._

**What changed.** Final session 1 is complete (PR #37; CI runs #462 and #464 green on every job). Before the live tests the owner
asked whether Servabo can be sold and make money, raised four issues, and proposed "Evidence-to-Resolution". A new cloud session,
**Final session 2A** (`docs/sessions/FINAL-2-UPGRADE.md`, Opus 5.5 High), now runs before the live session, which becomes **Final
session 2B** (`docs/sessions/FINAL-2-LIVE.md`). Wherever a section above says "Final session 2", it means 2B. 2A reads "Final session
1 → Final session 2" and ends by writing "Final session 2A → Final session 2B" and rewriting the live prompt.

| The owner's question | Where 2A answers it |
| --- | --- |
| Is it worth investing in; can it make money? | Phase 0A: `docs/product/COMMERCIAL-READINESS.md` (buyers, competitors with today's prices, what is proven, the money model, risks); Phase 5: an accuracy report on real invoices and a pilot playbook |
| Custom domains: $199 add-on or included? | Phase 1 (N-187): the code bundles it into every paid plan, so nobody can buy it, yet RUNBOOK lists $199 and `dodo_setup.py` creates its product. Decided: Business and Enterprise only; the add-on retired; every doc and the website agree |
| Safety jobs depend on host cron | Phase 2: every safety job reports its runs into the app; the in-app scheduler alerts on a stale or never-run job without failing readiness; sweeps move into the scheduler where safe; an installer script for the host part; a preflight line; a rehearsal that stops cron on purpose |
| Prompt injection through document text | Phase 3: a map of every path from outside text to an effect (`docs/hardening/PROMPT-INJECTION.md`), invariants with registry-walking tests (nothing approves or pays; recipients never come from a document; fenced prompts; autonomy unmoved by text; escaped templates), and new red-team documents |
| Prices too high for India | Phase 1 (N-187): rupee prices per user (Starter ₹1,499, Business ₹4,999, Enterprise ₹14,999; yearly ten months), the GST add-on ₹1,499 or ₹14,990 a year, a 14-day trial, "Developer" shown as "Starter", allowances resized so every price keeps the margin rules |
| Evidence-to-Resolution | Phase 0B assesses it against today's engines (most pieces exist in separate engines; nothing joins them, and only Helm's value ledger counts an outcome on evidence). Phase 6 builds a thin layer (one read model, closure only on evidence, one outcome ledger counted once, "Recovered, verified" beside "Found") **only if** four stated tests pass |

**Final session 1's leftovers** (its hand-over §3) are 2A's Phase 4: warning emails after a deletion, a zip in the global upload
tray, `k1a6`'s downgrade with rows present, and a check of the owner's lockfile commit `e51f736`.

**Numbers.** N-186 and N-187 are this plan; 2A starts at N-188 and F-619; browser specs continue at 135.

## TRINETRA review and the revised session 2A (2026-10-26)

_Decision N-189. Docs-only change; no code, no migration (head `tr1a2_review_outcomes`)._

**What landed after the 2A prompt was written.**
- **PR #39** redesigned the Documents and AI Assistant consoles (`docs/ui/documents-assistant-upgrade.md`; `GET …/work-items/counts`).
  Its browser spec reused the number 122, and it wrote no campaign record. **Closed in Final session 2A:** the spec is now
  `139-premium-documents-assistant.spec.ts`; the counts row in COVERAGE.csv says what its test proves; FINDINGS has the record.
- **PR #40, TRINETRA** (`docs/trinetra/`, N-188, F-619 to F-625): reviewed TDS evidence for invoices on which a customer withheld tax.
  It has four tables, 20 routes, a LIGHT job, a Helm annotation and reminder hold, a website page, and CI run 40282980125 and
  `main` #478 green. Live processing is off; customers see a synthetic preview.

**What the review found** (by reading the merged code; 2A proves each with a failing test first, or records it as not a defect):

| # | Finding | Where | Why it matters |
| --- | --- | --- | --- |
| 1 | A confirmed withholding makes Helm refuse **every** cash reminder for the invoice, even when most of it is unpaid cash; the refusal is a FAILED action at send time, not a Guard block, and it survives the flag being turned off | `trinetra/helm_adapter.py`, `helm/hands.py`, `helm/executor.py` | It can stop collections, which Helm sells |
| 2 | "Current" means `work_items.updated_at` is unchanged, and that column moves on **any** update (a rename or summary by automation, batch healing, a reprocess) | `trinetra/service.py`, `db/base.py` | False "stale": reconfirming clears allocations; a statement snapshot becomes unusable |
| 3 | The seller check compares an extracted PAN as printed (no upper-casing or spacing rules), ignores the PAN inside `vendor_gstin`, falls back to the name alone, and can raise a 500 on non-ASCII text | `trinetra/service.py` (`receivable`) | Real invoices refused, or matched on a name |
| 4 | Plan capacities count every snapshot and case ever made, and nothing archives them | `trinetra/service.py`, `api/v1/trinetra.py` | A Business organization stops for good after 12 imports or 500 cases |
| 5 | A PAN is unique only within a workspace | `trinetra/service.py` (`create_profile`) | The same government posting can be allocated twice in one organization |
| 6 | One global switch; no way to turn TRINETRA on for a single pilot customer | `core/config.py` and every gate | The launch gates require a pilot |
| 7 | `trinetra.recompute` computes the summary and discards it | `workers/handlers/trinetra.py`, `trinetra/hooks.py` | Work with no effect; nobody is told when evidence goes stale |
| 8 | Smaller points: the case list does several queries per row; the page's write forms check `role === "ADMIN"` only; TRINETRA rows are deleted on erasure while GST rows are kept (N-163); statements are typed row by row | `api/v1/trinetra.py`, `pages/trinetra/Trinetra.tsx`, `compliance/data_map.py` | Speed, an owner's view, one lifecycle policy, real-world usability |

**What is in good shape.** Exact money (integer micros); revision checks; locks; the many-to-many allocation that cannot spend a
posting twice within a profile; refusal of unverified official formats; masked and encrypted PAN with key rotation; scoped
exports with formula and HTML safety; compliance registry entries; isolation sweeps; honest website and in-app copy ("live
access awaits validation"); no model call, no sending, no money movement.

**Where it goes.** `docs/sessions/FINAL-2-UPGRADE.md` gained:
- **Phase T** (items 1 to 12), which fixes all of the above;
- TRINETRA in Phase 0 (its place in the commercial page; the reference design for the resolution assessment);
- TRINETRA in Phase 1 (its plan row, its rupee and "Starter" copy), Phase 3 (its extraction hints) and Phase 6 (its cases as
  their own kind, never counted as cash);
- a TRINETRA pilot phase in the live prompt it rewrites (Phase 8).

PR #39's spec number and coverage text are in Phase 4. The GST speed test that flapped once on `main` (#465, then green on #468,
#472, #478) is Phase 4 item 0: timings in its failure message; the budget does not move.

## Plan change: Final session 2T finishes TRINETRA for Business and Enterprise (2026-10-26)

_Decision N-190. Docs-only change; no code, no migration._

**Why.** The owner wants TRINETRA on Business and Enterprise, working like Helm, three-way matching and GST Credit, with nothing left
behind. 2A's Phase T would only have fixed the review's defects and kept TRINETRA gated. Finishing it needs a whole session, so it now
has one: **Final session 2T**, `docs/sessions/FINAL-2T-TRINETRA.md`, run after 2A and before 2B.

**What 2T does.**
- **Phase 0:** a completion matrix (`docs/trinetra/COMPLETION.md`): every requirement of the owner's original brief
  (`docs/trinetra/ORIGINAL-BRIEF.md`, added in this change) and every "like every other feature" integration, each with its status and
  evidence. No row may stay missing.
- **Phase 1:** the review's defects fixed test-first (the Helm hold, evidence versions, the seller check, one PAN per organization,
  the case list, the forms' roles, one lifecycle rule).
- **Phase 2:** three modes (off, pilot, on; ships as "pilot"), plans, capacities that work for a real year, a 50-a-month inquiry
  allowance on Business.
- **Phase 3:** statements in without typing: a template, and readers for the Form 26AS / Form 168 text download and the AIS CSV, each
  self-checked against the file's own totals and "unverified" until 2B.
- **Phase 4:** expectations from records: printed hints, a template, Zoho Books' TDS withheld.
- **Phase 5:** the whole money model: credit notes, reversals, advances, split payments, the brief's statuses, reject and annotate.
- **Phase 6:** resolution end to end: authorized inquiries with secure request links and replies, Enterprise approval chains, a
  closure ledger, measured cycle time.
- **Phase 7:** woven in like every other feature: Getting started, search, notifications and the digest, the value receipt and the
  monthly summary, automation triggers, webhooks and API, a warehouse dataset, the organization view, the Resolution layer, Helm.
- **Phase 8:** the screens the brief describes, and a user guide.
- **Phase 9:** performance, hostile files, isolation, injection, privacy.
- **Phase 10:** records, TRINETRA's phase in the live prompt, the launch-checklist step.

**After 2T.** 2B proves the readers on the owner's own Form 26AS / AIS files and marks them verified. Then the owner's CA reads the
wording (about an hour) and the owner sets the mode to "on". TCS, payroll TDS, filing, portal access and tax advice are out of scope on
purpose. Final session 2A keeps only TRINETRA's plan row and copy and its existing paths in the injection map; its numbers start at
N-191.

## Final session 2A → Final session 2B (2026-10-27)

Final session 2A (`docs/sessions/FINAL-2-UPGRADE.md`, PR
[sabarishwarne2001/servabo#43](https://github.com/sabarishwarne2001/servabo/pull/43)) made Servabo sellable in India, made the
safety jobs report and alert, mapped and tested prompt injection, and built the proof kit. Findings F-626 to F-636 and decisions
N-191 to N-198 are in FINDINGS.md and NEEDS-OWNER.md; the injection map is `docs/hardening/PROMPT-INJECTION.md`; the commercial
reading is `docs/product/COMMERCIAL-READINESS.md`. Everything below was proven in the cloud against **stand-ins** (a stand-in
Dodo, a model stand-in, an SMTP catcher). **Nothing of it has met the real service.** Final session 2T (TRINETRA) runs before
2B and adds its own section after this one. The live prompt (`docs/sessions/FINAL-2-LIVE.md`) has been rewritten to match.

### 1. What Final session 2B must try for real

| Feature | Settings | Turn it on locally | The stand-in that proved it here | A real success looks like |
| --- | --- | --- | --- | --- |
| **Rupee and yearly prices** (N-187; DODO.md, DODO-LOCAL-TEST.md journey I) | `GATEWAY_PRICE_ID_*` (with `_YEARLY`, `_INR`, `_YEARLY_INR`), `DODO_ADDON_PRODUCT_GST_CREDIT*`: fifteen products | `python scripts/dodo_setup.py --create-test-products`, paste the lines, `python scripts/dodo_setup.py` until all fifteen are OK; an organization whose workspace is in Asia/Kolkata | `tests/fakes/fake_dodo.py` (checkout, seat change, yearly, rupees; F-627, F-628); browser specs 32 and 137 | Billing in rupees; Business × 3 monthly quotes ₹17,696 with GST and shows the ₹15,000 approval note with yearly offered; Dodo's page offers UPI and RuPay and a tax ID pre-filled with the GSTIN; a fourth seat stays on the rupee product |
| **The buyer's GSTIN and the tax split on Dodo's invoice** (N-193, OPEN) | none | Journey I, then open Dodo's invoice PDF | Nothing can stand in: Dodo's documentation does not say | Write down whether the invoice prints the buyer's GSTIN and splits CGST and SGST or IGST. If not, N-193 stays OPEN with what it shows: Indian buyers who claim input credit need the owner's own GST invoice |
| **Custom domains only on Business and Enterprise** (N-187) | none | Organization → Branding & custom domains on a Starter, then a Business organization | `tests/api/test_starter_packaging.py`; the add-on lock card | Starter: "Custom domains come with Business and Enterprise", nothing to buy; Business: the domain form |
| **Safety jobs report and alert** (RUNBOOK §9.6; N-194) | `SAFETY_JOB_REPORT_TOKEN` (the same in `.env.production` and `/etc/servabo/sweepers.env`), `SERVABO_PUBLIC_URL`, optional `ALERT_WEBHOOK`, `SAFETY_JOBS_UNWATCHED` (default: the three PITR jobs), `OPERATOR_ALERT_EMAILS` | The production rehearsal in WSL 2: `servabo-install-host-jobs`, then stop cron 20 minutes (the uptime job's 15-minute deadline) and run `handle_safety_jobs({})` in the worker | `tests/services/test_safety_jobs.py`, `tests/operational/test_install_host_jobs.py`, `test_host_cron_lines.py` (the wrappers against a fake report endpoint), the jobs console spec | The installer ends "Ready"; every job shows "install check"; the uptime job succeeds every minute; with cron stopped, one "Safety job stopped: Uptime heartbeat …" email (and webhook post), `/health/ready` `"safety_jobs": "degraded"` with 200; cron restarted clears it |
| **Prompt injection through real models** (PROMPT-INJECTION.md) | `GROQ_API_KEY`; a BYOK key | Write the corpus's `injection` cases to a folder (FINAL-2-LIVE Phase 3 has the one-liner); an Enterprise organization with Helm in Act mode | Every model call stood in; `tests/engines/test_injection_corpus_live.py` counts every effect before and after; the six invariant tests | Nothing changes beyond ordinary processing; every document with the instruction is held for a person; no email to `exfil@attacker.example`; what each model answered is recorded |
| **A learned address is a suggestion** (N-195, F-631) | none | Helm → Settings → Suppliers and customers, after an invoice with a supplier email | `test_learned_contact_needs_confirmation_live.py`, HelmSettings tests | The address shows with "Use this address for …"; no reminder goes until it is pressed; after it, the reminder arrives |
| **A person decides every Helm payment** (N-196, F-633) | none | A mandate in Act mode | `tests/services/helm/test_guard.py`, `test_prompt_injection_no_money_moves_alone.py` | Act mode still asks before scheduling, approving, releasing a hold on or marking paid |
| **Accuracy report** (Phase 5) | none | 30 to 50 real invoices in a fresh workspace and the filled truth sheet; `python scripts/accuracy_report.py --workspace <id> --truth truth.csv --out accuracy.md` before any correction | `tests/scripts/test_accuracy_report.py` (synthetic extractions) | A figure per field and for the key fields, the misses listed, how many wrong fields went to review; published in LIVE-VERIFICATION.md and COMMERCIAL-READINESS.md, never rounded up |
| **Deletion warnings** (N-164) | the mail relay | Delete a throwaway workspace; `python scripts/e2e_stand_in.py run-job --job compliance.deletion_notices`, then again with `--now` 26 days later | `tests/api/test_deletion_notices.py` (fake relay, controlled clock) | Owners and admins get "… will be erased on <date>" once and "Last chance: …" once; Restore ends them; members get nothing |
| **A zip in the global upload tray** | none | The upload button in the top bar, on a page other than Documents | Browser spec 138 | The tray shows one archive row, then every document read |
| **The safety-job checks in `preflight.py --online`** | as above | `python scripts/preflight.py --online` against the rehearsal | `tests/scripts/test_preflight.py` | Late jobs named; none when all report |

### 2. Commands Final session 2B can use

All in `backend/`; development and test databases only, except where it says production.

| Command | What it is for | Throwaway organization only? |
| --- | --- | --- |
| `python scripts/dodo_setup.py [--create-test-products]` | Check or create the fifteen test-mode products; refuses live mode | No (test account only) |
| `python scripts/accuracy_report.py --workspace ID --truth CSV [--out MD] [--json] [--tag T]` | Measured accuracy against a truth sheet (`scripts/accuracy_truth_template.csv`); only reads | No |
| `python scripts/e2e_stand_in.py run-job --job compliance.deletion_notices [--now ISO]` | Send the deletion warnings that are due; `--now` plays the clock outside production | **Yes**: it emails the owners and admins of every deleted workspace or organization |
| `python scripts/e2e_stand_in.py run-job --job ops.safety_jobs` | Run the hourly safety-job check now (development) | No (it alerts the operator) |
| `sudo [SERVABO_ROOT=PATH] backend/deploy/bin/servabo-install-host-jobs [--check] [--venv]` | Install and check the host cron jobs (production or the rehearsal) | n/a |
| `deploy/bin/servabo-report-run NAME started\|succeeded\|failed [DETAIL]` | What each cron wrapper calls to report a run; never fails the job | n/a |
| `python -c "from tests.fixtures.corpus import MANIFEST, build; …"` | Write the red-team documents to a folder (the full line is in FINAL-2-LIVE Phase 3) | n/a |

### 3. What was not reached, in the order to do it next

1. **The Resolution layer ("Recoveries", N-191)** was declined for 2A by the cut line, after Phases 1 to 5 and the records:
   it is the first build after the pilots, with RESOLUTION-ASSESSMENT.md as its plan (PRODUCT-NEXT §2.0).
2. **N-197:** whether ERP auto-post should skip a case that completed because of an outside upload (it posts data, never a
   payment). The owner decides; until then it posts.
3. **N-198:** the pilot price. PILOT-PLAYBOOK.md is ready apart from it.
4. **The sweeps' dry runs (N-194):** some sweeps change data or send email with no dry run, so the installer only sends
   "install check" reports for them; a real night's run is the first real success.
5. **The full browser and backend suites** ran on the ready PR's CI, not locally (STATE says whether it was green).

### 4. What is unverified, in plain words

- **Dodo in rupees**: UPI, RuPay, the tax ID field, the ₹15,000 mandate behaviour and the invoice's GST lines come from Dodo's
  documentation and search extracts, not from a real checkout (N-192, N-193).
- **The prices themselves** are the owner's delegated decision (N-187); no Indian customer has paid them yet.
- **Real cron on a real host**: the wrappers and the installer were run against a fake report endpoint and a fake crontab;
  no real cron has reported to a real app, and no real alert email or webhook post has arrived.
- **Real models against the red-team documents**: every test stood the model in. The invariants do not rely on the model,
  but what Groq or a customer's model answers is unknown.
- **The injection patterns** recognise English, Hindi and four money commands; a new phrasing in another language is not
  flagged (the autonomy hold depends on it; the other invariants do not).
- **The accuracy figure**: the script is tested on synthetic data; there is no figure on real invoices yet.
- **The deletion warnings in a real inbox** (Gmail and Outlook).
