# TRINETRA completion matrix

_Started 2026-10-28 (Final session 2T). This is the proof that nothing was left behind: one row per requirement of the owner's
brief (`ORIGINAL-BRIEF.md`) and one per "like every other feature" item._

**Status words** (the only ones allowed at the finish): **Done before 2T**, **Built in 2T**, **Verified in 2B** (set by Final session 2B),
**Owner's step**, **Out of scope**. While the session runs a row may say **2T pending**; the finish line (STATE.md) requires none left.
A row "Built in 2T" that depends on a real file or service also says what 2B must prove ("2B: …").

Out of scope on purpose: TCS (isolated and switched off), payroll TDS (Form 16, employer returns), filing, portal access or login,
advice on rates, sections or which credit to claim, and reading statements from PDF (TRACES password-protects them; the text and CSV
downloads carry the same data).

## A. The brief, section by section

### §0 Product principle

| Requirement | Status | Evidence | Reason / note |
| --- | --- | --- | --- |
| Audit current architecture, write a dependency map | Done before 2T | `EXISTING-CAPABILITY-MAP.md`, `ARCHITECTURE.md` | Refreshed in 2T Phase 10 |
| Expected withholding sourced from approved invoice/accounting records and confirmed deductions, never assumed from a payment shortfall | 2T pending | Reviewed expectation: `service.reconfirm`; test `test_bank_shortfall_does_not_create_a_tax_basis`. Records-derived suggestions: Phase 4 | |
| Reconcile gross vs bank-net vs customer advice vs government statement | Done before 2T | `service.view`, `domain.reconcile` | Split remittances: Phase 5 |
| Separate expected / customer-asserted / booked / posted / unmatched / contested / resolved / CA-verified | Done before 2T | `domain.Credit` dimensions, statuses | New statuses: Phase 5 |
| Absent row is not evidence of evasion or a claimable credit | Done before 2T | `domain.reconcile` note; `test_no_statement_or_expectation_is_unknown_not_missing_credit` | |
| Exception-specific action plans: ask customer, gather records, accountant tasks, compare a later import, evidence dossier | 2T pending | Draft + dossier exist; authorized send: Phase 6 | |
| Measure confirmed credit-gap closure and reviewer time; never claim refunds or cash recovery | 2T pending | `outcomes.py` (comparison with previous import); cumulative ledger and measured time: Phase 6 | |
| Anti-duplication: reuse OCR, TruthMesh, GST, Helm, requests, quotas, jobs, etc. | Done before 2T | `EXISTING-CAPABILITY-MAP.md` | |
| Helm must not mislabel confirmed withholding as unpaid cash; never change Helm settlement semantics silently | 2T pending | `helm_adapter.py`, tests in `test_helm_adapter.py`; net-of-TDS cash reminder and Guard block: Phase 1.1 | |

### §1 Mandatory repository investigation

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Read the listed docs and code; audit the whole repo for existing 26AS/TDS/TCS code | Done before 2T | `EXISTING-CAPABILITY-MAP.md` | Re-read in 2T start-up |
| `EXISTING-CAPABILITY-MAP.md`, narrow architecture, no second ledger | Done before 2T | same | |

### §2 Tax rules and report formats

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Verify current authoritative sources, with access dates, in `LEGAL-SOURCES.md` | 2T pending | `LEGAL-SOURCES.md` (2026-10-25); reader sources and dates: Phase 3 | |
| Income-tax Act 2025 from 1 Apr 2026; keep old and new labels, never conflate FY and Tax Year | Done before 2T | `domain.tax_period`; `test_year_boundary_and_historical_labels`; readers keep the file's own label: Phase 3 | |
| Section 393 table items vs old sections: never converted | 2T pending | Phase 3 (rows keep the printed section or table item) | |
| Manual upload of official files only; no credentials, CAPTCHA bypass, scraping, invented API | Done before 2T | `LEGAL-SOURCES.md`; no network code in `services/trinetra/` | |
| No autonomous filing; no advice on which credit to claim; uncertainty blocks recommendations | Done before 2T | `domain.reconcile` note; USER-GUIDE and wording in 2T | |
| UI terminology: expected deduction, deductor-reported, posted in uploaded statement, unverified gap, CA-reviewed | Done before 2T | `frontend/src/pages/trinetra/` | Re-checked in Phase 8 |
| Scope to business TDS receivables; TCS isolated and gated | Out of scope | `access.tcs_supported = false` | TCS has different rules and statements; the brief says to gate it until trustworthy |

### §3A Onboarding and import

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| First run explains the five-way evidence chain, permissions, data handling, unsupported sources | 2T pending | Phase 8 first-run tutorial | |
| Import CSV/XLSX/TXT statements with strict limits, mapping preview, owner confirmation, fingerprint and parser version | 2T pending | Typed rows exist (`reviewed-statements`, 500 rows). Template and readers: Phase 3 | |
| PDF statements: refuse clearly rather than guess | 2T pending | Refusal route exists; password-protected PDF message: Phase 3 | PDF parsing out of scope (see top) |
| Unsupported or ambiguous statement returns a clear refusal | Done before 2T | `POST /official-statements`, `test_official_format_refusal_and_entity_confirmation` | Readers add their own refusals in Phase 3 |
| Read invoices and accounting/ERP records through current services | 2T pending | Invoices: `receivable()`. Accounting/ERP (Zoho): Phase 4 | |
| Read bank evidence through the Helm adapter; no separate importer | Done before 2T | `service.bank_evidence` | |
| Customer advice/certificates uploaded through document intake and attached to a case | Done before 2T | `POST …/review` evidence kinds; `test_case_review_evidence_remains_distinct_and_versioned` | |
| Per-organization PAN profile, masked display, optional TAN counterparty mapping and review | 2T pending | Encrypted profile exists. One profile per legal entity per organization: Phase 1.4. TAN directory: Phase 4 | |
| Disallow mixing of entities, PANs, workspaces, years, identifiers | 2T pending | `domain.Scope`, composite FKs; cross-workspace PAN: Phase 1.4 | |
| Explicit scope preview before importing | Done before 2T | `POST …/reviewed-statements/preview` | Mapping preview for files: Phase 3 |

### §3B Reconciliation engine

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Integer micros/Decimal; versioned paise policy | Done before 2T | `domain.money`, `VERSION` | |
| Distinct dimensions: gross, tax basis (only if sourced), net bank, customer-stated, booked, posted, certificates, credit notes, reversals, advances, open difference | 2T pending | Gross, bank, advice, booked, posted exist. Taxable basis, credit notes, reversals, advances: Phase 5 | |
| Never infer a basis or percentage from a bank gap; never apply TDS to GST value | Done before 2T | `test_bank_shortfall_does_not_create_a_tax_basis` | Keep in Phase 5 tests |
| 1:N / N:1 / grouped postings, splits, multiple remittances | 2T pending | Allocation is many-to-many (`test_grouped_and_split_allocations_conserve_statement_value`). Several remittances through Helm lines: Phase 5 | |
| Matching keys: PAN/TAN, entity, year, customer, period, section/table item, amounts, reference | 2T pending | TAN, scope, year, amount, reference exist. Section/table item and transaction date: Phase 3 | |
| Exact / suggested / unmatched / ambiguous; no auto-confirm of ambiguous; no reuse of statement amount | Done before 2T | `domain.allocate`, `test_duplicate_and_ambiguous_candidates_are_never_added` | |
| Immutable snapshots; later imports supersede the active view without destroying human adjudications | Done before 2T | `uq_trinetra_active_snapshot`, `test_snapshot_reimport_allocations_and_stale_decisions` | Capacities no longer count superseded snapshots: Phase 2 |
| Field-level explanation with provenance | 2T pending | Phase 8 drawer (which keys agreed, reader or template, rule version) | |
| Idempotent version-aware recompute; deletion/archival; tenant-status gating | 2T pending | `trinetra.recompute`, tenant gate. Evidence fingerprint instead of `updated_at`: Phase 1.2. Job does real work: Phase 7 | |
| Gap exposure is an investigation queue, not an asset | Done before 2T | Wording and note on every figure | |
| Statuses: pending report, possible missing posting, amount mismatch, TAN/PAN mismatch suspected, duplicate/late posting, disputed, verified corrected, closed-with-exception | 2T pending | First six exist. Duplicate, late, verified corrected, unresolved: Phase 5 | |

### §3C Review, resolution and controls

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Workspace case queue with ownership, root cause, aging, priority, drawer, correction tracking | Done before 2T | `POST …/review`, cockpit, drawer | |
| Reason for each discrepancy with clickable sources and rule/parser version | 2T pending | Phase 8 | |
| Approve, reject, correct or annotate a match, with reason, concurrency check, audit | 2T pending | Approve/correct exist (versioned decisions). Reject and annotate: Phase 5 | |
| Draft inquiry emails; no autonomous sending; reuse templates, outbox, anti-spam, secure request links | 2T pending | Draft exists. Authorized send with the existing request link: Phase 6 | |
| Show who authorized and sent | 2T pending | Phase 6 | |
| Record correction responses, Form 16A, re-run after updated statement; close as posted / explained / withdrawn / unresolved; CA approval | 2T pending | Evidence kinds and closure exist; "unresolved" and approval chains: Phases 5 and 6 | |
| Exports: XLSX/CSV and an evidence report with masked identifiers, snapshots, logic, history, approval, disclaimer | Done before 2T | `export.py`, `test_dossier_masks_identifiers_escapes_formula_and_html_and_audits` | New evidence kinds in Phase 6; egress lockdown: Phase 7 |
| Helm integration read-only/projection-first with invariants preventing double counting | 2T pending | `projection.py`, `test_cash_plus_withholding_cannot_be_counted_twice`. Net cash reminder: Phase 1.1 | |

### §3D Dashboard, actions, reports, sample

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| KPIs: expected, withheld by source, posted, possible gap, open cases, aging, later outcomes | Done before 2T | `summary()` | By source confidence: Phase 8 |
| Cockpit with quick filters by tax year, customer, exception type, status, workspace | 2T pending | Year/status/search exist; customer and workspace filters: Phase 8 | |
| Row opens a drawer with checklist, audit log, amounts, review buttons | 2T pending | Drawer exists; amount waterfall: Phase 8 | |
| Five-stage evidence path as provenance stages | Done before 2T | `Trinetra.tsx` | |
| Sample company with at least 8 synthetic scenarios, labelled, removable | Done before 2T | `sample.py`, `test_sample_has_consistent_totals_and_no_live_write` | Credit note / reversal scenario checked in Phase 5 |
| KPIs by source confidence and as-of date; evidence-freshness banner | 2T pending | As-of exists; banner and confidence: Phase 8 | |
| Accessible errors, loading, zero state, upgrade state, first-run tutorial | 2T pending | Phase 8 | |

### §4 Database, API, worker

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Few, genuinely needed entities, all scoped, composite FKs, constraints, one head | Done before 2T | `models/trinetra.py`, migrations `tr1a1`, `tr1a2` | New tables in 2T are listed in `ARCHITECTURE.md` |
| Role-authorized routes for onboarding, profiles, preview/import, runs, summary, cases, decisions, drafting/sending, exports, sample | 2T pending | 20 routes. Sending, template/readers, directory: Phases 3 to 6 | |
| Entitlement gating, read-only sample for non-paying plans, server-side role/workspace checks | 2T pending | `capability.trinetra`. One mode helper for every gate: Phase 2 | |
| Job registration, retries, idempotency, outbox, billing gates, metering, notifications, audit, telemetry, export/retention/erasure, platform admin | 2T pending | Jobs, audit, data map exist. Metering of inquiries, notifications, platform administration (pilot enrolment): Phases 2, 6, 7 | |
| No endpoint reachable by guessing another tenant ID | Done before 2T | `test_no_guessed_tenant_access_or_job_status`, isolation sweeps | Sweeps extended to every new route in Phase 9 |
| Background jobs: explicit tenant gate and replay safety | Done before 2T | `handlers/trinetra.py`, `test_worker_replay_and_status_gates` | |

### §5 Frontend

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Servabo shell, tokens, light/dark, accessibility, responsive | Done before 2T | Spec 135, axe light/dark, 390/768/1440 | New screens add specs from 141 |
| Navigation entry, entity selector, tax-year filter | 2T pending | Nav entry exists; entity selector: Phase 8 | |
| Hero "TRINETRA / Credit assurance" with the brief's subtitle | Done before 2T | `Trinetra.tsx` | |
| Four KPI cards with source/as-of tooltip | 2T pending | Cards exist; tooltips by confidence: Phase 8 | |
| Evidence-path strip | Done before 2T | `Trinetra.tsx` | |
| Searchable, sortable, paginated queue; empty states | Done before 2T | `Trinetra.tsx` | |
| Case insight panel: waterfall, citations, ambiguity flags, checklist, decision, inquiry draft, timeline | 2T pending | Most exist; waterfall and ambiguity flags: Phase 8 | |
| Case detail page with side-by-side sources and reviewer controls; mobile table-to-card | Done before 2T | `CaseDetail.tsx`, `CaseReview.tsx` | |
| Sample-demo mode with "illustrative synthetic data" and upgrade CTA | Done before 2T | `Trinetra.tsx` | Upgrade moment names Business: Phase 2 |
| Keyboard/screen-reader support, focus, error boundaries | Done before 2T | Spec 135 | |
| Website `/trinetra`, nav, product cards, SEO, sitemap, copy, docs; bounded claims; pricing matches entitlement | 2T pending | Page exists; "Business and Enterprise" and rollout wording: Phase 10 | |

### §6 Commercial packaging

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| `capability.trinetra` in the real registry, versioned tier publisher; base prices untouched | Done before 2T | `seed_quota_tiers.py`, `TENANCY-AND-PLANS.md` | |
| Free trial / Developer: synthetic demo only | Done before 2T | `workspace(live=True)` capability gate | Upgrade moment names Business: Phase 2 |
| Business: live; 2 profiles, 12 snapshots, 500 cases, 50 inquiries a month | 2T pending | Profiles, snapshots, cases exist as lifetime counts. Active/open counting and the inquiry allowance: Phase 2 | |
| Enterprise: all Business plus cross-workspace and multi-entity reporting, approval chains, higher caps, scoped API/webhook, export controls | 2T pending | Organization summary, `trinetra:read`, review event exist. Approval chains, ledger, dataset, controls: Phases 6 and 7 | |
| Real server-side plan checks, upgrade UX, grandfathering compatibility | 2T pending | Phase 2 | |
| Website plan rules consistent with the catalogue; exact owner steps for payment products | Owner's step | `pricing.json` generated; no payment product is needed (capability only) | |

### §7 Security, privacy, lifecycle

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| PAN/TAN least privilege, isolation, encryption, purpose limits | Done before 2T | Encrypted PAN, keyed fingerprints, masked display | TAN scrubber pattern: Phase 9 |
| Retention, exports, erasure, legal holds | 2T pending | `data_map.py`; one deliberate rule for tax evidence: Phase 1.7; legal holds: Phase 7 | |
| No raw PAN/account numbers in logs, URLs, telemetry, screenshots, emails | 2T pending | Existing masking; explicit test across logs, URLs, events, emails, exports: Phase 9 | |
| Reuse upload validation, SSRF controls, size and decompression protection | 2T pending | Phase 3 (files go through the existing intake) | |
| Threat model | 2T pending | `THREAT-MODEL.md`; updated in Phase 9 | |
| No processing without permitted subscription status; labelled production vs simulated | Done before 2T | `tenant_gate`, sample labels | |
| No filing, no corrections to the government, no money movement | Done before 2T | No such code | |
| Deterministic by default; AI drafts metered, revisable, non-authoritative | Done before 2T | No AI in `services/trinetra/` | |

### §8 Milestones and mandatory test classes

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| M0 to M6 | Done before 2T | PR #40, `DELIVERY.md` | 2T repeats the validation in its own PR |
| Old/new Act dates, section labels, cross-year contamination, unsupported formats, synthetic official-format fixtures | 2T pending | Dates and labels tested; section/table item and fixtures: Phase 3 | Real-file proof: 2B |
| PAN/TAN mismatch, grouped postings, many-to-one, credit note, reversal, partial receipt, already allocated, currency guard, signed amounts, rounding | 2T pending | Most tested; credit note and reversal: Phase 5 | |
| Sparse evidence gives honest uncertainty; audited, concurrency-safe overrides; idempotent imports | Done before 2T | `test_missing_evidence_is_unknown`, `test_concurrent_reviewers_cannot_double_allocate` | |
| IDOR, plan and trial gating, revoked link, HTML/script injection, file bombs, export masking | 2T pending | Existing tests; revoked/expired link and file bombs: Phases 3, 6, 9 | |
| Helm, GST, TruthMesh unaffected; withholding never double counted | 2T pending | Existing suites; extended with Phase 1.1 | |
| CI migration up/down/up, drift, backend, frontend, Playwright by role/plan, axe, responsive, CSP, scans, bounded load | 2T pending | Finish line | |

### §9 Documentation and final PR

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Runbook, config, checklists, API specs, plan matrix, lifecycle docs, help, website, troubleshooting | 2T pending | Phase 10 | |
| PRODUCT, ARCHITECTURE, EXISTING-CAPABILITY-MAP, LEGAL-SOURCES, THREAT-MODEL, TEST-PLAN, LAUNCH-GATES with owner validation list; metric definitions; sample walkthrough | 2T pending | Exist; refreshed in Phase 10 | |
| Real statement exports, authorized pilot, adviser sign-off, billing setup | Owner's step | LAUNCH-GATES | Final 2B and the owner's CA |
| Do not assert "100%" until real-source validation is complete | Done before 2T | Wording here and in LAUNCH-GATES | Stays until 2B marks rows "Verified in 2B" |

## B. Like every other feature

| Where GST Credit / Helm / matching are woven in | Status | Evidence | Note |
| --- | --- | --- | --- |
| Getting started step | 2T pending | Phase 7.1 | |
| Global search (never by PAN or TAN) | 2T pending | Phase 7.2 | |
| Notification preferences ("TDS credit") and real `trinetra.recompute` work | 2T pending | Phase 7.3 | |
| Weekly digest line | 2T pending | Phase 7.4 | |
| Value receipt and monthly summary (found vs now visible; never cash) | 2T pending | Phase 7.5 | |
| Automation triggers `gap_found`, `evidence_stale`, `closed`, recipes; never sends an inquiry | 2T pending | Phase 7.6 | |
| Public webhooks and read API for cases and summaries (Enterprise) | 2T pending | Phase 7.7 | |
| Warehouse dataset (Enterprise) | 2T pending | Phase 7.8 | |
| Organization view per legal entity, no double count (Enterprise) | 2T pending | Phase 7.9 | |
| Recoveries (Resolution layer) joins as its own kind | 2T pending | Phase 7.10 | |
| Helm ledger shows withheld beside commercial balance; planner reads net cash | 2T pending | Phase 1.1 and 7.11 | |
| Enterprise egress lockdown on exports; legal holds on evidence | 2T pending | Phase 7.12 | |
| User guide (`docs/trinetra/USER-GUIDE.md`) | 2T pending | Phase 8 | |
| Performance budget test and `PERFORMANCE.md` | 2T pending | Phase 9 | |
| `preflight.py` reports mode, enrolment, unverified readers | 2T pending | Phase 2.3 | |
| Explicit TAN pattern in the error-tracking scrubber | 2T pending | Phase 9 | |
| Three modes and the single "is it live for this organization" helper | 2T pending | Phase 2.1 | |
