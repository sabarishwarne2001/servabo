# Upgrade audit — Final session 1 (2026-10-22)

_Written before any code changed. Plain-language map of what has fallen behind since the last full review, with the file and line
that proves each point, a severity and the phase that fixes it. Severity: **P0** = correctness or data, **P1** = money or trust,
**P2** = polish. Finding numbers continue the campaign's list (F-546 onward)._

How to read a row: *what we found* (plain words) → *evidence* (file:line, or the command that showed it) → *fixed in*.

## 1. Data lifecycle (what happens to a customer's data when it is erased, expires or the customer leaves)

The product has **234 tables** (`Base.metadata`, counted with `scripts` introspection on 2026-10-22). Before this session no single
place said, for each table, what erasure, the retention sweep, deleting a workspace or an organization, and the data export do with
it. Four routes existed, each with its own hand-written list.

| # | Sev | Finding | Evidence | Fixed in |
| --- | --- | --- | --- | --- |
| F-546 | P0 | **Erasing a person's documents leaves copies of their content behind.** Erasure blanks the document's text, entities, chunks, exemplars, corrections and payment-risk flags but keeps the document row, so the `ON DELETE CASCADE` rules never run. What survives with no rule of its own: the GST match and decision rows (they quote the invoice's supplier, number and amounts), Helm promises, settlements and actions, automation execution traces (a trace records the value each condition read), the outbox and webhook-delivery payloads (JSON copies of events), notification bodies, and Helm tasks and notes. | `erasure_service.py:277-385` (`_destroy_documents` lists nine stores, none of these); `models/gst.py:67-71` (`_work_item_fk`, CASCADE); `models/helm.py:80,337` (composite FKs); `models/automation_execution.py` (SET NULL) | 1A |
| F-547 | P0 | **The retention sweep does the opposite: it deletes the document row, so the same CASCADE rules silently delete money records.** `gst_matches`, `gst_decisions`, `helm_promises`, `helm_settlements`, `helm_value_events`, `helm_actions`, `helm_tasks` and `helm_cash_positions` all cascade from `work_items`. A customer who sets "purge documents after 2 years" therefore loses the GST match results and the Helm ledger rows Indian law (and the customer's accountant) expects to be kept. Meanwhile `automation_executions` (SET NULL) keeps the values its conditions read, and `outbox_events`, `webhook_deliveries` and `notification_deliveries` payloads are never touched. | `sweep_compliance.py:88-211` (`_purge_work_items` ends with `DELETE FROM work_items`); the FK list printed by the introspection (about 30 foreign keys to `work_items` are CASCADE, 6 are SET NULL) | 1A |
| F-548 | P0 | **"Delete organization" and "delete workspace" only archive.** `archive_organization` sets `status = ARCHIVED` and turns off API keys; `archive_workspace` does the same. Nothing ever removes the data afterwards, so the honest answer to the enterprise question "what happens to our data when we leave" is "it stays". | `organization_service.py:377-420`; `workspace_service.py:400`; no script in `backend/scripts/` purges an archived organization | 1A |
| F-549 | P0 | **The data export is missing most of what a customer owns.** The bundle has members, workspaces, documents (metadata only), conversations, messages, audit logs, invoices. It has no GST books or matches, no Helm ledger or mandates, no automation rules, no field corrections, no entities, no cases, no obligations. A customer leaving takes less than they put in. | `export_service.py:84-278` (eight sections) | 1A |
| F-550 | P1 | **GSTIN embeds a PAN.** For a sole proprietor, a GSTIN (kept in GST books) is that person's personal data. No rule says what a kept row keeps after erasure. | `models/gst.py` (`supplier_gstin`); decision N-161 | 1A |
| F-551 | P0 | **No test notices a new table.** Sessions F, J and Helm added about 40 tables; none was asked "what does erasure do with you". The registry plus its completeness test (new in 1A) makes a table without a decision fail the build. | `tests/` has no test comparing models with the erasure code | 1A |

## 2. Plans and add-ons

| # | Sev | Finding | Evidence | Fixed in |
| --- | --- | --- | --- | --- |
| F-552 | P1 | **The upgrade dialog of the GST trigger names plans but not the GST Credit add-on** (Developer should be offered the $49 add-on, as the GST page does). `onUpgrade` receives the capability, not the add-on key. | `RecipeGallery.tsx:28,239` and `TriggerCard.tsx` (`onUpgrade(capability, feature)`); HANDOFF "Session J" | 1D |
| F-553 | P1 | **No test walks every locked surface** to prove it names the right plan or add-on and opens the right checkout; each session checked its own. | no such test under `backend/tests` or `frontend/src` | 3B |

## 3. New engines against old surfaces

| # | Sev | Finding | Evidence | Fixed in |
| --- | --- | --- | --- | --- |
| F-554 | P1 | **GST Credit sends nothing.** There is no notification category for it; an unfiled supplier or a 180-day deadline is visible only to someone who opens the page. | `notification_preferences_service.py:28-37` (categories: security, billing, usage, workflow, monthly summary, Helm, Helm briefing); no call to `notification_service` anywhere under `services/gst/` | 3A |
| F-555 | P2 | **Global search cannot find a GST supplier, a GST invoice or an automation rule.** It queries documents, entities and cases only. | `global_search_service.py:119-159` | 5 |
| F-556 | P1 | **Getting started stops at "ask a question".** Nothing leads a new customer to GST Credit, Helm or a recipe: the places where Servabo finds money. | `components/onboarding/GettingStarted.tsx` | 2C |
| F-557 | P2 | **No public `gst.*` or automation-run webhook events; the warehouse has no GST or Helm dataset.** | `core/webhook_events.py`; `services/analytics/export_engine.py` | 6 |
| F-558 | P1 | **Zip upload exists in the worker but nothing queues it and the upload screen refuses `.zip`.** | `workers/handlers/__init__.py:578` registers `batch.expand_archive`; its name appears only in `workers/profiles.py:152` and the handler table, never in an enqueue call; `UploadDropzone.tsx` accept list | 2A |
| F-559 | P1 | **Nothing receives email.** Accounts-payable teams live in a shared inbox. | no inbound-mail route anywhere under `app/api/v1/` (public routes: `public_document_requests.py`, `public_calendar_feeds.py`, `public_pricing.py`, `public/gateway.py`) | 2B |
| F-560 | P1 | **No error tracking.** Operator alerts say *that* something failed, not *where*. | `grep -ril sentry backend/app frontend/src` finds only cost-line names in `schemas/cogs.py`; no SDK, no DSN setting | 4A |
| F-561 | P1 | **ERP OAuth is "paste your client id, secret and refresh token"** — no Connect button, no consent screen. | `services/erp/presets.py` (`OAUTH2_REFRESH_TOKEN`) | 3C |
| F-562 | P2 | **Nothing on screen shows a value came from the e-invoice QR code**, or whether its signature was checked. | `services/gst/` stores it in the extraction metadata; the document viewer never reads it (N-140) | 3D |
| F-563 | P1 | **No one command says whether a setup is ready.** A launch can fail on a missing setting. | no `scripts/preflight.py` | 4B |

## 4. Outside providers and libraries

| # | Sev | Finding | Evidence | Fixed in |
| --- | --- | --- | --- | --- |
| F-564 | P1 | **BYOK suggests retired models.** Gemini: `gemini-2.0-flash`, `gemini-1.5-pro`, `gemini-1.5-flash`. OpenAI and Azure: `gpt-4o`, `gpt-4o-mini`, `o3-mini`. A customer who picks one and gets a raw provider 404 thinks the product is broken. | `byok_providers.py:212-290` | 1B |
| F-565 | P1 | **The BigQuery cost-reconciliation map names only 1.5, 2.0 and 2.5 models**; a current model's bill line would not map to a price-book row. | `reconciliation/gemini_bigquery.py:24-33` | 1B |
| F-566 | P2 | **`google-generativeai` (deprecated) is installed but nothing imports it** (only comments mention it); `google-genai` is what the code uses. Removing it drops one old dependency chain (`google-ai-generativelanguage`). | `grep -rn "generativeai" app scripts tests` finds comments only; `requirements.txt:49`, `requirements-web.txt:38` | 1B |
| F-567 | P1 | **pip-audit finds 30 advisories**: Pillow 12.3.0 (ten, fixed in 13.0.0), pypdf 6.19.0 (five, fixed in 6.21.1), certifi 2026.6.17 (fixed in 2026.10.19). | `pip-audit -r requirements.txt --no-deps` on 2026-10-22 | 1C |
| F-568 | P2 | **Old pins:** `alembic==1.13.1` (1.20.1 available), `SQLAlchemy==2.0.28` (2.0.x current), `pydantic==2.10.6` (2.14.1), `pydantic-settings==2.7.1` (2.16.1), FastAPI 0.136.3 (0.159.1), starlette 1.7.0 (1.9.0). Majors (SQLAlchemy 2.1, openai 3, anthropic 2, mistralai 3, google-genai 2, torch) are recorded, not done. | `pip list --outdated` on 2026-10-22 | 1C |
| F-569 | P2 | **Frontend:** `npm audit` reports 11 (2 critical, 6 high) on all dependencies, **0** on what ships (`--omit=dev`). The build-tool ones sit under Tailwind 3 (N-119) and the test tooling. Many minor updates are available inside the declared ranges. | `npm audit`, `npm outdated` on 2026-10-22 | 1C |

## 5. Session J's leftovers

| # | Sev | Finding | Evidence | Fixed in |
| --- | --- | --- | --- | --- |
| F-570 | P2 | **Run-history reasons use Western grouping** ("INR 1,250,000.00") where the builder uses lakh grouping. | evaluator reason text (`services/automation/`) | 1D |
| F-571 | P2 | **`{{trigger.local_date}}` is refused** while `{{event.local_date}}` works. | HANDOFF "Session J" | 1D |
| F-572 | P2 | **Two Playwright runs that share `frontend/dist` wipe each other's bundle.** | `frontend/e2e/scripts/`, `README.md` | 1D |

## 6. Screens, accessibility, docs

| # | Sev | Finding | Evidence | Fixed in |
| --- | --- | --- | --- | --- |
| F-573 | P1 | **axe runs in 11 of 99 browser spec files.** Most pages have never had an accessibility check in dark mode. | `grep -l axe frontend/e2e/tests/*.ts \| wc -l` = 11 of 99 | 5 |
| F-574 | P2 | **Money formatting has no guard.** `helm/money.ts` and `value_receipt._indian` exist, but nothing stops a component from writing `toLocaleString("en-US")` or `"INR " + n`. | no such `check:self` rule | 5 |
| F-575 | P2 | **`docs/PRODUCT-NEXT.md` says things the code no longer does** (Stripe and QuickBooks for India; "correct a field beside the page" unbuilt although `f53ccc8` built it). | `docs/PRODUCT-NEXT.md` | 7 |

Screens (route-by-route at 1440 and 390 px, light and dark) are measured in Phase 5 by a spec that visits every route generated from
the router; its findings are appended below in "Phase 5 results".

## Ranked list (what is done first, and why)

1. **F-546, F-547, F-548, F-549, F-550, F-551** (data lifecycle): P0, and the answer to every enterprise questionnaire. One registry and a test that keeps it complete.
2. **F-567 libraries** (Pillow, pypdf, certifi): P1, the advisory CI job, quick.
3. **F-564, F-565, F-566 models**: a BYOK customer's first experience.
4. **F-570 to F-572 and F-552** (Session J's leftovers): small and visible.
5. **F-558, F-559** (zip, email-in): the feature most likely to turn a trial into daily use.
6. **F-556** (Getting started), **F-554** (GST digest), **F-553** (upgrade moments), **F-561** (Zoho, Tally), **F-562** (QR badge).
7. **F-560, F-563** (error tracking, `preflight.py`): the owner can run it.
8. **F-573 to F-575** and the rest of Phase 5, then Phase 6 (F-557).

**Changes to the plan from the study.** Added to 1A (P0): the organization and workspace purge (F-548) and the keep-or-destroy decision for money
records (F-547), because the study found the retention sweep *destroys* what the brief says must be kept. Added to 1C: pypdf and certifi.
Nothing in the brief was found already done, except that `google-generativeai` is unused (F-566) and PRODUCT-NEXT #9 and #3 are built.

## Found while building (Phase 2 onward)

Bugs the walk-through tests found. Each has the failing test that proved it and the fix, in the same commit (evidence rule).

| # | Sev | Finding | Proof (test that failed first) | Fixed in |
| --- | --- | --- | --- | --- |
| F-576 | P1 | **A plan lock reached from a button raised the "you are out of quota" banner.** The client let `ADDON_REQUIRED` through to the page but sent `CAPABILITY_REQUIRED` to the quota banner, so a customer who simply needed a higher plan was told they had run out of something. | `frontend/src/services/api/client402.test.ts` (`CAPABILITY_REQUIRED does not raise the quota banner`) | 3B |
| F-577 | P1 | **A billing contact was offered "View plans" / "See plans" and "Add GST Credit" where only an owner can buy.** F-192 made the Billing page owner-only for plan, payment method and seats, but the lock dialog, the lock banner, the "View plans" action and four Helm banners still offered the upgrade to the BILLING role, who then arrived at a page that said "Only an organization owner can change the plan". The sale stalled with the person who cannot close it. | `frontend/src/components/billing/upgradeMoments.test.tsx` (role BILLING, 32 surfaces) | 3B |
| F-578 | P2 | **The server's plan refusal did not name the plans.** `CAPABILITY_REQUIRED` said "is included on higher plans"; the body now carries `included_in` and the message names them ("the Business and Enterprise plans"). | `backend/tests/api/test_upgrade_moments.py::test_the_refusal_for_a_capability_names_the_plans_that_carry_it` (32 capabilities; `KeyError: 'included_in'` before) | 3B |
| F-579 | P2 | **The 80% usage email led to the top of the Billing page, the 80% banner had no way out (only the 100% banner had "Upgrade"), and nobody was warned that seats were nearly used.** Now: the email goes to the plan picker; the banner has "Upgrade"; owners and administrators are told at four of five seats and when every seat is taken, with "Add seats" (or "Choose a plan" where seats come with the plan). | `backend/tests/services/test_usage_limit_alerts.py` (5 new), `upgradeMoments.test.tsx` (80% banner) | 3B |
| F-580 | P1 | **Settings added in this session (and the earlier e-invoice key) never reached the production containers.** `docker-compose.prod.yml` passed only the variables it listed, so `ZIP_UPLOAD_MAX_MB`, the email-in settings, the archived-data purge settings and `EINVOICE_QR_PUBLIC_KEY_PEM` set in `.env` were silently ignored. Now passed with the settings' own defaults (and Zoho and error tracking). | script comparing `.env.production.template` names with the compose file: 17 missing before | 4A |

| # | Sev | Finding | Proof | Fixed in |
| --- | --- | --- | --- | --- |
| F-581 | P2 | **Organization names could be blank or padded with spaces.** | `test_org_console_general.py` | `7b54de2` |
| F-582 | P1 | **A retention period of billions of days crashed the save** (a database "integer out of range"), so the owner saw a server error. At most 100 years now. | `test_org_console_email_slo_compliance.py` (a DataError before) | `2834b00` |
| F-583 | P2 | **Transactional email accepted a server, user name or sender name made of spaces.** | `test_org_console_email_slo_compliance.py` | `c0bb141` |
| F-584 | P1 | **Moving a data region without the acknowledgement was accepted** when the field was simply left out, so the owner's "I understand existing files stay in the old region" was never recorded. | 200 before, 422 after | `05b4952` |
| F-585 | P2 | **A service-level target of billions crashed the save.** | `test_org_console_email_slo_compliance.py` | `86036b2` |
| F-586 | P1 | **A typo in a retention field (such as "9o") was saved as "keep forever"**, and a save gave no feedback. | spec 128 | `922495d` |
| F-587 | P2 | **A refused service-level target said only "failed".** | spec 128 | `0d36727` |
| F-588 | P2 | **An API key could be named with spaces only.** | `test_org_console_credentials.py` | `cc05d9e` |
| F-589 | P2 | **An API key accepted the same scope twice and an expiry in the past.** | `test_org_console_credentials.py` | `cc05d9e` |
| F-590 | P1 | **A webhook address with a user name and password in it was stored whole**, so the password would show in the console and in logs; a port of 99999 was accepted and could never work. | 201 before, 422 after | `99253c2` |
| F-591 | P2 | **Brand names could hold line breaks and control characters** (they reach emails and the browser tab). | `test_org_console_platform.py` | `7a70881` |
| F-592 | P2 | **An egress rule of digits and dots that is not an IP address was accepted.** | `test_org_console_platform.py` | `2c9c770` |
| F-593 | P2 | **The API keys page printed a generic failure and let a past date be picked for the expiry.** | spec 130 | `e1d7a8f` |
| F-594 | P2 | **Deleting a webhook endpoint left its delivery log open and asking for a page that no longer existed.** | spec 130 | `ab9e0f3` |
| F-595 | P2 | **A domain claim accepted an IP address, `.local`, a name starting with a hyphen, and a list (saved as the text "['a.com']").** None could ever be verified. | nine cases, 201 before | `ad77b96` |
| F-596 | — | Not used (the number was skipped while merging two findings into F-595). | | |
| F-597 | P2 | **Below the plan, the Developer platform page printed "The request log could not be loaded." after three refused requests** and never said the feature was not included. | spec 131 | `57458f6` |
| F-598 | P1 | **Administrators were told "Access restricted" on Enterprise identity although decision N-006 says they read it** and the sidebar offered it. Every write stays the owner's, on the server and in each panel. | spec 131; specs 89 and 100 now say what is true | `bbc68c9` |
| F-599 | P2 | **A refused domain claim showed a generic line instead of the server's reason.** | spec 131 | `f1fe4d8` |
| F-600 | P2 | **An audit-log end date before the start date was sent and returned nothing, with no explanation.** | spec 131 | `5f66b07` |
| F-601 | P2 | **The new-workspace and new-organization forms had no `main` landmark**, so a screen-reader user could not jump to the content. | spec 132 (axe) | `7a5a365` |
| F-602 | P2 | **The jobs console's tabs pointed at panels that did not exist, and its scrolling tables could not be reached with the keyboard.** | spec 132 (axe: critical `aria-valid-attr-value`, serious `scrollable-region-focusable`) | `7a5a365` |
| F-603 | P1 | **Raw server text reached people.** Eight screens put `error.message` into a toast, and a validation failure read like `body.name: String should have at least 1 character`. Now a server sentence for a refusal (4xx), a plain fallback for a fault (5xx), and a validation list turned into one sentence; `check:self` fails a new case. | `errors.validation.test.ts`; "no raw error text" guard | `66137c7`, `1443236` |
| F-604 | P2 | **Rupees were grouped in thousands on billing and revenue screens** (₹150,000.00) beside lakh grouping in Helm and GST (₹1,50,000.00), depending on the browser's language; nothing stopped a screen building its own money text. One formatter, and a guard. | `formatMoney.test.ts`; "money, one way" guard | `61397b5` |
| F-605 | P1 | **A new workspace had an empty initials badge where a logo should be**, and the logo itself was the old one. The new Servabo logo replaces it everywhere and is the default for any workspace without its own (or whose own will not load). **The artwork was supplied as a picture only: this is a vector recreation (see NEEDS-OWNER N-176).** | `defaultLogo.test.tsx`, spec 125 | `93ca674` |

## Status at the end of Final session 1

Every finding above F-581 came from the study; each is now **done** (the commit is in `git log` under its number, the proof is in the tests named in
FINDINGS.md), with these notes:

- **F-546 to F-551** (data lifecycle): done (1A). One registry, `data_map.py`, and a test that fails for a table without a decision.
- **F-552, F-553, F-577 to F-579** (plans and upgrade moments): done (1D, 3B).
- **F-554, F-556** (GST notices and the digest, Getting started): done (3A, 2C). The digest in a real inbox is unverified (HANDOFF).
- **F-555** (global search): done in Phase 5 (suppliers, invoices, workflows; spec 133 and the backend tests).
- **F-557** (webhook events, warehouse datasets): done in Phase 6 (migration k1a6, docs/product/WEBHOOK-EVENTS.md, `GST_MATCHES` and `HELM_LEDGER`).
- **F-558, F-559** (zip, email-in), **F-560, F-563** (error tracking, `preflight.py`), **F-561, F-562** (Zoho and Tally, the QR badge): done; each outside
  connection is unverified against the real service (HANDOFF "Final session 1 → Final session 2").
- **F-564 to F-569** (models, libraries): done. **Alembic stays at 1.13.1** (the study proposed 1.20.1): the newer Alembic renders 287 operations of the drift check differently, so moving needs its own session to regenerate `alembic/drift_baseline.txt` with intent. SQLAlchemy 2.0.55 stays; it renders five index lines of the baseline differently, and those five lines were updated (CI's "Migration head & drift" job was red from the library bump until then, F-568). A new advisory for `opentelemetry-api` 1.43.0 (CVE-2026-114603, fixed in 1.45.1) appeared during the session; the six coupled opentelemetry pins moved to 1.45.1 and 0.66b1 (F-567). **F-570 to F-572**: done.
- **F-573** (axe in few specs): done. Specs 72 and 74 walk the page catalogue in light, dark and four widths; spec 132 walks the pages the catalogue
  predates; `routeSweepCoverage.test.ts` fails when a router page is in neither. **F-574** (money guard): done. **F-575** (PRODUCT-NEXT): done.
- **F-580** (settings that never reached the containers): done.

## Phase 5 results

- **Accessibility, light and dark, every page.** Specs 72 and 74 (the catalogue: 23 workspace pages, 18 organization pages, 3 platform pages, the public pages)
  and spec 132 (GST Credit in a workspace and an organization, Helm's ten pages, the new-workspace form, the jobs console) run axe in the light and the dark
  theme (Helm's dark theme is its Night Bridge). The sweep found F-601 and F-602; both fixed; all pass. Moderate and minor axe findings are recorded as
  annotations on the tests, not failures.
- **Phone, 390 px.** Spec 74 (375 px) and spec 132 (390 px): no page scrolls sideways; wide tables scroll inside their own box. Three dialogs (the command
  palette, the recipe gallery, the mobile drawer through spec 126) fit the screen. Spec 132 opens every page the sweeps named.
- **Not walked, and why.** Pages that need an id in the address (a case, a certificate, an ERP posting) are opened by the specs for those features; the
  partner portal has its own sign-in (spec 100); the payment return page needs the provider's answer.
- **Money, one way** (F-604), **no raw error text** (F-603), **shared load-failed block**: the nine organization console pages each repeat the same
  "couldn't be loaded / Try again" block (80 files in the app do). It is consistent in words and behaviour and tested per page, so it was **left as it is**;
  a shared component is a refactor with no user-visible change (PRODUCT-NEXT, "polish").
- **Global search** finds GST suppliers (by name or GSTIN), GST invoices (by number) and automation rules (by name), each opening its page narrowed to the
  match; scoped to the person's workspaces and grants; a plan that does not open the GST lists shows no GST result.
- **The website** says in one honest line each what zip upload, email-in, the GST Monday email and the Zoho Books and Tally connections do; all 44
  screenshots were retaken from the demo company (41 look different: new logo, resizable sidebar, rupee grouping).

## Found by CI after the PR was ready

| # | Sev | Finding | Proof | Fixed in |
| --- | --- | --- | --- | --- |
| F-606 | P1 | **The Postmark inbound webhook and Zoho's callback were mounted under `/api/v1/public/`**, the namespace of the API-key gateway (its own rate limit and scopes), which `test_no_gateway_route_is_registered_as_public` exists to keep clear. Moved to `/api/v1/inbound/postmark` and `/api/v1/erp/zoho/callback` (N-185). | pytest shard 1 on CI failed; passes after; browser specs 119 and 122 pass | this commit |
| F-607 | P1 | **CI's "Migration head & drift" was red from the library bump** (my model for `erp_oauth_states` also lacked what its migration created). See "Status at the end of Final session 1". | `check_migration_drift.py` | `65c1cda` |
| F-608 | P1 | **Two new workspace-scoped collections, `getting-started` and `inbound-email`, had no cross-tenant isolation test**, which `test_every_scoped_collection_has_an_isolation_test` requires. Real proofs added: a second workspace of the same organization and a workspace of another organization see none of A's email-in addresses, senders or held messages, cannot approve, discard or delete them, and mail to B's address lands in B alone; a new workspace's checklist is not ticked by A's documents, and another organization's workspace is refused. | pytest shard 2 on CI failed; passes after | this commit |
| F-609 | P1 | **The host crontab had two `compliance` lines** (the old nightly one and the one I added for deleted workspaces and held email), but the host rule is one line, and so one monitor, per sweep name: `test_every_sweep_line_is_covered_here` failed on CI (pytest shard 4). The two new flags (`--archived --inbound`) now sit on the existing line. | pytest shard 4 on CI failed; the 33 tests of `tests/operational/test_host_cron_lines.py` pass after | this commit |
| F-610 | P2 | **Three tests still expected the old Western grouping of a rupee amount** (`INR 118,000.00`) after F-570 moved the run history, emails and notices to lakh grouping (`INR 1,18,000.00`). I had changed two such expectations then and missed `test_automation_document_fields.py` and two in `test_automation_conditions_live.py` (found on CI shard 3; the live ones by looking for the same text). The assertions say the same thing (the trace shows the real amount and the threshold); only the written form changed, as F-570 specified. | pytest shard 3 on CI failed; the 59 tests of both files pass after | this commit |
| F-611 | P1 | **My purge of archived workspaces deleted document chunks with raw SQL that carried no workspace predicate** (`DELETE FROM document_chunks WHERE work_item_id = ANY(...)`), which the vector-scoping rule forbids; `test_no_unscoped_chunk_access_in_app` failed on CI shard 1. The delete now goes through `chunk_scope.delete_chunks_for_work_item`, per workspace. The data-lifecycle registry (`data_map.py`) only names the table as a key, so it joins `erasure_service.py` on that test's allow-list with a reason. | pytest shard 1 on CI failed; 304 tests of the scoping, data-map, archived-purge, retention-purge and legal-hold files pass after | this commit |
| F-612 | P2 | **The "Saved…" confirmation on Calibrated autonomy vanished at once.** After a save the page set the message and then refetched the settings; the refetch gave it a new settings object, and the effect that resets the sliders also cleared the message. The message is now cleared only when another decision type is selected. (It was already there; the browser suite reached it for the first time on CI.) | browser spec 129 failed on CI; passes after (with specs 133, 101) | this commit |
| F-613 | P1 | **A search result opened while the Invoices tab was already showing did not narrow it.** The tab read `?supplier=` and `?number=` once, when it mounted; opening an invoice result from a supplier-narrowed list changed the address but left the old filter and an empty number box. The tab now follows both parameters when they change. | browser spec 133 failed on CI; passes after | this commit |
| F-614 | P3 | **Three browser specs still expected old wording.** Specs 109 and 110 expected rupees in Western grouping (F-570 changed the written form to lakh grouping: `INR 12,50,000.00`, `INR 4,50,000.00`, `INR 2,50,000.00`), and spec 101 expected the label `No logo` where the page now says `Default logo` (the Servabo logo is the default, N-176). The checks keep their meaning. | browser specs 101, 109, 110 failed on CI; 8 + 22 browser tests pass after | this commit |
| F-615 | P3 | **`test_a_ledger_that_is_a_day_old_is_not_drift` failed when a CI shard ran across UTC midnight.** The file fixes `TODAY = date.today()` when it is imported, while the nightly build uses the date it runs on; a shard takes about 40 minutes, so one that started before midnight compared against yesterday (found on pytest shard 3, 23 to 24 Oct). The test now compares with the date after the nightly run. Not caused by this PR's changes; the assertion keeps its meaning. | pytest shard 3 on CI failed once; the 5 tests of the file pass after | this commit |
| F-616 | P3 | **Browser spec 127 (revoke an invitation) raced itself.** After sending the same address a second time it asserted "still exactly one pending", which is true before the server has answered; the next step revoked at once, so a revoke that reached the server first let the second send create a new pending invitation (failed once on CI, passed on the run before). The spec now waits for the server's answer to the second send before it revokes. The product's invitation code was not at fault and this PR did not touch it. | browser spec 127 failed once on CI; passes (7 of 7) after | this commit |
| F-617 | P3 | **Browser spec 125 (the new logo) measured the logo once, between two renders.** It passed the visibility check and then `boundingBox()` found no element, because the sidebar re-rendered once the workspace had loaded (failed once on CI, passed on the run before). The size check now retries until the logo is wider than 20 px (`expect.poll`); the check that the logo is the Servabo mark, with no initials badge, is unchanged. The logo and the sidebar were not at fault. | browser spec 125 failed once on CI; passes (2 of 2) after | this commit |
| F-618 | P2 | **`test_two_reviewers_share_one_queue_live` failed on CI about one run in two, with a CancelledError after every assertion had passed.** The test client cancels the server's handler the moment its `with` block ends; a handler still giving back its leases and taking its avatar down is cancelled in the middle of it, and the cancellation comes out of the `with`. Reproduced here: under CPU load 2 of 8 runs failed with the same error, none without load. The test now closes the admin's channel and waits until the hub holds no connection of the workspace before it leaves the block. The product code (hub, route) is unchanged and this PR did not touch it; an unrelated change can only have moved the odds, as both runs of the same code passed once and failed twice. | pytest shard 4 on CI failed twice running; under the same load that failed 2 of 8 before, 12 of 12 runs pass after | this commit |

