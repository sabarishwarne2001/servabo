# TRINETRA completion matrix

_Started and finished 2026-10-28 (Final session 2T). No row is left "missing" or "pending". This is the proof that nothing was left behind: one row per requirement of the owner's
brief (`ORIGINAL-BRIEF.md`) and one per "like every other feature" item._

**Status words** (the only ones allowed at the finish): **Done before 2T**, **Built in 2T**, **Verified in 2B** (set by Final session 2B),
**Owner's step**, **Out of scope**. Rows that need a real file or service say **2B:** and what 2B must prove: the three official statement readers (Form 26AS text, Form 168 text, AIS CSV) have never read a real file, the Zoho Books read has never met a real organization, and no real inbox has received an inquiry.
A row "Built in 2T" that depends on a real file or service also says what 2B must prove ("2B: …").

Out of scope on purpose: TCS (isolated and switched off), payroll TDS (Form 16, employer returns), filing, portal access or login,
advice on rates, sections or which credit to claim, and reading statements from PDF (TRACES password-protects them; the text and CSV
downloads carry the same data).

## A. The brief, section by section

### §0 Product principle

| Requirement | Status | Evidence | Reason / note |
| --- | --- | --- | --- |
| Audit current architecture, write a dependency map | Done before 2T | `EXISTING-CAPABILITY-MAP.md`, `ARCHITECTURE.md` | Refreshed in 2T Phase 10 |
| Expected withholding sourced from approved invoice/accounting records and confirmed deductions, never assumed from a payment shortfall | Built in 2T | `suggestions.py`, `service.reconfirm`; `test_suggestions.py`, `test_bank_shortfall_does_not_create_a_tax_basis` | Only a person accepts a suggestion, with a reason (N-204). 2B: the Zoho read on a real organization. |
| Reconcile gross vs bank-net vs customer advice vs government statement | Done before 2T | `service.view`, `domain.reconcile` | Split remittances: Phase 5 |
| Separate expected / customer-asserted / booked / posted / unmatched / contested / resolved / CA-verified | Done before 2T | `domain.Credit` dimensions, statuses | New statuses: Phase 5 |
| Absent row is not evidence of evasion or a claimable credit | Done before 2T | `domain.reconcile` note; `test_no_statement_or_expectation_is_unknown_not_missing_credit` | |
| Exception-specific action plans: ask customer, gather records, accountant tasks, compare a later import, evidence dossier | Built in 2T | `inquiries.py`, `export.py`; `test_resolution.py`, spec 143 | A person edits, approves and presses Send; dossier and exports as before. 2B: a real inbox. |
| Measure confirmed credit-gap closure and reviewer time; never claim refunds or cash recovery | Built in 2T | `outcomes.py`, `trinetra_outcomes`; `test_outcomes.py`, `test_resolution.py` | The closure ledger says "TDS now visible", never cash or a refund; review minutes are effort. |
| Anti-duplication: reuse OCR, TruthMesh, GST, Helm, requests, quotas, jobs, etc. | Done before 2T | `EXISTING-CAPABILITY-MAP.md` | |
| Helm must not mislabel confirmed withholding as unpaid cash; never change Helm settlement semantics silently | Built in 2T | `helm_adapter.py`, `helm/service.withholding_holds`; `test_helm_adapter.py`, `tests/services/helm/test_withholding_hold.py` | Net-of-TDS reminders and the stale-evidence safety hold (F-641). |

### §1 Mandatory repository investigation

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Read the listed docs and code; audit the whole repo for existing 26AS/TDS/TCS code | Done before 2T | `EXISTING-CAPABILITY-MAP.md` | Re-read in 2T start-up |
| `EXISTING-CAPABILITY-MAP.md`, narrow architecture, no second ledger | Done before 2T | same | |

### §2 Tax rules and report formats

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Verify current authoritative sources, with access dates, in `LEGAL-SOURCES.md` | Built in 2T | `LEGAL-SOURCES.md` (25 and 28 Oct 2026); `readers.py` source notes | The official hosts were unreachable on 28 Oct: readers were written from secondary sources. 2B. |
| Income-tax Act 2025 from 1 Apr 2026; keep old and new labels, never conflate FY and Tax Year | Done before 2T | `domain.tax_period`; `test_year_boundary_and_historical_labels`; readers keep the file's own label: Phase 3 | |
| Section 393 table items vs old sections: never converted | Built in 2T | `statements/common.py` (rows keep the printed section text); `test_statement_readers.py` | Never converted either way. |
| Manual upload of official files only; no credentials, CAPTCHA bypass, scraping, invented API | Done before 2T | `LEGAL-SOURCES.md`; no network code in `services/trinetra/` | |
| No autonomous filing; no advice on which credit to claim; uncertainty blocks recommendations | Done before 2T | `domain.reconcile` note; USER-GUIDE and wording in 2T | |
| UI terminology: expected deduction, deductor-reported, posted in uploaded statement, unverified gap, CA-reviewed | Done before 2T | `frontend/src/pages/trinetra/` | Re-checked in Phase 8 |
| Scope to business TDS receivables; TCS isolated and gated | Out of scope | `access.tcs_supported = false` | TCS has different rules and statements; the brief says to gate it until trustworthy |

### §3A Onboarding and import

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| First run explains the five-way evidence chain, permissions, data handling, unsupported sources | Built in 2T | `Tutorial.tsx`, `AccessNotice.tsx`, the examples; spec 135 and 141 |  |
| Import CSV/XLSX/TXT statements with strict limits, mapping preview, owner confirmation, fingerprint and parser version | Built in 2T | `statements/` (template, AIS, Form 26AS/168), `POST /statement-files(/preview)`; `test_statement_files.py`, `test_hostile_files.py`, spec 143 | 5 MB and 5,000 rows; a mapping preview for AIS; the person confirms. 2B: real files. |
| PDF statements: refuse clearly rather than guess | Built in 2T | `statements/detect.py`; `test_statement_files.py` | A PDF is refused with the reason (TRACES password-protects it). PDF reading is out of scope. |
| Unsupported or ambiguous statement returns a clear refusal | Done before 2T | `POST /official-statements`, `test_official_format_refusal_and_entity_confirmation` | Readers add their own refusals in Phase 3 |
| Read invoices and accounting/ERP records through current services | Built in 2T | `suggestions.py` (invoice figures, template, Zoho); `test_suggestions.py`, `test_zoho_tds.py` | Zoho is read only. 2B: a real Zoho Books organization. |
| Read bank evidence through the Helm adapter; no separate importer | Done before 2T | `service.bank_evidence` | |
| Customer advice/certificates uploaded through document intake and attached to a case | Done before 2T | `POST …/review` evidence kinds; `test_case_review_evidence_remains_distinct_and_versioned` | |
| Per-organization PAN profile, masked display, optional TAN counterparty mapping and review | Built in 2T | `directory.py`, `service.create_profile`; `test_one_entity_one_profile.py`, `test_suggestions.py` | One profile per legal entity per organization (F-645); a TAN is mapped to a customer once, by a person. |
| Disallow mixing of entities, PANs, workspaces, years, identifiers | Built in 2T | `domain.Scope`, composite FKs, `org_pan_fingerprint`; `test_one_entity_one_profile.py`, `test_domain.py` | A clear 409 names the workspace that holds the PAN. |
| Explicit scope preview before importing | Done before 2T | `POST …/reviewed-statements/preview` | Mapping preview for files: Phase 3 |

### §3B Reconciliation engine

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Integer micros/Decimal; versioned paise policy | Done before 2T | `domain.money`, `VERSION` | |
| Distinct dimensions: gross, tax basis (only if sourced), net bank, customer-stated, booked, posted, certificates, credit notes, reversals, advances, open difference | Built in 2T | `domain.py` (taxable basis only when sourced, credit notes, reversals, advances); `test_money_model.py` | A bank gap never creates a basis. |
| Never infer a basis or percentage from a bank gap; never apply TDS to GST value | Done before 2T | `test_bank_shortfall_does_not_create_a_tax_basis` | Keep in Phase 5 tests |
| 1:N / N:1 / grouped postings, splits, multiple remittances | Built in 2T | `domain.allocate`, pairings; `test_money_model.py` | Several remittances arrive through Helm lines. |
| Matching keys: PAN/TAN, entity, year, customer, period, section/table item, amounts, reference | Built in 2T | `domain.py`, `statements/` (TAN, section or table item, transaction date, amounts, reference); `test_domain.py`, `test_statement_readers.py` |  |
| Exact / suggested / unmatched / ambiguous; no auto-confirm of ambiguous; no reuse of statement amount | Done before 2T | `domain.allocate`, `test_duplicate_and_ambiguous_candidates_are_never_added` | |
| Immutable snapshots; later imports supersede the active view without destroying human adjudications | Done before 2T | `uq_trinetra_active_snapshot`, `test_snapshot_reimport_allocations_and_stale_decisions` | Capacities no longer count superseded snapshots: Phase 2 |
| Field-level explanation with provenance | Built in 2T | `domain.explain`, `match_explanations` in the case detail, `CaseInsight.tsx`; `test_explain.py` | Which keys agreed, which reader, which rule version. |
| Idempotent version-aware recompute; deletion/archival; tenant-status gating | Built in 2T | `versions.py` (`v2:` fingerprints), `handlers/trinetra.py`, `notices.py`; `test_versions.py`, `test_evidence_lifecycle.py`, `test_notices.py` | A touch is not a change; the job says what is new (F-642, F-647). |
| Gap exposure is an investigation queue, not an asset | Done before 2T | Wording and note on every figure | |
| Statuses: pending report, possible missing posting, amount mismatch, TAN/PAN mismatch suspected, duplicate/late posting, disputed, verified corrected, closed-with-exception | Built in 2T | `service.py` statuses (POSTED, LATE_POSTING, VERIFIED_CORRECTED, UNRESOLVED …); `test_money_model.py` |  |

### §3C Review, resolution and controls

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Workspace case queue with ownership, root cause, aging, priority, drawer, correction tracking | Done before 2T | `POST …/review`, cockpit, drawer | |
| Reason for each discrepancy with clickable sources and rule/parser version | Built in 2T | `explain`, `CaseInsight.tsx`; `test_explain.py` |  |
| Approve, reject, correct or annotate a match, with reason, concurrency check, audit | Built in 2T | `service.decide` (ALLOCATE, reject, annotate, close); `test_money_model.py`, `test_workflows.py` | Concurrency by case revision. |
| Draft inquiry emails; no autonomous sending; reuse templates, outbox, anti-spam, secure request links | Built in 2T | `inquiries.py`; `test_resolution.py`, spec 143 | Reuses the Helm mail hand and the secure request link; allowance 50 a month on Business; a failed mail revokes its link. 2B: a real inbox. |
| Show who authorized and sent | Built in 2T | `inquiries.view` (created, approved, sent by); `test_resolution.py` |  |
| Record correction responses, Form 16A, re-run after updated statement; close as posted / explained / withdrawn / unresolved; CA approval | Built in 2T | `inquiries.py` reply attach, evidence kinds, `approvals.py`; `test_resolution.py` | UNRESOLVED closure and the Enterprise approval chain exist. |
| Exports: XLSX/CSV and an evidence report with masked identifiers, snapshots, logic, history, approval, disclaimer | Done before 2T | `export.py`, `test_dossier_masks_identifiers_escapes_formula_and_html_and_audits` | New evidence kinds in Phase 6; egress lockdown: Phase 7 |
| Helm integration read-only/projection-first with invariants preventing double counting | Built in 2T | `projection.py`, `helm_adapter.py`; `test_cash_plus_withholding_cannot_be_counted_twice`, `test_helm_adapter.py` | Helm's ledger shows the withheld amount beside the commercial balance. |

### §3D Dashboard, actions, reports, sample

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| KPIs: expected, withheld by source, posted, possible gap, open cases, aging, later outcomes | Done before 2T | `summary()` | By source confidence: Phase 8 |
| Cockpit with quick filters by tax year, customer, exception type, status, workspace | Built in 2T | `Trinetra.tsx` (entity, tax period, status, search, sort); spec 135, 142 |  |
| Row opens a drawer with checklist, audit log, amounts, review buttons | Built in 2T | `CaseInsight.tsx`, `Waterfall.tsx`, `CaseReview.tsx`; spec 142, 144 |  |
| Five-stage evidence path as provenance stages | Done before 2T | `Trinetra.tsx` | |
| Sample company with at least 8 synthetic scenarios, labelled, removable | Done before 2T | `sample.py`, `test_sample_has_consistent_totals_and_no_live_write` | Credit note / reversal scenario checked in Phase 5 |
| KPIs by source confidence and as-of date; evidence-freshness banner | Built in 2T | `Kpis.tsx`, `FreshnessBanner.tsx`; spec 144 |  |
| Accessible errors, loading, zero state, upgrade state, first-run tutorial | Built in 2T | `AccessNotice.tsx`, `Tutorial.tsx`; spec 141 to 144 (axe light and dark, 390 px) |  |

### §4 Database, API, worker

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Few, genuinely needed entities, all scoped, composite FKs, constraints, one head | Done before 2T | `models/trinetra.py`, migrations `tr1a1`, `tr1a2` | New tables in 2T are listed in `ARCHITECTURE.md` |
| Role-authorized routes for onboarding, profiles, preview/import, runs, summary, cases, decisions, drafting/sending, exports, sample | Built in 2T | `app/api/v1/trinetra.py` (workspace routes), `admin/trinetra.py`; `test_isolation_sweep.py` | Every route is swept from OpenAPI. |
| Entitlement gating, read-only sample for non-paying plans, server-side role/workspace checks | Built in 2T | `mode.py`, `capability_gate`; `test_modes.py`, spec 141 | One helper for every gate. |
| Job registration, retries, idempotency, outbox, billing gates, metering, notifications, audit, telemetry, export/retention/erasure, platform admin | Built in 2T | `handlers/trinetra.py`, `scheduler.py`, `data_map.py`, `mode._audit`; `test_notices.py`, `test_capacities.py`, `test_modes.py` | Platform administration is the pilot console and `scripts/trinetra_pilot.py`. |
| No endpoint reachable by guessing another tenant ID | Done before 2T | `test_no_guessed_tenant_access_or_job_status`, isolation sweeps | Sweeps extended to every new route in Phase 9 |
| Background jobs: explicit tenant gate and replay safety | Done before 2T | `handlers/trinetra.py`, `test_worker_replay_and_status_gates` | |

### §5 Frontend

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Servabo shell, tokens, light/dark, accessibility, responsive | Done before 2T | Spec 135, axe light/dark, 390/768/1440 | New screens add specs from 141 |
| Navigation entry, entity selector, tax-year filter | Built in 2T | `Trinetra.tsx`; spec 135, 142 |  |
| Hero "TRINETRA / Credit assurance" with the brief's subtitle | Done before 2T | `Trinetra.tsx` | |
| Four KPI cards with source/as-of tooltip | Built in 2T | `Kpis.tsx`; spec 135, 144 |  |
| Evidence-path strip | Done before 2T | `Trinetra.tsx` | |
| Searchable, sortable, paginated queue; empty states | Done before 2T | `Trinetra.tsx` | |
| Case insight panel: waterfall, citations, ambiguity flags, checklist, decision, inquiry draft, timeline | Built in 2T | `CaseInsight.tsx`, `Waterfall.tsx`, `InquiryPanel.tsx`; spec 142, 143 |  |
| Case detail page with side-by-side sources and reviewer controls; mobile table-to-card | Done before 2T | `CaseDetail.tsx`, `CaseReview.tsx` | |
| Sample-demo mode with "illustrative synthetic data" and upgrade CTA | Done before 2T | `Trinetra.tsx` | Upgrade moment names Business: Phase 2 |
| Keyboard/screen-reader support, focus, error boundaries | Done before 2T | Spec 135 | |
| Website `/trinetra`, nav, product cards, SEO, sitemap, copy, docs; bounded claims; pricing matches entitlement | Built in 2T | `website/src/pages/trinetra.astro`, `config/site.ts` (`TRINETRA.status`), `lib/pricing.ts`; website checks | "Business and Enterprise", "rolling out" until `PUBLIC_TRINETRA_STATUS=available`; no refund, guaranteed-credit or government claim (N-210). |

### §6 Commercial packaging

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| `capability.trinetra` in the real registry, versioned tier publisher; base prices untouched | Done before 2T | `seed_quota_tiers.py`, `TENANCY-AND-PLANS.md` | |
| Free trial / Developer: synthetic demo only | Done before 2T | `workspace(live=True)` capability gate | Upgrade moment names Business: Phase 2 |
| Business: live; 2 profiles, 12 snapshots, 500 cases, 50 inquiries a month | Built in 2T | `seed_quota_tiers.py`, `service.capacity`; `test_capacities.py` | Business: 2 profiles, 12 snapshots, 500 open cases, 50 inquiries a month; working counts, with a retention ceiling. |
| Enterprise: all Business plus cross-workspace and multi-entity reporting, approval chains, higher caps, scoped API/webhook, export controls | Built in 2T | `approvals.py`, `outcomes.py`, `export_engine` dataset, `trinetra:read`, `/organizations/…/trinetra/*`; `test_resolution.py`, `test_integrations.py`, `test_warehouse_dataset.py`, spec 142, 144 | Enterprise: 10, 60, 5,000 and the Enterprise features. |
| Real server-side plan checks, upgrade UX, grandfathering compatibility | Built in 2T | `mode.py`, `capability_gate`; `test_modes.py`, spec 141, 142 | The upgrade moment names Business. |
| Website plan rules consistent with the catalogue; exact owner steps for payment products | Owner's step | `pricing.json` generated; no payment product is needed (capability only) | |

### §7 Security, privacy, lifecycle

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| PAN/TAN least privilege, isolation, encryption, purpose limits | Done before 2T | Encrypted PAN, keyed fingerprints, masked display | TAN scrubber pattern: Phase 9 |
| Retention, exports, erasure, legal holds | Built in 2T | `data_map.py`, `test_lifecycle_rule.py`, `test_integrations.py` (legal hold) | One deliberate rule (N-203); a legal hold keeps the invoice and so the case. |
| No raw PAN/account numbers in logs, URLs, telemetry, screenshots, emails | Built in 2T | `test_privacy.py`, `core/error_tracking.py` (`[tan]`), `tests/infra/test_error_tracking.py` | One whole journey with every log captured. |
| Reuse upload validation, SSRF controls, size and decompression protection | Built in 2T | `statements/common.py` limits, `bank_parse` helpers; `test_hostile_files.py` | A hostile corpus is run through every reader and template. |
| Threat model | Built in 2T | `THREAT-MODEL.md` (readers, sending, approvals, integrations); `test_isolation_sweep.py`, `test_prompt_injection_*` |  |
| No processing without permitted subscription status; labelled production vs simulated | Done before 2T | `tenant_gate`, sample labels | |
| No filing, no corrections to the government, no money movement | Done before 2T | No such code | |
| Deterministic by default; AI drafts metered, revisable, non-authoritative | Done before 2T | No AI in `services/trinetra/` | |

### §8 Milestones and mandatory test classes

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| M0 to M6 | Done before 2T | PR #40, `DELIVERY.md` | 2T repeats the validation in its own PR |
| Old/new Act dates, section labels, cross-year contamination, unsupported formats, synthetic official-format fixtures | Built in 2T | `test_year_boundary_and_historical_labels`, `test_statement_readers.py`, `backend/tests/fixtures/trinetra/` | Synthetic fixtures; the real-file proof is 2B. |
| PAN/TAN mismatch, grouped postings, many-to-one, credit note, reversal, partial receipt, already allocated, currency guard, signed amounts, rounding | Built in 2T | `test_domain.py`, `test_money_model.py` (credit note, reversal, partial receipt, already allocated, currency guard, signed amounts, rounding) |  |
| Sparse evidence gives honest uncertainty; audited, concurrency-safe overrides; idempotent imports | Done before 2T | `test_missing_evidence_is_unknown`, `test_concurrent_reviewers_cannot_double_allocate` | |
| IDOR, plan and trial gating, revoked link, HTML/script injection, file bombs, export masking | Built in 2T | `test_isolation_sweep.py`, `test_hostile_files.py`, `test_resolution.py` (revoked link), exports tests |  |
| Helm, GST, TruthMesh unaffected; withholding never double counted | Built in 2T | The full backend suite at the finish line; `test_withholding_hold.py` |  |
| CI migration up/down/up, drift, backend, frontend, Playwright by role/plan, axe, responsive, CSP, scans, bounded load | Built in 2T | Finish line (STATE.md): `tr2t1` to `tr2t10`, one head; backend, frontend, website and the browser suite; specs 141 to 144 | See `TEST-PLAN.md`, "Executed validation, Final session 2T". |

### §9 Documentation and final PR

| Requirement | Status | Evidence | Note |
| --- | --- | --- | --- |
| Runbook, config, checklists, API specs, plan matrix, lifecycle docs, help, website, troubleshooting | Built in 2T | `docs/RUNBOOK.md`, `docs/CONFIGURATION.md`, `HANDOFF.md` (launch checklist step 13), `USER-GUIDE.md`, `CHANGELOG.md` |  |
| PRODUCT, ARCHITECTURE, EXISTING-CAPABILITY-MAP, LEGAL-SOURCES, THREAT-MODEL, TEST-PLAN, LAUNCH-GATES with owner validation list; metric definitions; sample walkthrough | Built in 2T | `PRODUCT.md`, `ARCHITECTURE.md`, `EXISTING-CAPABILITY-MAP.md`, `LEGAL-SOURCES.md`, `THREAT-MODEL.md`, `TEST-PLAN.md`, `LAUNCH-GATES.md` | Rewritten in 2T. |
| Real statement exports, authorized pilot, adviser sign-off, billing setup | Owner's step | LAUNCH-GATES | Final 2B and the owner's CA |
| Do not assert "100%" until real-source validation is complete | Done before 2T | Wording here and in LAUNCH-GATES | Stays until 2B marks rows "Verified in 2B" |

## B. Like every other feature

| Where GST Credit / Helm / matching are woven in | Status | Evidence | Note |
| --- | --- | --- | --- |
| Getting started step | Built in 2T | `getting_started.tick_trinetra`; `test_integrations.py` |  |
| Global search (never by PAN or TAN) | Built in 2T | `global_search_service._tds_hits`, `CommandPalette`; `test_integrations.py`, `searchHits.test.ts` |  |
| Notification preferences ("TDS credit") and real `trinetra.recompute` work | Built in 2T | `notification_preferences_service` (`TDS_CREDIT`), `notices.announce`; `test_notices.py` | A notice once per case revision; more than five at once are one. |
| Weekly digest line | Built in 2T | `notices.send_digest`, `emails/trinetra.py`; `test_notices.py` | Monday 09:00 in the organization's zone, only when there is something to say. |
| Value receipt and monthly summary (found vs now visible; never cash) | Built in 2T | `value_receipt._tds`; `test_integrations.py` | "Found" and "now visible", never added to money figures. |
| Automation triggers `gap_found`, `evidence_stale`, `closed`, recipes; never sends an inquiry | Built in 2T | `automation/emitters.py`, `triggers.py`, `recipes.py`; `test_case_events.py` | Actions: notify, assign, tag, post to chat; never an inquiry. |
| Public webhooks and read API for cases and summaries (Enterprise) | Built in 2T | `core/webhook_events.py`, `GET /organizations/{id}/trinetra/cases`; `test_case_events.py`, `test_integrations.py` | Ids, states and amounts only. |
| Warehouse dataset (Enterprise) | Built in 2T | `export_engine.TRINETRA_CASES`; `test_warehouse_dataset.py` |  |
| Organization view per legal entity, no double count (Enterprise) | Built in 2T | `service.entities`, `OrganizationTrinetra.tsx`; `test_integrations.py`, spec 144 | Each legal entity counted once. |
| Recoveries (Resolution layer) joins as its own kind | Built in 2T | `recoveries/adapters.py` (`TdsCredit`), migration `tr2t10`; `test_tds_recoveries.py` | Kept out of every "found money" total. |
| Helm ledger shows withheld beside commercial balance; planner reads net cash | Built in 2T | `helm/service.withholding_holds`, `HelmCockpit.tsx`, `HelmLedger.tsx`; `test_helm_adapter.py`, `test_withholding_hold.py` |  |
| Enterprise egress lockdown on exports; legal holds on evidence | Built in 2T | `test_integrations.py` (egress refusal and legal hold) | An inquiry is refused in words when the mail server is blocked. |
| User guide (`docs/trinetra/USER-GUIDE.md`) | Built in 2T | `docs/trinetra/USER-GUIDE.md` |  |
| Performance budget test and `PERFORMANCE.md` | Built in 2T | `tests/performance/test_trinetra_budgets.py`, `docs/hardening/PERFORMANCE.md`, F-650 | 2.6 s, 4.0 s and 1.7 s against 5 s. |
| `preflight.py` reports mode, enrolment, unverified readers | Built in 2T | `scripts/preflight.py` (`check_trinetra`); `tests/scripts/test_preflight.py` |  |
| Explicit TAN pattern in the error-tracking scrubber | Built in 2T | `core/error_tracking.py`; `tests/infra/test_error_tracking.py` |  |
| Three modes and the single "is it live for this organization" helper | Built in 2T | `mode.py`; `test_modes.py` |  |
