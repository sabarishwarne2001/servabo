# Final session 1: bring every part up to date, and build what earns money

| | |
| --- | --- |
| **Where** | Claude Code on the web (the cloud), repository `servabo` |
| **Model / effort** | **Opus 5.5, High** |
| **Before you start** | PR #35 (Session J) and PR #36 (which added this file) are merged, and **CI is green on `main`** |
| **After it** | Final session 2, on your own PC (`docs/sessions/FINAL-2-LIVE.md`) |
| **Replaces** | The old "Session E" (product wins). The old "Session D" became Final session 2. |
| **External cost** | Zero. Every outside service is played by a stand-in in this session; Final session 2 connects the real accounts. |
| **If usage runs out** | Type `continue` in the same session after the reset. Each phase is finished, tested and pushed before the next one starts. |

**How to start.** Open a new Claude Code session on the web for `servabo`, choose Opus 5.5 with High
effort, and paste either everything below the line or this one sentence:

> Read `docs/sessions/FINAL-1-UPGRADE.md` on `main` and carry it out from section 0. Never stop to ask me.

---

# Final session 1: study, bring up to date, and build what earns money

## 0. Why this session exists

Servabo is a multi-tenant B2B SaaS for document intelligence and finance automation. A solo founder in
India builds it; he is new to SaaS. Its first customers are Indian SMB distributors and manufacturers.
Explain everything you report in plain language, with no jargon left unexplained.

Since the last full review the product gained a lot, one session at a time:

- **Helm**, the flagship (payment planning with mandates, the Promise ledger, the Guard, the Monday briefing) and its
  Night Bridge look;
- **GST Credit** (Session F): GSTR-2B import, matching, IMS recommendations, the 180-day rule, the e-invoice QR code;
- **the value receipt** (G) and **the monthly summary email** (H);
- **the GST Credit add-on** for Developer, $49 a month (H);
- **Automation rebuilt end to end** (J): 37 triggers, 16 steps, safety at volume, a full-page builder, recipes, and no
  browser pop-ups anywhere.

Each session was careful about its own feature. **Nobody has gone back over the whole product since.**
Older parts were not told about the new stores, the new events and the new money paths. Some lists of outside
models have gone stale. Some ideas in `docs/PRODUCT-NEXT.md` are worth real money and are still unbuilt, while
others are already built and the list does not say so.

**This session does three things, in this order:**

1. **Study** the whole product and write down, with evidence, everything that has fallen behind.
2. **Bring it up to date**: data lifecycle, outdated model lists and libraries, Session J's leftovers, and every
   screen, so the product is consistent and correct.
3. **Build the PRODUCT-NEXT items that earn money**, and only those. Each one has a "why it earns money" line
   below; keep to it.

It ends with a precise hand-over to **Final session 2**. That session runs on the owner's PC and tries
everything you build against the real outside services: Dodo, Groq, Gemini, PaddleOCR, Postmark, Sentry,
Zoho Books, Tally, Slack, Gmail. **Build every outside connection so that it can be switched on by settings alone.**
Final session 2 must not need to change code just to connect a real account.

### What a read of the code found on 2026-10-22 (verify every point before you rely on it)

| Area | What was found | Where |
| --- | --- | --- |
| Erasure | Erasing a person's documents clears the document's text, entities, chunks, exemplars, corrections, payment-risk flags and the rest, **but keeps the document row**. So `ON DELETE CASCADE` never fires, and these survive with no rule of their own: GST book and match rows, Helm ledger rows, automation execution traces (a trace records the values each condition read), outbox and webhook-delivery payloads, and notification bodies. | `backend/app/services/compliance/erasure_service.py` (`_destroy_documents`, `PRESERVED_FINANCIAL_TABLES`); `models/gst.py` and `models/helm.py` (composite foreign keys, CASCADE); `models/automation_execution.py` (SET NULL) |
| Tenant export | The organization's data export bundle has members, workspaces, documents, conversations, messages, audit logs and invoices. It has **no** GST, Helm, automation rules, corrections, entities, cases or obligations. | `backend/app/services/compliance/export_service.py` |
| Retention sweep | It purges documents and conversations. Check what each purge leaves behind in the newer stores (traces with SET NULL keep their values). | `backend/scripts/sweep_compliance.py` |
| AI models | BYOK suggests `gemini-2.0-flash`, `gemini-1.5-pro` and `gemini-1.5-flash` (Google has retired or is retiring these), and `gpt-4o`, `gpt-4o-mini` and `o3-mini` for OpenAI and Azure. The model price book and the BigQuery reconciliation map name the same old models. `google-generativeai` (a deprecated SDK) is still in the requirements beside `google-genai`. | `backend/app/core/byok_providers.py`, `backend/scripts/seed_price_book.py`, `backend/app/services/reconciliation/gemini_bigquery.py`, `backend/requirements*.txt` |
| Libraries | Pillow 12.3.0 has advisories that are fixed only in 13 (N-159, advisory CI red). Old pins: `alembic==1.13.1`, `SQLAlchemy==2.0.28`, `pydantic==2.10.6`, `pydantic-settings==2.7.1`. Tailwind 3 carries a build-tool advisory (N-119). | `backend/requirements*.txt`, `frontend/package.json` |
| Notifications | The categories are security, billing, usage, workflow, monthly summary, Helm and the Helm briefing. **GST has no category and sends nothing.** A supplier who has not filed, or a 180-day deadline coming up, is visible only to someone who opens the page. | `backend/app/services/notification_preferences_service.py`; nothing in `backend/app/services/gst/` notifies |
| Search | Global search finds documents, entities and cases only. It cannot find a GST supplier by GSTIN, an invoice in the GST books or an automation rule. | `backend/app/services/global_search_service.py` |
| Getting started | The checklist is upload, read, ask, invite. Nothing leads a new customer to GST Credit, Helm or a recipe: the places where Servabo finds money. | `frontend/src/components/onboarding/GettingStarted.tsx` |
| Webhooks and warehouse | Public webhook events have no `gst.*` and no automation-run events. The warehouse datasets are usage roll-ups, document metadata, assistant turns and automation runs: no GST, no Helm. | `backend/app/core/webhook_events.py`, `backend/app/services/analytics/export_engine.py` |
| Intake | **Zip upload:** the zip handler exists with its limits (`batch.expand_archive`), but nothing queues it, and the upload screen does not accept `.zip`. **Email-in:** nothing receives mail. | `backend/app/services/ingestion/archive.py`, `backend/app/workers/handlers/ingestion.py`, the upload tray |
| Error tracking | None. The operator alerts say *that* something failed, not *where*. | — |
| ERP | Zoho Books, QuickBooks, Business Central, S/4 and NetSuite presets exist, and so does a Tally Prime XML voucher file with a "download" transport. OAuth exists only as "paste your client id, secret and refresh token" (`OAUTH2_REFRESH_TOKEN`). There is **no "Connect" button** with the provider's consent screen. ERP posting is Business and Enterprise (`capability.erp_posting`). | `backend/app/services/erp/` (`presets.py`, `service.py`, `vocabulary.py`, `formats/tally.py`) |
| E-invoice QR | It is read during processing and stored in the extraction metadata. **Nothing on screen shows that a value came from the QR code**, or whether its signature was checked (it cannot be without NIC's key, N-140). | `backend/app/services/gst/`, the document viewer |
| PRODUCT-NEXT | It still says "none of them is built", talks about Stripe and QuickBooks for India, and lists "correct a field beside the page" (#9) as unbuilt. **#9 is built:** `field_correction_service.py`, `PATCH …/work-items/{id}/fields`, `ExtractedFieldsPanel.tsx`, commit `f53ccc8`. #3 (yearly) is built. #2 does not apply on Dodo (N-118). #10 (packs that set up their checks and redaction) is still unbuilt (F-408). | `docs/PRODUCT-NEXT.md` |
| Session J leftovers | (a) The GST trigger's upgrade dialog does not name the GST Credit add-on (`TriggerCard` → `onUpgrade` passes the capability, not the add-on). (b) Run-history reasons use Western grouping ("INR 1,250,000.00") where the builder uses lakh grouping. (c) `{{trigger.local_date}}` is refused; only `{{event.local_date}}` works. (d) Two Playwright runs that share `frontend/dist` can wipe each other's bundle. | `docs/hardening/HANDOFF.md`, "Session J → next sessions" |
| Accessibility | axe runs in 11 of the 99 browser spec files. Most pages have never had an accessibility check in dark mode. | `frontend/e2e/tests/` |

## 1. Authority and rules

- **Full founder authority.** Decide like a careful senior engineer at a top SaaS company, build it, and record every
  decision in `docs/hardening/NEEDS-OWNER.md` as `DECIDED (Final 1)`. Never stop to ask. The next free numbers are in
  `STATE.md`: decisions from **N-161** (N-160 is the plan change that created this session), findings from **F-546**,
  browser specs from **118**.
- **Do not change any price, plan, trial length or plan allowance.** Put a new capability on the plans that already carry
  that kind of capability. If something deserves a price of its own, record it in NEEDS-OWNER as `OPEN` with your
  recommendation and leave the price alone.
- **Evidence rule (CLAUDE.md):** a bug is fixed only when a test failed first, the fix is applied, that test passes and the
  rest of the suite still passes. Anything not proven is reported as "unverified".
- **CLAUDE.md hard rules hold:**
  - no secrets, `.env` files or binaries in git;
  - never weaken, skip or delete a test;
  - never push to `main`;
  - exactly one Alembic head, proven with up, down and up;
  - leave `archive/` and the historical scripts alone;
  - test-mode credentials only.
- **Never contact a live outside service from a test.** Write stand-ins in the style of `backend/tests/fakes/fake_dodo.py`
  for Postmark inbound, Sentry ingest, Zoho Books (accounts and API) and every provider you touch. The cloud sandbox
  cannot reach them anyway. Read the providers' public documentation with WebSearch and WebFetch, and cite the page and
  the date in a code comment wherever you rely on a documented behaviour.
- **The old product name must not come back** anywhere outside the allowlist in
  `backend/tests/core/test_the_old_name_is_gone.py`. That includes new docs, code and comments.
- **Every new route, setting and migration is accounted for:**
  - each new route gets a coverage-ledger row: `python docs/hardening/tools/campaign_slices.py --check all` exits 0;
  - each new setting is in `config.py`, `docs/CONFIGURATION.md` (regenerate with `docs/hardening/tools/config_reference.py`),
    `backend/.env.example` and the production template (`test_configuration_contract.py` and
    `test_production_env_template.py` must stay green);
  - regenerate `frontend/src/types/api.generated.d.ts` when the API changes (the frontend's `verify-api-contracts` script
    tells you), and `docs/hardening/TENANCY-AND-PLANS.md` if anything a plan carries changes (`test_tenancy_doc_is_current.py`).
- **Branch and PR.**
  - Use the session's assigned branch.
  - Open a **draft** PR at the start (draft PRs skip the heavy CI jobs) and push after every finished phase.
  - One logical change per commit; each message says what and why.
  - Mark the PR ready only at the end.
- **Never merge, and never call the work finished, while CI is red.** Fix the cause, or prove it is unrelated and fix that
  first (the rule since Session I). The advisory `pip-audit` job is the one exception, and you will try to turn it green
  in Phase 1.
- **If cut off,** continue from the first unticked box in `STATE.md`. Never restart a phase that is ticked.
- **Usage discipline.**
  - At most two helper agents at a time, each with a narrow brief and a clear "done when".
  - Run long suites in the background. Keep command output short (`-q`, `--maxfail=5`, `| tail -50`).
  - Run the full backend and browser suites once at the end, or let CI run them on the ready PR.
- **The cut line.** Phases 1 to 3 are the must-haves. If usage gets tight in Phase 4 or later, finish the item in hand,
  push, write the hand-over (§11) and stop cleanly. Final session 2 copes with any item you did not reach: it skips it
  and says so.

## 2. Start-up

1. **Read, in this order:**
   - `CLAUDE.md`;
   - `docs/hardening/STATE.md` (the top three sections);
   - `docs/hardening/HANDOFF.md`: "Plan change: the two final sessions", then "Session J", "I", "H", "G", "F", the "Owner launch
     checklist", and "Website and payments session" for Dodo;
   - `docs/PRODUCT-NEXT.md`;
   - `docs/hardening/NEEDS-OWNER.md` from N-118 onward (skim), and N-140, N-145, N-146, N-158, N-159 and N-160 in full;
   - `docs/product/GST-CREDIT.md`, `docs/product/FLAGSHIP.md`, `docs/helm/VISUAL.md`, `docs/automation/README.md`;
   - `docs/billing/DODO.md`;
   - `docs/RUNBOOK.md` §9, `docs/hardening/COSTS.md`, `docs/CONFIGURATION.md`;
   - `frontend/e2e/README.md`.
2. **Read the code** behind every row of the table in §0, plus:
   - the intake path: `document_intake_service.py`, the upload sessions, the upload tray;
   - the platform mail relay and `trial_notice.py` / `monthly_receipt_email.py` (the email pattern to reuse);
   - `plan_catalog.py`, `seed_quota_tiers.py`, `capability_gate.py`, `addon_gate.py` (who gets what);
   - the ERP posting pipeline end to end (`erp/service.py`, `transport/http.py`, `formats/tally.py`).
3. **Stand up the stack** as the STATE.md environment notes describe (Postgres 16 with pgvector 0.8, Redis, Python 3.12 venv,
   `npm ci`, the browser stack from `frontend/e2e/scripts/start-stack.sh`). Keep the environment block in the session
   scratchpad, outside the repo.
4. **Open the draft PR** and write this session's checklist at the top of `STATE.md`:
   - a "Current phase — Final session 1" section;
   - one box per phase item below;
   - the next free N-, F- and spec numbers.

## 3. Phase 0: the study (write it down before you change anything)

Write **`docs/hardening/UPGRADE-AUDIT.md`**: an honest, evidence-backed inventory of what has fallen behind. It is the map for
everything after it and a record the owner can read.

Look through each of these lenses. Give each finding a file and line, a one-line plain explanation, a severity
(P0 correctness or data, P1 money or trust, P2 polish), and the phase that fixes it.

1. **Data lifecycle.** For every table, decide whether it holds a document's content, a person's data or a money record.
   For each, ask whether erasure, the retention sweep, workspace and organization deletion, and the tenant export each
   handle it. Start from the §0 table and look for more (cases, obligations, TruthMesh, collab, packets, redaction jobs,
   assistant suites, batch items).
2. **Plans and add-ons.** For every capability and the three add-ons, ask whether each locked surface names the right plan
   or add-on, opens the right checkout, and shows a preview where the product promises one.
3. **New engines vs old surfaces.** For GST Credit, Helm, the value receipt and the new automation, ask whether search,
   notifications and the digest, Getting started, webhooks, the warehouse, the tenant export, the public API docs and the
   website each know about them.
4. **Outside providers.** For every provider name, model id, API version and SDK in the code, ask whether it is still
   current (check the provider's page today).
5. **Libraries.** Run `pip list --outdated` and `npm outdated`, read `pip-audit` and `npm audit`, and sort each upgrade
   into safe-now, needs-care or major (record the major ones; do not do them).
6. **Screens.**
   - Walk every route at 1440 px and 390 px, in light and dark.
   - Look for horizontal scrolling on a phone, empty states that say nothing useful, a raw error shown to a person, and
     loading states that jump.
   - Look for money not shown the Servabo way: INR with lakh grouping (`frontend/src/components/helm/money.ts`,
     `value_receipt._indian`); other currencies with their own symbol.
   - Look for a page that does not follow Lumen (Documents) or Night Bridge (Helm): `docs/helm/VISUAL.md`.
7. **Docs.** Look for any document that says something the code no longer does. PRODUCT-NEXT is the known one.

Finish Phase 0 with a **ranked list** at the end of the audit file. Then adjust the phases below:

- add what the study found that is P0;
- drop anything the study proves is already done;
- record each change in STATE.md.

Do not let the study eat the session: about one tenth of it at most.

## 4. Phase 1 (P0): correct and current

### 1A. Data lifecycle: one registry, and a test that keeps it complete

**Why it earns money:** larger Indian customers now ask about the DPDP Act 2023, and every enterprise questionnaire asks
"what happens to our data when we delete it or leave". A truthful answer closes deals; a wrong one loses them.

- **Build one registry** (for example `backend/app/services/compliance/data_map.py`). It names every table that holds a
  document's content, a person's data or a money record. For each table it says what erasure, the retention sweep,
  workspace and organization deletion, and the tenant export each do with it.
- **Write a test that compares the registry with the database's real tables** (from the models' metadata). It fails when
  a table holding a `work_item_id`, a `user_id`, a free-text column or a JSON payload has no entry. **A new table without a
  decision then fails the build** for every future session.
- **Decide, and record as N-numbers:**
  - Content that quotes or copies the erased documents goes with them: automation traces' condition values, notification
    bodies, outbox and webhook-delivery payloads, digest snapshots, Helm notes.
  - Money records the law makes the organization keep stay: the GST books and matches, Helm ledger amounts and
    `invoices`. Indian GST law requires books for 72 months; check the section and cite it.
  - A kept record loses every person's name and every free-text field that came from the erased content.
  - A **GSTIN embeds a PAN.** For a sole proprietor that is personal data. Decide what a kept row keeps.
- **Fix erasure, the retention sweep and deletion to follow the registry,** test-first. Write one failing test per store:
  "a trace still holds the erased invoice's amount", and so on.
- **The tenant export bundle** gains the GST books and matches, the Helm ledger and mandates, the automation rules (as JSON
  a person could re-import), the field corrections, and the entities and cases.
  - Respect the existing row limits and residency rules.
  - The export is a promise customers rely on when they leave, so test its contents.

### 1B. Outdated AI models and provider lists

**Why it earns money:** a BYOK customer who picks a suggested model and gets an error thinks the product is broken.

- Check today's model lists on the providers' own pages: Google Gemini, OpenAI, Anthropic, Azure OpenAI, Mistral and Groq.
  Update `suggested_models` for each provider to models that are available now, with the date in a comment.
- **A saved routing policy that names a retired model** must give a plain message: "Google retired gemini-1.5-pro; choose
  another model". It must not give a raw provider 404. Write a test with the stand-in returning the provider's real "model
  not found" shape.
- **The model price book** (`seed_price_book.py`) and the BigQuery reconciliation map:
  - add the current models' token prices from the providers' price pages, with the date;
  - keep the old rows, because history must still cost correctly;
  - the margin and COGS tests stay green.
  This is Servabo's cost, not a customer price, so it is in scope.
- **The default platform model:** check that Groq still serves `openai/gpt-oss-120b`, and check its price. If not, pick
  the closest current model, record why, and update `.env.example`, CONFIGURATION.md and the seeds.
- **Remove `google-generativeai`** from the requirements if nothing imports it. Prove that with a search and the test
  suite. Update `test_image_requirements.py` if it lists packages.

### 1C. Libraries

- **Pillow 13 (N-159).**
  - Try the upgrade. Run the image, PDF rendering, OCR-stub, QR, redaction and thumbnail tests.
  - If `paddleocr`, `paddlex` or another pinned package refuses Pillow 13, keep 12.x, record exactly which package blocks
    it, and keep the advisory.
  - Real OCR cannot run here: list it as Final session 2's job (§11).
- **Safe-now upgrades only:** patch and minor versions whose changelogs show nothing breaking, for example SQLAlchemy 2.0.x,
  Alembic 1.x, pydantic 2.x with pydantic-settings, and the FastAPI family.
  - One library family per commit.
  - Keep `requirements.txt` and its `requirements-*.txt` partners consistent (Session I learned that a bump can need its
    partner pinned too).
  - Install the full set on Python 3.12 and run the suite.
- **Frontend:** minor and patch updates within the declared ranges. Keep `@playwright/test` pinned unless a bug forces it.
- **Out of scope** (record each in NEEDS-OWNER or PRODUCT-NEXT): Tailwind 4 (N-119), React or Vite majors, Python 3.13.
- **Goal:** the advisory `pip-audit` job green, or every remaining advisory explained in one line with the package that blocks it.

### 1D. Session J's leftovers

1. **The GST trigger's upgrade dialog** names the GST Credit add-on and offers it to a Developer organization, as the GST page
   does. Write a browser assertion in spec 116 or a new spec.
2. **Run-history reasons format INR with lakh grouping**, and other currencies their own way. Use one formatter shared with
   the builder's sentences, and write a backend test for the reason text.
3. **`{{trigger.local_date}}`** is accepted as an alias of `{{event.local_date}}`. If you decide against the alias, the error
   must name the right variable. Record the decision.
4. **Browser runs that share `frontend/dist`:** give each run its own build folder or port by default in the e2e scripts.
   Document it in `frontend/e2e/README.md`.

**Phase 1 is done when** every item has its tests, CI on the draft PR is green for the jobs that run on drafts, and STATE.md
is ticked. Push.

## 5. Phase 2 (P0): intake that turns a trial into daily use

### 2A. Zip upload (PRODUCT-NEXT #6)

**Why it earns money:** a customer with a backlog uploads one archive on day one, and sees the value receipt fill up before
the trial ends.

- The documents upload screen and the upload tray accept `.zip`.
- Each supported file inside becomes its own document through the **existing** intake path. Plan limits, file checks,
  processing, GST, Helm and the receipt all apply unchanged.
- **Reuse `batch.expand_archive` and its limits, and prove every limit with a test:**
  - total unpacked size, file count and nesting;
  - `../` path traversal and absolute paths;
  - symlinks and encrypted entries;
  - a zip bomb (a high compression ratio).
- `__MACOSX/` and `.DS_Store` are skipped silently.
- **A GSTR-2B JSON inside a zip is not a document.** It is skipped with the words "This looks like a GSTR-2B file: import it on
  the GST credit page", and a link to that page.
- The tray shows one parent item with per-file progress and a plain summary: "38 documents added, 2 skipped: not a supported
  file type".
- **Over the plan limit part-way:**
  - the files that fit are added;
  - the rest are listed as "not added: your plan's monthly limit" with the upgrade action;
  - nothing is half-added.
- **Tests:** backend tests for each case, and browser spec 118 with a real zip of three PDFs, one `.DS_Store` and one GSTR-2B
  JSON.

### 2B. Email-in (PRODUCT-NEXT #1)

**Why it earns money:** accounts-payable teams live in a shared inbox. Forwarding invoices to Servabo is the feature most likely
to turn a trial into daily use. Every document that arrives this way feeds GST Credit, Helm and the receipt with no extra work.

**Decide and record** (defaults given; change them only with a reason):

- **The provider is Postmark inbound,** because Servabo already plans to send through Postmark (N-027).
  - Read Postmark's inbound documentation today: the webhook JSON, `MailboxHash`, the 403-stops-retries rule, the retry
    schedule, and how the webhook should be secured.
  - Postmark documents **HTTP basic auth in the webhook URL** rather than a signature. Implement that: a long random
    credential, compared in constant time.
  - Also allow an optional IP allowlist setting, if Postmark publishes its inbound IPs.
- **Addresses must work before the owner has a domain.** Route on Postmark's `MailboxHash`:
  - without a domain: `<postmark-inbound-hash>+<workspace-token>@inbound.postmarkapp.com`;
  - after the domain exists: `<workspace-token>@in.<your-domain>`.
  The workspace token is long, random and rotatable. **Never use the workspace's name or slug.** After a rotation the old
  token stops working, and mail to it is refused with 403 so Postmark stops retrying.
- **Senders:** only the workspace's allowed senders or domains are accepted directly. Mail from anyone else is **held** for an
  admin to approve, and the admin is notified. Nothing is ever silently dropped.
- **Plans:** email-in is on every plan, the trial included, and counts exactly like uploads. Over the limit, or in the
  trial's read-only state, the message is held with a notice.

**Build:**

- **A public route** for the inbound webhook.
  - It keeps a request size limit and is idempotent on Postmark's `MessageID`.
  - It answers 200 to a duplicate, and 403 to an unknown or rotated address. Write down which other codes it uses and why.
  - It is rate limited. It never echoes the credential, and never logs a body or an attachment.
- **Attachments** go through the existing intake path, with the sender, the subject and the received time kept as the
  document's source. The document screen shows "Arrived by email from …".
  - A zip uses 2A's path.
  - A GSTR-2B JSON is held with 2A's message.
  - Inline images under a small size (signatures and logos) are ignored. Record the threshold.
  - A message with no usable attachment is listed as held, with the reason "no attachment Servabo can read".
- **The settings page** (workspace → Email-in):
  - the address with a copy button;
  - Rotate, using the in-app `ConfirmDialog` and **never a native pop-up**;
  - the allowed senders and domains;
  - held messages with Approve and Discard;
  - recent arrivals.
- **New settings:**
  - `POSTMARK_INBOUND_WEBHOOK_USER` and `POSTMARK_INBOUND_WEBHOOK_PASSWORD` (empty means email-in is off);
  - `INBOUND_EMAIL_DOMAIN` (empty means the `inbound.postmarkapp.com` form);
  - `POSTMARK_INBOUND_HASH`.
  Pick clear names and keep them consistent; the ones above are suggestions.
- **Tests:**
  - a stand-in Postmark posts real-shaped JSON (copy the shape from the docs) with a PDF, a zip and a GSTR-2B;
  - plus a wrong credential, an unknown token, a rotated token, a disallowed sender, a replayed `MessageID`, an oversize body,
    over the plan limit, and the read-only trial;
  - **one test proves the chain:** an emailed GST invoice appears in the GST books, and in Helm's ledger when Helm is on;
  - browser spec 119 covers the settings page, rotate and approve-held.
- **Docs:**
  - RUNBOOK: Postmark's inbound server, the webhook URL with its credential, the `MailboxHash` form now, the MX record for
    `in.<domain>` later;
  - a new owner launch-checklist step after step 5;
  - one honest line on the website's product page and the accounts-payable page.

### 2C. Getting started: "first money found"

**Why it earns money:** a trial converts when the customer sees money found in their own documents. Today the checklist
stops at "ask a question".

- The checklist becomes a short path to the first finding. Each step links to the exact place and ticks itself from real
  data, never from a click:
  1. add documents: upload, a zip, or forward to the email-in address (shown with a copy button);
  2. see them read;
  3. import a GSTR-2B (on plans where GST Credit is a preview, the step shows the preview and says what the add-on or plan
     unlocks);
  4. open Helm with the sample company, or with your own invoices on plans that have Helm;
  5. turn on one recipe;
  6. invite a teammate.
- When the value receipt has its first non-zero figure, the checklist says so in one line with the amount (the receipt's
  own honesty rules), and links to the receipt.
- It can be dismissed and brought back. Members see only the steps they can do.
- **Tests:** a unit test for each step's tick rule, and a browser spec on a fresh trial organization.

**Phase 2 is done when** zip and email-in work end to end against the stand-ins, Getting started ticks from real data,
everything has its tests, and the records are updated. Push.

## 6. Phase 3 (P1): reasons to stay and reasons to upgrade

### 3A. GST weekly digest and a GST notification category

**Why it earns money:** it keeps GST Credit, and its add-on, in front of the owner every week. Without it the add-on is
something a customer forgets they pay for.

- **A new notification category, "GST credit",** optional and on by default. Its audience is organization owners, admins
  and the billing role (like Helm's).
- **In-app notices** for:
  - a GSTR-2B import finishing;
  - an invoice crossing into the last 30 days of its 180-day window;
  - a supplier who has not filed by the 14th, when Servabo has their invoices;
  - IMS actions pending before the filing date.
  Each notice is sent once, through the existing notification service. Emailed only as warnings, following the existing
  rule.
- **The Monday digest email** (reuse the monthly summary's email block and its mail-client checklist):
  - this week's ITC at risk;
  - suppliers not reported;
  - deadlines in the next 30 days;
  - pending IMS actions;
  - one link to the GST page.
  Sent only when there is something to report, in INR with lakh grouping.
- **Where GST Credit is only a preview** (Developer without the add-on, and the trial), the digest shows the totals alone,
  with "Unlock the lists: GST Credit add-on, $49 a month". This follows exactly the preview rules the GST page already uses,
  and never shows more than the preview shows.
- **Tests:**
  - the selection rules with a controlled clock;
  - the preview variant;
  - opt-out;
  - the audience;
  - "nothing to report sends nothing".
  Add a `run-job` entry so Final session 2 can send one to a real inbox (`backend/scripts/e2e_stand_in.py run-job …`).

### 3B. Upgrade moments, everywhere

**Why it earns money:** every locked feature is a sales moment. A lock that names the wrong plan, or leads nowhere, loses the
sale.

- **List every locked surface:** each capability gate and add-on gate the frontend can hit (start from `capability_gate.py`,
  `addon_gate.py` and the frontend's upgrade components).
- **Write one test (backend or Vitest) that walks the list.** For each surface it checks that:
  - the right plan or add-on is named;
  - the action opens the right checkout (plan or add-on);
  - an owner sees Upgrade, and a member sees "Ask your owner".
- **The 80% usage email and banner:** offer "add seats" or "upgrade" with one click to the right place.
- No price, plan or allowance changes (§1).

### 3C. Zoho Books "Connect", and Tally Prime made easy (PRODUCT-NEXT #5, retargeted to India)

**Why it earns money:** "invoice received → bill entered in my books" is what Indian SMBs pay for, and it is the strongest
reason to choose Business over Developer. QuickBooks left India in 2023. Zoho Books and Tally are what these customers use.

**Zoho Books with sign-in (OAuth 2.0 authorization code):**

- Read Zoho's OAuth and Books API documentation today: the data centres and their accounts and API hosts (India
  `accounts.zoho.in`, plus `.com`, `.eu` and the others), scopes, refresh tokens, the organization id, and the bills
  endpoint with its GST fields. Cite them.
- **"Connect Zoho Books"** on the ERP targets page:
  - choose the data centre (India by default);
  - Zoho's consent screen opens;
  - the callback stores an encrypted refresh token using the existing secret encryption (and its rotation sweep);
  - pick the Zoho organization;
  - done.
  The OAuth `state` parameter is signed, single-use and short-lived, and bound to the workspace and the person. The redirect
  URI comes from settings.
- **Disconnect** revokes the token at Zoho where the API allows it, and forgets it here. **A refused or expired token**
  shows "Reconnect Zoho Books", never a raw error, and the posting waits rather than fails silently.
- **Bills carry the GST fields Zoho Books expects** (the vendor's GSTIN, the place of supply, the tax heads and HSN on the
  lines), mapped from the finance schema. Use the existing preset and posting pipeline, so exactly-once delivery,
  approvals and the ledger stay as they are.
- **New settings:** `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET` and `ZOHO_REDIRECT_URI` (empty means the button explains how to
  turn it on).
- **Tests:**
  - a stand-in Zoho (accounts plus Books) for the consent round trip, a forged or replayed `state`, token refresh, a revoked
    token, a bill accepted, a bill refused with Zoho's real error shape, and the data-centre hosts;
  - one browser spec covering connect through the stand-in.

**Tally Prime, guided:**

- A "Tally Prime" preset card that sets up the existing download transport in three plain steps:
  1. name your ledgers (party, purchase, CGST, SGST, IGST);
  2. approve bills;
  3. download the import file, and import it in Tally with Gateway of Tally → Import → Vouchers.
- The GST ledgers are mapped from the tax heads. The file validates against the existing XSD.
- **Tests:** a backend test that a GST bill's voucher balances, with the tax ledgers split correctly for intra-state
  (CGST + SGST) and inter-state (IGST).

Both stay on Business and Enterprise (`capability.erp_posting`), exactly as ERP posting is today. **Record as `OPEN` whether
the Tally file should also come to Developer;** it is a pricing question.

### 3D. Show where an e-invoice value came from (N-140)

- On the document screen, each field read from the e-invoice QR code shows a small badge: "From the e-invoice QR code".
  The IRN is shown with a copy button.
- **The signature line:**
  - "signature not checked" when NIC's key is not configured (today);
  - "signature checked" when `EINVOICE_QR_PUBLIC_KEY_PEM` is set and the signature verifies;
  - "signature does not match" in the warning colour when it fails.
- If the model's value differs from the QR's value, both are shown and the QR's value is preferred. Follow whatever
  Session F decided, and record it if it was never decided.
- **Tests:** the three signature states (generate a key pair in the test), and an axe check of the badge in light and dark.

**Phase 3 is done when** all four have their tests and the records are updated. Push.

## 7. Phase 4 (P1): the owner can run it

### 4A. Error tracking (PRODUCT-NEXT #4)

**Why it earns money:** every support conversation gets shorter. The owner sees *which line failed, for whom, how often*
before the customer finishes typing.

- **Sentry's free plan in its EU data region.** Check the current free-plan limits on Sentry's pricing page and record them
  in COSTS.md. The SDK also speaks to **GlitchTip** (self-hosted, free), so the owner can switch by changing one setting.
  Write the trade-off in plain words.
- **Wire it to:**
  - the API;
  - every worker loop, including `receipt.monthly`, the GST recompute, the new GST digest and the OCR worker's QR reading;
  - the email-in handler;
  - the web app.
- **Settings:**
  - `SENTRY_DSN` (backend) and `VITE_SENTRY_DSN` (frontend). **Empty means off.**
  - The environment, the release (image tag or git SHA), and a traces sample rate that defaults to 0.
- **Privacy (test it):**
  - `send_default_pii` is off;
  - a `before_send` strips emails, tokens, API keys, cookies, `Authorization` headers, request bodies, query strings with
    secrets, document text and extracted field values (GSTINs, PANs, invoice numbers, amounts and bank accounts from
    documents), and email-in sender addresses;
  - organization and workspace ids are kept, as opaque UUIDs.
- **What is sent:** 5xx errors and unhandled exceptions only. Expected 4xx are not sent.
- **The production guard:** optional. When a DSN is set it must be https.
- **CSP:** if the web app's CSP must allow the ingest host, derive it from the DSN, and keep the CSP tests green.
- **Tests:** a stand-in ingest receives one event from the API, one from a worker and one from the web app, with every
  listed field stripped. A browser check proves the web app sends nothing when the DSN is empty.
- **Docs:** RUNBOOK (create the project in the EU region, paste the DSN), the env templates, CONFIGURATION.md, COSTS.md.

### 4B. `backend/scripts/preflight.py`: one command that says whether a setup is ready

**Why it earns money:** a launch that fails on a missing setting costs the first customers. Final session 2 and every
deploy will run this.

- **`python scripts/preflight.py`** reads the settings exactly as the app does and prints a plain table: each item **OK**,
  **MISSING**, **WRONG** or **SKIPPED**, with a one-line fix and where to click.
- **It never prints a secret.** At most it says "set" and gives the last four characters of a public id.
- **What it checks:**
  - the environment and URLs (https in production; `FRONTEND_URL` and `WEBSITE_URL`);
  - the database, Redis and storage (including R2 and its jurisdiction setting);
  - the mail relay;
  - Groq, Gemini and BYOK encryption keys;
  - Dodo: test or live consistent with the keys, the eight product ids present, the webhook secret set;
  - email-in, Zoho and Sentry;
  - the backup key file, `ALERT_WEBHOOK` and `OPERATOR_ALERT_EMAILS`;
  - the NIC key (optional);
  - the CPU-only image setting.
- **Modes:**
  - **`--offline`** (the default) checks configuration only and contacts nothing.
  - **`--online`** makes read-only calls: list Dodo products, list Groq models, an SMTP login without sending, a storage
    head-bucket, a Sentry DSN parse and a Postmark server read.
  - **`--send-test-email you@example.com`** sends exactly one message.
  - It refuses to run `--online` against live Dodo keys unless `--i-mean-live` is given, and even then it only reads.
- **Exit codes:** 0 for ready, 1 for not ready. A `--json` flag gives machine-readable output.
- **Tests:** each check with the stand-ins, and "no secret ever appears in the output" across every mode.
- **Docs:** RUNBOOK §9 (run it before the first start and after every change of settings), and the owner launch checklist
  step 7.

**Phase 4 is done when** both have their tests and docs. Push.

## 8. Phase 5 (P1/P2): every screen up to date

1. **An accessibility sweep.**
   - One new browser spec visits every route a signed-in owner can open (generate the list from the router, so a new page
     is included automatically). It runs axe in light and dark, and in Helm's Night Bridge for Helm routes.
   - Fix every serious and critical violation. Record any you leave, with the reason.
2. **The phone pass.** On every route at 390 px:
   - no horizontal page scroll;
   - wide tables scroll inside their own container;
   - dialogs fit the screen.
   Assert the "no horizontal scroll" part in the same sweep spec.
3. **Money, one way.** Use one formatter for every place money is shown (INR in lakh and crore grouping with ₹; other
   currencies with their own symbol). Add a small self-check (in `check:self`) that refuses `toLocaleString("en-US"` and
   hand-built `"INR " +` strings in components, with an allowlist for the formatter itself.
4. **States.** Empty, loading and error states use the shared components, and say what to do next in plain words. **No raw
   error text reaches a person.** Fix the worst pages the study found, not every page.
5. **Search.**
   - Global search also finds GST suppliers (by GSTIN or name), invoices in the GST books (by invoice number) and
     automation rules (by name).
   - Each result respects workspace scope and plan. Locked results show nothing.
   - Write tests, including the second-workspace refusal the route sweeps use.
6. **The website.**
   - The product page, the accounts-payable page and the GST credit page get one honest line each about zip upload,
     email-in, the GST digest and the Zoho Books and Tally connections.
   - Refresh the screenshots with `website/scripts/capture-screenshots.mjs`.
   - Website typecheck and checks stay green.

## 9. Phase 6 (P2): integrations for bigger customers (only if Phases 1 to 5 are green)

- **Public webhook events:** `gst.return.imported`, `gst.invoice.at_risk` (the 180-day window), `gst.supplier.not_reported`,
  `automation.run.failed` and `automation.run.held`.
  - Document their payloads in the developer docs.
  - Payloads carry ids and figures, never document text.
  - Every emitter announces each event once, following Session J's `emit_once` pattern.
- **Warehouse datasets** (Enterprise): the GST matches and the Helm ledger, following the existing dataset contract and its
  tests.
- **Document packs that do everything they promise (PRODUCT-NEXT #10, F-408):**
  - enabling a pack proposes its suggested checks in Clause assertions, one click to accept each;
  - starting a redaction of that document type pre-selects the pack's redaction profile;
  - the card stops saying "not applied yet".

## 10. Rewrite `docs/PRODUCT-NEXT.md`

Make it true today, then make it useful for after launch.

- **A status line on every existing item:**
  - #1, #4 and #6: done in Final 1;
  - #2: not applicable while Dodo bills hard limits (N-118);
  - #3: done (yearly prices; the owner creates them in Dodo);
  - #5: Zoho Books Connect and Tally guided, done in Final 1; Xero and QuickBooks Online later, for other markets;
  - #7 and #8: not started;
  - #9: done earlier (`f53ccc8`);
  - #10: done, or not, depending on Phase 6.
- **Replace every Stripe-specific instruction** with the Dodo equivalent.
- **A new ranked list for after the first customers,** each with "why it earns money", build days and running cost:
  - **CA firms as a channel:** one chartered accountant manages GST for 20 to 200 small clients. A multi-client GST view
    built on the existing partner and reseller tenancy (ARCH-27) could make each CA a reseller.
  - **WhatsApp-in:** Indian suppliers send invoices on WhatsApp. It needs Meta's Business API, a cost and a verification;
    write down what it takes.
  - **An annual price and a rupee price for the GST Credit add-on** (Session H).
  - **Premium models as credits** (#7).
  - **The automation Wait step** (N-154).
  - **Benchmarks** (#8), only with enough customers.
  - **Tailwind 4** (removes N-119).
- **Change the closing recommendation** to the next one or two items after launch.

## 11. The hand-over to Final session 2 (write it with care)

Final session 2 runs on the owner's Windows PC, with the owner present, and connects the real accounts. It trusts this
section. Add a section **"Final session 1 → Final session 2"** to `docs/hardening/HANDOFF.md` containing:

1. **A table: "What Final session 2 must try for real".** One row per outside connection or real-world behaviour you built
   or changed:
   - the feature;
   - the setting names;
   - exactly how to turn it on locally;
   - the stand-in that proved it here;
   - what a real success looks like on screen or in the inbox.

   At least these rows:
   - email-in through a real Postmark inbound server and a tunnel;
   - Sentry receiving from the API, a worker and the web app;
   - Zoho Books Connect against a real free Zoho Books organization (India data centre);
   - the Tally file imported into Tally Prime (the free Educational mode is enough);
   - the GST digest in a real inbox;
   - Pillow 13 (or 12.x) with real PaddleOCR on scans;
   - the updated model lists with real Groq and a real Gemini key;
   - `preflight.py --online`;
   - the QR badge with a real e-invoice (and NIC's key, if the owner has it).
2. **Every new `run-job` or `e2e_stand_in.py` command** Final session 2 can use, and what each is for. Say which ones must
   only ever run on a throwaway organization.
3. **What you did not reach,** in the order you would do it next.
4. **What is unverified,** in plain words.

Also update the top of `docs/hardening/STATE.md` with the next action: "Final session 2 on the owner's PC".

## 12. Finish line

- **Phases 1 to 3 done and tested.** Phases 4 to 6 as far as usage allowed, each item either done with tests or listed as not
  reached.
- `pytest -q`, the frontend's typecheck, lint, `check:self`, `test:unit` and build, and the full browser suite pass, locally
  or on the ready PR's CI.
- `campaign_slices.py --check all` exits 0. There is one Alembic head, with up, down and up in CI.
- **Records updated:**
  - `docs/hardening/UPGRADE-AUDIT.md`;
  - `FINDINGS.md`, `COVERAGE.csv`, `STATE.md`, `HANDOFF.md` (§11), `NEEDS-OWNER.md`;
  - `PRODUCT-NEXT.md`, `CHANGELOG.md`, `RUNBOOK.md`, `CONFIGURATION.md`, the env templates, `COSTS.md`;
  - the website;
  - `docs/automation/README.md`, if automation changed.
- **Mark the PR ready.** The PR description explains, for a non-engineer:
  - what changed;
  - why each change earns money or protects it;
  - what Final session 2 will try.
- **CI is green before the owner merges.** Then stop, and tell the owner in five lines or fewer what was built, what was
  fixed and what Final session 2 will check.
