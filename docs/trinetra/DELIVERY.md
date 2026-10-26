# Project TRINETRA delivery and review record

Date: 26 October 2026. Branch: `hardening/trinetra`. Base:
`bf8f57f691aec7122d9ebaf4a4e13ae9d22ae19c`. Pull request:
[sabarishwarne2001/servabo#40](https://github.com/sabarishwarne2001/servabo/pull/40).
Main has not been changed or merged into. The original Markdown attachment and
PNG direction were reviewed, and the preliminary audit was checked against code.

**Delivered: a gated, functional reviewed-evidence workflow. Full production
acceptance of the original request is incomplete.** Live processing defaults off.
Official formats, signed/advance workflows and the remaining product/legal gates
below are not represented as completed implementation. The current PR checks and
description are the final-head validation record; this document records the
executed evidence available when it was committed.

## Implemented behavior

| Area | Reviewable result |
| --- | --- |
| Profiles and intake | Masked/encrypted PAN profiles; canonical invoice and supporting document selection; explicit source/entity/year preview; immutable, idempotent human-transcribed statement snapshots. Unsupported official layouts are refused. |
| Reconciliation | Exact Decimal/integer-micros amounts with paise input policy; scoped many-to-many allocations; no double use of a posting; ambiguity stays a suggestion; absent/stale evidence stays unknown. |
| Review | Reasons, optimistic revisions and serialized allocations; ownership, priority, due date and root cause; multiple supporting sources; reconfirmation after source changes; disputed/explained/withdrawn/independent accountant review. |
| Cash/withholding | Separate gross, bank, advice, accounting and posted amounts. Explicit agreeing advice/accounting confirmation creates a read-only Helm annotation and holds gross reminders. No settlement or cash mutation. |
| Outcomes | Current accountant-reviewed gap closure compared with the previous import, capped by increased statement evidence; optional self-reported review minutes. No savings or recovery claim. |
| API and workers | Typed workspace APIs and restricted Enterprise organization summary; shared debounced LIGHT jobs/status, tenant/subscription gates, audit and optional transactional review webhook. |
| App | Lumen shell/navigation, four KPIs, five evidence stages, search/filter/sort/pagination, case drawer, side-by-side sources, real import/review/job/export controls and Enterprise summary. |
| Packaging | Read-only synthetic preview for Free/Developer; bounded Business/Enterprise capability grants via the existing tier publisher. No base price, provider, cadence or plan-name changes. |
| Website/help | `/trinetra`, actual synthetic app screenshots, navigation/home card/sitemap, generated pricing alignment, feature help, source register, architecture, threat model and deployment instructions. |
| Security/lifecycle | Composite scope FKs, role/API-key denial, version checks, encrypted identity/key rotation, safe exports, canonical evidence erasure/retention/export registry, finite capacity and query bounds. |

## Architecture and anti-duplication evidence

Four evidence tables reference canonical documents; there is no additional invoice,
bank or cash ledger. Helm `ledger_store`, identity and bank authorization supply
facts and access rules. Its reminder hand consults the narrow withholding hold.
TruthMesh, procurement, discussions and secure requests remain on existing
document review surfaces. GST supplies spreadsheet escaping and export patterns,
never TDS values. Existing jobs, outbox, tenant gates, encryption rotation,
compliance data map and tier publication own their respective lifecycles.

See [EXISTING-CAPABILITY-MAP.md](EXISTING-CAPABILITY-MAP.md) for exact ownership
and [ARCHITECTURE.md](ARCHITECTURE.md) for data flow and limits. Repository-wide
searches found no existing Indian TDS engine; X12's `TDS` segment is an invoice total.

## Database, API and UI wiring

- `tr1a1_credit_assurance` follows `k1a7_pack_check_dismissals`: profiles,
  statement snapshots, credit references and decisions; scope/index/check rules;
  API-key scope and webhook vocabulary.
- `tr1a2_review_outcomes` follows it: previous-import comparisons, review minutes
  and supporting-source lifecycle references with backward-compatible defaults.
- One head. Local populated downgrade/upgrade passed; CI passed full-chain
  downgrade-to-base/upgrade and the no-new-drift check (282 existing baseline entries).
- `/api/v1/workspaces/{workspace_id}/trinetra` exposes access/sample, profiles,
  preview/import, cases/details/reviews, draft inquiry, exports, summary and jobs.
  `/api/v1/organizations/{organization_id}/trinetra/summary` adds readable-workspace
  Enterprise reporting. Generated OpenAPI TypeScript contracts are checked in.
- The app calls these APIs, uses canonical document viewers, and polls actual job
  status. Browser 136 exercises intake through export using synthetic PDFs and
  local service stand-ins; no backend success response is mocked for that journey.

## Executed validation and failures

[TEST-PLAN.md](TEST-PLAN.md) records commands, coverage and results. Key evidence:

- Full CI `40254658271` on `bcec7de9`: all four backend shards, frontend, website,
  encoding, migrations/drift and Python audit passed. Browser spec 129 had a loading
  race; Stripe and live-TRINETRA phases were not reached on that run. The race was
  reproduced and fixed; final-head browser checks must be read on the PR.
- Local backend checks: 326 TRINETRA/lifecycle, 402 Helm/engine, 56 image/extraction
  and 7 document-console tests passed. These sets overlap; their counts are not
  added into a unique-test total. Initial integration failures and reruns are documented.
- Frontend: 291 unit tests, 12 API contracts, typecheck/build/lint/self-check passed.
  Browser: 6 TRINETRA sample/accessibility checks; 1 full synthetic live review;
  30 existing review/procurement checks; 6 delayed-response autonomy runs passed.
- Website typecheck/build, links, HTML, axe/CSP/responsiveness and shipped-dependency
  audit passed. Both CI website jobs passed Lighthouse's unchanged minimum 95
  across all categories/pages, including TRINETRA. An earlier local home/pricing
  performance run failed under load and is retained in the test record.
- Python audit initially failed on filelock/setuptools advisories. Updated full/web
  pins, dependency contracts and `pip check` passed; audit now finds no known vulnerabilities.
- Interrupted local full-suite attempts are not passes. Real OCR/AI accuracy,
  government files, customer outcomes and live integrations were not tested.

## Mockup fidelity and financial corrections

The app preserves Servabo's shell, Lumen typography/tokens and both themes. It
uses the reference's four-card hierarchy, five-stage strip, exception queue and
case-insight panel, with mobile cards and keyboard/focus handling. The source
comparison view extends that layout using existing document viewers. The PNG's
colors and dimensions are direction, not a replacement design system.

Nine read-only synthetic scenarios derive their figures from the deterministic
engine. Historical FY 2025–26/AY 2026–27 is distinct from Tax Year 2026–27. Unknown
gaps are excluded rather than treated as zero. The erroneous 194C/10% example is
not copied; no unreviewed statutory rate, section or taxable base is asserted.
The samples have not received independent tax-adviser approval.

## Remaining acceptance and deployment gates

[LAUNCH-GATES.md](LAUNCH-GATES.md) is the owner checklist. Specifically unfinished:
verified official CSV/XLSX/TXT/PDF layouts and legally usable fixtures; automatic
ERP-derived expectations; complete signed credit-note/reversal/advance treatment;
configurable multi-stage approval policy; authorized inquiry sending; TCS; independent
tax/privacy/security review; an authorized customer pilot and real outcome validation.
The implemented independent accountant review is not a configurable approval chain.
Manual transcription is not an official parser. Canonical intake has type/size/
active-content/decompression protections, but no malware scanner.

Before an authorized pilot: back up/restore-test; apply and check the single migration
head; dry-run/publish additive tiers and review same-price carry-forward; verify
encryption-key rotation; deploy API and LIGHT workers on the same revision; validate
source formats, privacy and adviser acceptance; only then enable the live flag in
that deployment. Keep samples labelled and check failures, stale sources, exports
and erasure in staging. See the [RUNBOOK supplement](../RUNBOOK.md#trinetra-deployment-supplement)
for commands. Disable the flag before rollback and export history: downgrading the
TRINETRA migrations destroys its derived evidence/history. Existing withholding
holds remain while their rows remain, even when the flag is disabled.

No production deployment, payment product creation, external inquiry, government
filing, customer-data processing or merge was performed.

## Full changed-file inventory

The paths below cover this PR relative to its stated base, including generated
contracts and screenshots. The behavior/ownership tables above explain their purpose.

- `.github/workflows/ci.yml`
- `CHANGELOG.md`
- `README.md`
- `backend/.env.example`
- `backend/.env.production.template`
- `backend/alembic/versions/tr1a1_credit_assurance.py`
- `backend/alembic/versions/tr1a2_review_outcomes.py`
- `backend/app/api/capability_gate.py`
- `backend/app/api/v1/router.py`
- `backend/app/api/v1/trinetra.py`
- `backend/app/core/config.py`
- `backend/app/core/entitlements.py`
- `backend/app/core/finance_schema.py`
- `backend/app/core/plan_limits.py`
- `backend/app/core/scopes.py`
- `backend/app/core/webhook_events.py`
- `backend/app/models/__init__.py`
- `backend/app/models/api_key.py`
- `backend/app/models/trinetra.py`
- `backend/app/services/compliance/data_map.py`
- `backend/app/services/compliance/export_service.py`
- `backend/app/services/encryption_rotation_service.py`
- `backend/app/services/helm/hands.py`
- `backend/app/services/helm/hooks.py`
- `backend/app/services/helm/service.py`
- `backend/app/services/trinetra/__init__.py`
- `backend/app/services/trinetra/domain.py`
- `backend/app/services/trinetra/events.py`
- `backend/app/services/trinetra/export.py`
- `backend/app/services/trinetra/fields.py`
- `backend/app/services/trinetra/helm_adapter.py`
- `backend/app/services/trinetra/hooks.py`
- `backend/app/services/trinetra/outcomes.py`
- `backend/app/services/trinetra/projection.py`
- `backend/app/services/trinetra/sample.py`
- `backend/app/services/trinetra/schemas.py`
- `backend/app/services/trinetra/service.py`
- `backend/app/workers/handlers/__init__.py`
- `backend/app/workers/handlers/trinetra.py`
- `backend/app/workers/profiles.py`
- `backend/app/workers/tenant_gate.py`
- `backend/docker-compose.prod.yml`
- `backend/requirements-web.txt`
- `backend/requirements.txt`
- `backend/scripts/seed_quota_tiers.py`
- `backend/tests/engines/test_trinetra_isolation.py`
- `backend/tests/isolation/test_owner_set_concurrency.py`
- `backend/tests/services/test_extraction_prompt_contract.py`
- `backend/tests/trinetra/test_api.py`
- `backend/tests/trinetra/test_controls.py`
- `backend/tests/trinetra/test_domain.py`
- `backend/tests/trinetra/test_evidence_lifecycle.py`
- `backend/tests/trinetra/test_helm_adapter.py`
- `backend/tests/trinetra/test_outcomes.py`
- `backend/tests/trinetra/test_projection.py`
- `backend/tests/trinetra/test_workflows.py`
- `docs/CONFIGURATION.md`
- `docs/PRODUCT-NEXT.md`
- `docs/RUNBOOK.md`
- `docs/hardening/COVERAGE.csv`
- `docs/hardening/FINDINGS.md`
- `docs/hardening/NEEDS-OWNER.md`
- `docs/hardening/STATE.md`
- `docs/hardening/TENANCY-AND-PLANS.md`
- `docs/product/WEBHOOK-EVENTS.md`
- `docs/trinetra/ARCHITECTURE.md`
- `docs/trinetra/AUDIT.md`
- `docs/trinetra/DELIVERY.md`
- `docs/trinetra/EXISTING-CAPABILITY-MAP.md`
- `docs/trinetra/LAUNCH-GATES.md`
- `docs/trinetra/LEGAL-SOURCES.md`
- `docs/trinetra/PRODUCT.md`
- `docs/trinetra/TEST-PLAN.md`
- `docs/trinetra/THREAT-MODEL.md`
- `frontend/e2e/support/routes.ts`
- `frontend/e2e/tests/129-org-byok-branding-egress-autonomy.spec.ts`
- `frontend/e2e/tests/132-new-pages-sweep.spec.ts`
- `frontend/e2e/tests/135-trinetra.spec.ts`
- `frontend/e2e/tests/136-trinetra-review.spec.ts`
- `frontend/src/App.tsx`
- `frontend/src/components/layout/navigation.ts`
- `frontend/src/constants/capabilities.ts`
- `frontend/src/constants/planFeatures.ts`
- `frontend/src/pages/helm/HelmLedger.tsx`
- `frontend/src/pages/organization/OrganizationApiKeys.tsx`
- `frontend/src/pages/trinetra/CaseDetail.tsx`
- `frontend/src/pages/trinetra/CaseReview.tsx`
- `frontend/src/pages/trinetra/ExportEvidence.tsx`
- `frontend/src/pages/trinetra/OrganizationTrinetra.tsx`
- `frontend/src/pages/trinetra/ReconciliationRun.tsx`
- `frontend/src/pages/trinetra/ReviewTools.tsx`
- `frontend/src/pages/trinetra/SourcePicker.tsx`
- `frontend/src/pages/trinetra/Trinetra.tsx`
- `frontend/src/pages/trinetra/WorkspaceEvidence.tsx`
- `frontend/src/pages/trinetra/format.test.ts`
- `frontend/src/pages/trinetra/format.ts`
- `frontend/src/routes/tenantPaths.ts`
- `frontend/src/services/api/trinetra.ts`
- `frontend/src/types/api.generated.d.ts`
- `frontend/src/types/apiKey.ts`
- `frontend/src/types/helm.ts`
- `frontend/src/types/webhook.ts`
- `frontend/src/utils/displayTime.ts`
- `website/scripts/check-a11y.mjs`
- `website/scripts/check-lighthouse.mjs`
- `website/src/assets/screenshots/trinetra-dark.png`
- `website/src/assets/screenshots/trinetra-light.png`
- `website/src/config/site.ts`
- `website/src/data/pricing.json`
- `website/src/lib/pricing.ts`
- `website/src/pages/index.astro`
- `website/src/pages/sitemap.xml.ts`
- `website/src/pages/trinetra.astro`
