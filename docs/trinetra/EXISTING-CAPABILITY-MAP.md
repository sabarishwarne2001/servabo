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
| Helm contacts, outbound mail hand and secure document requests (Final 2T) | An inquiry goes only to a contact a person confirmed in Helm, through the same mail hand and request link; a reply attaches to its case | No second mailer, no address book, no learned address as a recipient |
| Existing Zoho Books connector (Final 2T) | A read-only scan for invoices with TDS (unverified until 2B) | No new connector, no write to Zoho |
| Notifications, preferences, outbox, automation triggers and recipes, public webhooks and the read API (Final 2T) | `TDS credit` category, `trinetra.case.*` events, three triggers and two recipes, an Enterprise cases API | No new delivery system; a rule can notify, assign, tag or post to chat, never send an inquiry |
| Getting started, global search, value receipt, Recoveries (Final 2T) | One step, one hit kind (never by PAN or TAN), "found" and "now visible" lines, Recoveries kind `TDS_CREDIT` | No second checklist, search index or "found money" total |
| Analytics export engine (Final 2T) | Warehouse dataset `TRINETRA_CASES` (Enterprise) | No second export pipeline |
| Egress policy, legal holds and the compliance data map (Final 2T) | An inquiry refused in words when the mail server is blocked; a held invoice keeps its case; every new table is mapped | No TRINETRA-only policy engine |
| Platform administration, preflight and the error-tracking scrubber (Final 2T) | The pilot console, a TRINETRA block in preflight, a TAN pattern in the scrubber | No second operator console |
| Existing statement import conventions (bank parsing helpers) (Final 2T) | CSV/XLSX row reading with size and row ceilings | No new binary parser; PDF is not read |

Open integration work is enumerated in LAUNCH-GATES.md. In particular, the official statement readers are written but
**unverified** until Final session 2B reads a real file, and the Zoho read has never met a real organization. Printed extraction
fields appear only as unapproved hints (a suggestion a person accepts). Later closure is recorded once in the closure ledger
("TDS now visible"), and review effort is derived from the existing TRINETRA decision and snapshot evidence; neither is a
cross-product recovery or savings ledger. Supporting evidence uses canonical document review, discussions and secure-request surfaces.
