> **The owner's original brief for TRINETRA, kept verbatim (2026-10-26)** so that Final session 2T can check every requirement
> against what exists (`docs/trinetra/COMPLETION.md`). The UI image it mentions is not in the repository. Read it as the
> statement of intent; the decisions since are in `docs/hardening/NEEDS-OWNER.md` (N-188 onward).

# SERVABO TRINETRA

**Project:** TRINETRA — Withholding-to-Credit Assurance and Resolution Engine
**Repository:** `sabarishwarne2001/servabo` (inspect current `main` first)
**Visual reference:** attach `SERVABO_TRINETRA_UI_CONCEPT.png` (reference only; the illustration's names, FY/TY labels, sample amounts, tax sections, and workflow states are *not authoritative*).
**Requested output:** Complete implementation on a dedicated feature branch, tests, documentation, website integration, and a reviewable final PR. Do not push directly to `main`, merge, deploy, or touch real customer/tax data. Do not claim untested completion.

## 0. Product principle: create a truly distinct capability, not a new name for old code

Before editing, audit Servabo's actual current architecture and write a dependency map. TRINETRA's unique domain is **India TDS/TCS credit assurance at the receiving business**, with a connected, source-cited exception-resolution workflow:

1. Source commercial entitlement/expected withholding from approved invoice/accounting records and confirmed deductions, without assuming every payment shortfall is TDS.
2. Reconcile gross invoice/receivable values against bank-net receipts (including splits and batches), contemporaneous customer withholding advice and posted government tax-credit statement records (historical/current Form 26AS or other supported official source exports).
3. Separate what is *expected*, *customer-asserted*, *booked*, *government-statement-posted*, *unmatched*, *contested*, *resolved* and *CA-verified*. Detect evidence gaps; do not equate an absent row with evasion or a legally claimable credit.
4. Offer exception-specific action plans: ask the customer/deductor for their advice/certificate or a correction, gather supporting records, create accountant review tasks, compare a later import, and export an evidence dossier.
5. Measure auditably confirmed **credit-gap closure** and reviewer time; never claim tax refunds, cash recovery, payments, regulatory filing, or tax advice.

**Explicit anti-duplication:** Do not rebuild generic OCR, TruthMesh, GST Credit/GSTR-2B, Helm receivables reminders, Helm payment/bank evidence, Helm certificates, existing review discussions/locks, procurement matching, secure external document requests, quotas, auth, ERP connectors, job infrastructure, analytics, or website patterns. Link to their canonical records/services or compose services through a narrowly defined adapter. Maintain distinct TDS credit facts and the reconciliation/exception workflow only. Existing Helm receivables must not mislabel confirmed withholding as unpaid customer cash. Never silently change Helm's existing paid/settlement semantics; add a reviewed projection/adjustment interface with comprehensive regression tests where warranted.

## 1. Mandatory repository investigation

Read `README.md`, `CLAUDE.md`, `docs/RUNBOOK.md`, `docs/CONFIGURATION.md`, `docs/PRODUCT-NEXT.md`, `docs/hardening/{STATE,NEEDS-OWNER,TENANCY-AND-PLANS,COSTS,SECURITY-REVIEW}.md`, `docs/helm/{ARCHITECTURE,MANDATES}.md`, `docs/product/{FLAGSHIP,GST-CREDIT}.md`, current latest release/session notes, and relevant API/data model/worker/frontend/website code. Especially inspect:

- `backend/app/services/helm/{snapshot,ledger,settlements,bank_parse,bank_match,certificate,guard}.py`, `backend/app/models/helm.py`.
- `backend/app/services/truthmesh/`, `backend/app/services/procurement_matching/`, `backend/app/services/collab/`, existing case/requests and `backend/app/api/v1/public_document_requests.py`.
- `backend/app/services/gst/` (tax data patterns but **no GST credit reuse as TDS credit**), ERP imports, document extraction and provenance, queue/worker handlers.
- `backend/app/core/{entitlements,plan_limits,usage_events}.py`, `backend/scripts/seed_quota_tiers.py`, existing capabilities and billing version rules.
- Frontend routers, navigation, review hub, Helm/GST pages, auth/permission gates, API hooks, style tokens and tests; `website/src/pages/`, `website/src/lib/pricing.*` and Astro navigation/SEO.

Audit the *whole* repository for any existing 26AS, TRACES, TDS, TCS, deduction or withholding implementation before creating new modules. Produce `docs/trinetra/EXISTING-CAPABILITY-MAP.md` documenting direct reuse vs actual gap. If current code already covers a proposed item, integrate into it instead of cloning it. Follow established coding and migration conventions. Keep architecture narrow, no second ledger for invoice/bank facts.

## 2. Verify current Indian tax rules and report formats before any substantive rules

Use current authoritative Income Tax Department/CBDT/TRACES resources (and source links in `docs/trinetra/LEGAL-SOURCES.md`, with access dates); do not rely on a stale static TDS rule table. **Income-tax Act 2025 took effect 1 Apr 2026.** The relevant law for withholding depends on the triggering event (credit/payment whichever is earlier); historical 1961 Act tax years continue to require their historical handling. Official FAQs cover the transition of old TDS sections to the new Section 393 tables, and TCS to Section 394. Support the correctly labeled old/new tax-year formats in parsers and summaries; do not guess the meaning of a column or conflate FY 2025–26 and Tax Year 2026–27. Form 26AS and related statement export layouts can differ by tax year; verify sample structures legally usable in tests. Prefer manual upload of officially downloaded files; **no credential harvesting, CAPTCHA bypass, tax-portal scraping or unapproved automated portal access**. Never invent a direct government API. Legal review required for rate/section/eligibility advice; uncertainty must block unsupported recommendations. No autonomous return filing or advice on which credit to claim.

Current official pointers to recheck before coding:
- https://www.incometaxindia.gov.in/w/income-tax-act-2025-comes-into-force-from-1st-april-2026
- https://www.incometax.gov.in/iec/foportal/help/all-topics/e-filing-services/tds-compliance
- https://www.incometaxindia.gov.in/tax-services/process-annual-tax-statement-traces-form-26as-form-168

The user is purchasing **reconciliation evidence**, not automatic legal conclusions. UI terminology: 'expected deduction', 'deductor-reported', 'posted in uploaded statement', 'unverified gap', 'CA-reviewed'. Scope to business TDS receivables initially, not payroll TDS employer returns; TCS is secondary and must be isolated, validated or gated until trustworthy.

## 3. Product workflows (real end-to-end implementation)

### A. Onboarding and import
- First run explains the five-way evidence chain (invoice, accounting expectation, bank receipts, customer advice/certificate, official statement); permissions, data handling, and unsupported sources.
- Import current/historical annual tax statement via supported CSV/XLSX/TXT/PDF formats *only after determining reliable structure*. Parse within strict size/row/zip limits; PDF extraction uses existing stack, but if an unsupported/ambiguous statement is encountered, return a clear refusal rather than produce false numbers. Mapping preview and owner confirmation for ambiguous columns; preserve original evidence with source fingerprint and parser version.
- Read existing invoice and accounting/ERP records through current APIs/services. Read existing bank evidence through Helm adapter (no separate importer). Additional customer TDS certificates/advice can be uploaded through existing document intake and attached to a credit case.
- Per organization PAN/tax profile with masked display, controlled access, optional TAN counterparty mapping and review; disallow accidental mixing of legal entities, PANs, workspaces, financial years/tax years and tax identifiers. Explicit scope preview before importing.

### B. Reconciliation engine (deterministic core)
- Use integer micros/Decimal throughout; paise rounding policy explicitly versioned. Never use binary floats for amounts.
- Model **gross receivable**, tax basis (only if sourced), net bank payment(s), customer-stated withheld TDS, accounting-book TDS, government-statement posting, certificates, credit notes, reversals, advances and open difference as distinct dimensions.
- Do not infer a taxable basis or applicable percentage from a bank-payment gap alone. Don't incorrectly apply TDS to GST value; this is nuanced and requires verified rule context. Where missing, mark unknown and ask the accountant.
- Support 1:N/N:1 and grouped/quarterly government postings, invoice splits and multiple remittances. Matching keys include PAN/TAN, entity, tax year, customer, transaction/credit period, section/table item, reported amounts, invoice or voucher reference when supplied. Clearly differentiate exact / suggested / unmatched / ambiguous; **no auto-confirming ambiguous allocations** and no reuse of the same statement amount in multiple credits.
- Imported statement versions are immutable snapshots; later imports supersede the chosen active view without destroying prior human adjudications. Explain matches at field level with provenance and canonical transaction references. Use idempotent version-aware recomputes, correct handling of deletion/archival and tenant-status gating.
- Tax-credit gap exposure is an *investigation queue*, not an asset booked, guaranteed credit, or recoverable sum. Build clear statuses including pending report, possible missing posting, amount mismatch, TAN/PAN mismatch suspected, duplicate/late posting, disputed, verified corrected, and closed-with-exception.

### C. Review, resolution and controls
- Workspace case queue with ownership, root cause, aging, priority, document/evidence drawer and correction tracking.
- Explain the *reason* for each discrepancy with direct clickable source references and rule/parser version. A user can approve, reject, correct or annotate a match with explicit reason, concurrency/version checks and audit trail.
- Draft deductible/credit inquiry emails with approved details for deductor; no autonomous external email sending at launch. Reuse existing email templates/outbox, anti-spam controls and secure document-request links (do not implement second outside-user portal). Show who authorized and sent the request.
- Human reviewers may record the customer's correction response, supporting Form 16A/statement, and re-run reconciliation after updated 26AS. A case closes as *posted/verified*, *resolved by explanation*, *withdrawn* or *unresolved* based on evidence, not on a promise. CA approval where needed.
- Exports: reviewer-friendly XLSX/CSV and an evidence report with tax year, masked identifiers, source snapshots, amount logic, discrepancy history, approval and disclaimer. Use existing export and certificate patterns, not an independent cryptographic trust product.
- Integrate with Helm in **read-only/projection-first** mode; if adding net-of-TDS receivable reporting, define invariant tests that prevent double-counting withholding as cash and prevent retroactive mutation of the canonical Helm bank settlement without review.

### D. Dashboard, actions, reports, sample data
- KPIs: expected withholding (supported), withheld/confirmed by source, posted statement amount, possible gap, open cases, aging and later confirmed reconciliation outcomes. Do not imply every missing credit is immediately claimable.
- Main screen is the 'Credit assurance' cockpit; global quick filters by tax year, customer, exception type, status and workspace. Selecting a row opens a case-insight drawer with evidence checklist, audit log, amounts and review buttons.
- Five-stage evidence path: Invoice → Bank receipt → Deductor evidence → Government statement → Reviewed resolution. These are provenance stages, not a process that automatically progresses on incomplete evidence.
- Sample Indian company with at least 8 synthetic scenarios: exact posted, partial remittance, disputed deduction, no government posting, late posting, incorrect TAN, grouped quarter entry, invalid source file, credit note/reversal. **All sample numerals, dates, section labels and tax years must be internally consistent and law-reviewed; do not copy the image's sample figures or periods as accounting truth.** Sample distinct from real data, removable and clearly labeled.
- Report KPIs by source confidence and import 'as-of' date. Add actionable evidence-freshness banner. Accessible errors, loading, zero state, upgraded-tier state and first-run tutorial.

## 4. Proposed database/API/worker design — adapt to actual repository

Create only genuinely needed entities (naming is advisory): `trinetra_tax_profiles`, `trinetra_statement_imports`, `trinetra_statement_lines`, `trinetra_credit_expectations` (a **derived/reference view**, not a new financial ledger), `trinetra_allocations`, `trinetra_exceptions`, `trinetra_exception_events`, `trinetra_decisions` and `trinetra_rule_versions`. Use as few tables as necessary. For evidence attachments, point to existing work items/secure objects instead of duplicating blobs. All records carry `organization_id` and `workspace_id` when relevant, legal entity/tax year isolation, indexed search keys, uniqueness/idempotency keys, composite FKs and not-null/check constraints. Keep migration model/drift parity; one Alembic head, safe migrations and documented backward compatibility.

Expose real, role-authorized routes following the existing URL conventions: onboarding/access, tax profiles, preview/import, reconciliation runs/status, summary, exception list/details, reviewer decisions, request drafting/sending with authorization, exports and sample tenant. Support cursor pagination or existing patterns, bounded filters and stable typed Pydantic response schemas. Entitlement gating on reads/writes as appropriate, read-only sample for nonpaying plans, and server-side role/workspace checks. Integrate job handler registration, retries, idempotency, outbox where needed, billing gates, metering, notifications, audit, error codes, telemetry, export/retention/erasure and platform administration. No endpoint can be reachable by guessing another tenant ID. All background jobs require explicit tenant gate and replay safety.

## 5. Frontend UI and mockup instructions

Use the attached `SERVABO_TRINETRA_UI_CONCEPT.png` as an **art-direction reference** only. Preserve existing Servabo shell, typography, UX/navigation architecture, tokens, light/dark theme, accessibility and responsiveness; do not copy pixels, invented routes or inaccurate labels from the image. Implement polished production JSX/TypeScript connected to actual live APIs (no placeholders or hard-coded backend success). Desktop layout:

- Left Servabo navigation has clearly named TRINETRA under finance/GST capabilities; right workspace/entity selector and tax-year filter.
- Hero 'TRINETRA / Credit assurance' with subtitle 'Trace withheld tax from invoice to government statement.'
- Four primary KPI cards (expected, posted, possible gap, unresolved), each with source/as-of tooltip and appropriate caution.
- Evidence-path progress strip (invoice → bank → deductor statement/certificate → government statement → review).
- Searchable, sortable, paginated 'Credit exception queue' with amount, counterparty, invoice reference, tax year, case reason, age and status; explicit empty states.
- Right 'Case insight' panel: amount waterfall/variance, clickable source citations, ambiguity flags, evidence checklist, versioned analyst decision, approved inquiry draft and audit timeline.
- Case detail page with side-by-side source documents and reviewer controls. Responsive mobile uses table-to-card transformation, accessible tabs/drawers; light mode coherent.
- Optional sample-demo mode when plan gated, with prominent 'illustrative synthetic data' indicator and discoverable upgrade CTA.

Implement genuine keyboard/screen-reader support, focus and error boundaries, strong visual hierarchy and minimized cognitive load. No extraneous gamified animations. Website `/trinetra` dedicated product page with problem/solution, explicitly bounded capabilities, sample illustration/screenshots, true pricing table and CTA; add nav, product cards, SEO, sitemap, copy and docs. Marketing cannot claim 'first ever', tax refunds, guaranteed credit, direct tax authority integration or fabricated customer testimonials. Match production feature entitlement exactly.

## 6. Commercial packaging (authorization)

Do not alter current base subscription prices, payment provider, billing cadence, legacy prices or plan names. Make an additive entitlement `capability.trinetra` using the **actual** entitlement registry, versioned tier publisher and backend capability enforcement:

- **Free trial / Developer:** clearly labeled, read-only synthetic demo only; no live tax document ingestion, reconciliation or real case exports.
- **Business:** live TRINETRA for the organization's authorized workspaces; all core reconciliation, review, drafted inquiries and evidence exports. Bounded quota baseline proposal: 2 legal entity PAN profiles/org, 12 tax-year snapshots per org, 500 live exceptions/org, 50 approved outbound inquiries/month; choose actual safe counters after auditing existing quota/meter semantics and processing cost. No unit-cost surprises, no bypass of existing document/OCR quotas.
- **Enterprise:** all Business features, cross-workspace and multi-entity reporting subject to access scoping, approval chains, higher negotiated caps, scoped API/webhook and advanced integration/export controls. Avoid unbounded processing. Ensure real server-side plan checks, upgrade UX and versioning/grandfathering compatibility with existing subscriptions.

Plan rules and prices on the public website must remain consistent with current source-of-truth catalog. If tier upgrade requires owner-operated payment products, write exact steps; never invent real product IDs.

## 7. Security, tax privacy, data life cycle and operational quality

Treat PAN, TAN, bank documents and returns as confidential personal/business finance data: least privilege, tenant/organization/workspace/legal-entity isolation, secrets and tokens masking, encryption as existing platform supports, purpose-limited use, opt-in external communication, no cross-tenant pooling or training, retention controls, exports, erasure and legal holds. Avoid including raw PAN or account numbers in application logs, URLs, telemetry, screenshots or generated emails unless strictly required and authorized. Reuse existing upload virus/type validation, SSRF controls and file size/decompression protection. Define trust boundaries in `docs/trinetra/THREAT-MODEL.md` and data flows in architecture doc.

No processing without permitted subscription status. Production and simulated runs must be labeled. Verified absence of a tax statement record does not establish unlawful conduct. Do not automatically file income-tax returns, submit correction requests to the government, move money or claim the platform is a regulated intermediary. Default AI-independent deterministic operation; optional AI drafts are always metered, revisable and not authoritative.

## 8. Delivery milestones and acceptance tests

**M0 — repo audit / architecture:** Trace exact reuse, record module ownership, revised tax-law/source/rule verification and UI contracts before editing. Write failing acceptance cases.
**M1 — data/import:** Alembic, models, validated statement preview/import, fixtures and source provenance.
**M2 — engine:** tax-year segmentation, deterministic allocations, gap status, manual adjudication, reconciliation versioning and idempotent recompute.
**M3 — real API/worker:** capability gates, role checks, background handlers, audit, outbox/metering and exports.
**M4 — full UI:** app navigation, cockpit, worklist, case inspector, first-run, multi-step review, dialogs and all state types.
**M5 — billing and website:** published tiers, upgrade copy, pricing and product website, demo and documentation.
**M6 — rigorous validation:** run all practical full-suite checks and author the final PR report.

Mandatory test classes:
- Old Act/new Act dates and section labels, cross-tax-year contamination and unsupported formats; synthetic official-format input fixtures verified against legally obtained samples.
- PAN/TAN mismatch, grouped or quarterly postings, multiple invoices to one line, multiple lines to one invoice, credit note, reversal, partial bank receipt, already allocated credits, currency guard, signed amounts and rounding; no duplicate tax-credit allocation.
- Missing/sparse bank/source records produce honest uncertainty, never fake missing-credit claims. Manual overrides are audited and concurrency-safe. Imports/reimports idempotent; tenant archive/purge constraints respected.
- Tenant, workspace, tax entity and role IDOR prevention; every API variant gated by plan and trial/payment status; revoked link, HTML/script injection, file bombs, sensitive export masking and direct URL access.
- Confirm existing Helm, GST, TruthMesh and review features are unaffected; test that withholding is never double-counted as unpaid receivable or cash receipt.
- CI migration up/down/up and drift, all applicable backend tests, frontend typecheck/lint/build/self-checks, Playwright E2E with sample and role/plan matrix, accessibility, responsiveness, CSP, security scans and bounded-load tests. Include report of actual commands/results; do not claim external service tests were run if they weren't.

## 9. Owner documentation and final PR

Update deployment/runbook, config, operational checklists, API specs, plan matrix, lifecycle/retention docs, feature help, website and troubleshooting. Include `docs/trinetra/PRODUCT.md`, `ARCHITECTURE.md`, `EXISTING-CAPABILITY-MAP.md`, `LEGAL-SOURCES.md`, `THREAT-MODEL.md`, `TEST-PLAN.md`, `LAUNCH-GATES.md` with an explicit owner validation list (real statement exports, authorized customer pilot, tax adviser sign-off and permitted billing setup). Add metric definitions and sample-case walkthrough.

Commit coherent, working milestones on one feature branch and open a PR for review. If a task is blocked by tax portal credentials, external integrations, legal verification, infrastructure or test runners, implement all other safe pieces, ship the unverified functionality disabled, and list the blocker precisely. Do not fabricate connectors, success rates or results. Your final response must report: full changed-file summary, actual architecture reuse and anti-duplication evidence, verified vs unverified features, DB migrations, API/UI wiring, backend/frontend/browser tests run with outcomes, deployment checklist, image/mockup fidelity, remaining risks and PR URL. **Do not assert '100%' until all necessary production and real-source validation is actually complete.**
