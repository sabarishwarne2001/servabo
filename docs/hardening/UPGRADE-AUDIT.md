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
