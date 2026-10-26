# Existing capabilities and TRINETRA boundaries

Baseline reviewed: `a63f7f5969d37c4d7e77da8b691908fd2f8d8b7d` (the existing branch).
The original 133-line specification was downloaded and read on 2026-10-24.
The previous AUDIT is an inventory, not a completed implementation report.

Repository-wide searches found no dedicated Indian TDS/TCS/26AS engine. The X12
`TDS` segment is an invoice total, not an Indian withholding tax service.

| Existing owner | Integration | Boundary |
|---|---|---|
| WorkItem / ordinary document intake | Evidence references use composite document/workspace foreign keys | No new OCR, blob store or independent document uploader |
| Helm bank/service authorization | Case detail reads matched INR lines through viewer, book and restricted-workspace gates | No bank importer or settlement writes; bank gaps never infer TDS |
| Helm integer money conventions | Micros and Decimal arithmetic | No second cash ledger |
| Helm ledger and reminder hand | Scoped annotation and send-time withholding review hold | Commercial totals and canonical bank settlements are not rewritten |
| Platform encryption rotation | Both profile ciphertext columns join its existing target registry | No separate key lifecycle or JWT-derived tax identifier |
| TruthMesh / procurement matching | Canonical source documents remain available in existing review UI | No duplicate graph or matching engine for procurement |
| GST export safety | Formula-neutralizing helper | No GSTR-2B rows treated as TDS credit |
| Capability registry and versioned tier publisher | capability.trinetra on Business/Enterprise | No base prices, cadence, provider or existing subscription pins changed |
| Standard tenant dependencies and billing gate | Role/tenant/plan gates before all live operations | Sample-only access is read-only |
| Job service, worker profile and tenant gate | Idempotent bounded reconciliation | No second queue or scheduler |
| Compliance data map/export | Explicit purge, erasure and export entries | No unverified GST statutory retention exemption |
| App shell / Astro / pricing generator | Existing primitives, navigation, INR formatting, generated plan data | No independent design system or invented pricing |

Open integration work is enumerated in LAUNCH-GATES.md. In particular, this
implementation does not claim ERP-derived expectations, automatic evidence
extraction, net-of-TDS Helm payment adjustments or official-statement parsing.
Printed extraction fields appear only as unapproved hints. Later closure and review
effort are derived from the existing TRINETRA decision/snapshot evidence, not a second
cross-product recovery ledger. Supporting evidence uses canonical document review,
discussions and secure-request surfaces.
