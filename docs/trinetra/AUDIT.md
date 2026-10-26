# TRINETRA: existing-service audit

Audited baseline: `bf8f57f691aec7122d9ebaf4a4e13ae9d22ae19c` on `main`.
Implementation branch: `hardening/trinetra`.

This is the pre-implementation code audit, not an implementation or validation
report. The uploaded implementation specification was not yet readable while the
execution environment was starting. Its requirements must be reconciled with this
inventory before implementation. No test has been executed for TRINETRA yet.

## Existing functionality to reuse

| Area | Current implementation | TRINETRA integration boundary |
| --- | --- | --- |
| Bank imports and receipts | `backend/app/models/helm.py`; `services/helm/bank.py`, `bank_parse.py` | Reference existing bank accounts, imports and lines. Reuse bounded tabular parsing, file hashing, line deduplication and masked account display. Do not create another banking ledger. |
| Settlement | `services/helm/settlements.py`, `bank_match.py` | Helm confirms full-invoice or agreed-discount payments. A receipt net of TDS needs explicit TDS allocations against the existing line; do not relax Helm's settlement invariant. |
| Money and invoice references | `services/helm/money.py`, `ledger.py`, `bank_match.py` | Use integer micros and Decimal, shared date parsing and invoice-reference boundary matching. Ambiguous matches remain suggestions. |
| Document extraction | `backend/app/core/finance_schema.py`; existing enrichment pipeline | Extend the authoritative finance field vocabulary. Do not add a separate OCR, embedding or extraction pipeline. |
| Document-change propagation | `services/helm/hooks.py`; `services/gst/hooks.py` | Existing hooks receive enrichment, verification, corrections and deletion. Add a debounced TRINETRA consumer to this shared path. |
| Background work | `services/job_service.py`; `workers/handlers/`, profiles and tenant gate | Reuse transactional enqueue, trace propagation, idempotency keys and retries. Register job types in every existing worker catalogue and activity/billing gate. Global sweeps must gate each tenant independently. |
| TruthMesh | `services/truthmesh/loader.py`, `linker.py`; `models/truthmesh.py` | Read existing scoped document facts and links for evidence context. Do not create another graph or infer confirmed tax credit from a document link. |
| GST | `services/gst/`; `api/v1/gst.py` | Reuse isolation, import, matching-review, summary and export patterns. GST returns and TDS credit remain distinct financial records. |
| Collaboration and evidence | `services/collab/`; review queue; `document_evidence_service.py` | Reuse threads, review projections and source highlighting. Do not build parallel comments, presence or evidence storage. |
| Billing | `core/entitlements.py`, `api/capability_gate.py`, `services/billing/entitlement_service.py` | Add grants through the existing capability and plan-version system. A separate add-on is appropriate only if the specification requires it. |
| Plan catalogue | `scripts/seed_quota_tiers.py`, `scripts/export_public_pricing.py` | Keep backend entitlements and generated website pricing aligned. Existing subscriptions pin versions; use the established publish/carry-forward process for deployment. |
| Sample company | `services/helm/sample_company.py`, `services/gst/sample.py` | Extend the existing Meridian sample lifecycle. Generate reconciled totals from the same underlying cases and keep sample workspaces immutable to ordinary writes. |
| App shell and navigation | `frontend/src/App.tsx`, `routes/tenantPaths.ts`, `components/layout/navigation.ts` | Reuse DashboardLayout, tenant guards and shared sidebar/command-palette navigation. Query keys must include workspace scope. |
| Design system | Shared PageHeader, UI primitives, StatusPill and dialog-focus handling | Follow Servabo's tokens, responsive layout and existing error/loading/upgrade states. Use the supplied image as direction. |
| Display formatting | `frontend/src/components/helm/money.ts`, `utils/displayTime.ts` | Use Indian digit grouping and the existing money unit. Preserve calendar dates across timezones. |
| Public website | Astro Base, SectionHead, PlanBadge, ClosingCta and Shot components | Extend the repository website, navigation and explicit sitemap. Regenerate pricing data rather than hand-editing generated prices. |

No dedicated TDS or tax-year service path was found in the audited tree. This
does not make shared accounting, banking, evidence or matching services redundant.

## Security and data integrity requirements from the existing architecture

- Bank access must check the Helm book, the line's workspace and restricted
  workspace suggestions. Organization ownership alone is insufficient:
  `bank._require_read`, `bank._require_line`, `bank.line_json` and
  `service.book_for` already encode these boundaries.
- Workspace APIs use `RequireWorkspaceRole` and explicit context, workspace and
  organization checks. New routes should use the standard path parameter names
  so automated tenant, role and API-key sweeps discover them.
- Add composite foreign keys for organization/workspace and document/workspace
  relationships. Retained bank evidence must keep its workspace scope after a
  linked document is removed.
- Register every new table in `services/compliance/data_map.py` with explicit
  erasure, retention and purge behavior. Export decisions must agree with
  `export_service.GENERIC_SECTIONS`. Do not copy GST's statutory retention
  rationale automatically to TDS.
- Reuse spreadsheet formula neutralization (`services/gst/export.py::safe`),
  export auditing and `Cache-Control: no-store`. New audit enum values require
  matching model and database migrations.
- Test cross-tenant access, restricted workspaces within one organization,
  API-key default denial, roles, billing states, sample immutability,
  cross-workspace foreign keys, overlapping allocations, duplicate imports,
  hostile spreadsheet content and lifecycle registration.
- Keep exactly one Alembic head and test upgrade/downgrade with populated rows.

## Corrections required in the visual reference

The image is a design reference, not authoritative financial sample data.

- 15 April 2026 is in FY 2026–27. It cannot be paired with FY 2025–26.
  Historical FY 2025–26 corresponds to AY 2026–27; a tax-year label must not
  silently substitute for an assessment-year label.
- Rs 78,000 on Rs 7,80,000 is a 10% deduction. It is inconsistent with an
  ordinary corporate contractor example under historical section 194C at 2%.
  The selected sample must state a coherent section, rate, taxable base and date.
  Separately stated GST must not silently inflate the TDS base.
- Rs 18,42,000 minus Rs 14,80,000 is Rs 3,62,000. Confirmation and gap percentages
  are approximately 80.35% and 19.65%; rounded 80% and 20% labels are reasonable.
  Final sample cards, queue rows and case detail must derive from one dataset.

## Validation infrastructure

Real API and engine tests need a dedicated PostgreSQL 16 database with pgvector
and Redis. The test fixture drops/recreates its configured test database; do not
run separate pytest processes against the same database. Engine fixtures can
drain selected real job handlers without a worker subprocess.

The browser harness supports local storage, labelled ML stubs and local service
stand-ins. Its strict fixtures reject unexpected HTTP errors, console errors and
native dialogs. New routes must be registered in the accessibility/phone sweep
catalogue. Capability labels and generated public pricing have existing
completeness/freshness checks.

Implementation status and executed validation will be recorded separately once
the specification and execution workspace are available.

## Verification against the implemented branch — 26 October 2026

The historical inventory above was checked against the current code after the
complete original attachment became readable. The repository instructions and
the specification's required product, configuration, runbook, tenancy, security,
Helm, GST, campaign and owner-decision documents have now been read, including
all of NEEDS-OWNER. The saved checkpoint was not treated as implementation.
Repository-wide withholding/26AS/TRACES searches confirmed the missing TDS domain;
the existing X12 `TDS` segment means invoice total.

The final boundaries differ from the preliminary proposals in these ways:

- Canonical invoice facts, bank permissions, job hooks, compliance lifecycle,
  billing versions and export escaping are reused as recorded in
  [EXISTING-CAPABILITY-MAP.md](EXISTING-CAPABILITY-MAP.md).
- No bank parser or tax-portal connector is added. Unverified official formats are
  refused; reviewed transcriptions retain their canonical source and fingerprint.
- TruthMesh/procurement context, discussions and secure requests remain on the
  existing document review surface. TRINETRA does not create a parallel graph or
  portal. The sample is a read-only synthetic response, with no extra workspace
  or financial records to purge.
- Helm's commercial ledger and settlements are unchanged. An explicit reviewed
  withholding annotation and reminder hold prevent treating the whole balance as
  cash still to chase; the hold does not settle an invoice.
- There is no existing virus scanner to reuse. The threat model now states the
  actual intake protections and this inherited limitation.
- The sample avoids unreviewed statutory rates and section labels. Historical
  FY/AY and post-April-2026 tax-year labels are distinct; independent adviser review
  remains open. The image's erroneous tax example is not copied.

Current implementation, executed results and remaining acceptance gates are in
[ARCHITECTURE.md](ARCHITECTURE.md), [TEST-PLAN.md](TEST-PLAN.md) and
[LAUNCH-GATES.md](LAUNCH-GATES.md). The original audit's future-tense statements
above are retained as history, not current release claims.
