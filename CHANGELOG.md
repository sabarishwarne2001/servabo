# Changelog

_FlowPilot AI was renamed Servabo on 2026-10-16. Entries below that date keep the old name._

All notable changes to this project will be documented here.

## [Unreleased]

### Added — TRINETRA pilot console (2026-10-30, F-652)

- **Platform → TRINETRA pilot**: a platform administrator enrols an organization in the TRINETRA pilot, or withdraws it, from the
  browser, with a reason kept in that organization's audit log. It shows the server's mode and every enrolled organization (slug,
  reason, date, and a warning when its plan has no TRINETRA). The command line still works.
- A platform administrator who opens an organization's TRINETRA page while it waits for the pilot sees how to open it, with a button to
  the console. Customers see the same sentence as before.

### Fixed

- TRINETRA said "1 days open"; it says "1 day open" (and "1 day old" for a statement).
- The organization console's sidebar and the workspace switcher's list showed a first letter instead of the Servabo logo (F-653).

### Added — TRINETRA (TDS credit) finished for Business and Enterprise (Final session 2T, 2026-10-28)

- **TRINETRA** checks whether the tax a customer withheld from your invoice reached your tax statement, invoice by invoice, and shows
  what is missing as a thing to investigate. Never a refund, never advice on a rate or section, never filing. It is on **Business and
  Enterprise** and ships in **pilot** mode (`TRINETRA_MODE`: off, pilot, on): an organization is live once the operator enrols it
  (`scripts/trinetra_pilot.py`, or the platform admin API). The official Form 26AS and Form 168 readers are unverified until a real
  file has been read (Final session 2B).
- **Bring in your statement** from Servabo's template (CSV or Excel), an AIS CSV (you confirm which column means what) or a Form
  26AS / Form 168 text download; see everything it read before anything is saved. **Find the invoices to check** from a figure
  printed on an invoice, an expected-TDS template (for Tally users) or a read-only look at Zoho Books; a person accepts each.
- **Credit notes, reversals and advances**, closing a case without resolution, a "why was this matched" explanation on every case.
- **Ask the customer for the document**: a draft a person edits, approves and sends, to a contact confirmed in Helm, once a week per
  case, within the plan's monthly allowance. **Enterprise approval chains** for closing a case, and "TDS now visible in your
  statement" (never cash).
- **It shows up where you already look:** Getting started, search, notifications and the Monday line, the value receipt, rules and
  recipes ("a gap is found"), Recoveries, Helm. Enterprise adds public events and a read API, a warehouse dataset and an
  organization view that counts each legal entity once.

### Fixed — TRINETRA (Final session 2T)

- **Helm no longer chases tax the customer already withheld**, including with net-of-TDS reminders and when the evidence is stale (F-641).
- **A rename or a touch of a document is no longer "a change"; a replaced file is** (F-642). **The seller on the invoice has to be the
  legal entity** (F-643). **One legal entity, one profile per organization** (F-645), and **the plan's capacities are enforced** (F-644).
- **The recompute job now does something**: it says what is new (F-647). **The case list asks the database once, not once per case**
  (F-648), and the summary no longer slows down with the number of cases (28 s to 2.6 s at 5,000 cases, F-650).

### Added — Recoveries (Final session 2A, N-191; the owner's request of 2026-10-27)

- **Recoveries** (Documents → Recoveries, Business and Enterprise): every money issue Servabo finds (GST credit waiting on a
  supplier, a probable duplicate, a price above the purchase order, a supplier statement difference, a payment deadline)
  with its amount, its due date, an owner and the next steps, from Found to Being fixed to **Verified**, which only evidence
  grants. "Not money: <reason>" is recorded and never counted. Other plans see the counts and what was found.
- **"Recovered, verified"** on the value receipt and the monthly summary, beside what was found and never added to it; Helm's
  outcomes are counted in it once. The GST digest says how many issues need an owner; Getting started links to the page.

### Changed — the open decisions, settled with the owner's authority (2026-10-27)

- **ERP auto-post waits for a person** when a supplier's upload through a request link completed a case (N-197).
- **The pilot offer:** one month on Business for up to 3 seats at ₹9,999 plus GST, credited against the first year (N-198).
- **The email logo** carries a small white panel, so Gmail's phone apps in dark mode show it clearly (N-199).

### Fixed

- **"Re-plan now" in Helm** waits a moment for a plan already running instead of saying "already planning" (F-637).

### Changed — Emails show the real Servabo logo (owner request, 2026-10-27; N-199)

- Every email sent as Servabo shows the logo itself (the ribbon mark and the wordmark, light and dark) instead of a plain
  "S" tile. The picture travels inside the email, so it shows without "load images?" and no email gains a web address.

### Changed — Final session 2A, Phases 6 to 8: the decision, the records, the live prompt (2026-10-27)

- **The Resolution layer ("Recoveries", N-191) was not built in this session**: declined by the session's cut line after
  the must-haves; it is the first build after the pilots (`docs/product/RESOLUTION-ASSESSMENT.md`).
- **The live session's prompt (`docs/sessions/FINAL-2-LIVE.md`) rewritten** for what exists now: the fifteen Dodo products in
  both currencies and the rupee journey, the safety jobs' stale alert in the production rehearsal, the red-team documents
  through real models, the accuracy report on real invoices, the deletion warnings in a real inbox. Final session 2T adds
  TRINETRA's phase.
- **The deletion-warning job honours `run-job --now` outside production**, so the "last chance" email can be seen without
  waiting 25 days.
- The hand-over to Final session 2B (`docs/hardening/HANDOFF.md`) and the owner's guide (`docs/FINAL-SESSIONS.md`).

### Added — Final session 2A, Phase 5: the proof kit (2026-10-27)

- **`scripts/accuracy_report.py`** measures extraction accuracy on real documents against a truth sheet the customer fills
  (`scripts/accuracy_truth_template.csv`): accuracy by field, documents with every key field right, how many wrong fields
  went to review, and every miss. A Markdown report fit to show a customer.
- **`docs/product/PILOT-PLAYBOOK.md`**: how to run a 30-day paid pilot with a distributor, from day-1 documents to the case
  study.

### Security — Final session 2A, Phase 3: prompt injection, mapped and tested (2026-10-27)

- **The map** (`docs/hardening/PROMPT-INJECTION.md`): every way outside text enters, every model that reads it, every effect,
  and six invariants enforced by tests that walk the code.
- **An email address read from an invoice is never written to until a person confirms it** (Helm, Settings, Suppliers and
  customers). Existing addresses need one confirmation (N-195).
- **Helm never pays, approves a payment, releases a hold or marks paid on its own**, in any mode (N-196).
- No automatic approval rests on a document that reads like instructions to the AI (English, Hindi, money commands).
- Every prompt that reads a document fences it as data; outbound emails bound every value from a document; a QR code whose
  invoice number is a sentence is not read.

### Added — Final session 2A, Phase 4: leftovers (2026-10-27)

- **Warning emails after a deletion** (N-164): the owners and admins of a deleted workspace or organization are emailed at once
  ("will be erased on <date>; restore until then") and 5 days before the erasure ("last chance").
- **The upload tray on a conversation takes a zip**, by the same path as the Documents page.
- The GST speed test names the slow step when it fails (the budget is unchanged); migration `k1a6`'s downgrade is proven with rows.

### Fixed — Final session 2A, Phases 1 to 4 (CI)

- ERP pages answered a Free organization "not found" instead of naming the plans that include ERP posting (F-630).
- The website's pages showing rupees loaded 100 KB of extra fonts for the ₹ sign; only the Latin fonts load now.

### Added — Final session 2A, Phase 2: safety jobs that cannot stop silently (2026-10-26)

- **Every server cron job reports its runs to the app** (sweeps, backups, restore drill, uptime check). When one has not
  succeeded within its deadline, or never reported a day after start, the operator is emailed once a day (and
  `ALERT_WEBHOOK` hears it); Platform admin, Background jobs, shows it in red; readiness says `safety_jobs: degraded`
  but the site stays up; `preflight.py --online` names it.
- **`servabo-install-host-jobs`** installs the cron files and proves every job can report (RUNBOOK 9.6). New settings:
  `SAFETY_JOB_REPORT_TOKEN`, `ALERT_WEBHOOK`, `SAFETY_JOBS_UNWATCHED`. The sweeps stay on cron (N-194).

### Added — Final session 2A, Phase 1: sellable in India (2026-10-26)

- **Prices in rupees and yearly** (N-187), per seat: Starter ₹1,499 or $49 a month, ₹14,990 or $490 a year; Business ₹4,999
  or $299 a month, ₹49,990 or $2,990 a year; Enterprise ₹14,999 or $799 a month (all in `docs/hardening/TENANCY-AND-PLANS.md`,
  margins in `docs/hardening/COSTS.md` §4). Fifteen Dodo products (`scripts/dodo_setup.py`); GST Credit sold monthly and
  yearly in both currencies.
- **Rupee checkout**: billing country India, UPI and RuPay, a GSTIN required and pre-filled from the organization's own GSTR-2B.
  Before paying, a monthly total above ₹15,000 (with GST) says Indian banks ask the payer to approve each such payment, and offers
  yearly instead.
- **14-day trial** with 100 documents and 200 pages; **"Developer" is now called Starter** (the plan key stays `developer`).
- **Custom domains are included in Business and Enterprise**; the $199 add-on is retired. **The Tally Prime file is on Starter**.
- **The website shows rupees by default** with a switch to dollars.

### Fixed — Final session 2A, Phase 1

- A seat or plan change moved a rupee or yearly subscriber onto dollar monthly billing (F-627).
- A seat increase whose charge failed was applied unpaid; a rupee subscriber was quoted the dollar seat price (F-628).
- The margin test never checked yearly prices (F-626); the payment confirmation named the plan by its key (F-629).

### Docs — Final session 2T: TRINETRA finished for Business and Enterprise (2026-10-26)

- **TRINETRA gets its own session** (N-190): `docs/sessions/FINAL-2T-TRINETRA.md`, after 2A and before 2B. It fixes the review's
  defects and builds every remaining requirement of the owner's original brief, now kept as `docs/trinetra/ORIGINAL-BRIEF.md`,
  plus every integration the other features have. A completion matrix leaves no row missing.
- **Three modes replace the single switch:** off, pilot and on. 2B proves the statement readers on the owner's own files, his CA
  reads the wording, and he switches it on for Business and Enterprise.
- **Final session 2A** no longer carries "Phase T"; it touches TRINETRA only for its plan row and copy and the injection map.
- **Updated to the new order:** the owner's guide, STATE, HANDOFF, the live prompt's note and TRINETRA's launch gates.

### Docs — Final session 2A revised after TRINETRA (2026-10-26)

- **TRINETRA reviewed** (N-189; HANDOFF "TRINETRA review and the revised session 2A"). Found in the merged code:
  - the Helm reminder hold stops cash reminders for the whole invoice;
  - evidence goes "stale" on any touch to a document;
  - the seller check ignores the GSTIN;
  - plan capacities never free up;
  - one PAN can live in two workspaces;
  - there is no pilot switch for one organization;
  - the recompute job does nothing.

  `docs/sessions/FINAL-2-UPGRADE.md` gained Phase T to fix them test-first, with TRINETRA kept off for everyone but an enrolled
  pilot.
- **STATE put in order:** TRINETRA's pre-merge checkpoint now says it was merged, with its final green runs; one "Last updated"
  line on top.

### Added — Project TRINETRA (2026-10-26; live processing gated)

- Reviewed business-TDS expectations, immutable statement transcriptions, conserved
  allocations, versioned decisions, source comparison, inquiry drafts and CSV/XLSX/HTML
  evidence exports. Canonical documents, Helm, jobs, outbox and compliance services are reused.
- Credit-assurance cockpit, nine synthetic scenarios, scoped Enterprise reporting,
  API/webhook access, and `/trinetra` on the public website. Business/Enterprise
  capabilities are additive; existing prices, plan names and payment products stay intact.
- Explicit reviewed withholding annotates Helm receivables and holds gross reminders;
  it never becomes cash or rewrites a settlement. Later gap closure requires increased
  statement evidence and current accountant review; recorded minutes mean effort, not savings.
- Migrations `tr1a1_credit_assurance` and `tr1a2_review_outcomes` follow `k1a7` in one
  chain. PAN and identity salts join platform encryption rotation; supporting sources
  join erasure/retention handling. Filelock/setuptools pins address audit findings.
- `TRINETRA_LIVE_ENABLED=false` by default. Official file parsers, TCS, signed/advance
  workflows and inquiry sending are unsupported. See `docs/trinetra/DELIVERY.md` and
  `LAUNCH-GATES.md` for executed tests and incomplete production acceptance.

### Docs — Final session 2A, the upgrade before the live tests (2026-10-23)

- **A new session runs before the live tests** (N-186): `docs/sessions/FINAL-2-UPGRADE.md`. It answers the owner's commercial
  questions (a readiness page, an accuracy report, a pilot playbook), fixes the custom-domain price contradiction, makes the safety
  jobs report into the app, maps and tests prompt injection, finishes Final session 1's leftovers, assesses Evidence-to-Resolution
  (and builds a thin version only if it passes stated tests), and rewrites the live prompt, now Final session 2B.
- **Prices for India decided** (N-187): rupee prices per user (Starter ₹1,499, Business ₹4,999, Enterprise ₹14,999; yearly ten
  months), the GST Credit add-on in rupees and yearly, a 14-day trial, custom domains on Business and Enterprise only, the Tally file
  on Starter. Built by session 2A; the dollar prices do not change.

### Added — Final session 1: bring every part up to date, build what earns money (2026-10-22)

Findings F-546 to F-605, decisions N-161 to N-184. The study is `docs/hardening/UPGRADE-AUDIT.md`; the hand-over to Final session 2 is in `docs/hardening/HANDOFF.md`.

- **A customer's data is accounted for** (F-546 to F-551). One registry (`data_map.py`) says, for every table, what erasure, the retention sweep, deleting a workspace or an
  organization and the data export do with it, and a test fails for a table with no decision. Deleting a workspace or organization now really purges its data
  (30 days after archiving; the money records and the audit trail stay; N-162, N-163), and the export carries what a customer owns (GST books, Helm, automation, entities).
- **Zip upload and email-in** (F-558, F-559). One zip becomes its documents; a workspace has its own address and forwarded invoices become documents (Postmark inbound;
  listed senders at once, anyone else held for an administrator). **Getting started** leads to the first money found (F-556).
- **GST credit tells you** (F-554): in-app notices and a Monday email, once, only when there is something to say, with rupees in lakh grouping. **Upgrade moments** (F-552, F-553, F-576 to F-579):
  every lock names the plan that includes it, only an owner is sent to buy, the 80% usage and seat warnings go to the fix.
- **Zoho Books Connect and a guided Tally Prime file** (F-561), **the e-invoice QR badge** (F-562), **error tracking** with Sentry or GlitchTip, scrubbed and off by default (F-560),
  and **`scripts/preflight.py`**: one command that says whether a setup is ready, with `--send-test-email` and `--send-test-error` (F-563).
- **Models and libraries** (F-564 to F-569): current model lists and a plain sentence for a retired model, Pillow 13, pypdf, certifi, SQLAlchemy 2.0.55, pydantic (Alembic stays at 1.13.1: 1.20 changes the drift check's output); `google-generativeai` removed.
- **Public webhook events** `gst.return.imported`, `gst.invoice.at_risk`, `gst.supplier.not_reported`, `automation.run.failed`, `automation.run.held` (F-557; migration k1a6; `docs/product/WEBHOOK-EVENTS.md`),
  **warehouse datasets** `GST_MATCHES` and `HELM_LEDGER` for Enterprise, and **document packs that do what they promise** (F-408; migration k1a7): enabling a pack proposes its checks under
  Clause assertions, one click each, and the Redact menu offers the pack's profile first.
- **Screens** (F-573 to F-575, F-601 to F-604): every page is walked in light and dark and at phone width (specs 72, 74, 132 and a guard that fails when a page is in none); money
  is shown one way (rupees in lakh and crore, with a guard); no raw error text reaches a person (with a guard); global search finds GST suppliers, GST invoices and workflows.
- **The organization console, tab by tab** (F-581 to F-600). All 17 tabs have backend tests and browser specs 127 to 131; 19 real defects were fixed (a huge number crashed a save, a
  typo became "keep forever", a webhook address kept its password, administrators were refused Enterprise identity, and more).
- **Resizable sidebars** on every screen that has one (mouse, finger, keyboard; spec 126) and **the new Servabo logo** everywhere, as the default for any workspace without its own (F-605; a vector
  recreation, N-176).
- **The website** says what zip upload, email-in, the GST Monday email and the Zoho and Tally connections do, with all screenshots retaken.

### Changed — Final session 1

- **Rupees are grouped the Indian way everywhere** (₹12,34,567.50), whatever the person's language (N-182). A tool of yours that read the old grouping needs to expect the new one.
- **Administrators can read Enterprise identity** (webhooks and the audit log too); writes stay the owner's (N-006, N-178).
- **Database:** migrations `k1a1` to `k1a7` (see below; one head, `k1a7_pack_check_dismissals`). `k1a6` widens the webhook-event CHECKs; `k1a7` adds `workspace_schema_presets.dismissed_checks`.

### Docs — The two final sessions (2026-10-22)

- **Sessions D and E are replaced by two final sessions** (N-160). `docs/FINAL-SESSIONS.md` explains them for the owner;
  `docs/sessions/FINAL-1-UPGRADE.md` (study, bring every part up to date, build what earns money) and
  `docs/sessions/FINAL-2-LIVE.md` (everything for real on the owner's PC) are the prompts. STATE, HANDOFF, NEEDS-OWNER, the Dodo
  walk-through and the GST unverified list now point at them.
- **`docs/PRODUCT-NEXT.md` tells the truth again:** "correct a field beside the page" (#9) and the yearly switch (#3) were already
  built, the final overage invoice (#2) does not apply on Dodo, and accounting connections (#5) are retargeted to Zoho Books and
  Tally for India.

### Added — Automation, end to end (Session J, 2026-10-21)

- **Conditions that are always right** (F-535 to F-539, N-153). A condition on an amount used to compare with `float()`, so
  `₹ 1,18,000` or `INR 118,000.00` never matched "greater than"; a date could not be compared at all; a comma split "Acme, Inc";
  and a model's `supplier_gstin` never matched a condition on `vendor_gstin`. One typed evaluator now reads amounts (with a
  currency, never converted), dates (before, after, within, older than, in the workspace's format and zone), fixed values,
  lists and booleans, reads documents through the finance schema's alias map, and offers three worked-out fields (document age,
  has an IRN, days until due). Every rule saved before answers exactly as it did (a compatibility corpus proves it). A run's trace
  now says what each condition read and why it decided.
- **Fourteen more triggers** (37 in all): GSTR-2B imported, an invoice waiting for its supplier, GST credit at risk of reversal,
  payment-risk flags, legal holds placed and released, TruthMesh conflicts opened and resolved, every day, every week, run by
  hand on one document, Helm (a mandate breached, an action waiting for approval; these can only tell, mail, post, call out,
  review or tag, N-150), and a document received through a request link. Each is announced exactly once, from the engine that
  knows, and only when a rule is listening.
- **Seven more steps** (16 in all): tag a document, send to review assigned to a person or role, place a legal hold, post to
  Slack or Microsoft Teams (the channel's address is stored encrypted and never shown, N-152), remind a GST supplier, create a
  follow-up, ask a supplier for a document. None can approve or pay anything.
- **Safe at volume** (N-151, N-155, N-157). Each rule is held to 200 runs an hour unless it says otherwise, with an optional
  once-per-document cooldown; runs held back are listed as Skipped, never lost, and the author gets one notice a day. A
  workspace administrator can pause every automation. A failed run can be retried (with a warning before a message could go
  twice). Every save keeps a version with a plain-words diff and Restore. Preview shows what a rule would have done on the last
  30 days, without sending or writing anything, and "Why didn't my rule run?" answers for a document. Three migrations
  (`j1a1`, `j1a2`, `j1a3`); one Alembic head.
- **A new builder and pages** (N-149, N-156). The builder is a full-page editor drawn as a flow (When, Only if, Yes and No,
  Then and Otherwise) with an inspector, a searchable trigger picker, typed inputs (an amount with a currency, a date picker,
  dropdowns for fixed values, lists, between), live message previews, Test & preview and an hourly limit and cooldown. Sixteen
  ready-made recipes (India first) open it filled in; rule cards show their sentence, health and owner and can be filtered;
  Run history filters by outcome, rule and date, shows Skipped runs and retries failed ones; each document has an Automation
  tab.
- **Servabo's own dialogs instead of the browser's pop-ups** (F-540, F-541). Thirteen `confirm` and `prompt` calls are replaced;
  Escape closes only the top dialog; an ESLint rule, two `check:self` scans and a browser-test fixture stop them coming back.
- **Unit tests for the frontend** (Vitest, `npm run test:unit`, in the Frontend CI job and its contract test): the builder's
  model, the sentence builder, the value inputs and the dialogs.

### Fixed — CI on this branch (Session J)

- **`npm audit` turned red** on `follow-redirects` 1.16.0 (two new high advisories, also red on `main`): lockfile bump to 1.16.1
  (F-544). The advisory Pillow warning from `pip-audit` is left for a decision (N-159).
- **People you could assign a review to were listed by email only**; they now show their name (F-543).
- **The version history could page unstably**; it now ends on a unique key (F-542).
- **A GST supplier reminder could never be sent**: Helm stores a supplier it derived from documents under `gstin:<GSTIN>` and never filled the `tax_id` column the reminder searched, so no supplier ever had a "known contact" (F-545).

### Fixed — CI after PR #33 (Session I, 2026-10-20)

- **A browser test could lose its own upload.** The run-history test (spec 13) clicked "Start Ingestion" and left the page at
  once, which cancels a request still on its way; when the server lost that race no automation run ever existed and the test
  waited two minutes for an empty timeline (F-531). It now waits for the server to accept the upload, finds that document's
  run, and opens that run's chain; a second test holds the upload back a second to keep the race from returning.
- **Documents of plain text are processed faster.** The e-invoice QR search no longer renders pages that are only text, which
  cost the worker about 0.9 s per document (F-532, N-147); pages with a picture, a drawing or a form are searched as before.
- **`aiohttp` 3.14.4** (three security advisories) and `yarl` 1.25.1, which it needs (F-533).

### Added — A green main, the GST Credit add-on, the monthly summary (Session H, 2026-10-19)

- **GST Credit add-on**: a Developer organization can buy the GST Credit lists (suppliers, invoices with IMS recommendations,
  decisions, export, reminders) for $49 a month for the whole organization, as the third add-on. Business and Enterprise
  include it through their plan. When it ends the page returns to the preview and every import, match and decision is kept.
  Offered on the GST page (and both ways on the trial), listed on Billing → Add-ons, named in the value receipt, and on the
  website's pricing page (a new Add-ons section) and `/gst-credit`. One migration (`h1a6_gst_credit_addon`); the Dodo setup
  now creates eight products.
- **Monthly summary email**: on the 1st of each month the owners of a paying organization get last month's value receipt,
  only when it found something, once per organization per month, with a "Monthly summary" switch (on by default). One
  migration (`h1a7_monthly_receipt_sends`), one worker job (`receipt.monthly`).

### Changed

- **GST matching is faster** (storing results with one `COPY`, suggestion lookups by supplier and day, the garbage collector
  paused while a recompute runs): matching 10,000 records against 10,000 invoices went from about 4.2 s to about 2.2 s on the
  build machine, because it took 11.48 s on CI and failed
  `main`. The budget did not move.
- **CI**: the frontend audit blocks on what ships (`npm audit --omit=dev`) and only reports build tools; every job runs on
  `ubuntu-24.04`; `checkout`, `setup-node`, `setup-python` on v7 and `upload-artifact` on v6 (Node.js 24).

### Fixed

- An add-on's checkout returned the customer to an empty address (F-530).

### Added — The value receipt (Session G, 2026-10-19)

- **Value receipt**: real figures from a customer's own documents, in rupees, shown where a purchase is decided and every
  month after: GST credit waiting on suppliers (and at risk under the 180-day rule, and claimable now), the Time machine's
  latest replay (confirmed, likely and potential kept apart), probable duplicate invoices, supplier bank-account changes,
  overcharges against purchase orders, and Helm's value held. Nothing is estimated, currencies and honesty classes are never
  added, zero is left out, and the sample company is never counted.
- **Where**: the trial banner's last three days (the headline), the "Your free trial has ended" dialog (a receipt card with
  links to the evidence), the plan page ("Your trial so far"), the Documents Overview ("Found this month", every plan), a
  one-page PDF ("Download as PDF"), and both trial emails. For owners, admins and the billing role; members see today's text.
- **API**: `GET /organizations/{org}/value-receipt?period=trial|month` and `.pdf`, kept ten minutes in Redis. No migration.

### Added — GST Credit (Session F, 2026-10-19)

- **GST credit**: import a GSTR-2B and see which input tax credit you can claim, which suppliers have not reported your
  invoices, what differs, and what to do in the GST portal's Invoice Management System; the 180-day exposure; an Excel
  export and a supplier reminder. Documents → GST credit. Every plan can import and see the six figures; Business and
  Enterprise get the lists, decisions, export and reminders. Recommendations, not tax advice.
- **Enterprise**: GST credit across every workspace (Organization → GST credit, all workspaces) and the `gst:read` API
  key scope. Migration `g1a1_gst_credit` adds five tables and the key scope.
- **Helm**: mandates "Pay within 180 days of the invoice date" (recommended, on in the sample company) and "Hold payment
  until the supplier has reported the invoice in GSTR-2B" (off by default); neither can make a payment late under the MSMED
  Act or the 180-day rule. A Guard check "GST credit secured" and a drafted request to suppliers who have not reported.
- **Reading**: the extraction prompt now asks a model for every field the product reads (F-524); the e-invoice QR code
  (IRN) is read during processing.
- **Website**: a `/gst-credit` page.

### Changed — FlowPilot AI is now Servabo (2026-10-16)

There are no customers yet, so every protocol identifier that carried the old name changes once,
now. Anything built against the old names (a webhook receiver, a script that holds an API key, a
DNS record) must use the new ones:

| What | Before | After |
|---|---|---|
| Outgoing webhook signature header | `X-FlowPilot-Signature` | `X-Servabo-Signature` |
| Outgoing webhook delivery headers | `X-FlowPilot-Delivery-Id`, `X-FlowPilot-Event-Type`, `X-FlowPilot-Attempt` | `X-Servabo-Delivery-Id`, `X-Servabo-Event-Type`, `X-Servabo-Attempt` |
| Outgoing User-Agent strings | `FlowPilot-Webhooks/1.0`, `FlowPilot-ERP/1`, `FlowPilot-ARCH26/1.0` | `Servabo-Webhooks/1.0`, `Servabo-ERP/1`, `Servabo-ARCH26/1.0` |
| Public API version header | `X-FlowPilot-API-Version` | `X-Servabo-API-Version` |
| Spend-limit and export response headers | `X-FlowPilot-Spend-Limit`, `-Spend-Period`, `-Spend-Resets-At`, `X-FlowPilot-Export-Truncated` | `X-Servabo-Spend-Limit`, `-Spend-Period`, `-Spend-Resets-At`, `X-Servabo-Export-Truncated` |
| Domain-verification TXT record value | `flowpilot-site-verification=…` | `servabo-site-verification=…` |
| Domain-verification TXT record name (subdomain form) | `_flowpilot.<domain>` | `_servabo.<domain>` |
| Custom-domain challenge record | `_flowpilot-challenge.<host>` | `_servabo-challenge.<host>` |
| Live-review WebSocket subprotocol | `flowpilot.review.v1` | `servabo.review.v1` |
| Refresh cookie | `flowpilot_refresh` | `servabo_refresh` (everyone signs in again once) |
| API key prefixes | `fp_live_…` / `fp_test_…` | `svb_live_…` / `svb_test_…` (re-create local keys) |
| Browser storage keys | `flowpilot_auth_session`, `flowpilot_ui_preferences`, `flowpilot_tenant_selection` | `servabo_auth_session`, `servabo_ui_preferences`, `servabo_tenant_selection` (theme and last workspace reset once) |
| Sovereign licence format | `flowpilot-licence/1` | `servabo-licence/1` |

### Removed — the old name is no longer read (Session B, 2026-10-18)

There are no installations from before the rename, so the one-release compatibility is gone.
**Operators must use the `SERVABO_*` setting names: the old `FLOWPILOT_*` names are no longer read**
(by the API, the worker, the scripts in `backend/scripts/` and `backend/deploy/bin/`). Also gone:

- API keys starting `fp_live_` / `fp_test_` (only `svb_live_` / `svb_test_` are keys);
- backups and local backup folders written under the old name (`flowpilot-<stamp>.fpbk`, `.flowpilot_*`);
- `--loop stripe` and the `worker-stripe` service role (use `--loop billing` and `worker-billing`);
- old display values rewritten to Servabo (`PROJECT_NAME=FlowPilot AI` now shows as written);
- the launchers' shim for Docker volumes named `flowpilot_*`.

The values that were once published as defaults (`flowpilot_default_*` peppers) stay refused by the
production guard for good.

### Changed — the local databases are published on this computer only (Session B, 2026-10-18)

`backend/docker-compose.yml` publishes Postgres (5432), Redis (6379) and MinIO (9000, console 9001)
on `127.0.0.1` instead of every network interface.

### Changed — Helm's Promise ledger updates incrementally (Session B, 2026-10-18)

A document change used to recompute the whole workspace's ledger (4.07 s at 10,000 documents, budget 1 s).
It now re-projects that document and what depends on it (0.70 s), and gives exactly what a full rebuild
gives. The nightly rebuild checks that, repairs a difference and raises an operator alert of the new kind
`HELM_LEDGER_DRIFT`. Migration `h1a5_helm_ledger_incremental` adds two bookkeeping tables
(`helm_ledger_state`, `helm_ledger_dirty`) and an index on `helm_promises.fulfilments`; a migration
`b1a1_pan_card_phrase` lets the Aadhaar / PAN card document pack recognise a real PAN card.

### Fixed — carried-over defects (Session B, 2026-10-18)

Batch operations (two dispatches or adds at once, archived batches, totals over every batch, packages of
erased documents, extra files in a package), TruthMesh (a deleted or erased document leaves the mesh and
its conflicts at once, a rebuild keeps people's decisions on links, the reason is audited, lighter read
models), document packs (whole-word phrases, one answer on a tie, a real audit trail), conversation
retention counted from the last message, a refused tenant refreshes the app, and every list endpoint
refuses an `offset` above 2,147,483,647 (422) instead of failing with a 500. FINDINGS.md F-469 to F-499.

### Planned

- Backend foundation
- Frontend foundation
- PostgreSQL integration
- Authentication
- Work Item processing
- AI pipeline
- Automation Engine
